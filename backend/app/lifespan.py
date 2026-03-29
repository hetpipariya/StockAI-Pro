from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI

from app.config import DATABASE_URL, ENABLE_WS
from app.connectors import SmartAPIConnector
from app.services.db import check_db_connection, init_db
from app.services.instrument_master import get_instrument_count, load_instruments
from app.services.market_state import is_market_open
from app.services.redis_client import get_redis
from app.services.scheduler import start_scheduler, stop_scheduler
from app.websocket.handler import (
    DEFAULT_WATCHLIST,
    get_ws_connector,
    is_ws_streaming,
    set_event_loop,
    set_ws_connector,
    start_smartapi_ws,
)

logger = logging.getLogger(__name__)

_DB_BACKEND = "SQLite" if DATABASE_URL.startswith("sqlite") else "PostgreSQL"
try:
    parsed = urlparse(DATABASE_URL)
    if parsed.hostname:
        clean_path = (parsed.path or "")
        for sep in ("\n", "\r", "`n", "`r"):
            clean_path = clean_path.split(sep)[0]
        for marker in ("JWT_SECRET=", "APP_ENV=", "ENV=", "REDIS_URL="):
            clean_path = clean_path.split(marker)[0]
        clean_path = clean_path.strip()
        _DB_LOCATION = f"{parsed.hostname}:{parsed.port}{clean_path}"
    else:
        _DB_LOCATION = "configured"
except Exception:
    _DB_LOCATION = "configured"


def _log_model_artifact_status() -> None:
    """Log model artifact availability without failing startup."""
    try:
        from app.inference.models import MODEL_DIR
    except ModuleNotFoundError:
        from .inference.models import MODEL_DIR  # type: ignore

    required = ("model.pkl", "scaler.pkl", "features.pkl")
    missing = [name for name in required if not (MODEL_DIR / name).exists()]

    if missing:
        logger.warning(
            "[STARTUP] Model artifacts missing in %s: %s. API will run with HOLD-safe fallbacks.",
            MODEL_DIR,
            ", ".join(missing),
        )
    else:
        logger.info("[STARTUP] Model artifacts verified in %s", MODEL_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    def _loop_exception_handler(_loop: asyncio.AbstractEventLoop, context: dict):
        msg = context.get("message", "Unhandled event loop exception")
        err = context.get("exception")
        logger.error("[LOOP] %s | exception=%s", msg, err)

    loop.set_exception_handler(_loop_exception_handler)

    logger.info("[STARTUP] Initializing database...")
    try:
        await init_db()
        logger.info("[STARTUP] Database schema ensured")
    except Exception as exc:
        logger.exception("[STARTUP] DB schema initialization failed: %s", exc)

    logger.info("[STARTUP] Database backend: %s (%s)", _DB_BACKEND, _DB_LOCATION)
    try:
        db_ok = await check_db_connection(retries=3, delay=2.0)
    except Exception as exc:
        logger.warning("[STARTUP] DB health check failed: %s", exc)
        db_ok = False
    if db_ok:
        logger.info("[STARTUP] Database connection verified")
    else:
        logger.warning("[STARTUP] Database connection could not be verified")

    logger.info("[STARTUP] Restoring trading state...")
    try:
        from app.trading.trading_state import load_trading_state

        await asyncio.to_thread(load_trading_state)
        logger.info("[STARTUP] Trading state restored")
    except Exception as exc:
        logger.warning("[STARTUP] Trading state restore failed: %s", exc)

    logger.info("[STARTUP] Initializing Redis...")
    try:
        await get_redis()
    except Exception as exc:
        logger.warning("[STARTUP] Redis init failed; in-memory cache fallback active: %s", exc)

    logger.info("[STARTUP] Loading instrument master...")
    try:
        count = await asyncio.to_thread(load_instruments)
        logger.info("[STARTUP] %d instruments loaded", count)
    except Exception as exc:
        logger.warning("[STARTUP] Instrument master load failed: %s", exc)

    connector = None
    if ENABLE_WS:
        connector = SmartAPIConnector()
        set_ws_connector(connector)
        try:
            await asyncio.to_thread(connector.login)
            logger.info("[STARTUP] SmartAPI logged in")
        except Exception as exc:
            logger.warning("[STARTUP] SmartAPI login failed (mock mode possible): %s", exc)

        logger.info("[STARTUP] Starting SmartAPI websocket...")
        try:
            start_smartapi_ws(DEFAULT_WATCHLIST)
        except Exception as exc:
            logger.warning("[STARTUP] SmartAPI websocket start failed: %s", exc)
    else:
        logger.warning("[STARTUP] ENABLE_WS=false — SmartAPI WebSocket startup skipped")

    _log_model_artifact_status()

    logger.info("[STARTUP] Warming up ML model...")
    try:
        try:
            from app.inference.runner import predict_symbol
        except ModuleNotFoundError:
            from .inference.runner import predict_symbol

        warmup_result = predict_symbol(symbol="RELIANCE", timeframe="15m", latest_ltp=1400.0)
        logger.info("[STARTUP] Model warmup complete: signal=%s confidence=%d%%", warmup_result.signal, warmup_result.confidence)
    except Exception as exc:
        logger.warning("[STARTUP] Model warmup failed: %s", exc)

    try:
        start_scheduler()
    except Exception as exc:
        logger.warning("[STARTUP] Scheduler start failed: %s", exc)

    logger.info("=" * 60)
    logger.info("  StockAI Pro - Backend Ready")
    logger.info("  Instruments: %s", get_instrument_count())
    logger.info("  SmartAPI: %s", "Connected" if (connector and connector.is_logged_in) else "Not connected")
    logger.info("  Market: %s", "Open" if is_market_open() else "Closed")
    logger.info("  WS Stream: %s", "started" if is_ws_streaming() else "not started")
    logger.info("=" * 60)
    logger.info("[STARTUP] Server startup sequence completed")

    yield

    logger.info("[SHUTDOWN] Stopping services...")
    try:
        stop_scheduler()
    except Exception as exc:
        logger.warning("[SHUTDOWN] Scheduler stop failed: %s", exc)

    ws_connector = get_ws_connector()
    if ws_connector:
        try:
            ws_connector.stop_ws()
            ws_connector.terminate_session()
        except Exception:
            pass

    logger.info("[SHUTDOWN] Clean shutdown complete")
