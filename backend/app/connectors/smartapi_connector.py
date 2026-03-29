"""
SmartAPI (AngelOne) connector — production-ready singleton.
Login, historical data, WebSocket, orders.
Credentials from .env; never hardcode.
"""
from __future__ import annotations

import os
import time
import threading
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Callable, Optional, Any
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

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
        self._login_lock = threading.Lock()
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

    def _sync_get_session(self):
        """Try to load cached session from Redis/memory (sync wrapper)."""
        from app.services.redis_client import get_session_token
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return None
            return loop.run_until_complete(get_session_token())
        except Exception:
            try:
                return asyncio.run(get_session_token())
            except Exception:
                return None

    def _sync_store_session(self, token_data):
        from app.services.redis_client import store_session_token
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(store_session_token(token_data))
                return
            loop.run_until_complete(store_session_token(token_data))
        except Exception:
            try:
                asyncio.run(store_session_token(token_data))
            except Exception:
                pass

    def _sync_clear_session(self):
        from app.services.redis_client import clear_session
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(clear_session())
                return
            loop.run_until_complete(clear_session())
        except Exception:
            try:
                asyncio.run(clear_session())
            except Exception:
                pass

    # ─── Login / Session ───

    def login(self, force: bool = False) -> dict:
        """
        Login to SmartAPI. Thread-safe with retry.
        Returns session data dict.
        """
        with self._login_lock:
            return self._login_impl(force)

    def _login_impl(self, force: bool = False) -> dict:
        from SmartApi import SmartConnect

        if not all([self.api_key, self.client_id, self.client_pwd, self.totp_secret]):
            logger.error("[SMARTAPI] Missing credentials in .env — check SMARTAPI_API_KEY, CLIENT_ID, CLIENT_PWD, TOTP_SECRET")
            raise ValueError("Missing SmartAPI credentials")

        # Try cached session from Redis (unless forced re-login)
        if not force:
            session = self._sync_get_session()
            if session and session.get("authToken") and session.get("feedToken"):
                self._obj = SmartConnect(self.api_key)
                self._auth_token = session["authToken"]
                self._feed_token = session["feedToken"]
                self._refresh_token = session.get("refreshToken")
                self._login_time = time.monotonic()
                logger.info("[SMARTAPI] Session restored from cache")
                return {"status": True, "authToken": self._auth_token, "feedToken": self._feed_token}

        # Fresh login with retry (3 attempts)
        self._obj = SmartConnect(self.api_key)
        last_err = None

        for attempt in range(1, 4):
            try:
                totp = self._get_totp()
                logger.info(f"[SMARTAPI] Login attempt {attempt}/3 for client {self.client_id}")
                data = self._obj.generateSession(self.client_id, self.client_pwd, totp)

                if not data or not data.get("status"):
                    msg = data.get("message", "Unknown error") if data else "No response"
                    logger.warning(f"[SMARTAPI] Login attempt {attempt} failed: {msg}")
                    last_err = msg
                    if attempt < 3:
                        time.sleep(2 ** attempt)  # 2s, 4s backoff
                    continue

                d = data["data"]
                self._auth_token = d.get("jwtToken")
                self._refresh_token = d.get("refreshToken")
                self._feed_token = d.get("feedToken")
                if not self._feed_token and hasattr(self._obj, "getfeedToken"):
                    self._feed_token = self._obj.getfeedToken()
                self._login_time = time.monotonic()

                # Cache session
                self._sync_store_session({
                    "authToken": self._auth_token,
                    "feedToken": self._feed_token,
                    "refreshToken": self._refresh_token,
                })
                logger.info("[SMARTAPI] ✓ Login successful — tokens acquired")
                return {"status": True, "authToken": self._auth_token, "feedToken": self._feed_token}

            except Exception as e:
                last_err = str(e)
                logger.warning(f"[SMARTAPI] Login attempt {attempt} exception: {e}")
                if attempt < 3:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"[SMARTAPI] Login failed after 3 attempts: {last_err}")

    def _ensure_login(self):
        """Auto-login if not logged in or session expired (>55 min)."""
        if not self.is_logged_in or self.session_age_minutes > 55:
            logger.info("[SMARTAPI] Session expired or missing — re-login")
            self.login(force=True)

    def _refresh_session(self):
        """Try to refresh token; fall back to full re-login."""
        if self._obj and self._refresh_token:
            try:
                _rate_limit()
                resp = self._obj.generateToken(self._refresh_token)
                if resp and resp.get("status") and resp.get("data"):
                    d = resp["data"]
                    self._auth_token = d.get("jwtToken", self._auth_token)
                    self._refresh_token = d.get("refreshToken", self._refresh_token)
                    if hasattr(self._obj, "getfeedToken"):
                        self._feed_token = self._obj.getfeedToken()
                    self._login_time = time.monotonic()
                    self._sync_store_session({
                        "authToken": self._auth_token,
                        "feedToken": self._feed_token,
                        "refreshToken": self._refresh_token,
                    })
                    logger.info("[SMARTAPI] Token refreshed")
                    return
            except Exception as e:
                logger.warning(f"[SMARTAPI] Token refresh failed: {e}")
        # Fall back to full login
        self.login(force=True)

    def _handle_api_error(self, resp: dict, context: str) -> bool:
        """
        Check response for retryable errors. Returns True if caller should retry.
        AG8001 = Invalid Token (expired session)
        AG8002 = Rate limit exceeded
        """
        if not resp or not isinstance(resp, dict):
            return False
        msg = resp.get("message", "")
        error_code = resp.get("errorcode", "")

        if error_code in ("AG8001", "AG8003") or "Invalid Token" in msg or "token" in msg.lower():
            logger.warning(f"[SMARTAPI] {context}: token expired ({error_code}), refreshing session")
            self._refresh_session()
            return True

        if error_code == "AG8002" or "rate" in msg.lower():
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
            if interval_api in ("ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "FIFTEEN_MINUTE", "THIRTY_MINUTE"):
                from_date = to_date - timedelta(days=7)
            else:
                from_date = to_date - timedelta(days=30)
        if from_date >= to_date:
            from_date = to_date - timedelta(days=2)

        # Clamp date range to SmartAPI limits
        if interval_api in ("ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "FIFTEEN_MINUTE", "THIRTY_MINUTE"):
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

        logger.info(f"[SMARTAPI] getCandleData: token={symbol_token}, interval={interval_api}, {fd} → {td}")

        for attempt in range(3):
            try:
                _rate_limit()
                t0 = time.monotonic()
                resp = self._obj.getCandleData(params)
                elapsed = (time.monotonic() - t0) * 1000
                logger.info(f"[SMARTAPI] getCandleData took {elapsed:.0f}ms")
            except Exception as e:
                logger.warning(f"[SMARTAPI] getCandleData error (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    self._refresh_session()
                    time.sleep(1)
                    continue
                return []

            if not resp:
                logger.warning(f"[SMARTAPI] getCandleData returned None or empty (attempt {attempt + 1})")
                if attempt < 2:
                    time.sleep(1)
                    continue
                return []

            if isinstance(resp, dict):
                if self._handle_api_error(resp, "getCandleData") and attempt < 2:
                    continue
                if not resp.get("status"):
                    logger.error(f"[SMARTAPI] getCandleData error: {resp.get('message', 'Unknown')}")
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
                logger.info(f"[SMARTAPI] Got {len(data)} candles (Requested Limit: {limit})")
                return data[-limit:]
            else:
                logger.warning(f"[SMARTAPI] Empty candle data returned from valid response (attempt {attempt + 1})")
                if attempt < 2:
                    time.sleep(1.5)
                    continue
                return []

        return []

    # ─── LTP Snapshot ───

    def get_ltp(self, symbol_token: str, exchange: str = "NSE", tradingsymbol: str = "") -> Optional[dict]:
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
                        resp = self._obj.ltpData({"exchange": exchange, "tradingsymbol": ts, "symboltoken": token_str})
                    if resp and isinstance(resp, dict):
                        if resp.get("status") and resp.get("data"):
                            logger.info("[SMARTAPI] LTP via ltpData OK")
                            return resp["data"]
                        if attempt == 0 and self._handle_api_error(resp, "ltpData"):
                            continue
                except Exception as e:
                    logger.warning(f"[SMARTAPI] ltpData failed (attempt {attempt+1}): {e}")
                    if attempt == 0:
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
                        resp = self._obj.getMarketData({"mode": "LTP", "exchangeTokens": exchange_tokens})
                    if resp and isinstance(resp, dict):
                        if resp.get("status") and resp.get("data"):
                            logger.info("[SMARTAPI] LTP via getMarketData OK")
                            # getMarketData returns {"fetched": [...], "unfetched": [...]}
                            fetched = resp["data"].get("fetched", [])
                            if fetched:
                                item = fetched[0]
                                return {
                                    "ltp": float(item.get("ltp", 0)),
                                    "open": float(item.get("open", 0)),
                                    "high": float(item.get("high", 0)),
                                    "low": float(item.get("low", 0)),
                                    "close": float(item.get("close", item.get("ltp", 0))),
                                    "volume": int(item.get("volume", item.get("tradeVolume", 0)) or 0),
                                }
                            # If data is directly the LTP dict (old format)
                            if "ltp" in resp["data"]:
                                return resp["data"]
                        if attempt == 0 and self._handle_api_error(resp, "getMarketData"):
                            continue
                except Exception as e:
                    logger.warning(f"[SMARTAPI] getMarketData failed (attempt {attempt+1}): {e}")
                    if attempt == 0:
                        self._refresh_session()
                break

        # Fallback: derive from latest 1m candle
        try:
            logger.info("[SMARTAPI] LTP fallback: fetching latest 1m candle")
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=3)
            rows = self.fetch_history(symbol_token, exchange, "1m", from_dt, to_dt, 1)
            if rows:
                last = rows[-1]
                if isinstance(last, (list, tuple)) and len(last) >= 5:
                    return {
                        "ltp": float(last[4]), "open": float(last[1]),
                        "high": float(last[2]), "low": float(last[3]),
                        "close": float(last[4]),
                        "volume": int(last[5]) if len(last) > 5 else 0,
                    }
                elif isinstance(last, dict):
                    close = float(last.get("4", last.get("close", 0)))
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

    def start_ws(self, token_list: list[dict], on_message: Callable[[Any], None]):
        """
        Start SmartAPI WebSocket for live ticks.
        token_list: [{"exchangeType": 1, "tokens": ["2881", "3045"]}]
        on_message: callback(msg_dict)
        """
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        self._ensure_login()
        if not self._feed_token:
            logger.error("[WS] No feedToken — cannot start WebSocket")
            return

        correlation_id = "stockai-pro-1"
        mode = 2  # LTP mode (1=LTP, 2=Quote, 3=SnapQuote)

        self._ws_should_reconnect = True
        self._ws_reconnect_delay = 1.0

        def _create_and_run():
            while self._ws_should_reconnect:
                try:
                    sws = SmartWebSocketV2(
                        self._auth_token,
                        self.api_key,
                        self.client_id,
                        self._feed_token,
                    )

                    def _on_data(wsapp, message):
                        try:
                            on_message(message)
                        except Exception as e:
                            logger.error(f"[WS] Tick handler error: {e}")

                    def _on_open(wsapp):
                        logger.info(f"[WS] ✓ Connected — subscribing {len(token_list)} groups")
                        self._ws_reconnect_delay = 1.0  # Reset backoff
                        sws.subscribe(correlation_id, mode, token_list)

                    def _on_error(wsapp, error):
                        logger.error(f"[WS] Error: {error}")
                        if "AG800" in str(error) or "Invalid Token" in str(error):
                            logger.error("[WS] Force clearing session due to Token Error")
                            self._sync_clear_session()
                            try:
                                self.login(force=True)
                            except Exception:
                                pass

                    def _on_close(wsapp):
                        logger.info("[WS] Connection closed")
                        if self._ws_should_reconnect:
                            logger.info(f"[WS] Reconnecting in {self._ws_reconnect_delay:.1f}s")
                            time.sleep(self._ws_reconnect_delay)
                            self._ws_reconnect_delay = min(self._ws_reconnect_delay * 1.5, 30.0)
                            # Refresh session before reconnect
                            try:
                                self._refresh_session()
                            except Exception:
                                pass

                    sws.on_data = _on_data
                    sws.on_open = _on_open
                    sws.on_error = _on_error
                    sws.on_close = _on_close
                    self._ws = sws
                    sws.connect()  # Blocks until closed

                except Exception as e:
                    logger.error(f"[WS] Connection failed: {e}")
                    if self._ws_should_reconnect:
                        time.sleep(self._ws_reconnect_delay)
                        self._ws_reconnect_delay = min(self._ws_reconnect_delay * 1.5, 30.0)

        self._ws_thread = threading.Thread(target=_create_and_run, daemon=True, name="SmartAPI-WS")
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

    def place_order(self, order_payload: dict) -> dict:
        """Place order via SmartAPI."""
        self._ensure_login()
        _rate_limit()
        try:
            resp = self._obj.placeOrderFullResponse(order_payload)
            return resp
        except Exception as e:
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
            self._sync_clear_session()
