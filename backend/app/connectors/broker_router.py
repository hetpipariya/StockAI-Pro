from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app import config
from .smartapi_connector import SmartAPIConnector
from .upstox_connector import UpstoxConnector

logger = logging.getLogger(__name__)

_FAILURE_COOLDOWNS = {
    "auth": 180.0,
    "rate_limit": 30.0,
    "websocket": 15.0,
    "downtime": 60.0,
    "unknown": 20.0,
}


@dataclass(frozen=True)
class BrokerDecision:
    broker: str
    fallback_used: bool
    reason: str = ""


class BrokerRouter:
    """Primary SmartAPI, fallback Upstox, with circuit-breaker routing."""

    def __init__(
        self,
        primary: str | None = None,
        fallback: str | None = None,
        smartapi: SmartAPIConnector | None = None,
    ) -> None:
        self.primary_name = self._normalize_name(primary or config.BROKER_PRIMARY)
        self.fallback_name = self._normalize_name(fallback or config.BROKER_FALLBACK)
        self._connectors: dict[str, Any] = {
            "smartapi": smartapi or SmartAPIConnector(),
        }
        self._active_broker = self.primary_name if self.primary_name in self._connectors else "smartapi"
        self._lock = threading.RLock()
        self._breaker_until: dict[str, float] = {name: 0.0 for name in ("smartapi", "upstox")}
        self._breaker_reason: dict[str, str] = {name: "" for name in ("smartapi", "upstox")}
        self._last_success: dict[str, float] = {name: 0.0 for name in ("smartapi", "upstox")}
        self._upstox_connector: UpstoxConnector | None = None

    @staticmethod
    def _normalize_name(name: str | None) -> str:
        normalized = str(name or "").strip().lower()
        return normalized if normalized in {"smartapi", "upstox"} else "smartapi"

    @property
    def active_broker(self) -> str:
        with self._lock:
            return self._active_broker

    def _broker_order(self) -> list[str]:
        brokers = [self.primary_name, self.fallback_name]
        order: list[str] = []
        for broker in brokers:
            if broker in self._connectors and broker not in order:
                order.append(broker)
        for broker in self._connectors:
            if broker not in order:
                order.append(broker)
        return order

    def _breaker_open(self, broker: str) -> bool:
        return time.monotonic() < self._breaker_until.get(broker, 0.0)

    def _classify_failure(self, exc: Exception) -> tuple[str, str]:
        message = str(exc).lower()
        if any(token in message for token in ("invalid token", "token expired", "unauthorized", "auth", "login failed", "refresh required")):
            return "auth", str(exc)
        if any(token in message for token in ("429", "rate limit", "too many requests")):
            return "rate_limit", str(exc)
        if any(token in message for token in ("websocket", "ws", "connection closed", "disconnect")):
            return "websocket", str(exc)
        if any(token in message for token in ("timeout", "temporarily unavailable", "connection refused", "server error", "503", "502", "504")):
            return "downtime", str(exc)
        return "unknown", str(exc)

    def _open_breaker(self, broker: str, reason_kind: str, detail: str) -> None:
        cooldown = _FAILURE_COOLDOWNS.get(reason_kind, _FAILURE_COOLDOWNS["unknown"])
        self._breaker_until[broker] = time.monotonic() + cooldown
        self._breaker_reason[broker] = detail
        logger.warning(
            "[BROKER] %s breaker opened for %.0fs (%s): %s",
            broker.upper(),
            cooldown,
            reason_kind,
            detail,
        )

    def _record_success(self, broker: str) -> None:
        with self._lock:
            self._last_success[broker] = time.monotonic()
            self._breaker_until[broker] = 0.0
            self._breaker_reason[broker] = ""
            self._active_broker = broker

    def _record_failure(self, broker: str, exc: Exception) -> tuple[str, str]:
        kind, detail = self._classify_failure(exc)
        with self._lock:
            self._open_breaker(broker, kind, detail)
            if kind == "auth" or "unauthorized" in detail.lower() or "401" in detail.lower() or "403" in detail.lower() or "token expired" in detail.lower():
                from app.services.broker_session_manager import broker_session_manager
                broker_session_manager.update_state(broker, status="TOKEN_EXPIRED", token_valid=False)
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            broker_session_manager.mark_token_expired_db(broker),
                            loop
                        )
                except Exception:
                    pass
        return kind, detail

    def _connector(self, broker: str) -> Any:
        if broker not in self._connectors:
            if broker == "upstox":
                return self._create_upstox_connector(force_new=False)
            raise KeyError(f"Unknown broker: {broker}")
        return self._connectors[broker]

    def _create_upstox_connector(self, *, force_new: bool = True) -> UpstoxConnector:
        with self._lock:
            if force_new or self._upstox_connector is None:
                self._upstox_connector = UpstoxConnector(validate_on_init=False)
            return self._upstox_connector

    def _invoke(self, broker: str, method_name: str, *args: Any, **kwargs: Any) -> Any:
        connector = self._connector(broker)
        method = getattr(connector, method_name)
        return method(*args, **kwargs)

    def _try_route(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        # Check active broker state before invocation (except for auth recovery methods)
        if method_name not in ("login", "ensure_login", "refresh_session"):
            from app.services.broker_session_manager import broker_session_manager
            state = broker_session_manager.get_state(self._active_broker)
            if state.get("status") in ("TOKEN_EXPIRED", "REAUTH_REQUIRED", "AUTH_FAILED"):
                broker_session_manager.log_event(
                    "[WS_BLOCKED]",
                    self._active_broker,
                    details=f"Blocked routed call {method_name} because broker state is {state.get('status')}"
                )
                raise RuntimeError(f"Broker connection blocked: token is expired or unauthorized ({state.get('status')})")

        attempts: list[str]
        with self._lock:
            active = self._active_broker
            attempts = [active] + [broker for broker in self._broker_order() if broker != active]

        last_exc: Exception | None = None
        for broker in attempts:
            if self._breaker_open(broker):
                continue
            try:
                result = self._invoke(broker, method_name, *args, **kwargs)
                self._record_success(broker)
                return result
            except Exception as exc:
                last_exc = exc
                kind, detail = self._record_failure(broker, exc)
                logger.warning(
                    "[BROKER] %s.%s failed on %s (%s): %s",
                    broker,
                    method_name,
                    method_name,
                    kind,
                    detail,
                )
                if broker == "smartapi" and kind == "auth":
                    with self._lock:
                        self._breaker_until["upstox"] = 0.0
                        self._breaker_reason["upstox"] = ""
                        self._upstox_connector = None
                if broker == "upstox":
                    with self._lock:
                        self._upstox_connector = None
                continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"No available broker for {method_name}")

    def login(self, force: bool = False) -> dict[str, Any]:
        return self._try_route("login", force=force)

    def ensure_login(self) -> None:
        try:
            self._try_route("ensure_login")
        except Exception as exc:
            if self._classify_failure(exc)[0] == "auth":
                logger.warning("[BROKER] smartapi auth failed; forcing fresh upstox validation")
                upstox = self._create_upstox_connector(force_new=True)
                upstox.ensure_login()
                self._record_success("upstox")
                return
            raise

    def refresh_session(self) -> bool:
        try:
            return bool(self._try_route("refresh_session"))
        except Exception as exc:
            if self._classify_failure(exc)[0] == "auth":
                upstox = self._create_upstox_connector(force_new=True)
                return bool(upstox.refresh_session())
            raise

    def fetch_history(
        self,
        symbol_token: str,
        exchange: str = "NSE",
        interval: str = "1m",
        from_date=None,
        to_date=None,
        limit: int = 500,
    ) -> list[Any]:
        try:
            return list(self._try_route(
                "fetch_history",
                symbol_token,
                exchange,
                interval,
                from_date,
                to_date,
                limit,
            ) or [])
        except Exception as exc:
            if self._classify_failure(exc)[0] == "auth":
                upstox = self._create_upstox_connector(force_new=True)
                return list(upstox.fetch_history(symbol_token, exchange, interval, from_date, to_date, limit) or [])
            raise

    def fetch_latest(self, symbol_token: str, exchange: str = "NSE", tradingsymbol: str = "") -> Any:
        try:
            return self._try_route("fetch_latest", symbol_token, exchange, tradingsymbol)
        except Exception as exc:
            if self._classify_failure(exc)[0] == "auth":
                upstox = self._create_upstox_connector(force_new=True)
                return upstox.fetch_latest(symbol_token, exchange, tradingsymbol)
            raise

    def get_ltp(self, symbol_token: str, exchange: str = "NSE", tradingsymbol: str = "") -> Any:
        return self.fetch_latest(symbol_token, exchange, tradingsymbol)

    def subscribe(self, token_list, on_message=None):
        try:
            return self._try_route("subscribe", token_list, on_message)
        except Exception as exc:
            if self._classify_failure(exc)[0] == "auth":
                upstox = self._create_upstox_connector(force_new=True)
                return upstox.subscribe(token_list, on_message)
            raise

    def unsubscribe(self, tokens) -> bool:
        try:
            return bool(self._try_route("unsubscribe", tokens))
        except Exception:
            upstox = self._create_upstox_connector(force_new=True)
            return bool(upstox.unsubscribe(tokens))

    def start_ws(self, token_list, on_message):
        return self.subscribe(token_list, on_message)

    def subscribe_ws_tokens(self, tokens: list[str]) -> bool:
        return bool(self.subscribe(tokens))

    def active_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_broker": self._active_broker,
                "primary": self.primary_name,
                "fallback": self.fallback_name,
                "breaker_until": dict(self._breaker_until),
                "breaker_reason": dict(self._breaker_reason),
            }
