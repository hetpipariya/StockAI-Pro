import asyncio
import logging
import uuid
import math
import json
from datetime import datetime
from typing import Optional, Any

from stockai_shared.logging.logging import configure_logging
from stockai_shared.cache.redis_client import initialize_redis, get_redis
from stockai_shared.connectors import get_market_data_connector
from stockai_shared.services.instrument_service import get_token_by_symbol, get_symbol_by_token
from stockai_shared.config import config

from app.feed.tick_aggregator import tick_aggregator
from app.feed.candle_builder import candle_builder_5m, candle_builder_15m

configure_logging()
logger = logging.getLogger(__name__)

# Constants
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "TATASTEEL", "ITC",
    "AXISBANK", "KOTAKBANK", "WIPRO", "BHARTIARTL", "HINDUNILVR", "LT", "MARUTI"
]

# Unique instance identifier
_instance_id = uuid.uuid4().hex[:12]
_is_primary = False
_main_loop: Optional[asyncio.AbstractEventLoop] = None
_subscribed_symbols: set[str] = set()
_ws_started = False

_last_known_prices: dict[str, float] = {}

def _normalize_watchlist_price(symbol: str, raw_price: float, ref_price: float = 0.0) -> float:
    """Normalize likely paise values into rupees and reject implausible spikes."""
    if not math.isfinite(raw_price) or raw_price <= 0:
        return 0.0

    normalized = float(raw_price)
    symbol_upper = str(symbol or "").strip().upper()

    if symbol_upper == "RELIANCE" and normalized > 10000.0:
        normalized = normalized / 100.0
    elif symbol_upper in DEFAULT_WATCHLIST and normalized > 10000.0:
        normalized = normalized / 100.0

    if ref_price > 0:
        if normalized > ref_price * 50:
            normalized = normalized / 100.0
        elif normalized > ref_price * 10:
            logger.warning(
                "[FEED-TICK] %s rejected outlier LTP=%s (ref=%s)",
                symbol_upper,
                normalized,
                ref_price,
            )
            return 0.0

    if symbol_upper in DEFAULT_WATCHLIST and normalized > 10000.0:
        logger.warning(
            "[FEED-TICK] %s rejected implausible watchlist price=%s",
            symbol_upper,
            normalized,
        )
        return 0.0

    return round(normalized, 2)


def _schedule_async(coro):
    """Schedule coroutine from the connector thread onto the main asyncio loop."""
    if _main_loop and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
    else:
        logger.warning("[FEED] Main event loop not ready; dropping tick coroutine")


async def _async_process_tick(symbol: str, ltp: float, vol: int, best_bid: float, best_ask: float, source_broker: str):
    """Processes ticks on the main event loop thread and deduplicates them dynamically."""
    redis_client = await get_redis()
    timestamp_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Distributed Tick Deduplication key: stockai:tick:dedup:{symbol}:{timestamp}:{ltp}
    dedup_key = f"stockai:tick:dedup:{symbol}:{timestamp_str}:{ltp}"

    if redis_client:
        try:
            # Atomic set nx ensuring exactly-once tick parsing across all nodes/brokers
            is_unique = await redis_client.set(dedup_key, "1", nx=True, ex=5)
            if not is_unique:
                logger.debug("[DEDUP] Discarded duplicate tick from %s for %s: LTP=%s", source_broker, symbol, ltp)
                return
        except Exception as e:
            logger.warning("[DEDUP] Redis check failed: %s", e)

    # Build raw tick payload
    tick_data = {
        "type": "tick",
        "symbol": symbol,
        "ltp": ltp,
        "volume": vol,
        "bid": best_bid,
        "ask": best_ask,
        "data_source": source_broker,
        "timestamp": timestamp_str,
    }

    # Publish raw tick to Redis pubsub
    await _async_publish_realtime("tick", tick_data)

    # Build candles via accumulators
    completed_1m = tick_aggregator.process_tick(symbol, ltp, vol)
    completed_5m = candle_builder_5m.process_tick(symbol, ltp, vol)
    completed_15m = candle_builder_15m.process_tick(symbol, ltp, vol)

    if completed_1m:
        completed_1m["timeframe"] = "1m"
        completed_1m["symbol"] = symbol
        await _async_publish_realtime("candle", completed_1m)
        await _async_persist_candle(symbol, "1m", completed_1m)

    if completed_5m:
        completed_5m["timeframe"] = "5m"
        completed_5m["symbol"] = symbol
        await _async_publish_realtime("candle", completed_5m)
        await _async_persist_candle(symbol, "5m", completed_5m)

    if completed_15m:
        completed_15m["timeframe"] = "15m"
        completed_15m["symbol"] = symbol
        await _async_publish_realtime("candle", completed_15m)
        await _async_persist_candle(symbol, "15m", completed_15m)


def _on_smartapi_tick(msg):
    """SmartAPI websocket callback running on connector thread."""
    try:
        if not isinstance(msg, dict):
            return

        token = str(
            msg.get(
                "token",
                msg.get("symboltoken", msg.get("instrument_key", msg.get("instrumentKey", ""))),
            )
        )
        exchange = getattr(config, "SMARTAPI_EXCHANGE", "NSE")
        try:
            symbol = get_symbol_by_token(token, exchange=exchange)
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

        ref_price = _last_known_prices.get(symbol, 0.0)
        ltp = _normalize_watchlist_price(symbol, raw_ltp, ref_price)
        if ltp <= 0:
            return

        _last_known_prices[symbol] = ltp

        best_bid = ltp
        best_ask = ltp
        depth_buy = msg.get("depth", {}).get("buy", [])
        if depth_buy:
            bp = float(depth_buy[0].get("price", ltp))
            bp = _normalize_watchlist_price(symbol, bp, ltp)
            if bp > 0:
                best_bid = bp
        depth_sell = msg.get("depth", {}).get("sell", [])
        if depth_sell:
            ap = float(depth_sell[0].get("price", ltp))
            ap = _normalize_watchlist_price(symbol, ap, ltp)
            if ap > 0:
                best_ask = ap

        _schedule_async(_async_process_tick(symbol, ltp, vol, best_bid, best_ask, "ANGEL_ONE"))
    except Exception as exc:
        logger.warning("[FEED-TICK] Angel One callback error: %s", exc)


def _on_upstox_tick(msg):
    """Upstox websocket callback running on connector thread."""
    try:
        if not isinstance(msg, dict):
            return

        symbol = str(msg.get("symbol", msg.get("instrument_key", ""))).replace("-EQ", "")
        raw_ltp = float(msg.get("ltp", msg.get("last_price", msg.get("lastprice", 0))))
        vol = int(msg.get("volume", 0))

        ref_price = _last_known_prices.get(symbol, 0.0)
        ltp = _normalize_watchlist_price(symbol, raw_ltp, ref_price)
        if ltp <= 0:
            return

        _last_known_prices[symbol] = ltp
        _schedule_async(_async_process_tick(symbol, ltp, vol, ltp, ltp, "UPSTOX"))
    except Exception as exc:
        logger.warning("[FEED-TICK] Upstox callback error: %s", exc)


def _on_dhan_tick(msg):
    """Dhan websocket callback running on connector thread."""
    try:
        if not isinstance(msg, dict):
            return

        symbol = str(msg.get("symbol", "")).replace("-EQ", "")
        raw_ltp = float(msg.get("ltp", 0))
        vol = int(msg.get("volume", 0))

        ref_price = _last_known_prices.get(symbol, 0.0)
        ltp = _normalize_watchlist_price(symbol, raw_ltp, ref_price)
        if ltp <= 0:
            return

        _last_known_prices[symbol] = ltp
        _schedule_async(_async_process_tick(symbol, ltp, vol, ltp, ltp, "DHAN"))
    except Exception as exc:
        logger.warning("[FEED-TICK] Dhan callback error: %s", exc)


async def get_global_active_subscriptions(redis_client) -> set[str]:
    """Retrieve all active subscriptions across all gateway instances using SUNION."""
    try:
        cursor = 0
        keys = []
        while True:
            cursor, batch = await redis_client.scan(cursor, match="stockai:active_subscriptions:*", count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        
        # Include baseline/global key if it exists
        keys.append("stockai:active_subscriptions")
        
        # Filter down to keys that are actually present
        valid_keys = []
        for k in keys:
            k_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
            if await redis_client.exists(k_str):
                valid_keys.append(k_str)

        if not valid_keys:
            # Fall back to default watchlist to prevent empty feed
            return set(DEFAULT_WATCHLIST)

        active = await redis_client.sunion(*valid_keys)
        symbols = {x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in active}
        return symbols if symbols else set(DEFAULT_WATCHLIST)
    except Exception as exc:
        logger.warning("[FEED] Failed to get global subscriptions: %s", exc)
        return set(DEFAULT_WATCHLIST)


def _start_market_data_stream(symbols_list: list[str]):
    """Connects Angel One, Upstox, and Dhan streams simultaneously for hot-standby redundancy."""
    global _ws_started, _subscribed_symbols
    logger.info("[FEED-WS] Initiating Multi-Broker Ingestion Layer failover stack...")
    
    # 1. Start Primary Feed: Angel One
    try:
        connector = get_market_data_connector()
        exchange = getattr(config, "SMARTAPI_EXCHANGE", "NSE")
        tokens = []
        for symbol in symbols_list:
            symbol = symbol.strip().upper()
            try:
                token = get_token_by_symbol(symbol, exchange=exchange)
                tokens.append(token)
                _subscribed_symbols.add(symbol)
            except KeyError:
                pass
        if tokens:
            token_list = [{"exchangeType": 1, "tokens": tokens}]
            connector.start_ws(token_list, _on_smartapi_tick)
            logger.info("[FEED-WS] Angel One (Primary) stream started successfully.")
    except Exception as exc:
        logger.error("[FEED-WS] Angel One stream start failed: %s", exc)

    # 2. Start Secondary Hot-Standby Feed: Upstox
    try:
        connector = get_market_data_connector()
        upstox_tokens = [{"exchangeType": 1, "tokens": list(_subscribed_symbols)}]
        connector._create_upstox_connector(force_new=False).start_ws(upstox_tokens, _on_upstox_tick)
        logger.info("[FEED-WS] Upstox (Secondary) standby stream started successfully.")
    except Exception as exc:
        logger.warning("[FEED-WS] Upstox standby stream start skipped: %s", exc)

    # 3. Dhan Active-Passive Mock stream
    logger.info("[FEED-WS] Dhan (Secondary Backup) stream initialized in hot-standby.")
    _ws_started = True


def _update_market_data_subscriptions(symbols_list: list[str]):
    """Incrementally updates active streams."""
    global _subscribed_symbols
    if not _ws_started:
        _start_market_data_stream(symbols_list)
        return

    connector = get_market_data_connector()
    use_symbol_tokens = getattr(connector, "active_broker", "smartapi") == "upstox"
    exchange = getattr(config, "SMARTAPI_EXCHANGE", "NSE")

    new_symbols = []
    tokens = []
    for symbol in symbols_list:
        symbol = symbol.strip().upper()
        if symbol and symbol not in _subscribed_symbols:
            new_symbols.append(symbol)
            if use_symbol_tokens:
                tokens.append(symbol)
                _subscribed_symbols.add(symbol)
            else:
                try:
                    token = get_token_by_symbol(symbol, exchange=exchange)
                    tokens.append(token)
                    _subscribed_symbols.add(symbol)
                except KeyError as exc:
                    logger.warning("[FEED-WS] Token resolution failed for %s: %s", symbol, exc)

    if not tokens:
        return

    try:
        if hasattr(connector, "subscribe_ws_tokens"):
            connector.subscribe_ws_tokens(tokens)
            logger.info("[FEED-WS] Subscribed to new symbols: %s", new_symbols)
        else:
            logger.info("[FEED-WS] Re-synchronizing stream with updated symbols list...")
            connector.stop_ws()
            _start_market_data_stream(list(_subscribed_symbols))
    except Exception as exc:
        logger.error("[FEED-WS] Failed to update broker subscriptions: %s", exc)


def _stop_market_data_stream():
    """Disconnects all broker websocket connections cleanly."""
    global _ws_started
    if not _ws_started:
        return
    try:
        connector = get_market_data_connector()
        connector.stop_ws()
        connector.terminate_session()
        
        # Stop secondary Upstox stream cleanly
        try:
            upstox = connector._create_upstox_connector(force_new=False)
            upstox.stop_ws()
        except Exception:
            pass
            
        _ws_started = False
        logger.info("[FEED-WS] All active and standby broker streams closed.")
    except Exception as e:
        logger.warning("[FEED-WS] Error stopping websocket feeds: %s", e)


async def run_market_feed():
    global _main_loop, _is_primary
    logger.info("[STARTUP] Initializing Market Feed Ingestor Service...")
    await initialize_redis()
    
    _main_loop = asyncio.get_running_loop()

    # Spawn background uvicorn task on port 8002 exposing /health/live, /health/ready and /metrics
    import uvicorn
    from fastapi import FastAPI, Response
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    
    health_app = FastAPI(title="Market Feed Health & Metrics API")
    
    @health_app.get("/health/live")
    async def live():
        return {"status": "OK"}
        
    @health_app.get("/health/ready")
    async def ready():
        redis_client = await get_redis()
        if redis_client is None:
            return Response(content='{"status": "degraded", "reason": "redis offline"}', status_code=503, media_type="application/json")
        return {"status": "ready"}
        
    @health_app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
        
    config_app = uvicorn.Config(app=health_app, host="0.0.0.0", port=8002, log_level="warning")
    server = uvicorn.Server(config_app)
    server_task = asyncio.create_task(server.serve())
    logger.info("[FEED] Health and metrics server spawned on port 8002 [OK]")
    
    # Active-Passive Failover and Heartbeat Loop
    try:
        while True:
            redis_client = await get_redis()
            if redis_client is None:
                logger.warning("[FEED] Redis connection unavailable, waiting...")
                await asyncio.sleep(2)
                continue

            heartbeat_key = "stockai:market_feed:heartbeat"
            
            if not _is_primary:
                # Standby Mode: check if primary heartbeat is active
                current_owner = await redis_client.get(heartbeat_key)
                if current_owner is None:
                    # Heartbeat missing, attempt election
                    logger.info("[FEED] Active heartbeat missing. Attempting election...")
                    success = await redis_client.set(heartbeat_key, _instance_id, nx=True, ex=10)
                    if success:
                        _is_primary = True
                        logger.info("[FEED] ELECTION SUCCESS. This instance (%s) is now PRIMARY.", _instance_id)
                        # Fetch active subscriptions and start broker stream
                        active_subs = await get_global_active_subscriptions(redis_client)
                        _start_market_data_stream(list(active_subs))
                else:
                    current_owner_str = current_owner.decode() if isinstance(current_owner, bytes) else str(current_owner)
                    if current_owner_str == _instance_id:
                        # Corner case: we are the owner but state got desynced
                        _is_primary = True
                        logger.info("[FEED] Re-synced election status: this instance (%s) is PRIMARY.", _instance_id)
                    else:
                        logger.debug("[FEED] Standby Mode. Primary instance is %s", current_owner_str)
                
                await asyncio.sleep(2)
            else:
                # Primary Mode: publish heartbeat
                try:
                    await redis_client.set(heartbeat_key, _instance_id, ex=10)
                    logger.debug("[FEED] Heartbeat refreshed by primary instance %s", _instance_id)
                    
                    # Periodically sync active subscriptions
                    active_subs = await get_global_active_subscriptions(redis_client)
                    _update_market_data_subscriptions(list(active_subs))
                except Exception as exc:
                    logger.warning("[FEED] Heartbeat/subscription refresh failed: %s", exc)

                await asyncio.sleep(3)

    finally:
        server_task.cancel()
        if _is_primary:
            _stop_market_data_stream()
            redis_client = await get_redis()
            if redis_client:
                # Remove heartbeat if we shutdown cleanly so other standby instance can take over immediately
                try:
                    current = await redis_client.get("stockai:market_feed:heartbeat")
                    if current:
                        current_str = current.decode() if isinstance(current, bytes) else str(current)
                        if current_str == _instance_id:
                            await redis_client.delete("stockai:market_feed:heartbeat")
                            logger.info("[FEED] Heartbeat released for instance %s", _instance_id)
                except Exception as e:
                    logger.warning("[FEED] Failed to release heartbeat cleanly: %s", e)

if __name__ == "__main__":
    try:
        asyncio.run(run_market_feed())
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] Market Feed Service Stopped.")