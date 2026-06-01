from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

from stockai_shared.cache.redis_client import (
    clear_session_sync,
    get_session_token_sync,
    store_session_token_sync,
)

logger = logging.getLogger(__name__)


class TokenManager:
    """Redis-backed SmartAPI token lifecycle manager.

    Design goals:
    - single refresh/login critical section across threads
    - async API surface without event-loop-bound locks
    - robust response parsing for SmartAPI inconsistencies
    """

    def __init__(
        self,
        *,
        login_callable: Optional[Callable[..., Any]] = None,
        refresh_callable: Optional[Callable[..., Any]] = None,
        validate_callable: Optional[Callable[..., Any]] = None,
        feed_token_callable: Optional[Callable[..., Any]] = None,
        on_session_update: Optional[Callable[[dict[str, Any]], Any]] = None,
        session_max_age_seconds: int = 3300,
        refresh_leeway_seconds: int = 120,
        max_retries: int = 3,
        validation_cache_seconds: int = 20,
        failure_cooldown_seconds: int = 60,
    ) -> None:
        self._login_callable = login_callable
        self._refresh_callable = refresh_callable
        self._validate_callable = validate_callable
        self._feed_token_callable = feed_token_callable
        self._on_session_update = on_session_update
        self._session_max_age_seconds = max(300, int(session_max_age_seconds))
        self._refresh_leeway_seconds = max(30, int(refresh_leeway_seconds))
        self._max_retries = max(1, int(max_retries))
        self._validation_cache_seconds = max(0, int(validation_cache_seconds))
        self._failure_cooldown_seconds = max(1, int(failure_cooldown_seconds))
        self._mutex = threading.Lock()
        self._session: Optional[dict[str, Any]] = None
        self._last_validation_epoch: float = 0.0
        self._blocked_until_monotonic: float = 0.0
        self._manual_relogin_required: bool = False

    def _check_cooldown(self) -> None:
        now = time.monotonic()
        if now < self._blocked_until_monotonic:
            wait = round(self._blocked_until_monotonic - now, 2)
            raise RuntimeError(f"Token cooldown active ({wait}s)")

    def _activate_cooldown(self) -> None:
        self._blocked_until_monotonic = time.monotonic() + self._failure_cooldown_seconds

    def _clear_cooldown(self) -> None:
        self._blocked_until_monotonic = 0.0

    def _raise_if_manual_relogin_required(self) -> None:
        if self._manual_relogin_required:
            raise RuntimeError(
                "SmartAPI manual relogin required: refresh token is invalid/revoked"
            )

    @staticmethod
    def _run_awaitable_sync(awaitable: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result["value"] = asyncio.run(awaitable)
            except BaseException as exc:  # pragma: no cover - defensive path
                error["exc"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()

        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    @staticmethod
    def _parse_epoch(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return 0.0
            try:
                return float(raw)
            except ValueError:
                pass

            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0

        return 0.0

    def _normalize_session_payload(
        self,
        payload: Any,
        *,
        fallback_refresh_token: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(payload, dict):
            return None

        data = payload.get("data", {})
        if not isinstance(data, dict):
            data = {}

        jwt_token = str(
            data.get("jwtToken")
            or data.get("authToken")
            or payload.get("jwtToken")
            or payload.get("authToken")
            or ""
        ).strip()
        refresh_token = str(
            data.get("refreshToken")
            or payload.get("refreshToken")
            or fallback_refresh_token
            or ""
        ).strip()
        feed_raw = data.get("feedToken", payload.get("feedToken"))
        feed_token = str(feed_raw).strip() if feed_raw not in (None, "") else None
        expiry = self._parse_epoch(
            data.get("expiry")
            or data.get("expiresEpoch")
            or data.get("expiresAt")
            or payload.get("expiry")
            or payload.get("expiresEpoch")
            or payload.get("expiresAt")
        )
        if expiry <= 0:
            expiry = time.time() + self._session_max_age_seconds

        if not jwt_token or not refresh_token:
            return None

        return {
            "jwtToken": jwt_token,
            "refreshToken": refresh_token,
            "feedToken": feed_token,
            "expiry": int(expiry),
        }

    def _is_session_fresh(self, session: Optional[dict[str, Any]]) -> bool:
        if not isinstance(session, dict):
            return False

        jwt_token = str(session.get("jwtToken") or "").strip()
        refresh_token = str(session.get("refreshToken") or "").strip()
        expiry = self._parse_epoch(session.get("expiry"))

        if not jwt_token or not refresh_token:
            return False
        return expiry > (time.time() + self._refresh_leeway_seconds)

    def _call_maybe_async_sync(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return self._run_awaitable_sync(result)
        return result

    def _invoke_login(self, *, force: bool) -> Any:
        if not callable(self._login_callable):
            raise RuntimeError("TokenManager login callable is not configured")

        return self._call_maybe_async_sync(self._login_callable, force=force)

    def _invoke_refresh(self, refresh_token: str) -> Any:
        if not callable(self._refresh_callable):
            raise RuntimeError("TokenManager refresh callable is not configured")

        return self._call_maybe_async_sync(self._refresh_callable, refresh_token)

    def _resolve_feed_token(self, current: Optional[str]) -> Optional[str]:
        if current:
            return current

        if not callable(self._feed_token_callable):
            return None

        try:
            resolved = self._call_maybe_async_sync(self._feed_token_callable)
            return str(resolved).strip() if resolved else None
        except Exception as exc:
            logger.debug("[TOKEN] feed token resolver failed: %s", exc)
            return None

    def _apply_session(self, session: dict[str, Any]) -> None:
        self._session = dict(session)
        if not callable(self._on_session_update):
            return

        try:
            self._call_maybe_async_sync(self._on_session_update, dict(session))
        except Exception as exc:
            logger.warning("[TOKEN] Session update hook failed: %s", exc)

    def _persist_and_apply(
        self,
        session: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        session = dict(session)
        session["feedToken"] = self._resolve_feed_token(session.get("feedToken"))
        store_session_token_sync(session)
        self._apply_session(session)
        self._manual_relogin_required = False

        if source == "login":
            logger.info("[TOKEN] Login success")
        elif source == "refresh":
            logger.info("[TOKEN] Refresh success")

        self._clear_cooldown()

        return session

    def _load_cached_session(self) -> Optional[dict[str, Any]]:
        if self._is_session_fresh(self._session):
            return dict(self._session or {})

        cached = get_session_token_sync()
        if cached is None:
            return None

        normalized = self._normalize_session_payload(cached)
        if not normalized:
            clear_session_sync()
            return None

        self._session = dict(normalized)
        return normalized

    def _validate_cached_session(self, session: dict[str, Any]) -> bool:
        if not callable(self._validate_callable):
            return True

        now = time.time()
        if (
            self._validation_cache_seconds > 0
            and (now - self._last_validation_epoch) < self._validation_cache_seconds
        ):
            return True

        try:
            try:
                result = self._call_maybe_async_sync(self._validate_callable, dict(session))
            except TypeError:
                result = self._call_maybe_async_sync(
                    self._validate_callable,
                    session.get("jwtToken"),
                    session.get("refreshToken"),
                )
        except Exception as exc:
            logger.warning("[TOKEN] Validation probe failed; keeping token: %s", exc)
            return self._is_session_fresh(session)

        is_valid = bool(result)
        if is_valid:
            self._last_validation_epoch = now
        return is_valid

    def _backoff(self, attempt: int) -> None:
        if attempt >= self._max_retries:
            return
        time.sleep(float(2 ** (attempt - 1)))

    @staticmethod
    def _response_error(response: Any) -> tuple[str, str]:
        if isinstance(response, dict):
            code = str(response.get("errorcode") or response.get("errorCode") or "")
            msg = str(response.get("message") or "")
            return code, msg
        return "", f"unexpected response type: {type(response).__name__}"

    def _login_locked(self, *, force: bool) -> dict[str, Any]:
        self._raise_if_manual_relogin_required()

        if not force:
            cached = self._load_cached_session()
            if cached and self._is_session_fresh(cached):
                if self._validate_cached_session(cached):
                    self._apply_session(cached)
                    logger.info("[TOKEN] Using cached token")
                    return dict(cached)
                logger.info(
                    "[TOKEN] Cached token failed validation; clearing stale cached session"
                )
                try:
                    clear_session_sync()
                except Exception as exc:
                    logger.debug("[TOKEN] Failed to clear invalid cached token: %s", exc)
                self._session = None
                self._last_validation_epoch = 0.0

        last_error = "no response"
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._invoke_login(force=True)
                normalized = self._normalize_session_payload(response)
                if normalized:
                    return self._persist_and_apply(normalized, source="login")

                code, msg = self._response_error(response)
                last_error = f"code={code} message={msg}"
                logger.warning(
                    "[TOKEN] Login failed attempt=%d/%d %s",
                    attempt,
                    self._max_retries,
                    last_error,
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[TOKEN] Login exception attempt=%d/%d %s",
                    attempt,
                    self._max_retries,
                    exc,
                )

            self._backoff(attempt)

        self._blocked_until_monotonic = time.monotonic() + self._failure_cooldown_seconds
        raise RuntimeError(f"SmartAPI login failed after retries: {last_error}")

    def _refresh_locked(self) -> Optional[dict[str, Any]]:
        cached = self._load_cached_session()
        refresh_token = str((cached or {}).get("refreshToken") or "").strip()
        if not refresh_token:
            logger.warning("[TOKEN] Refresh token missing; relogin required")
            return None

        last_error = ""
        is_stale_token = False
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._invoke_refresh(refresh_token)
                normalized = self._normalize_session_payload(
                    response,
                    fallback_refresh_token=refresh_token,
                )

                if normalized:
                    if not normalized.get("feedToken") and cached:
                        normalized["feedToken"] = cached.get("feedToken")
                    return self._persist_and_apply(normalized, source="refresh")

                code, msg = self._response_error(response)
                last_error = f"code={code} message={msg}"
                logger.warning(
                    "[TOKEN] Refresh failed attempt=%d/%d %s",
                    attempt,
                    self._max_retries,
                    last_error,
                )

                lowered = msg.lower()
                if code == "AG8001" or "invalid token" in lowered or code == "AG8003":
                    is_stale_token = True
                    logger.error(
                        "[TOKEN] Broker rejected refresh token as invalid (AG8001/AG8003). "
                        "Token is stale or revoked. Clearing cached session. "
                        "Relogin required. Error: %s", last_error
                    )
                    clear_session_sync()
                    self._session = None
                    self._manual_relogin_required = False
                    break

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[TOKEN] Refresh exception attempt=%d/%d %s",
                    attempt,
                    self._max_retries,
                    exc,
                )

            self._backoff(attempt)

        if is_stale_token:
            logger.warning("[TOKEN] Stale refresh token invalidated; attempting controlled relogin.")
        elif last_error:
            logger.warning("[TOKEN] Refresh failed -> relogin (%s)", last_error)
        else:
            logger.warning("[TOKEN] Refresh failed -> relogin")
        return None

    async def login(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.login_sync)

    async def refresh_token(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.refresh_token_sync)

    async def force_relogin(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.force_relogin_sync)

    async def get_valid_token(self) -> str:
        return await asyncio.to_thread(self.get_valid_token_sync)

    async def get_cached_session(self) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_cached_session_sync)

    async def persist_session(
        self,
        *,
        jwt_token: str,
        refresh_token: str,
        feed_token: Optional[str] = None,
        expiry: Optional[float] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.persist_session_sync,
            jwt_token=jwt_token,
            refresh_token=refresh_token,
            feed_token=feed_token,
            expiry=expiry,
        )

    async def clear_cached_session(self) -> None:
        await asyncio.to_thread(self.clear_cached_session_sync)

    def login_sync(self) -> dict[str, Any]:
        with self._mutex:
            self._check_cooldown()
            return self._login_locked(force=False)

    def get_valid_token_sync(self) -> str:
        with self._mutex:
            self._check_cooldown()
            self._raise_if_manual_relogin_required()

            cached = self._load_cached_session()
            if cached and self._is_session_fresh(cached):
                self._apply_session(cached)
                logger.info("[TOKEN] Using cached token")
                return str(cached.get("jwtToken") or "")

            refreshed = self._refresh_locked()
            if refreshed:
                return str(refreshed.get("jwtToken") or "")

            self._raise_if_manual_relogin_required()

            relogin_session = self._login_locked(force=True)
            return str(relogin_session.get("jwtToken") or "")

    def refresh_token_sync(self) -> dict[str, Any]:
        with self._mutex:
            self._check_cooldown()
            self._raise_if_manual_relogin_required()

            refreshed = self._refresh_locked()
            if refreshed:
                return refreshed

            self._raise_if_manual_relogin_required()
            return self._login_locked(force=True)

    def force_relogin_sync(self) -> dict[str, Any]:
        with self._mutex:
            clear_session_sync()
            self._session = None
            self._manual_relogin_required = False
            self._clear_cooldown()
            logger.info("[TOKEN] Force relogin requested")
            return self._login_locked(force=True)

    def get_cached_session_sync(self) -> Optional[dict[str, Any]]:
        with self._mutex:
            cached = self._load_cached_session()
            return dict(cached) if cached else None

    def persist_session_sync(
        self,
        *,
        jwt_token: str,
        refresh_token: str,
        feed_token: Optional[str] = None,
        expiry: Optional[float] = None,
    ) -> dict[str, Any]:
        payload = self._normalize_session_payload(
            {
                "jwtToken": jwt_token,
                "refreshToken": refresh_token,
                "feedToken": feed_token,
                "expiry": expiry,
            },
            fallback_refresh_token=refresh_token,
        )
        if not payload:
            raise ValueError("Invalid session payload")

        with self._mutex:
            return self._persist_and_apply(payload, source="manual")

    def clear_cached_session_sync(self) -> None:
        with self._mutex:
            clear_session_sync()
            self._session = None
