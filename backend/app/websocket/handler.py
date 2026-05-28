from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app import config
from app.connectors import BrokerRouter, get_market_data_connector
from app.services.candle_store import store_candles
from app.services.instrument_service import (get_symbol_by_token,
                                             get_token_by_symbol)
from app.services.market_state import is_market_open
from app.services.tick_aggregator import tick_aggregator
from app.websocket.relay import (RECONNECT_GRACE_SECONDS, broadcast_candle,
                                 broadcast_signal, broadcast_tick,
                                 socket_manager)

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
_ws_connector: Optional[BrokerRouter] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_cached_candle_builder_15m = None
_cached_candle_builder_5m = None
_last_live_tick_time = 0.0
_last_known_prices: dict[str, float] = {}
_last_known_prices_lock = threading.Lock()
_ip_connection_attempts: dict[str, list[float]] = {}
_ip_connection_lock = threading.Lock()
_ws_state = "DISCONNECTED"
_ws_reconnect_attempt = 0
_ws_reconnect_task = None
_ws_subscription_lock = threading.Lock()
_ws_subscribed_symbols: set[str] = set()


_WS_BASE_BACKOFF_SECONDS = 1
_WS_MAX_BACKOFF_SECONDS = 60
_WS_MAX_RETRY_ATTEMPTS = 10  # Increased for production resilience
_WATCHLIST_PRICE_MAX = 10000.0
_WS_CIRCUIT_BREAKER_RESET_TIME = 300  # 5 minutes before resetting circuit breaker
_MOCK_IDLE_THRESHOLD_SECONDS = 20.0

_MOCK_BASE_PRICE = {
    "RELIANCE": 1348.10,
    "TCS": 2590.00,
    "INFY": 1331.50,
    "HDFCBANK": 798.00,
    "SBIN": 1040.45,
    "ICICIBANK": 1283.50,
    "TATASTEEL": 146.80,
    "ITC": 303.00,
    "AXISBANK": 1098.20,
    "KOTAKBANK": 371.85,
    "WIPRO": 530.40,
    "BHARTIARTL": 1859.70,
    "HINDUNILVR": 2412.30,
    "LT": 3890.30,
    "MARUTI": 12180.00,
}


def _normalize_watchlist_price(
    symbol: str, raw_price: float, ref_price: float = 0.0
) -> float:
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
            logger.warning(
                "[TICK] %s rejected outlier LTP=%s (ref=%s)",
                symbol_upper,
                normalized,
                ref_price,
            )
            return 0.0

    if symbol_upper in DEFAULT_WATCHLIST and normalized > _WATCHLIST_PRICE_MAX:
        logger.warning(
            "[TICK] %s rejected implausible watchlist price=%s",
            symbol_upper,
            normalized,
        )
        return 0.0

    return round(normalized, 2)


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _event_loop
    _event_loop = loop


def set_ws_connector(connector: Optional[BrokerRouter]) -> None:
    global _ws_connector
    _ws_connector = connector
    if connector is None:
        _set_ws_state("DISCONNECTED")


def get_ws_connector() -> Optional[BrokerRouter]:
    return _ws_connector


def get_or_create_ws_connector() -> BrokerRouter:
    global _ws_connector
    if _ws_connector is None:
        _ws_connector = get_market_data_connector()
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


def get_last_known_price(symbol: str) -> float | None:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return None

    with _last_known_prices_lock:
        value = _last_known_prices.get(normalized)
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or float(value) <= 0:
        return None
    return round(float(value), 2)


def _resolve_mock_base_price(symbol: str) -> tuple[float, bool]:
    """Resolve a deterministic fallback LTP for mock ticks.

    Returns (price, seeded) where seeded indicates if no prior live/cached value existed.
    """
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        return 1.0, True

    with _last_known_prices_lock:
        cached = _last_known_prices.get(normalized_symbol)
    if isinstance(cached, (int, float)) and math.isfinite(cached) and cached > 0:
        normalized_cached = _normalize_watchlist_price(normalized_symbol, float(cached), 0.0)
        if normalized_cached > 0:
            with _last_known_prices_lock:
                _last_known_prices[normalized_symbol] = normalized_cached
            return normalized_cached, False

    seeded_price = _MOCK_BASE_PRICE.get(normalized_symbol)
    if not seeded_price:
        # Deterministic fallback for symbols outside curated watchlist.
        token = sum(ord(ch) for ch in normalized_symbol)
        seeded_price = round(100 + (token % 5000) * 0.73, 2)

    normalized_seeded = _normalize_watchlist_price(normalized_symbol, float(seeded_price), 0.0)
    if normalized_seeded <= 0:
        normalized_seeded = max(1.0, float(seeded_price))

    with _last_known_prices_lock:
        _last_known_prices[normalized_symbol] = normalized_seeded
    return normalized_seeded, True



async def mock_ws_data_job() -> None:
    """Emit synthetic websocket ticks when mock mode is enabled.

    Behavior:
    - Off-hours: send unavailable ticks for all watchlist symbols.
    - Market open but feed idle: seed missing symbols and mark seeded payloads unavailable.
    """
    if not bool(getattr(config, "ENABLE_MOCK_DATA", False)):
        return

    market_open = is_market_open()
    tick_age = get_last_tick_age_seconds()
    feed_idle = tick_age >= _MOCK_IDLE_THRESHOLD_SECONDS

    # During market hours with healthy feed, do not emit mock ticks.
    if market_open and not feed_idle:
        return

    for raw_symbol in DEFAULT_WATCHLIST:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue

        ltp, seeded = _resolve_mock_base_price(symbol)

        if market_open:
            mock_reason = "IDLE_FEED_SEEDED" if seeded else "IDLE_FEED_STALE"
            unavailable = seeded
        else:
            mock_reason = "OFF_HOURS_SEEDED" if seeded else "OFF_HOURS_STALE"
            unavailable = True

        payload = {
            "ltp": ltp,
            "bid": ltp,
            "ask": ltp,
            "volume": 0,
            "is_mock": True,
            "unavailable": bool(unavailable),
            "mock_reason": mock_reason,
            "data_source": "MOCK",
        }

        await broadcast_tick(symbol, payload)


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


async def _persist_completed_5m_candle(symbol: str, candle: dict):
    try:
        await store_candles(symbol, "5m", [candle])
    except Exception as exc:
        logger.error("[TICK] Failed to persist 5m candle: %s", exc)


async def _broadcast_signal_update(symbol: str):
    """Compute and push latest prediction for a symbol after candle close."""
    try:
        from app.services.bundle_service import get_history, get_prediction, get_snapshot

        # Signal updates run after local candle completion, so prefer cache/DB paths
        # to avoid broker auth storms when SmartAPI credentials are stale.
        history = await get_history(symbol=symbol, interval="1m", limit=200, allow_live=False)
        snapshot = await get_snapshot(symbol=symbol, allow_live=False)
        prediction = await get_prediction(
            symbol=symbol,
            horizon="15m",
            history=history,
            snapshot=snapshot,
            allow_live=False,
        )

        payload = {
            **prediction,
            "data_source": prediction.get(
                "data_source",
                snapshot.get("data_source", history.get("data_source", "UNKNOWN")),
            ),
        }
        await broadcast_signal(symbol, payload)
    except Exception as exc:
        logger.warning("[WS] Signal update failed for %s: %s", symbol, exc)


async def _run_live_executor(symbol: str):
    # Live trading execution requires explicit user context and is handled via
    # authenticated trading routes, not anonymous market-feed callbacks.
    logger.debug(
        "[EXECUTOR] Skipping feed-triggered execution for %s (no user context)", symbol
    )


def _get_auto_execution_contexts() -> list[dict]:
    """Resolve user contexts for feed-triggered 5m execution."""
    contexts: list[dict] = []
    seen: set[int] = set()

    try:
        from app.trading.user_state import trading_manager

        for summary in trading_manager.get_all_summaries():
            raw_user_id = summary.get("user_id")
            if raw_user_id is None:
                continue
            user_id = int(raw_user_id)
            if user_id in seen:
                continue
            seen.add(user_id)

            contexts.append(
                {
                    "user_id": user_id,
                    "mode": str(summary.get("mode", config.TRADING_MODE)).upper(),
                    "capital": float(
                        summary.get("starting_capital", config.STARTING_CAPITAL)
                    ),
                }
            )
    except Exception as exc:
        logger.warning("[EXECUTOR-5M] Failed reading in-memory user contexts: %s", exc)

    if not config.LIVE_5M_EXECUTE_ALL_ACTIVE_USERS:
        return contexts

    try:
        from app.services.db import UserModel, get_sync_db_session

        db_gen = get_sync_db_session()
        session = next(db_gen)
        if session is None:
            return contexts

        try:
            rows = (
                session.query(
                    UserModel.id,
                    UserModel.trading_mode,
                    UserModel.starting_capital,
                )
                .filter(UserModel.is_active.is_(True))
                .all()
            )
            for user_id, trading_mode, starting_capital in rows:
                uid = int(user_id)
                if uid in seen:
                    continue
                seen.add(uid)
                contexts.append(
                    {
                        "user_id": uid,
                        "mode": str(trading_mode or config.TRADING_MODE).upper(),
                        "capital": float(starting_capital or config.STARTING_CAPITAL),
                    }
                )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("[EXECUTOR-5M] Failed loading DB user contexts: %s", exc)

    return contexts


async def _run_live_executor_5m(symbol: str, completed_candle: dict):
    if not config.LIVE_5M_AUTO_EXECUTION_ENABLED:
        return

    contexts = await asyncio.to_thread(_get_auto_execution_contexts)
    if not contexts:
        logger.debug("[EXECUTOR-5M] No eligible users for feed-triggered execution")
        return

    from app.trading.live_executor_5m import get_executor_5m
    from app.trading.trade_logger import log_trade

    for ctx in contexts:
        user_id = int(ctx["user_id"])
        mode = str(ctx["mode"]).upper()
        capital = float(ctx["capital"])

        try:
            executor = await asyncio.to_thread(
                get_executor_5m,
                user_id,
                mode,
                capital,
            )
            result = await asyncio.to_thread(
                executor.on_candle_complete,
                symbol,
                completed_candle,
                user_id,
            )

            if result:
                logger.info(
                    "[EXECUTOR-5M] user_id=%s symbol=%s action=%s status=%s",
                    user_id,
                    symbol,
                    result.get("action"),
                    result.get("status"),
                )
        except Exception as exc:
            logger.exception(
                "[EXECUTOR-5M] user_id=%s symbol=%s execution failed: %s",
                user_id,
                symbol,
                exc,
            )
            await asyncio.to_thread(
                log_trade,
                "FAILED",
                f"AUTO5M-{symbol}",
                symbol,
                "NA",
                mode=mode,
                status="FAILED",
                reason="5m auto-execution runtime error",
                error=str(exc),
                user_id=user_id,
            )


def _on_smartapi_tick(msg):
    """SmartAPI websocket callback running on connector thread."""
    global _cached_candle_builder_15m, _cached_candle_builder_5m, _last_live_tick_time

    _last_live_tick_time = time.time()

    try:
        if not isinstance(msg, dict):
            return

        token = str(
            msg.get(
                "token",
                msg.get("symboltoken", msg.get("instrument_key", msg.get("instrumentKey", ""))),
            )
        )
        try:
            symbol = get_symbol_by_token(token, exchange=config.SMARTAPI_EXCHANGE)
        except KeyError:
            symbol = str(
                msg.get(
                    "tradingsymbol",
                    msg.get("symbol", msg.get("instrument_key", token)),
                )
            ).replace("-EQ", "")

        raw_ltp = float(
            msg.get("ltp", msg.get("last_traded_price", msg.get("lastprice", 0)))
        )
        vol = int(msg.get("volume", msg.get("volume_trade_for_the_day", 0)) or 0)
        with _last_known_prices_lock:
            ref_price = _last_known_prices.get(symbol)
        ltp = _normalize_watchlist_price(symbol, raw_ltp, float(ref_price or 0.0))
        if ltp <= 0:
            return

        with _last_known_prices_lock:
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

        if _cached_candle_builder_15m is None or _cached_candle_builder_5m is None:
            from app.trading.candle_builder import candle_builder_15m, candle_builder_5m

            _cached_candle_builder_15m = candle_builder_15m
            _cached_candle_builder_5m = candle_builder_5m

        completed_5m = _cached_candle_builder_5m.process_tick(symbol, ltp, vol)
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
            _schedule_async(_broadcast_signal_update(symbol))

        if completed_5m:
            _schedule_async(broadcast_candle(symbol, completed_5m))
            _schedule_async(_persist_completed_5m_candle(symbol, completed_5m))
            _schedule_async(_run_live_executor_5m(symbol, completed_5m))

        if completed_15m:
            _schedule_async(_run_live_executor(symbol))

    except Exception as exc:
        logger.warning("[TICK] Handler error: %s", exc)


def start_smartapi_ws(symbols_list: list[str]):
    """Start SmartAPI websocket subscription for requested symbols."""
    global _smartapi_ws_started, _ws_reconnect_attempt

    normalized_symbols: list[str] = []
    for symbol in symbols_list:
        normalized = str(symbol or "").strip().upper()
        if normalized and normalized not in normalized_symbols:
            normalized_symbols.append(normalized)

    if not normalized_symbols:
        logger.warning("[WS] Empty symbol list received for subscription")
        return

    connector = get_or_create_ws_connector()
    use_symbol_tokens = connector.active_broker == "upstox"

    tokens: list[str] = []
    with _ws_subscription_lock:
        for symbol in normalized_symbols:
            if _smartapi_ws_started and symbol in _ws_subscribed_symbols:
                continue

            if use_symbol_tokens:
                tokens.append(symbol)
                _ws_subscribed_symbols.add(symbol)
                continue

            try:
                token = get_token_by_symbol(symbol, exchange=config.SMARTAPI_EXCHANGE)
                tokens.append(token)
                _ws_subscribed_symbols.add(symbol)
            except KeyError as exc:
                logger.warning("[WS] %s", exc)

    if not tokens:
        if _smartapi_ws_started:
            logger.debug("[WS] No new tokens to subscribe")
            return
        logger.warning("[WS] No valid tokens to subscribe")
        _set_ws_state("FAILED")
        return

    if _smartapi_ws_started:
        if connector.subscribe_ws_tokens(tokens):
            logger.info("[WS] Added %d tokens to active stream", len(tokens))
            return
        logger.warning("[WS] Incremental subscribe failed; scheduling reconnect")
        _set_ws_state("RECONNECTING")
        _schedule_reconnect(sorted(_ws_subscribed_symbols) or normalized_symbols)
        return

    _set_ws_state("CONNECTING")

    token_list = [{"exchangeType": 1, "tokens": tokens}]
    try:
        if connector.active_broker == "upstox":
            upstox_tokens = [{"exchangeType": 1, "tokens": normalized_symbols}]
            connector.start_ws(upstox_tokens, _on_smartapi_tick)
        else:
            connector.start_ws(token_list, _on_smartapi_tick)
        _smartapi_ws_started = True
        _ws_reconnect_attempt = 0
        _set_ws_state("CONNECTED")
        logger.info("[WS] Subscribed to %d symbols", len(tokens))
    except Exception as exc:
        _smartapi_ws_started = False
        _set_ws_state("RECONNECTING")
        logger.error("[WS] Failed to start SmartAPI WebSocket: %s", exc)
        _schedule_reconnect(sorted(_ws_subscribed_symbols) or normalized_symbols)


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
                _WS_CIRCUIT_BREAKER_RESET_TIME,
            )
            _set_ws_state("FAILED")
            await asyncio.sleep(_WS_CIRCUIT_BREAKER_RESET_TIME)
            _ws_reconnect_attempt = 0  # Reset counter after waiting
            logger.info("[WS] Circuit breaker reset. Resuming reconnection attempts.")
            continue

        # Exponential backoff with randomized ±15% jitter to prevent reconnect storms
        base_wait = min(
            _WS_BASE_BACKOFF_SECONDS * (2 ** (_ws_reconnect_attempt - 1)),
            _WS_MAX_BACKOFF_SECONDS,
        )
        import random
        jitter = random.uniform(-0.15, 0.15) * base_wait
        wait_s = max(1.0, min(_WS_MAX_BACKOFF_SECONDS, base_wait + jitter))

        logger.warning(
            "[WS] Reconnect attempt %d/%d in %.1fs (exponential backoff with jitter)",
            _ws_reconnect_attempt,
            _WS_MAX_RETRY_ATTEMPTS,
            wait_s,
        )
        
        try:
            from app.services.metrics import WS_RECONNECT_ATTEMPTS
            WS_RECONNECT_ATTEMPTS.inc()
        except Exception:
            pass

        await asyncio.sleep(wait_s)


        try:
            start_smartapi_ws(symbols_list)
            if _smartapi_ws_started:
                logger.info(
                    "[WS] Reconnection successful on attempt %d", _ws_reconnect_attempt
                )
                return
        except Exception as exc:
            logger.error(
                "[WS] Reconnection attempt %d failed: %s", _ws_reconnect_attempt, exc
            )


def _schedule_reconnect(symbols_list: list[str]) -> None:
    global _ws_reconnect_task
    if _ws_reconnect_task and not _ws_reconnect_task.done():
        return
    if not _event_loop or not _event_loop.is_running():
        return
    _ws_reconnect_task = asyncio.run_coroutine_threadsafe(
        _retry_ws_connect(symbols_list), _event_loop
    )


async def auto_start_ws():
    """Scheduler callback to ensure WS stream is running."""
    if not _smartapi_ws_started or _ws_state in {
        "DISCONNECTED",
        "FAILED",
        "RECONNECTING",
    }:
        logger.info("[SCHEDULER] Auto-starting WebSocket")
        symbols = sorted(_ws_subscribed_symbols) or DEFAULT_WATCHLIST
        start_smartapi_ws(symbols)


async def _resolve_websocket_user_id(token: str) -> int | None:
    from app.services.db import AsyncSessionLocal, UserModel, is_transient_db_error
    from app.utils.auth_utils import decode_access_token
    from app.services.redis_client import get_cache, set_cache

    payload = decode_access_token(token)
    user_id = int(payload.get("user_id", payload["sub"]))

    # Check cached auth token to protect the database connection pool
    cache_key = f"auth:user_ws_resolve:{user_id}"
    cached_id = await get_cache(cache_key)
    if cached_id is not None:
        return int(cached_id)

    auth_timeout = max(0.5, float(config.WS_AUTH_DB_TIMEOUT_SECONDS))
    max_attempts = max(1, min(config.DB_MAX_RETRIES, 3))
    base_delay = max(0.05, float(config.DB_RETRY_BASE_DELAY_SECONDS))

    for attempt in range(1, max_attempts + 1):
        try:
            async with AsyncSessionLocal() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        select(UserModel.id)
                        .where(UserModel.id == user_id, UserModel.is_active.is_(True))
                        .limit(1)
                    ),
                    timeout=auth_timeout,
                )
                resolved_id = result.scalar_one_or_none()
                if resolved_id is not None:
                    await set_cache(cache_key, int(resolved_id), ttl=300)
                    return int(resolved_id)
                return None
        except Exception as exc:
            transient = is_transient_db_error(exc)
            if transient and attempt < max_attempts:
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise

    return None


async def _build_user_state_payload(user_id: int) -> dict[str, Any]:
    from app.trading.user_state import trading_manager

    state = await trading_manager.get_state(user_id=user_id)
    summary = state.get_summary()

    return {
        "type": "user_state",
        "user_id": user_id,
        "mode": summary.get("mode", "PAPER"),
        "balance": summary.get("capital", 0.0),
        "daily_pnl": summary.get("daily_pnl", 0.0),
        "daily_pnl_pct": summary.get("daily_pnl_pct", 0.0),
        "can_trade": summary.get("can_trade", False),
        "can_trade_reason": summary.get("can_trade_reason", ""),
        "positions": state.get_all_positions(),
        "orders": state.get_journal(limit=50),
        "timestamp": datetime.utcnow().isoformat(),
    }


async def _send_user_state_snapshot(
    websocket: WebSocket,
    user_id: int,
    source: str,
) -> None:
    payload = await _build_user_state_payload(user_id=user_id)
    payload["source"] = source
    await websocket.send_json(payload)


async def websocket_live(
    websocket: WebSocket, token: Optional[str] = Query(default=None)
):
    """Authenticated websocket endpoint: /ws?token=<jwt> (legacy alias: /live)."""
    client_host = websocket.client.host if websocket.client else "unknown"

    # IP Handshake Rate Limiting (max 5 connection attempts per 10 seconds per IP)
    now = time.time()
    with _ip_connection_lock:
        attempts = _ip_connection_attempts.setdefault(client_host, [])
        attempts = [t for t in attempts if now - t < 10.0]
        if len(attempts) >= 5:
            logger.warning("[WS][RATE-LIMIT] IP %s triggered connection storm limit. Rejecting connection.", client_host)
            try:
                from app.services.metrics import WS_THROTTLED_CONNECTIONS
                WS_THROTTLED_CONNECTIONS.inc()
            except Exception:
                pass
            await websocket.close(code=4029, reason="Too many connection attempts")
            return
        attempts.append(now)
        _ip_connection_attempts[client_host] = attempts

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        logger.warning("[WS] Rejected unauthenticated connection from %s", client_host)
        return


    try:
        user_id = await _resolve_websocket_user_id(token)
        if user_id is None:
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
    restored_symbols = socket_manager.pop_restored_symbols(client_id)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "WebSocket connected. Send subscribe message.",
                "connection_state": get_ws_state(),
                "restored_symbols": restored_symbols,
                "reconnect_grace_seconds": RECONNECT_GRACE_SECONDS,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        if restored_symbols:
            await websocket.send_json(
                {
                    "type": "restored_subscriptions",
                    "symbols": restored_symbols,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        await _send_user_state_snapshot(
            websocket=websocket,
            user_id=user_id,
            source="connect",
        )

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    await websocket.send_json(
                        {"type": "error", "message": "Payload must be a JSON object."}
                    )
                    continue
                await _process_ws_message(msg, client_id, user_id, websocket)

            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "connection_state": get_ws_state(),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "message": "Invalid JSON payload."}
                )
            except WebSocketDisconnect:
                break

    finally:
        # Clean up client subscriptions and trigger unsubscription of inactive symbols
        unsubscribed_tokens = await socket_manager.disconnect(client_id)
        if unsubscribed_tokens:
            connector = get_ws_connector()
            if connector:
                try:
                    connector.unsubscribe(unsubscribed_tokens)
                except Exception as exc:
                    logger.warning("[WS] Failed to unsubscribe tokens from broker on disconnect: %s", exc)
            with _ws_subscription_lock:
                for sym in unsubscribed_tokens:
                    _ws_subscribed_symbols.discard(sym)


async def _process_ws_message(
    msg: dict, client_id: str, user_id: int, websocket: WebSocket
):
    action = msg.get("action")

    if action == "subscribe":
        symbols = msg.get("symbols", [])
        
        # Max subscriptions guard per client to protect server memory bounds (max 50)
        current_subs = socket_manager._subscriptions.get(client_id, set())
        if isinstance(symbols, list) and len(current_subs) + len(symbols) > 50:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Subscription limit exceeded. Max 50 symbols allowed. Current count: {len(current_subs)}",
                }
            )
            return

        valid: list[str] = []
        rejected: list[str] = []
        if isinstance(symbols, list):

            for symbol in symbols:
                if not isinstance(symbol, str):
                    continue
                normalized = symbol.strip().upper()
                if not normalized or normalized in valid or normalized in rejected:
                    continue

                # Validate using live instrument service (not static watchlist) so
                # users can subscribe to any token-resolvable NSE symbol.
                try:
                    get_token_by_symbol(normalized, exchange=config.SMARTAPI_EXCHANGE)
                    valid.append(normalized)
                except KeyError:
                    rejected.append(normalized)

        await socket_manager.subscribe(client_id, valid)
        if valid:
            # start_smartapi_ws handles both initial start and incremental adds.
            start_smartapi_ws(valid)

        await websocket.send_json(
            {
                "type": "subscribed",
                "symbols": valid,
                "rejected_symbols": rejected,
                "connection_state": get_ws_state(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        logger.info(
            "[WS] user_id=%d client_id=%s subscribed=%s rejected=%s",
            user_id,
            client_id,
            valid,
            rejected,
        )

    elif action == "unsubscribe":
        symbols = msg.get("symbols", [])
        normalized = (
            [s.strip().upper() for s in symbols if isinstance(s, str)]
            if isinstance(symbols, list)
            else []
        )
        unsubscribed_tokens = await socket_manager.unsubscribe(client_id, normalized)
        if unsubscribed_tokens:
            connector = get_ws_connector()
            if connector:
                try:
                    connector.unsubscribe(unsubscribed_tokens)
                except Exception as exc:
                    logger.warning("[WS] Failed to unsubscribe tokens from broker: %s", exc)
            with _ws_subscription_lock:
                for sym in unsubscribed_tokens:
                    _ws_subscribed_symbols.discard(sym)
                    
        await websocket.send_json({"type": "unsubscribed", "symbols": normalized})

    elif action == "pong":
        return

    elif action == "ping":
        await websocket.send_json(
            {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    elif action in {"sync_state", "state", "get_state"}:
        await _send_user_state_snapshot(
            websocket=websocket,
            user_id=user_id,
            source="manual",
        )

    else:
        await websocket.send_json(
            {"type": "error", "message": f"Unknown action: {action}"}
        )


def setup_websocket_routes(app: FastAPI) -> None:
    app.websocket("/ws")(websocket_live)
    app.websocket("/live")(websocket_live)
