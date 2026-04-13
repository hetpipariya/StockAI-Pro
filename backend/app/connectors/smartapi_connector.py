"""
SmartAPI (AngelOne) connector — production-ready singleton.
Login, historical data, WebSocket, orders.
Credentials from .env; never hardcode.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from dotenv import load_dotenv

from app.services.token_manager import TokenManager

load_dotenv()

logger = logging.getLogger(__name__)


def _configure_smartapi_library_logging() -> None:
    # Suppress noisy SmartApi internals while keeping app-level logs visible.
    for logger_name in (
        "SmartApi",
        "smartapi",
        "smartConnect",
        "logzero",
    ):
        lib_logger = logging.getLogger(logger_name)
        lib_logger.setLevel(logging.CRITICAL)
        lib_logger.propagate = False
        lib_logger.disabled = True

    try:
        import logzero  # type: ignore
        from logzero import logger as logzero_logger  # type: ignore

        logzero.loglevel(logging.CRITICAL)
        logzero_logger.handlers.clear()
        logzero_logger.propagate = False
        logzero_logger.disabled = True
    except Exception:
        pass


_configure_smartapi_library_logging()

# ─── Interval mapping for SmartAPI getCandleData ───
INTERVAL_MAP = {
    "1m": "ONE_MINUTE",
    "3m": "THREE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h": "ONE_HOUR",
    "1d": "ONE_DAY",
}

# Rate limiter: SmartAPI allows ~3 requests/second
_api_lock = threading.Lock()
_last_api_call = 0.0
_MIN_API_INTERVAL = 0.34  # seconds between API calls
_SESSION_MAX_AGE_SECONDS = int(os.getenv("SMARTAPI_SESSION_MAX_AGE_SECONDS", "3300"))
_SESSION_REFRESH_LEEWAY_SECONDS = 120
_AUTH_FAILURE_THRESHOLD = max(
    2, int(os.getenv("SMARTAPI_AUTH_FAILURE_THRESHOLD", "3"))
)
_AUTH_FAILURE_WINDOW_SECONDS = max(
    10.0, float(os.getenv("SMARTAPI_AUTH_FAILURE_WINDOW_SECONDS", "90"))
)
_AUTH_SUSPEND_SECONDS = max(
    30.0, float(os.getenv("SMARTAPI_AUTH_SUSPEND_SECONDS", "180"))
)


def _rate_limit():
    """Enforce minimum interval between SmartAPI REST calls."""
    global _last_api_call
    with _api_lock:
        now = time.monotonic()
        wait = _MIN_API_INTERVAL - (now - _last_api_call)
        if wait > 0:
            time.sleep(wait)
        _last_api_call = time.monotonic()


@dataclass
class TickData:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: str


class SmartAPIConnector:
    """
    Production SmartAPI REST + WebSocket connector.
    Thread-safe singleton with auto-relogin on token expiry.
    """

    _instance: Optional["SmartAPIConnector"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton: always return the same instance."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        client_pwd: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ):
        if self._initialized:
            return
        self.api_key = api_key or os.getenv("SMARTAPI_API_KEY", "")
        self.client_id = client_id or os.getenv("SMARTAPI_CLIENT_ID", "")
        self.client_pwd = client_pwd or os.getenv("SMARTAPI_CLIENT_PWD", "")
        self.totp_secret = totp_secret or os.getenv("SMARTAPI_TOTP_SECRET", "")
        self._obj = None
        self._auth_token: Optional[str] = None
        self._feed_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._login_time: Optional[float] = None
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_reconnect_delay: float = 1.0
        self._ws_should_reconnect: bool = True
        self._ws_tokens: set[str] = set()
        self._login_lock = threading.Lock()
        self._session_lock = threading.RLock()
        self._session_expiry_epoch: float = 0.0
        self._auth_failure_count: int = 0
        self._auth_failure_window_start: float = 0.0
        self._auth_suspended_until: float = 0.0
        self._token_manager = TokenManager(
            login_callable=self._broker_login,
            refresh_callable=self._broker_refresh,
            validate_callable=self._validate_cached_session,
            feed_token_callable=self._broker_feed_token,
            on_session_update=self._on_token_session_update,
            session_max_age_seconds=_SESSION_MAX_AGE_SECONDS,
            refresh_leeway_seconds=_SESSION_REFRESH_LEEWAY_SECONDS,
            max_retries=3,
        )
        self._initialized = True
        logger.info("[SMARTAPI] Connector initialized (singleton)")

    # ─── Properties ───

    @property
    def is_logged_in(self) -> bool:
        return self._obj is not None and self._auth_token is not None

    @property
    def session_age_minutes(self) -> float:
        if not self._login_time:
            return float("inf")
        return (time.monotonic() - self._login_time) / 60

    # ─── Auth helpers ───

    def _get_totp(self) -> str:
        import pyotp

        return pyotp.TOTP(self.totp_secret or "").now()

    def _create_client(self):
        from SmartApi import SmartConnect

        self._obj = SmartConnect(self.api_key)
        self._apply_tokens_to_client()

    def _apply_tokens_to_client(self) -> None:
        if not self._obj:
            return

        if self._auth_token:
            for method_name in ("setAccessToken", "set_access_token"):
                if hasattr(self._obj, method_name):
                    try:
                        getattr(self._obj, method_name)(self._auth_token)
                    except Exception:
                        pass

        if self._refresh_token:
            for method_name in ("setRefreshToken", "set_refresh_token"):
                if hasattr(self._obj, method_name):
                    try:
                        getattr(self._obj, method_name)(self._refresh_token)
                    except Exception:
                        pass

    def _cache_session(self) -> None:
        if not (self._auth_token and self._refresh_token):
            return
        try:
            self._token_manager.persist_session_sync(
                jwt_token=self._auth_token,
                refresh_token=self._refresh_token,
                feed_token=self._feed_token,
                expiry=self._session_expiry_epoch,
            )
        except Exception as exc:
            logger.warning("[SMARTAPI] Failed to cache session in Redis: %s", exc)

    def _clear_cached_session(self) -> None:
        try:
            self._token_manager.clear_cached_session_sync()
        except Exception as exc:
            logger.warning("[SMARTAPI] Failed to clear cached session: %s", exc)

    def _on_token_session_update(self, session: dict[str, Any]) -> None:
        auth_token = str(session.get("jwtToken") or "").strip()
        refresh_token = str(session.get("refreshToken") or "").strip()
        if not auth_token or not refresh_token:
            return

        feed_token = str(session.get("feedToken") or "").strip() or None
        expiry = float(session.get("expiry") or 0.0)

        with self._session_lock:
            self._auth_token = auth_token
            self._refresh_token = refresh_token
            self._feed_token = feed_token
            self._login_time = time.monotonic()
            self._session_expiry_epoch = (
                float(expiry)
                if expiry and expiry > 0
                else time.time() + _SESSION_MAX_AGE_SECONDS
            )
            if self._obj is None:
                self._create_client()
            self._apply_tokens_to_client()

    def _sync_session_from_token_manager(self) -> bool:
        session = self._token_manager.get_cached_session_sync()
        if not session:
            return False
        self._on_token_session_update(session)
        return True

    def _broker_login(self, force: bool = False) -> Any:
        if not all([self.api_key, self.client_id, self.client_pwd, self.totp_secret]):
            raise ValueError("Missing SmartAPI credentials")

        del force
        with self._session_lock:
            if self._obj is None:
                self._create_client()

        totp = self._get_totp()
        _rate_limit()
        return self._obj.generateSession(self.client_id, self.client_pwd, totp)

    def _broker_refresh(self, refresh_token: str) -> Any:
        refresh_token = str(refresh_token or "").strip()
        if not refresh_token:
            raise ValueError("Missing SmartAPI refresh token")

        with self._session_lock:
            if self._obj is None:
                self._create_client()

        _rate_limit()
        try:
            return self._obj.generateToken(refresh_token)
        except TypeError as exc:
            # SmartApi SDK can crash on invalid refresh responses when it assumes
            # response["data"] is a dict but the API returns an empty string.
            if "string indices must be integers" in str(exc):
                return {
                    "status": False,
                    "success": False,
                    "errorCode": "AG8001",
                    "errorcode": "AG8001",
                    "message": "Invalid Token",
                    "data": {},
                }
            raise

    def _broker_feed_token(self) -> Optional[str]:
        with self._session_lock:
            if self._obj and hasattr(self._obj, "getfeedToken"):
                try:
                    token = self._obj.getfeedToken()
                    if token:
                        return str(token)
                except Exception as exc:
                    logger.debug("[TOKEN] getfeedToken failed: %s", exc)
        return self._feed_token

    def _probe_session(self) -> Any:
        if self._obj is None:
            return {"status": False, "message": "SmartAPI client not initialized"}

        if hasattr(self._obj, "rmsLimit"):
            _rate_limit()
            return self._obj.rmsLimit()

        if hasattr(self._obj, "position"):
            _rate_limit()
            return self._obj.position()

        if hasattr(self._obj, "getPosition"):
            _rate_limit()
            return self._obj.getPosition()

        if hasattr(self._obj, "getProfile"):
            probe = getattr(self._obj, "getProfile")
            _rate_limit()
            try:
                return probe()
            except TypeError:
                return probe(self._refresh_token)

        return {"status": True}

    def _validate_cached_session(self, session: dict[str, Any]) -> bool:
        auth_token = str(session.get("jwtToken") or "").strip()
        refresh_token = str(session.get("refreshToken") or "").strip()
        if not auth_token or not refresh_token:
            return False

        with self._session_lock:
            previous_auth = self._auth_token
            previous_refresh = self._refresh_token
            previous_feed = self._feed_token
            previous_login_time = self._login_time
            previous_expiry = self._session_expiry_epoch

            self._on_token_session_update(session)

        try:
            probe = self._probe_session()
        except Exception as exc:
            logger.warning("[TOKEN] Validation probe exception: %s", exc)
            probe = {"status": False, "message": str(exc)}

        is_valid = False
        if isinstance(probe, dict):
            message = str(probe.get("message") or "")
            error_code = str(probe.get("errorcode") or probe.get("errorCode") or "")
            lowered = message.lower()
            if error_code in ("AG8001", "AG8003"):
                session_age = self.session_age_minutes
                logger.info(
                    "[TOKEN] Cached broker token rejected (AG8001/AG8003); clearing stale session. "
                    "Session age: %.1f minutes.",
                    session_age,
                )
                is_valid = False
            elif "invalid token" in lowered or "token missing" in lowered:
                logger.info("[TOKEN] Cached token invalid or missing; refreshing session")
                is_valid = False
            else:
                status_value = probe.get("status")
                success_value = probe.get("success")
                data_value = probe.get("data")

                if status_value is not None:
                    is_valid = bool(status_value)
                elif success_value is not None:
                    is_valid = bool(success_value)
                elif data_value not in (None, "", [], {}):
                    is_valid = True
                else:
                    is_valid = True
        elif isinstance(probe, list):
            is_valid = True
        else:
            is_valid = bool(probe)

        if not is_valid:
            with self._session_lock:
                self._auth_token = previous_auth
                self._refresh_token = previous_refresh
                self._feed_token = previous_feed
                self._login_time = previous_login_time
                self._session_expiry_epoch = previous_expiry
                self._apply_tokens_to_client()

        return is_valid

    def _session_needs_refresh(self) -> bool:
        if not self._auth_token or not self._refresh_token:
            return True
        if not self._login_time:
            return True

        age_seconds = time.monotonic() - self._login_time
        if age_seconds >= _SESSION_MAX_AGE_SECONDS:
            return True

        if self._session_expiry_epoch > 0 and self._session_expiry_epoch <= (
            time.time() + _SESSION_REFRESH_LEEWAY_SECONDS
        ):
            return True

        return False

    def _is_auth_suspended(self) -> bool:
        with self._session_lock:
            return time.monotonic() < self._auth_suspended_until

    def _raise_if_auth_suspended(self) -> None:
        with self._session_lock:
            now = time.monotonic()
            if now >= self._auth_suspended_until:
                return
            wait = round(self._auth_suspended_until - now, 2)
        raise RuntimeError(f"SmartAPI auth temporarily suspended ({wait}s)")

    def _record_auth_success(self) -> None:
        with self._session_lock:
            if (
                self._auth_failure_count == 0
                and self._auth_failure_window_start == 0.0
                and self._auth_suspended_until == 0.0
            ):
                return

            self._auth_failure_count = 0
            self._auth_failure_window_start = 0.0
            self._auth_suspended_until = 0.0

    def _record_auth_failure(self, *, context: str, detail: str = "") -> None:
        should_open_breaker = False

        with self._session_lock:
            now = time.monotonic()
            if (
                self._auth_failure_window_start <= 0.0
                or (now - self._auth_failure_window_start) > _AUTH_FAILURE_WINDOW_SECONDS
            ):
                self._auth_failure_window_start = now
                self._auth_failure_count = 0

            self._auth_failure_count += 1

            if self._auth_failure_count >= _AUTH_FAILURE_THRESHOLD:
                self._auth_suspended_until = now + _AUTH_SUSPEND_SECONDS
                self._auth_failure_count = 0
                self._auth_failure_window_start = 0.0
                should_open_breaker = True

        if should_open_breaker:
            logger.error(
                "[SMARTAPI] Auth circuit breaker opened for %.0fs after repeated token failures (%s%s)",
                _AUTH_SUSPEND_SECONDS,
                context,
                f": {detail}" if detail else "",
            )
            self._clear_cached_session()

    # ─── Login / Session ───

    def login(self, force: bool = False) -> dict:
        """
        Login to SmartAPI. Thread-safe with retry.
        Returns session data dict.
        """
        with self._login_lock:
            return self._login_impl(force)

    def _login_impl(self, force: bool = False) -> dict:
        if force:
            session = self._token_manager.force_relogin_sync()
        else:
            session = self._token_manager.login_sync()

        if not isinstance(session, dict):
            raise RuntimeError("SmartAPI login returned invalid session payload")

        self._on_token_session_update(session)
        return {
            "status": True,
            "authToken": self._auth_token,
            "jwtToken": self._auth_token,
            "refreshToken": self._refresh_token,
            "feedToken": self._feed_token,
        }

    def _ensure_login(self):
        """Ensure a valid SmartAPI session exists for the next API call."""
        self._raise_if_auth_suspended()

        with self._session_lock:
            if self._obj is None:
                self._create_client()

        if self._session_needs_refresh():
            logger.info("[TOKEN] Session missing/expired; validating token")

        token = self._token_manager.get_valid_token_sync()
        if not token:
            raise RuntimeError("SmartAPI token manager returned empty token")

        self._sync_session_from_token_manager()

    def _refresh_session(self, relogin_on_fail: bool = True) -> bool:
        """Refresh token with retries; optionally fallback to full login."""
        with self._login_lock:
            try:
                session = self._token_manager.refresh_token_sync()
                if isinstance(session, dict):
                    self._on_token_session_update(session)
                    return True
                return False
            except Exception as exc:
                logger.warning("[TOKEN] Refresh failed: %s", exc)
                lowered = str(exc).lower()
                if "manual relogin required" in lowered:
                    logger.warning(
                        "[TOKEN] Manual broker re-login required; skipping automatic relogin"
                    )
                    return False
                if not relogin_on_fail:
                    return False

                logger.warning("[TOKEN] Refresh failed -> relogin")
                try:
                    session = self._token_manager.force_relogin_sync()
                    if isinstance(session, dict):
                        self._on_token_session_update(session)
                        return True
                except Exception as relogin_exc:
                    logger.error("[TOKEN] Re-login after refresh failure failed: %s", relogin_exc)

                return False

    @staticmethod
    def _is_token_error_response(resp: dict[str, Any]) -> bool:
        if not isinstance(resp, dict):
            return False

        msg = str(resp.get("message") or "")
        code = str(resp.get("errorcode") or resp.get("errorCode") or "")
        lowered = msg.lower()
        return (
            code in ("AG8001", "AG8003")
            or "invalid token" in lowered
            or "token missing" in lowered
            or "token expired" in lowered
        )

    def _handle_api_error(self, resp: dict, context: str) -> bool:
        """
        Check response for retryable errors. Returns True if caller should retry.
        AG8001 = Invalid Token (expired session)
        AG8002 = Rate limit exceeded
        """
        if not resp or not isinstance(resp, dict):
            return False
        msg = str(resp.get("message") or "")
        error_code = str(resp.get("errorcode") or resp.get("errorCode") or "")
        lowered = msg.lower()

        if self._is_token_error_response(resp):
            detail = f"{error_code} {msg}".strip()
            self._record_auth_failure(context=context, detail=detail)

            if self._is_auth_suspended():
                logger.error(
                    "[SMARTAPI] %s: auth suspended after repeated token errors; skipping refresh",
                    context,
                )
                return False

            logger.warning(
                f"[SMARTAPI] {context}: token expired ({error_code}), refreshing session"
            )
            refreshed = self._refresh_session(relogin_on_fail=True)
            if not refreshed:
                self._record_auth_failure(
                    context=context,
                    detail="refresh/relogin failed",
                )
            return refreshed

        if error_code == "AG8002" or "rate" in lowered:
            logger.warning(f"[SMARTAPI] {context}: rate limited, waiting 1s")
            time.sleep(1)
            return True

        return False

    # ─── Historical Data ───

    def fetch_history(
        self,
        symbol_token: str,
        exchange: str = "NSE",
        interval: str = "1m",
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 500,
    ) -> list:
        """
        Fetch historical OHLCV candles from SmartAPI.
        symbol_token: numeric AngelOne instrument token (e.g. '2881' for RELIANCE)
        Returns list of [timestamp, open, high, low, close, volume]
        """
        self._ensure_login()
        interval_api = INTERVAL_MAP.get(interval, "ONE_MINUTE")

        if not to_date:
            to_date = datetime.now()
        if not from_date:
            # Use 7 days for intraday to guarantee hitting trading days (weekends/holidays)
            if interval_api in (
                "ONE_MINUTE",
                "THREE_MINUTE",
                "FIVE_MINUTE",
                "FIFTEEN_MINUTE",
                "THIRTY_MINUTE",
            ):
                from_date = to_date - timedelta(days=7)
            else:
                from_date = to_date - timedelta(days=30)
        if from_date >= to_date:
            from_date = to_date - timedelta(days=2)

        # Clamp date range to SmartAPI limits
        if interval_api in (
            "ONE_MINUTE",
            "THREE_MINUTE",
            "FIVE_MINUTE",
            "FIFTEEN_MINUTE",
            "THIRTY_MINUTE",
        ):
            max_days = 60
        elif interval_api == "ONE_HOUR":
            max_days = 730
        else:
            max_days = 2000

        days_diff = (to_date - from_date).days
        if days_diff > max_days:
            from_date = to_date - timedelta(days=max_days)

        fd = from_date.strftime("%Y-%m-%d %H:%M")
        td = to_date.strftime("%Y-%m-%d %H:%M")

        params = {
            "exchange": exchange,
            "symboltoken": str(symbol_token),
            "interval": interval_api,
            "fromdate": fd,
            "todate": td,
        }

        logger.info(
            f"[SMARTAPI] getCandleData: token={symbol_token}, interval={interval_api}, {fd} → {td}"
        )

        for attempt in range(3):
            try:
                _rate_limit()
                t0 = time.monotonic()
                resp = self._obj.getCandleData(params)
                elapsed = (time.monotonic() - t0) * 1000
                logger.info(f"[SMARTAPI] getCandleData took {elapsed:.0f}ms")
            except Exception as e:
                logger.warning(
                    f"[SMARTAPI] getCandleData error (attempt {attempt + 1}): {e}"
                )
                if attempt < 2 and not self._is_auth_suspended():
                    self._refresh_session()
                    time.sleep(1)
                    continue
                return []

            if not resp:
                logger.warning(
                    f"[SMARTAPI] getCandleData returned None or empty (attempt {attempt + 1})"
                )
                if attempt < 2:
                    time.sleep(1)
                    continue
                return []

            if isinstance(resp, dict):
                if self._handle_api_error(resp, "getCandleData") and attempt < 2:
                    continue

                if self._is_token_error_response(resp):
                    logger.error(
                        "[SMARTAPI] getCandleData token invalid; skipping retries until re-login"
                    )
                    return []

                if not resp.get("status"):
                    logger.error(
                        f"[SMARTAPI] getCandleData error: {resp.get('message', 'Unknown')}"
                    )
                    if attempt < 2:
                        time.sleep(1)
                        continue
                    return []
                data = resp.get("data", [])
            elif isinstance(resp, list):
                data = resp
            else:
                logger.warning(f"[SMARTAPI] Unexpected response type: {type(resp)}")
                return []

            if data and len(data) > 0:
                logger.info(
                    f"[SMARTAPI] Got {len(data)} candles (Requested Limit: {limit})"
                )
                self._record_auth_success()
                return data[-limit:]
            else:
                logger.warning(
                    f"[SMARTAPI] Empty candle data returned from valid response (attempt {attempt + 1})"
                )
                if attempt < 2:
                    time.sleep(1.5)
                    continue
                return []

        return []

    # ─── LTP Snapshot ───

    def get_ltp(
        self, symbol_token: str, exchange: str = "NSE", tradingsymbol: str = ""
    ) -> Optional[dict]:
        """Get latest price snapshot. tradingsymbol e.g. RELIANCE-EQ."""
        self._ensure_login()
        ts = tradingsymbol or f"{symbol_token}-EQ"
        token_str = str(symbol_token)

        # Method 1: ltpData — try positional args first (new SDK), then dict (old SDK)
        if hasattr(self._obj, "ltpData"):
            for attempt in range(2):
                try:
                    _rate_limit()
                    # New SDK signature: ltpData(exchange, tradingsymbol, symboltoken)
                    try:
                        resp = self._obj.ltpData(exchange, ts, token_str)
                    except TypeError:
                        # Old SDK signature: ltpData({"exchange": ..., ...})
                        resp = self._obj.ltpData(
                            {
                                "exchange": exchange,
                                "tradingsymbol": ts,
                                "symboltoken": token_str,
                            }
                        )
                    if resp and isinstance(resp, dict):
                        if resp.get("status") and resp.get("data"):
                            logger.info("[SMARTAPI] LTP via ltpData OK")
                            self._record_auth_success()
                            return resp["data"]
                        if attempt == 0 and self._handle_api_error(resp, "ltpData"):
                            continue
                        if self._is_token_error_response(resp):
                            logger.warning(
                                "[SMARTAPI] ltpData token invalid; skipping remaining broker LTP methods"
                            )
                            return None
                except Exception as e:
                    logger.warning(
                        f"[SMARTAPI] ltpData failed (attempt {attempt + 1}): {e}"
                    )
                    if attempt == 0 and not self._is_auth_suspended():
                        self._refresh_session()
                break  # Don't retry if we got a non-retryable response

        # Method 2: getMarketData — new SDK needs (mode, {"NSE": [token]})
        if hasattr(self._obj, "getMarketData"):
            for attempt in range(2):
                try:
                    _rate_limit()
                    exchange_tokens = {exchange: [token_str]}
                    # New SDK: getMarketData(mode, exchangeTokens)
                    try:
                        resp = self._obj.getMarketData("LTP", exchange_tokens)
                    except TypeError:
                        resp = self._obj.getMarketData(
                            {"mode": "LTP", "exchangeTokens": exchange_tokens}
                        )
                    if resp and isinstance(resp, dict):
                        if resp.get("status") and resp.get("data"):
                            logger.info("[SMARTAPI] LTP via getMarketData OK")
                            self._record_auth_success()
                            # getMarketData returns {"fetched": [...], "unfetched": [...]}
                            fetched = resp["data"].get("fetched", [])
                            if fetched:
                                item = fetched[0]
                                return {
                                    "ltp": float(item.get("ltp", 0)),
                                    "open": float(item.get("open", 0)),
                                    "high": float(item.get("high", 0)),
                                    "low": float(item.get("low", 0)),
                                    "close": float(
                                        item.get("close", item.get("ltp", 0))
                                    ),
                                    "volume": int(
                                        item.get("volume", item.get("tradeVolume", 0))
                                        or 0
                                    ),
                                }
                            # If data is directly the LTP dict (old format)
                            if "ltp" in resp["data"]:
                                self._record_auth_success()
                                return resp["data"]
                        if attempt == 0 and self._handle_api_error(
                            resp, "getMarketData"
                        ):
                            continue
                        if self._is_token_error_response(resp):
                            logger.warning(
                                "[SMARTAPI] getMarketData token invalid; skipping remaining broker LTP methods"
                            )
                            return None
                except Exception as e:
                    logger.warning(
                        f"[SMARTAPI] getMarketData failed (attempt {attempt + 1}): {e}"
                    )
                    if attempt == 0 and not self._is_auth_suspended():
                        self._refresh_session()
                break

        # Fallback: derive from latest 1m candle
        if self._is_auth_suspended():
            logger.warning(
                "[SMARTAPI] LTP fallback skipped while auth is suspended; waiting for broker re-login"
            )
            return None

        try:
            logger.info("[SMARTAPI] LTP fallback: fetching latest 1m candle")
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=3)
            rows = self.fetch_history(symbol_token, exchange, "1m", from_dt, to_dt, 1)
            if rows:
                last = rows[-1]
                if isinstance(last, (list, tuple)) and len(last) >= 5:
                    self._record_auth_success()
                    return {
                        "ltp": float(last[4]),
                        "open": float(last[1]),
                        "high": float(last[2]),
                        "low": float(last[3]),
                        "close": float(last[4]),
                        "volume": int(last[5]) if len(last) > 5 else 0,
                    }
                elif isinstance(last, dict):
                    close = float(last.get("4", last.get("close", 0)))
                    self._record_auth_success()
                    return {
                        "ltp": close,
                        "open": float(last.get("1", last.get("open", 0))),
                        "high": float(last.get("2", last.get("high", 0))),
                        "low": float(last.get("3", last.get("low", 0))),
                        "close": close,
                        "volume": int(last.get("5", last.get("volume", 0)) or 0),
                    }
        except Exception as e:
            logger.warning(f"[SMARTAPI] LTP candle fallback failed: {e}")

        logger.error("[SMARTAPI] All LTP methods failed")
        return None

    # ─── WebSocket ───

    def _merge_ws_tokens(self, token_list: list[dict]) -> list[str]:
        new_tokens: list[str] = []
        with self._session_lock:
            for group in token_list:
                for token in group.get("tokens", []):
                    token_str = str(token).strip()
                    if not token_str:
                        continue
                    if token_str not in self._ws_tokens:
                        self._ws_tokens.add(token_str)
                        new_tokens.append(token_str)
        return new_tokens

    def _subscribe_new_tokens(self, tokens: list[str]) -> bool:
        if not tokens:
            return True

        if not self._ws:
            return False

        try:
            correlation_id = f"stockai-pro-inc-{int(time.time())}"
            self._ws.subscribe(
                correlation_id,
                2,
                [{"exchangeType": 1, "tokens": tokens}],
            )
            logger.info("[WS] Added %d new tokens to subscription", len(tokens))
            return True
        except Exception as exc:
            logger.warning("[WS] Incremental subscribe failed: %s", exc)
            return False

    def subscribe_ws_tokens(self, tokens: list[str]) -> bool:
        """Add tokens to active websocket subscription without duplicates."""
        normalized = [str(token).strip() for token in tokens if str(token).strip()]
        if not normalized:
            return True

        new_tokens = self._merge_ws_tokens([{"exchangeType": 1, "tokens": normalized}])
        if not new_tokens:
            return True
        return self._subscribe_new_tokens(new_tokens)

    def start_ws(self, token_list: list[dict], on_message: Callable[[Any], None]):
        """
        Start SmartAPI WebSocket for live ticks.
        token_list: [{"exchangeType": 1, "tokens": ["2881", "3045"]}]
        on_message: callback(msg_dict)
        """
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        self._ensure_login()
        if not self._feed_token:
            logger.warning("[WS] feedToken missing, attempting token refresh")
            self._refresh_session(relogin_on_fail=True)
            if not self._feed_token and self._obj and hasattr(self._obj, "getfeedToken"):
                try:
                    self._feed_token = self._obj.getfeedToken()
                except Exception:
                    self._feed_token = None
            if not self._feed_token:
                logger.error("[WS] No feedToken — cannot start WebSocket")
                return

        new_tokens = self._merge_ws_tokens(token_list)
        if self._ws_thread and self._ws_thread.is_alive():
            if new_tokens:
                self._subscribe_new_tokens(new_tokens)
            return

        correlation_id = "stockai-pro-1"
        mode = 2  # LTP mode (1=LTP, 2=Quote, 3=SnapQuote)

        self._ws_should_reconnect = True
        self._ws_reconnect_delay = 1.0

        def _create_and_run():
            """WebSocket connection loop with full error isolation.

            This runs in a daemon thread and must NEVER crash the main process.
            All exceptions are caught and logged, with automatic reconnection.
            """
            consecutive_errors = 0
            max_consecutive_errors = 5

            while self._ws_should_reconnect:
                try:
                    # Ensure we have valid credentials before connecting
                    if not self._auth_token or not self._feed_token:
                        logger.warning("[WS] Missing tokens, attempting login...")
                        try:
                            self.login(force=True)
                        except Exception as login_err:
                            logger.error(f"[WS] Login failed: {login_err}")
                            time.sleep(5)
                            continue

                    sws = SmartWebSocketV2(
                        self._auth_token,
                        self.api_key,
                        self.client_id,
                        self._feed_token,
                    )

                    def _on_data(wsapp, message):
                        """Handle incoming tick data with full error isolation."""
                        try:
                            on_message(message)
                        except Exception as e:
                            logger.error(f"[WS] Tick handler error: {e}")

                    def _on_open(wsapp):
                        """Handle WebSocket open event."""
                        try:
                            tokens = sorted(self._ws_tokens)
                            token_groups = [{"exchangeType": 1, "tokens": tokens}]
                            logger.info(
                                "[WS] ✓ Connected — subscribing %d tokens",
                                len(tokens),
                            )
                            self._ws_reconnect_delay = 1.0  # Reset backoff
                            if tokens:
                                sws.subscribe(correlation_id, mode, token_groups)
                        except Exception as e:
                            logger.error(f"[WS] on_open handler failed: {e}")

                    def _on_error(wsapp, *args):
                        """Handle WebSocket error event.

                        Using *args ensures compatibility with all SmartAPI versions.
                        """
                        try:
                            error = args[0] if args else "Unknown error"
                            logger.error(f"[WS] Error: {error}")
                            if "AG800" in str(error) or "Invalid Token" in str(error):
                                logger.error(
                                    "[WS] Force clearing session due to Token Error"
                                )
                                self._clear_cached_session()
                                try:
                                    self.login(force=True)
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"[WS] on_error handler failed: {e}")

                    def _on_close(wsapp, *args):
                        """Handle WebSocket close event.

                        SmartAPI SmartWebSocketV2 may call this with varying signatures.
                        Using *args ensures compatibility with all versions.
                        """
                        try:
                            # Extract close_status_code and close_msg from args if present
                            close_status_code = args[0] if len(args) > 0 else None
                            close_msg = args[1] if len(args) > 1 else None

                            logger.info(
                                "[WS] Connection closed: code=%s message=%s",
                                close_status_code,
                                close_msg,
                            )
                            if self._ws_should_reconnect:
                                logger.info(
                                    f"[WS] Reconnecting in {self._ws_reconnect_delay:.1f}s"
                                )
                                time.sleep(self._ws_reconnect_delay)
                                self._ws_reconnect_delay = min(
                                    self._ws_reconnect_delay * 1.5, 30.0
                                )
                                # Refresh session before reconnect
                                try:
                                    self._refresh_session()
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"[WS] on_close handler failed: {e}")

                    sws.on_data = _on_data
                    sws.on_open = _on_open
                    sws.on_error = _on_error
                    sws.on_close = _on_close
                    # Some SmartApi SDK versions bind websocket-client close/error events
                    # to private hooks (`_on_close`/`_on_error`) with strict signatures.
                    # Mirror our variadic-safe handlers there to avoid callback crashes.
                    sws._on_error = lambda wsapp, *args: _on_error(wsapp, *args)
                    sws._on_close = lambda wsapp, *args: _on_close(wsapp, *args)
                    self._ws = sws
                    sws.connect()  # Blocks until closed

                except Exception as e:
                    consecutive_errors += 1
                    logger.error(
                        f"[WS] Connection failed (attempt {consecutive_errors}/{max_consecutive_errors}): {e}"
                    )

                    # Circuit breaker: if too many consecutive errors, back off significantly
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(
                            "[WS] Too many consecutive errors, backing off for 60s"
                        )
                        time.sleep(60)
                        consecutive_errors = 0
                    elif self._ws_should_reconnect:
                        time.sleep(self._ws_reconnect_delay)
                        self._ws_reconnect_delay = min(
                            self._ws_reconnect_delay * 1.5, 30.0
                        )

        self._ws_thread = threading.Thread(
            target=_create_and_run, daemon=True, name="SmartAPI-WS"
        )
        self._ws_thread.start()
        logger.info("[WS] WebSocket thread started")

    def stop_ws(self):
        """Stop WebSocket and disable auto-reconnect."""
        self._ws_should_reconnect = False
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
            self._ws = None
        logger.info("[WS] WebSocket stopped")

    # ─── Orders ───

    def get_positions(self) -> list[dict]:
        """Fetch current broker positions with token-refresh retry and safe fallback."""
        self._ensure_login()
        if not self._obj:
            return []

        for attempt in range(2):
            try:
                _rate_limit()
                if hasattr(self._obj, "position"):
                    resp = self._obj.position()
                elif hasattr(self._obj, "getPosition"):
                    resp = self._obj.getPosition()
                else:
                    logger.error("[SMARTAPI] position API is not available in SDK")
                    return []

                if isinstance(resp, list):
                    return resp

                if isinstance(resp, dict):
                    if resp.get("status"):
                        data = resp.get("data", [])
                        if isinstance(data, list):
                            return data
                        if isinstance(data, dict):
                            nested = data.get("positions", [])
                            return nested if isinstance(nested, list) else []
                        return []

                    if attempt == 0 and self._handle_api_error(resp, "position"):
                        continue

                    logger.warning(
                        "[SMARTAPI] position call failed: %s",
                        resp.get("message", "Unknown error"),
                    )
                    return []

                logger.warning("[SMARTAPI] Unexpected position response type: %s", type(resp))
                return []

            except Exception as exc:
                logger.warning(
                    "[SMARTAPI] position call exception (attempt %d): %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    self._refresh_session()
                    continue
                return []

        return []

    def place_order(self, order_payload: dict) -> dict:
        """Place order via SmartAPI."""
        self._ensure_login()
        _rate_limit()
        try:
            resp = self._obj.placeOrderFullResponse(order_payload)
            return resp
        except Exception:
            self._refresh_session()
            _rate_limit()
            resp = self._obj.placeOrderFullResponse(order_payload)
            return resp

    # ─── Cleanup ───

    def terminate_session(self):
        """Logout and cleanup."""
        if self._obj:
            try:
                self._obj.terminateSession(self.client_id)
                logger.info("[SMARTAPI] Session terminated")
            except Exception as e:
                logger.warning(f"[SMARTAPI] Logout error: {e}")
            self._obj = None
            self._auth_token = None
            self._feed_token = None
            self._refresh_token = None
            self._clear_cached_session()
