from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_REST_MIN_INTERVAL_SECONDS = max(0.15, float(os.getenv("UPSTOX_MIN_API_INTERVAL_SECONDS", "0.25")))
_DEFAULT_RETRY_ATTEMPTS = max(1, int(os.getenv("UPSTOX_RETRY_ATTEMPTS", "3")))
_DEFAULT_RETRY_BACKOFF_SECONDS = max(0.2, float(os.getenv("UPSTOX_RETRY_BACKOFF_SECONDS", "0.5")))
_WS_RECONNECT_BASE_SECONDS = max(0.5, float(os.getenv("UPSTOX_WS_RECONNECT_BASE_SECONDS", "1.0")))
_WS_RECONNECT_MAX_SECONDS = max(5.0, float(os.getenv("UPSTOX_WS_RECONNECT_MAX_SECONDS", "60.0")))


class BrokerAuthenticationError(RuntimeError):
    """Custom exception raised when broker requests fail with 401/403 status codes."""
    pass


class UpstoxConnector:
    """Best-effort Upstox market-data connector with SmartAPI-compatible methods."""

    def _reload_runtime_env(self) -> None:
        """Reload the repo/runtime .env files so the latest token is visible in os.environ."""
        repo_root = Path(__file__).resolve().parents[3]
        for env_path in (repo_root / ".env", repo_root / "backend" / ".env"):
            if env_path.is_file():
                load_dotenv(dotenv_path=env_path, override=False)

    @staticmethod
    def _env_value(name: str, default: str = "") -> tuple[str, str]:
        value = os.getenv(name, default)
        source = "runtime_env" if value else "missing"
        return value or default, source

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        auth_code: Optional[str] = None,
        ws_url: Optional[str] = None,
        validate_on_init: bool = False,
    ) -> None:
        self._reload_runtime_env()

        self.api_key = api_key or os.getenv("UPSTOX_API_KEY", "")
        self.api_secret = api_secret or os.getenv("UPSTOX_API_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("UPSTOX_REDIRECT_URI", "")

        # Single source of truth check: load dynamic token from database first
        from app.services.broker_session_manager import broker_session_manager
        db_token = broker_session_manager.get_active_token_sync("upstox")

        self.access_token = access_token
        if self.access_token is None:
            self.access_token = db_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")

        self.refresh_token = refresh_token
        if self.refresh_token is None:
            state = broker_session_manager.get_state("upstox")
            self.refresh_token = state.get("refresh_token") or os.getenv("UPSTOX_REFRESH_TOKEN", "")

        self.auth_code = auth_code if auth_code is not None else os.getenv("UPSTOX_AUTH_CODE", "")
        self.ws_url = ws_url or os.getenv("UPSTOX_WS_URL", "wss://api.upstox.com/v2/feed/market-data-feed")
        self.base_url = "https://api.upstox.com/v2"

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Api-Version": "2.0",
            }
        )
        self._session_lock = threading.RLock()
        self._login_lock = threading.Lock()
        self._last_rest_call = 0.0
        self._is_logged_in = False
        from app.services.token_manager import BrokerCircuitBreaker
        self._circuit_breaker = BrokerCircuitBreaker("Upstox")
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_should_reconnect = True
        self._ws_tokens: set[str] = set()
        if self.access_token:
            self._session.headers["Authorization"] = f"Bearer {self.access_token}"

        token_loaded = bool(str(self.access_token or "").strip())
        logger.info(
            "[UPSTOX] init token_loaded=%s token_length=%d token_source=%s refresh_loaded=%s",
            token_loaded,
            len(str(self.access_token or "").strip()),
            "database" if db_token else ("runtime_env" if token_loaded else "missing"),
            bool(str(self.refresh_token or "").strip()),
        )

        if validate_on_init:
            if not token_loaded:
                raise RuntimeError("Upstox access token missing from environment")
            valid = self._validate_token()
            logger.info("[UPSTOX] init auth_validation=%s", "ok" if valid else "failed")
            if not valid:
                raise RuntimeError("Upstox access token failed validation at startup")

    @property
    def is_logged_in(self) -> bool:
        return bool(self._is_logged_in and self.access_token)

    def _rate_limit(self) -> None:
        with self._session_lock:
            now = time.monotonic()
            wait = _REST_MIN_INTERVAL_SECONDS - (now - self._last_rest_call)
            if wait > 0:
                time.sleep(wait)
            self._last_rest_call = time.monotonic()

    def _auth_headers(self) -> dict[str, str]:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(_DEFAULT_RETRY_ATTEMPTS):
            try:
                self._rate_limit()
                response = self._session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json_body,
                    timeout=timeout,
                    headers=self._auth_headers(),
                )
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", "1") or 1)
                    time.sleep(retry_after)
                    continue

                if response.status_code in (401, 403):
                    msg = f"Broker authentication failed with status code {response.status_code}: {response.text}"
                    from app.services.broker_session_manager import broker_session_manager
                    broker_session_manager.log_event("[AUTH_FAILED]", "upstox", details=msg)
                    raise BrokerAuthenticationError(msg)

                response.raise_for_status()
                if not response.text:
                    return {"status": True, "data": {}}
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
                return {"status": True, "data": payload}
            except BrokerAuthenticationError as exc:
                # Fast fail, bypass retry loop
                raise exc
            except Exception as exc:
                last_error = exc
                if attempt < _DEFAULT_RETRY_ATTEMPTS - 1:
                    time.sleep(_DEFAULT_RETRY_BACKOFF_SECONDS * (2**attempt))
        raise RuntimeError(f"Upstox request failed: {last_error}") from last_error

    @staticmethod
    def _parse_epochish(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return 0.0
            try:
                return float(raw)
            except ValueError:
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    return 0.0
        return 0.0

    def _validate_token(self) -> bool:
        try:
            self._request_json("GET", "/user/profile")
            self._is_logged_in = True
            logger.info(
                "[UPSTOX] auth_validation=ok token_loaded=%s token_length=%d",
                bool(str(self.access_token or "").strip()),
                len(str(self.access_token or "").strip()),
            )
            return True
        except BrokerAuthenticationError as exc:
            logger.warning(
                "[UPSTOX] auth_validation=failed token_loaded=%s token_length=%d error=%s",
                bool(str(self.access_token or "").strip()),
                len(str(self.access_token or "").strip()),
                exc,
            )
            self._is_logged_in = False
            raise exc
        except Exception as exc:
            logger.warning(
                "[UPSTOX] auth_validation=failed token_loaded=%s token_length=%d error=%s",
                bool(str(self.access_token or "").strip()),
                len(str(self.access_token or "").strip()),
                exc,
            )
            self._is_logged_in = False
            return False

    def login(self, force: bool = False) -> dict[str, Any]:
        if not self._circuit_breaker.can_attempt():
            logger.warning("[BROKER_AUTH_FAILED] [BROKER_CIRCUIT_OPEN] Upstox circuit breaker is OPEN. Suspending login attempt.")
            raise RuntimeError("Broker auth suspended: circuit is OPEN")

        with self._login_lock:
            try:
                if self.access_token and not force and self._validate_token():
                    self._circuit_breaker.record_success()
                    return {
                        "status": True,
                        "accessToken": self.access_token,
                        "refreshToken": self.refresh_token,
                        "feedToken": self.access_token,
                    }

                if self.refresh_token:
                    if self.refresh_session():
                        self._circuit_breaker.record_success()
                        return {
                            "status": True,
                            "accessToken": self.access_token,
                            "refreshToken": self.refresh_token,
                            "feedToken": self.access_token,
                        }

                if self.auth_code and self.api_key and self.api_secret and self.redirect_uri:
                    # Best-effort OAuth exchange scaffold. Upstox will return a JSON token payload
                    # when the auth code is still valid.
                    payload = self._request_json(
                        "POST",
                        "/login/authorization/token",
                        json_body={
                            "code": self.auth_code,
                            "client_id": self.api_key,
                            "client_secret": self.api_secret,
                            "redirect_uri": self.redirect_uri,
                            "grant_type": "authorization_code",
                        },
                    )
                    token_data = payload.get("data", payload)
                    if isinstance(token_data, dict):
                        self.access_token = str(token_data.get("access_token") or token_data.get("accessToken") or "").strip()
                        self.refresh_token = str(token_data.get("refresh_token") or token_data.get("refreshToken") or self.refresh_token or "").strip()
                        if self.access_token:
                            self._session.headers["Authorization"] = f"Bearer {self.access_token}"
                            self._is_logged_in = True
                            self._circuit_breaker.record_success()
                            return {
                                "status": True,
                                "accessToken": self.access_token,
                                "refreshToken": self.refresh_token,
                                "feedToken": self.access_token,
                            }

                raise RuntimeError("Upstox login failed: missing or invalid access token")
            except Exception as e:
                self._circuit_breaker.record_failure()
                logger.warning("[BROKER_AUTH_FAILED] Upstox login attempt failed: %s", e)
                raise e

    def ensure_login(self) -> None:
        if not self.login(force=False):
            raise RuntimeError("Upstox login unavailable")

    def refresh_session(self) -> bool:
        if not self.refresh_token:
            return self._validate_token()

        try:
            from app.services.broker_session_manager import broker_session_manager
            broker_session_manager.log_event("[TOKEN_REFRESH]", "upstox", details="Attempting token refresh")
            payload = self._request_json(
                "POST",
                "/login/authorization/token",
                json_body={
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                },
            )
            token_data = payload.get("data", payload)
            if isinstance(token_data, dict):
                new_access = str(token_data.get("access_token") or token_data.get("accessToken") or "").strip()
                if new_access:
                    self.access_token = new_access
                    self.refresh_token = str(token_data.get("refresh_token") or token_data.get("refreshToken") or self.refresh_token or "").strip()
                    self._session.headers["Authorization"] = f"Bearer {self.access_token}"
                    self._is_logged_in = True
                    return True
        except Exception as exc:
            logger.warning("[UPSTOX] Refresh failed: %s", exc)
        return self._validate_token()

    @staticmethod
    def _normalize_interval(interval: str) -> str:
        value = str(interval or "1m").strip().lower()
        return {
            "1m": "1minute",
            "3m": "3minute",
            "5m": "5minute",
            "15m": "15minute",
            "30m": "30minute",
            "1h": "60minute",
            "1d": "day",
        }.get(value, value)

    @staticmethod
    def _to_upstox_ts(value: datetime | None) -> str:
        if value is None:
            value = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _resolve_instrument_key(symbol_token: str, exchange: str = "NSE", tradingsymbol: str = "") -> str:
        token = str(symbol_token or "").strip()
        if token and ("|" in token or ":" in token):
            return token
        symbol = str(tradingsymbol or token or "").strip()
        exchange_value = str(exchange or "NSE").strip().upper() or "NSE"
        if symbol:
            return f"{exchange_value}|{symbol.replace('-EQ', '').upper()}"
        return token or symbol

    @staticmethod
    def _normalize_candle_rows(payload: Any) -> list[list[Any]]:
        if isinstance(payload, dict):
            payload = payload.get("data", payload)
        if isinstance(payload, dict):
            payload = payload.get("candles", payload.get("data", []))
        rows: list[list[Any]] = []
        if not payload:
            return rows
        for item in payload:
            if isinstance(item, (list, tuple)) and len(item) >= 5:
                rows.append(list(item[:6]))
                continue
            if isinstance(item, dict):
                ts = item.get("timestamp") or item.get("date") or item.get("time") or item.get("ts")
                rows.append([
                    ts,
                    item.get("open", item.get("o", 0)),
                    item.get("high", item.get("h", 0)),
                    item.get("low", item.get("l", 0)),
                    item.get("close", item.get("c", item.get("ltp", 0))),
                    item.get("volume", item.get("v", 0)),
                ])
        return rows

    def fetch_history(
        self,
        symbol_token: str,
        exchange: str = "NSE",
        interval: str = "1m",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[list[Any]]:
        self.ensure_login()
        interval_key = self._normalize_interval(interval)
        end_dt = to_date or datetime.now(timezone.utc)
        if from_date is None:
            from_date = end_dt - timedelta(days=7 if interval_key.endswith("minute") else 30)

        instrument_key = self._resolve_instrument_key(symbol_token, exchange=exchange)
        path = (
            f"/historical-candle/{instrument_key}/{interval_key}/"
            f"{self._to_upstox_ts(end_dt)}/{self._to_upstox_ts(from_date)}"
        )
        payload = self._request_json("GET", path)
        rows = self._normalize_candle_rows(payload)
        if limit > 0:
            rows = rows[-limit:]
        return rows

    def fetch_latest(
        self,
        symbol_token: str,
        exchange: str = "NSE",
        tradingsymbol: str = "",
    ) -> Optional[dict[str, Any]]:
        rows = self.fetch_history(symbol_token, exchange, "1m", None, None, 1)
        if not rows:
            return None
        last = rows[-1]
        if isinstance(last, (list, tuple)) and len(last) >= 5:
            return {
                "ltp": float(last[4]),
                "open": float(last[1]),
                "high": float(last[2]),
                "low": float(last[3]),
                "close": float(last[4]),
                "volume": int(last[5]) if len(last) > 5 else 0,
            }
        return None

    def get_ltp(self, symbol_token: str, exchange: str = "NSE", tradingsymbol: str = "") -> Optional[dict[str, Any]]:
        return self.fetch_latest(symbol_token, exchange, tradingsymbol)

    def start_ws(self, token_list: list[dict], on_message: Callable[[Any], None]):
        return self.subscribe(token_list, on_message)

    def subscribe(self, token_list, on_message=None):
        normalized = self._extract_tokens(token_list)
        if not normalized:
            return True
        with self._session_lock:
            self._ws_tokens.update(normalized)

        if on_message is None:
            return True

        try:
            from websocket import WebSocketApp  # type: ignore
        except Exception as exc:
            logger.warning("[UPSTOX] websocket-client unavailable: %s", exc)
            return False

        self._ws_should_reconnect = True

        def _runner() -> None:
            backoff = _WS_RECONNECT_BASE_SECONDS
            while self._ws_should_reconnect:
                try:
                    ws = WebSocketApp(
                        self.ws_url,
                        header=[f"Authorization: Bearer {self.access_token}"],
                        on_open=lambda _ws: logger.info("[UPSTOX] WebSocket connected"),
                        on_message=lambda _ws, message: on_message(message),
                        on_error=lambda _ws, error: logger.warning("[UPSTOX] WebSocket error: %s", error),
                        on_close=lambda _ws, *_args: logger.info("[UPSTOX] WebSocket closed"),
                    )
                    self._ws = ws
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as exc:
                    logger.warning("[UPSTOX] WebSocket loop error: %s", exc)
                if not self._ws_should_reconnect:
                    break
                time.sleep(backoff)
                backoff = min(backoff * 2, _WS_RECONNECT_MAX_SECONDS)

        if self._ws_thread and self._ws_thread.is_alive():
            return True
        self._ws_thread = threading.Thread(target=_runner, daemon=True)
        self._ws_thread.start()
        return True

    def unsubscribe(self, tokens) -> bool:
        normalized = {str(token).strip() for token in tokens if str(token).strip()}
        with self._session_lock:
            self._ws_tokens.difference_update(normalized)
        return True

    @staticmethod
    def _extract_tokens(token_list) -> list[str]:
        normalized: list[str] = []
        if not token_list:
            return normalized
        if isinstance(token_list, (list, tuple, set)):
            for item in token_list:
                if isinstance(item, dict):
                    for token in item.get("tokens", []):
                        token_str = str(token).strip()
                        if token_str and token_str not in normalized:
                            normalized.append(token_str)
                else:
                    token_str = str(item).strip()
                    if token_str and token_str not in normalized:
                        normalized.append(token_str)
        else:
            token_str = str(token_list).strip()
            if token_str:
                normalized.append(token_str)
        return normalized
