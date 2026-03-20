"""
Main ASGI app — REST + WebSocket relay + SmartAPI integration.
Production-ready with instrument master, tick aggregation, and auto-reconnect.
"""
from __future__ import annotations

import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from prometheus_fastapi_instrumentator import Instrumentator

from app.routes import auth, market, order_proxy, predict, indicators, symbols, trading, news, sentiment, backtest
from app.websocket.relay import (
    register_client, unregister_client, broadcast_tick,
    broadcast_candle, broadcast_status, get_client_count,
)
from app.connectors import SmartAPIConnector, get_symbol_token
from app.services.db import init_db
from app.services.redis_client import get_redis
from app.services.instrument_master import load_instruments, get_token, get_symbol, get_instrument_count
from app.services.tick_aggregator import tick_aggregator
from app.services.candle_store import store_candles
from app.services.market_state import is_market_open

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_smartapi_ws_started = False
_ws_connector: SmartAPIConnector | None = None
_event_loop: asyncio.AbstractEventLoop | None = None

# Default watchlist symbols to subscribe on startup
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN",
    "ICICIBANK", "TATASTEEL", "ITC", "AXISBANK", "KOTAKBANK",
    "WIPRO", "BHARTIARTL", "HINDUNILVR", "LT", "MARUTI",
]


def _on_smartapi_tick(msg):
    """
    Callback when SmartAPI WS receives tick — runs in WS thread.
    Resolves token → symbol, aggregates into candles, broadcasts to clients.
    """
    try:
        # Debug: log raw tick structure
        if isinstance(msg, dict):
            logger.debug(f"[TICK-RAW] keys={list(msg.keys())[:10]}")
        else:
            logger.warning(f"[TICK-RAW] Non-dict message: {type(msg).__name__} — {str(msg)[:200]}")
            return
        if not isinstance(msg, dict):
            return

        # Extract token and resolve to symbol name via instrument master
        token = str(msg.get("token", msg.get("symboltoken", "")))
        symbol = get_symbol(token)
        if not symbol:
            symbol = msg.get("tradingsymbol", token)
            if symbol:
                symbol = symbol.replace("-EQ", "")

        ltp = float(msg.get("ltp", msg.get("last_traded_price", msg.get("lastprice", 0))))
        vol = int(msg.get("volume", msg.get("volume_trade_for_the_day", 0)) or 0)

        if ltp <= 0:
            return

        # Extract bid/ask from depth if available
        best_bid = ltp
        best_ask = ltp
        depth_buy = msg.get("depth", {}).get("buy", [])
        if depth_buy and len(depth_buy) > 0:
            best_bid = float(depth_buy[0].get("price", ltp))
        depth_sell = msg.get("depth", {}).get("sell", [])
        if depth_sell and len(depth_sell) > 0:
            best_ask = float(depth_sell[0].get("price", ltp))

        logger.debug(f"[TICK] {symbol} LTP={ltp} VOL={vol}")

        # 1. Aggregate tick into 1m candle
        completed_candle = tick_aggregator.process_tick(symbol, ltp, vol)

        # 1b. Feed into 15m candle builder for live trading
        from app.trading.candle_builder import candle_builder_15m
        completed_15m = candle_builder_15m.process_tick(symbol, ltp, vol)

        # 2. Broadcast raw tick to frontend (for price badge)
        tick_data = {"ltp": ltp, "volume": vol, "bid": best_bid, "ask": best_ask}
        _schedule_async(broadcast_tick(symbol, tick_data))

        # 3. Broadcast completed candle if minute rolled over
        if completed_candle:
            _schedule_async(broadcast_candle(symbol, completed_candle))
            _schedule_async(_persist_completed_candle(symbol, completed_candle))

        # 4. On 15m candle completion, trigger live trading executor
        if completed_15m:
            _schedule_async(_run_live_executor(symbol))

        # 5. Check exits on every tick for open positions
        from app.trading.live_executor import get_executor
        executor = get_executor()
        if executor.router.has_position(symbol):
            exit_result = executor.check_exits(symbol, ltp)
            if exit_result:
                logger.info(f"[TICK-EXIT] {symbol}: {exit_result['reason']} PnL=₹{exit_result['pnl']:,.2f}")

    except Exception as e:
        logger.warning(f"[TICK] Handler error: {e}")


async def _persist_completed_candle(symbol: str, candle: dict):
    """Persist a completed 1m candle on the app event loop."""
    try:
        stored = await store_candles(symbol, "1m", [candle])
        if stored:
            logger.debug(f"[DB] Persisted candle {symbol} @ {candle.get('time')}")
    except Exception as e:
        logger.error(f"[TICK] Failed to persist candle: {e}")


async def _run_live_executor(symbol: str):
    """Run the live trading executor when a 15m candle completes."""
    try:
        from app.trading.live_executor import get_executor
        executor = get_executor()
        result = executor.on_candle_complete(symbol)
        if result:
            logger.info(f"[EXECUTOR] {result.get('action', 'UNKNOWN')} on {symbol}: {result}")
    except Exception as e:
        logger.error(f"[EXECUTOR] Error evaluating {symbol}: {e}")


def _schedule_async(coro):
    """Schedule an async coroutine from a sync thread onto the main event loop."""
    global _event_loop
    if not _event_loop or not _event_loop.is_running():
        logger.warning("[ASYNC] Event loop not ready; dropping scheduled coroutine")
        try:
            coro.close()
        except Exception:
            pass
        return None

    future = asyncio.run_coroutine_threadsafe(coro, _event_loop)

    def _done(fut):
        try:
            fut.result()
        except Exception as e:
            logger.error(f"[ASYNC] Scheduled coroutine failed: {e}")

    future.add_done_callback(_done)
    return future


def _start_smartapi_ws(symbols_list: list[str]):
    """Start SmartAPI WebSocket subscription for given symbols."""
    global _smartapi_ws_started, _ws_connector

    if _smartapi_ws_started:
        return

    if not _ws_connector:
        _ws_connector = SmartAPIConnector()

    # Resolve symbols to tokens via instrument master
    tokens = []
    for sym in symbols_list:
        token = get_token(sym)
        if token:
            tokens.append(token)
        else:
            logger.warning(f"[WS] Cannot resolve token for {sym} — skipping")

    if not tokens:
        logger.warning("[WS] No valid tokens to subscribe")
        return

    token_list = [{"exchangeType": 1, "tokens": tokens}]
    logger.info(f"[WS] Subscribing to {len(tokens)} symbols: {tokens[:5]}...")

    try:
        _ws_connector.login()
        _ws_connector.start_ws(token_list, _on_smartapi_tick)
        _smartapi_ws_started = True
    except Exception as e:
        logger.error(f"[WS] Failed to start SmartAPI WebSocket: {e}")


# ─── Scheduler ───

scheduler = AsyncIOScheduler()


async def regen_token():
    """Re-login SmartAPI every morning at 08:30 IST."""
    logger.info("[SCHEDULER] Regenerating SmartAPI token")
    global _ws_connector
    if not _ws_connector:
        _ws_connector = SmartAPIConnector()
    try:
        _ws_connector.login(force=True)
    except Exception as e:
        logger.error(f"[SCHEDULER] Token regen failed: {e}")


async def refresh_instruments():
    """Reload instrument master daily at 08:00 IST."""
    logger.info("[SCHEDULER] Refreshing instrument master")
    load_instruments(force=True)


async def auto_start_ws():
    """Auto-start SmartAPI WS when market opens (runs every minute Mon-Fri 9-15h)."""
    global _smartapi_ws_started, _ws_connector
    if is_market_open() and not _smartapi_ws_started:
        logger.info("[SCHEDULER] Market is open — auto-starting WebSocket")
        if not _ws_connector:
            _ws_connector = SmartAPIConnector()
            _ws_connector.login()
        _start_smartapi_ws(DEFAULT_WATCHLIST)
    elif not is_market_open() and _smartapi_ws_started:
        logger.info("[SCHEDULER] Market closed — stopping WebSocket")
        if _ws_connector:
            _ws_connector.stop_ws()
        _smartapi_ws_started = False


async def prewarm_predictions():
    """Pre-compute predictions every 15 minutes."""
    from app.routes.predict import get_predict
    logger.info("[SCHEDULER] Pre-warming predictions")
    for s in DEFAULT_WATCHLIST[:4]:
        try:
            await get_predict(symbol=s, horizon="15m")
        except Exception as e:
            logger.warning(f"[SCHEDULER] Pre-warm failed for {s}: {e}")


async def sync_broker_positions():
    """Periodically sync DB positions with broker (LIVE mode only)."""
    from app import config as _cfg
    if _cfg.TRADING_MODE != "LIVE":
        return
    try:
        from app.trading.live_executor import get_executor
        executor = get_executor()
        report = executor.router.sync_positions_with_broker()
        if report.get("mismatches"):
            logger.warning(f"[SYNC] Position mismatches found: {report['mismatches']}")
    except Exception as e:
        logger.error(f"[SYNC] Broker sync job failed: {e}")


# ─── App Lifecycle ───

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _event_loop, _ws_connector

    # Capture the running event loop for cross-thread scheduling
    _event_loop = asyncio.get_running_loop()

    # 1. Init database (creates tables)
    logger.info("[STARTUP] Initializing database...")
    await init_db()

    # 1b. Restore trading state from DB (positions, risk, PnL)
    logger.info("[STARTUP] Restoring trading state...")
    try:
        from app.trading.trading_state import load_trading_state
        await asyncio.to_thread(load_trading_state)
        logger.info("[STARTUP] ✓ Trading state restored")
    except Exception as e:
        logger.warning(f"[STARTUP] Trading state restore failed (will use defaults): {e}")

    # 2. Init Redis (optional)
    logger.info("[STARTUP] Initializing Redis...")
    await get_redis()

    # 3. Load instrument master (downloads ScripMaster JSON — runs in thread to avoid blocking event loop)
    logger.info("[STARTUP] Loading instrument master...")
    try:
        count = await asyncio.to_thread(load_instruments)
        logger.info(f"[STARTUP] ✓ {count} instruments loaded")
    except Exception as e:
        logger.warning(f"[STARTUP] Instrument master load failed (will use fallback): {e}")

    # 4. Login to SmartAPI (sync I/O — run in thread to avoid blocking event loop)
    _ws_connector = SmartAPIConnector()
    try:
        await asyncio.to_thread(_ws_connector.login)
        logger.info("[STARTUP] ✓ SmartAPI logged in")
    except Exception as e:
        logger.warning(f"[STARTUP] SmartAPI login failed (will use mock data): {e}")

    # 5. Start WebSocket if market is open
    if is_market_open():
        logger.info("[STARTUP] Market is open — starting WebSocket...")
        _start_smartapi_ws(DEFAULT_WATCHLIST)
    else:
        logger.info("[STARTUP] Market is closed — WebSocket deferred")

    # 6. Start scheduler
    scheduler.add_job(regen_token, 'cron', hour=8, minute=30)
    scheduler.add_job(refresh_instruments, 'cron', hour=8, minute=0)
    scheduler.add_job(prewarm_predictions, 'cron', minute='*/15')
    scheduler.add_job(auto_start_ws, 'cron', minute='*/1', hour='9-15', day_of_week='mon-fri')
    scheduler.add_job(sync_broker_positions, 'cron', minute='*/5', hour='9-15', day_of_week='mon-fri')
    scheduler.start()
    logger.info("[STARTUP] ✓ Scheduler started (including auto WS start + broker sync jobs)")

    logger.info("=" * 60)
    logger.info("  StockAI Pro — Backend Ready")
    logger.info(f"  Instruments: {get_instrument_count()}")
    logger.info(f"  SmartAPI: {'Connected' if _ws_connector.is_logged_in else 'Not connected'}")
    logger.info(f"  Market: {'Open' if is_market_open() else 'Closed'}")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("[SHUTDOWN] Stopping services...")
    scheduler.shutdown()
    if _ws_connector:
        try:
            _ws_connector.stop_ws()
            _ws_connector.terminate_session()
        except Exception:
            pass
    logger.info("[SHUTDOWN] ✓ Clean shutdown")


# ─── App ───

app = FastAPI(title="StockAI Pro API", version="2.0", lifespan=lifespan)
# ─── CORS: restrict to known origins (production + dev) ───
_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# ─── Global rate limiter for login/auth endpoints ───
_login_attempts: dict[str, list[float]] = {}
_LOGIN_RATE_LIMIT = 5        # max attempts
_LOGIN_RATE_WINDOW = 300     # per 5 minutes

@app.middleware("http")
async def rate_limit_auth(request: Request, call_next):
    """Rate-limit authentication endpoints to prevent brute-force attacks."""
    import time
    path = request.url.path
    if path in ("/api/v1/auth/login", "/token"):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        attempts = _login_attempts.get(client_ip, [])
        # Clean old attempts outside window
        attempts = [t for t in attempts if now - t < _LOGIN_RATE_WINDOW]
        if len(attempts) >= _LOGIN_RATE_LIMIT:
            logger.warning(f"[RATE-LIMIT] Blocked login attempt from {client_ip} — {len(attempts)} attempts in {_LOGIN_RATE_WINDOW}s")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many login attempts. Please wait 5 minutes."},
            )
        attempts.append(now)
        _login_attempts[client_ip] = attempts
    return await call_next(request)

# Instrument the app for Prometheus metric scraping
Instrumentator().instrument(app).expose(app)

app.include_router(auth.router)
app.include_router(auth.alias_router)
app.include_router(news.router)
app.include_router(sentiment.router)
app.include_router(backtest.router)
app.include_router(market.router)
app.include_router(order_proxy.router)
app.include_router(predict.router)
app.include_router(indicators.router)
app.include_router(symbols.router)
app.include_router(trading.router)


@app.get("/health")
def health():
    """Enhanced health check with system status."""
    return {
        "status": "ok",
        "service": "stockai-pro",
        "version": "2.0",
        "instruments": get_instrument_count(),
        "smartapi_connected": _ws_connector.is_logged_in if _ws_connector else False,
        "ws_clients": get_client_count(),
        "market_open": is_market_open(),
        "ws_streaming": _smartapi_ws_started,
    }


@app.post("/debug/start-ws")
async def debug_start_ws():
    """Force-start SmartAPI WebSocket (debug/diagnostic endpoint)."""
    global _smartapi_ws_started
    if _smartapi_ws_started:
        return {"status": "already_running", "market_open": is_market_open(), "clients": get_client_count()}
    try:
        _start_smartapi_ws(DEFAULT_WATCHLIST)
        return {"status": "started", "market_open": is_market_open()}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _sanitize_symbols(values) -> list[str]:
    if not isinstance(values, list):
        return []
    sanitized: list[str] = []
    seen = set()
    for item in values:
        if not isinstance(item, str):
            continue
        value = item.strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        sanitized.append(value)
    return sanitized


@app.websocket("/live")
async def websocket_live(ws: WebSocket):
    """Frontend WebSocket endpoint for real-time data."""
    await ws.accept()
    register_client(ws)

    # Send initial status
    await ws.send_text(json.dumps({
        "type": "status",
        "connected": _ws_connector.is_logged_in if _ws_connector else False,
        "ws_streaming": _smartapi_ws_started,
        "market_open": is_market_open(),
    }))

    # Heartbeat task: send ping every 30s to keep connection alive
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    await ws.send_text(json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    hb_task = asyncio.create_task(heartbeat())

    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=65)
            except asyncio.TimeoutError:
                continue

            try:
                msg = json.loads(data)
                if not isinstance(msg, dict):
                    continue

                action = msg.get("action", "")

                if action == "subscribe":
                    sub_symbols = _sanitize_symbols(msg.get("symbols", []))
                    logger.info(f"[WS] Client subscribing to: {sub_symbols}")

                    # Start SmartAPI WS if not already running and market is open
                    if not _smartapi_ws_started and sub_symbols and is_market_open():
                        _start_smartapi_ws(sub_symbols)

                    await ws.send_text(json.dumps({
                        "type": "subscribed",
                        "symbols": sub_symbols,
                        "streaming": _smartapi_ws_started,
                    }))

                elif action == "unsubscribe":
                    unsub_symbols = _sanitize_symbols(msg.get("symbols", []))
                    logger.info(f"[WS] Client unsubscribing from: {unsub_symbols}")

                elif action == "pong":
                    pass  # Client heartbeat response, connection is alive

            except json.JSONDecodeError:
                pass
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        logger.debug(f"[WS] Client error: {e}")
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except Exception:
            pass
        unregister_client(ws)


@app.websocket("/ws/market")
async def websocket_market(ws: WebSocket):
    """Alias for /live — frontend can connect via /ws/market."""
    await websocket_live(ws)

