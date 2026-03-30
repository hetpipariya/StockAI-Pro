from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.connectors import SmartAPIConnector
from app import config
from app.services.candle_store import store_candles
from app.services.instrument_master import get_symbol, get_token
from app.services.market_state import is_market_open
from app.services.tick_aggregator import tick_aggregator
from app.websocket.relay import (
    broadcast_candle,
    broadcast_tick,
    socket_manager,
)

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "SBIN",
    "ICICIBANK",
    "TATASTEEL",
    "ITC",
    "AXISBANK",
    "KOTAKBANK",
    "WIPRO",
    "BHARTIARTL",
    "HINDUNILVR",
    "LT",
    "MARUTI",
]

_smartapi_ws_started = False
_ws_connector: Optional[SmartAPIConnector] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_cached_candle_builder_15m = None
_last_live_tick_time = 0.0
_last_known_prices: dict[str, float] = {}
_ws_state = "DISCONNECTED"
_ws_reconnect_attempt = 0
_ws_reconnect_task = None

_WS_BASE_BACKOFF_SECONDS = 1
_WS_MAX_BACKOFF_SECONDS = 60
_WS_MAX_RETRY_ATTEMPTS = 10  # Increased for production resilience
_WATCHLIST_PRICE_MAX = 10000.0
_WS_CIRCUIT_BREAKER_RESET_TIME = 300  # 5 minutes before resetting circuit breaker


def _seed_price_for_symbol(symbol: str) -> float:
    """Generate a deterministic fallback price for symbols with no cached ticks."""
    normalized = str(symbol or "UNKNOWN").strip().upper()
    score = sum((idx + 1) * ord(ch) for idx, ch in enumerate(normalized))
    major = 100 + (score % 2400)
    minor = (score % 100) / 100.0
    return round(major + minor, 2)


def _normalize_watchlist_price(symbol: str, raw_price: float, ref_price: float = 0.0) -> float:
    """Normalize likely paise values into rupees and reject implausible spikes."""
    if not math.isfinite(raw_price) or raw_price <= 0:
        return 0.0

    normalized = float(raw_price)
    symbol_upper = str(symbol or "").strip().upper()

    # Explicit production guard requested by incident analysis.
    if symbol_upper == "RELIANCE" and normalized > _WATCHLIST_PRICE_MAX:
        normalized = normalized / 100.0
    elif symbol_upper in DEFAULT_WATCHLIST and normalized > _WATCHLIST_PRICE_MAX:
        normalized = normalized / 100.0

    if ref_price > 0:
        if normalized > ref_price * 50:
            normalized = normalized / 100.0
        elif normalized > ref_price * 10:
            logger.warning("[TICK] %s rejected outlier LTP=%s (ref=%s)", symbol_upper, normalized, ref_price)
            return 0.0

    if symbol_upper in DEFAULT_WATCHLIST and normalized > _WATCHLIST_PRICE_MAX:
        logger.warning("[TICK] %s rejected implausible watchlist price=%s", symbol_upper, normalized)
        return 0.0

    return round(normalized, 2)


def _resolve_mock_base_price(symbol: str) -> tuple[float, bool]:
    """Return (price, is_seeded) for mock emissions."""
    cached = float(_last_known_prices.get(symbol, 0.0) or 0.0)
    if cached > 0 and math.isfinite(cached):
        normalized_cached = _normalize_watchlist_price(symbol, cached)
        if normalized_cached > 0:
            if normalized_cached != round(cached, 2):
                logger.warning(
                    "[MOCK] Corrected cached price for %s from %s to %s",
                    symbol,
                    round(cached, 2),
                    normalized_cached,
                )
            _last_known_prices[symbol] = normalized_cached
            return normalized_cached, False

    seeded = _seed_price_for_symbol(symbol)
    _last_known_prices[symbol] = seeded
    return seeded, True


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _event_loop
    _event_loop = loop


def set_ws_connector(connector: Optional[SmartAPIConnector]) -> None:
    global _ws_connector
    _ws_connector = connector
    if connector is None:
        _set_ws_state("DISCONNECTED")


def get_ws_connector() -> Optional[SmartAPIConnector]:
    return _ws_connector


def get_or_create_ws_connector() -> SmartAPIConnector:
    global _ws_connector
    if _ws_connector is None:
        _ws_connector = SmartAPIConnector()
    return _ws_connector


def _set_ws_state(state: str) -> None:
    global _ws_state
    _ws_state = state


def get_ws_state() -> str:
    return _ws_state


def is_ws_streaming() -> bool:
    return _smartapi_ws_started and _ws_state == "CONNECTED"


def get_last_tick_age_seconds() -> float:
    if _last_live_tick_time <= 0:
        return float("inf")
    return max(0.0, time.time() - _last_live_tick_time)


def _schedule_async(coro):
    """Schedule coroutine on app event loop from SmartAPI callback thread."""
    if not _event_loop or not _event_loop.is_running():
        try:
            coro.close()
        except Exception:
            pass
        logger.warning("[ASYNC] Event loop not ready; dropping coroutine")
        return None

    future = asyncio.run_coroutine_threadsafe(coro, _event_loop)

    def _done(fut):
        try:
            fut.result()
        except Exception as exc:
            logger.error("[ASYNC] Scheduled coroutine failed: %s", exc)

    future.add_done_callback(_done)
    return future


async def _persist_completed_candle(symbol: str, candle: dict):
    try:
        await store_candles(symbol, "1m", [candle])
    except Exception as exc:
        logger.error("[TICK] Failed to persist candle: %s", exc)


async def _run_live_executor(symbol: str):
    # Live trading execution requires explicit user context and is handled via
    # authenticated trading routes, not anonymous market-feed callbacks.
    logger.debug("[EXECUTOR] Skipping feed-triggered execution for %s (no user context)", symbol)


def _on_smartapi_tick(msg):
    """SmartAPI websocket callback running on connector thread."""
    global _cached_candle_builder_15m, _last_live_tick_time

    _last_live_tick_time = time.time()

    try:
        if not isinstance(msg, dict):
            return

        token = str(msg.get("token", msg.get("symboltoken", "")))
        symbol = get_symbol(token)
        if not symbol:
            symbol = str(msg.get("tradingsymbol", token)).replace("-EQ", "")

        raw_ltp = float(msg.get("ltp", msg.get("last_traded_price", msg.get("lastprice", 0))))
        vol = int(msg.get("volume", msg.get("volume_trade_for_the_day", 0)) or 0)
        ref_price = _last_known_prices.get(symbol)
        ltp = _normalize_watchlist_price(symbol, raw_ltp, float(ref_price or 0.0))
        if ltp <= 0:
            return

        _last_known_prices[symbol] = ltp

        best_bid = ltp
        best_ask = ltp
        depth_buy = msg.get("depth", {}).get("buy", [])
        if depth_buy:
            bp = float(depth_buy[0].get("price", ltp))
            bp = _normalize_watchlist_price(symbol, bp, ltp)
            if bp <= 0:
                bp = ltp
            best_bid = bp
        depth_sell = msg.get("depth", {}).get("sell", [])
        if depth_sell:
            ap = float(depth_sell[0].get("price", ltp))
            ap = _normalize_watchlist_price(symbol, ap, ltp)
            if ap <= 0:
                ap = ltp
            best_ask = ap

        completed_candle = tick_aggregator.process_tick(symbol, ltp, vol)

        if _cached_candle_builder_15m is None:
            from app.trading.candle_builder import candle_builder_15m

            _cached_candle_builder_15m = candle_builder_15m
        completed_15m = _cached_candle_builder_15m.process_tick(symbol, ltp, vol)

        tick_data = {
            "ltp": ltp,
            "volume": vol,
            "bid": best_bid,
            "ask": best_ask,
            "data_source": "NSE_API",
        }
        _schedule_async(broadcast_tick(symbol, tick_data))

        if completed_candle:
            _schedule_async(broadcast_candle(symbol, completed_candle))
            _schedule_async(_persist_completed_candle(symbol, completed_candle))

        if completed_15m:
            _schedule_async(_run_live_executor(symbol))

    except Exception as exc:
        logger.warning("[TICK] Handler error: %s", exc)


def start_smartapi_ws(symbols_list: list[str]):
    """Start SmartAPI websocket subscription for requested symbols."""
    global _smartapi_ws_started, _ws_reconnect_attempt

    if _smartapi_ws_started:
        return

    _set_ws_state("CONNECTING")

    connector = get_or_create_ws_connector()

    tokens: list[str] = []
    for symbol in symbols_list:
        token = get_token(symbol)
        if token:
            tokens.append(token)
        else:
            logger.warning("[WS] Cannot resolve token for %s", symbol)

    if not tokens:
        logger.warning("[WS] No valid tokens to subscribe")
        _set_ws_state("FAILED")
        return

    token_list = [{"exchangeType": 1, "tokens": tokens}]
    try:
        connector.login()
        connector.start_ws(token_list, _on_smartapi_tick)
        _smartapi_ws_started = True
        _ws_reconnect_attempt = 0
        _set_ws_state("CONNECTED")
        logger.info("[WS] Subscribed to %d symbols", len(tokens))
    except Exception as exc:
        _smartapi_ws_started = False
        _set_ws_state("RECONNECTING")
        logger.error("[WS] Failed to start SmartAPI WebSocket: %s", exc)
        _schedule_reconnect(symbols_list)


async def _retry_ws_connect(symbols_list: list[str]):
    """Retry WebSocket connection with exponential backoff and circuit breaker.
    
    Uses exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
    Circuit breaker: After max retries, wait 5 minutes before trying again.
    """
    global _ws_reconnect_attempt

    while not _smartapi_ws_started:
        _ws_reconnect_attempt += 1
        
        # Circuit breaker: if max retries reached, wait longer before resetting
        if _ws_reconnect_attempt > _WS_MAX_RETRY_ATTEMPTS:
            logger.error(
                "[WS] Max retry attempts (%d) reached. Circuit breaker activated. "
                "Waiting %ds before resetting.",
                _WS_MAX_RETRY_ATTEMPTS,
                _WS_CIRCUIT_BREAKER_RESET_TIME
            )
            _set_ws_state("FAILED")
            await asyncio.sleep(_WS_CIRCUIT_BREAKER_RESET_TIME)
            _ws_reconnect_attempt = 0  # Reset counter after waiting
            logger.info("[WS] Circuit breaker reset. Resuming reconnection attempts.")
            continue
        
        # Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s
        wait_s = min(_WS_BASE_BACKOFF_SECONDS * (2 ** (_ws_reconnect_attempt - 1)), _WS_MAX_BACKOFF_SECONDS)
        logger.warning(
            "[WS] Reconnect attempt %d/%d in %.1fs (exponential backoff)",
            _ws_reconnect_attempt,
            _WS_MAX_RETRY_ATTEMPTS,
            wait_s
        )
        await asyncio.sleep(wait_s)
        
        try:
            start_smartapi_ws(symbols_list)
            if _smartapi_ws_started:
                logger.info("[WS] Reconnection successful on attempt %d", _ws_reconnect_attempt)
                return
        except Exception as exc:
            logger.error("[WS] Reconnection attempt %d failed: %s", _ws_reconnect_attempt, exc)


def _schedule_reconnect(symbols_list: list[str]) -> None:
    global _ws_reconnect_task
    if _ws_reconnect_task and not _ws_reconnect_task.done():
        return
    if not _event_loop or not _event_loop.is_running():
        return
    _ws_reconnect_task = asyncio.run_coroutine_threadsafe(_retry_ws_connect(symbols_list), _event_loop)


async def auto_start_ws():
    """Scheduler callback to ensure WS stream is running."""
    if not _smartapi_ws_started or _ws_state in {"DISCONNECTED", "FAILED", "RECONNECTING"}:
        logger.info("[SCHEDULER] Auto-starting WebSocket")
        start_smartapi_ws(DEFAULT_WATCHLIST)


async def mock_ws_data_job():
    """Fallback: emit stale/static prices when feed is idle or market is closed."""
    if not config.ENABLE_MOCK_DATA:
        return

    idle_time = get_last_tick_age_seconds()

    if not is_market_open():
        for symbol in DEFAULT_WATCHLIST[:10]:
            base_price, seeded = _resolve_mock_base_price(symbol)
            tick_data = {
                "ltp": base_price,
                "volume": 0,
                "bid": base_price,
                "ask": base_price,
                "signal": "HOLD",
                "is_mock": True,
                "unavailable": True,
                "mock_reason": "OFF_HOURS_SEEDED" if seeded else "OFF_HOURS_STALE",
                "data_source": "MOCK",
            }
            await broadcast_tick(symbol, tick_data)
        return

    if idle_time > 10:
        logger.warning("WARNING: Using mock data - SmartAPI connection idle for %.1fs", idle_time)
        for symbol in DEFAULT_WATCHLIST[:10]:
            base_price, seeded = _resolve_mock_base_price(symbol)
            tick_data = {
                "ltp": base_price,
                "volume": 0,
                "bid": base_price,
                "ask": base_price,
                "signal": "HOLD",
                "is_mock": True,
                "unavailable": seeded,
                "mock_reason": "IDLE_FEED_SEEDED" if seeded else "IDLE_FEED_STALE",
                "data_source": "MOCK",
            }
            await broadcast_tick(symbol, tick_data)


async def websocket_live(websocket: WebSocket, token: Optional[str] = Query(default=None)):
    """Authenticated websocket endpoint: /ws?token=<jwt> (legacy alias: /live)."""
    client_host = websocket.client.host if websocket.client else "unknown"

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        logger.warning("[WS] Rejected unauthenticated connection from %s", client_host)
        return

    try:
        from app.services.db import AsyncSessionLocal, UserModel
        from app.utils.auth_utils import decode_access_token

        payload = decode_access_token(token)
        user_id = int(payload["sub"])

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.id == user_id, UserModel.is_active == True)
            )
            user = result.scalars().first()

        if not user:
            await websocket.close(code=4003, reason="User not found")
            return

    except Exception as exc:
        await websocket.close(code=4001, reason="Invalid token")
        logger.warning("[WS] Auth failed from %s: %s", client_host, type(exc).__name__)
        return

    await websocket.accept()
    await _handle_ws_connection(websocket, user_id)


async def _handle_ws_connection(websocket: WebSocket, user_id: int):
    client_id = await socket_manager.connect(websocket, user_id)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "WebSocket connected. Send subscribe message.",
                "connection_state": get_ws_state(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    await websocket.send_json({"type": "error", "message": "Payload must be a JSON object."})
                    continue
                await _process_ws_message(msg, client_id, user_id, websocket)

            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "ping",
                        "connection_state": get_ws_state(),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload."})
            except WebSocketDisconnect:
                break

    finally:
        await socket_manager.disconnect(client_id)


async def _process_ws_message(msg: dict, client_id: str, user_id: int, websocket: WebSocket):
    action = msg.get("action")

    if action == "subscribe":
        from app.services.ticker_map import VALID_SYMBOLS

        symbols = msg.get("symbols", [])
        valid: list[str] = []
        if isinstance(symbols, list):
            for symbol in symbols:
                if not isinstance(symbol, str):
                    continue
                normalized = symbol.strip().upper()
                if normalized in VALID_SYMBOLS and normalized not in valid:
                    valid.append(normalized)

        await socket_manager.subscribe(client_id, valid)
        if valid and not _smartapi_ws_started:
            start_smartapi_ws(valid)

        await websocket.send_json(
            {
                "type": "subscribed",
                "symbols": valid,
                "connection_state": get_ws_state(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        logger.info("[WS] user_id=%d client_id=%s subscribed=%s", user_id, client_id, valid)

    elif action == "unsubscribe":
        symbols = msg.get("symbols", [])
        normalized = [s.strip().upper() for s in symbols if isinstance(s, str)] if isinstance(symbols, list) else []
        await socket_manager.unsubscribe(client_id, normalized)
        await websocket.send_json({"type": "unsubscribed", "symbols": normalized})

    elif action == "pong":
        return

    else:
        await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})


def setup_websocket_routes(app: FastAPI) -> None:
    app.websocket("/ws")(websocket_live)
    app.websocket("/live")(websocket_live)
