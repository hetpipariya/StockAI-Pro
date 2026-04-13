from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI

from app.config import DATABASE_URL, ENABLE_WS, TRADING_MODE
from app.services.db import check_db_connection, init_db
from app.services.instrument_service import (get_bootstrap_counts,
                                             refresh_instruments_daily)
from app.services.redis_client import get_redis
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.startup_manager import StartupManager
from app.websocket.handler import (DEFAULT_WATCHLIST, get_or_create_ws_connector,
                                   get_ws_connector, is_ws_streaming, set_event_loop,
                                   set_ws_connector, start_smartapi_ws)

logger = logging.getLogger(__name__)

_DB_BACKEND = "SQLite" if DATABASE_URL.startswith("sqlite") else "PostgreSQL"
try:
    parsed = urlparse(DATABASE_URL)
    if parsed.hostname:
        clean_path = parsed.path or ""
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


def _resolve_model_artifacts() -> tuple[Path, list[str]]:
    try:
        from app.inference.models import MODEL_DIR, REQUIRED_MODEL_FILES
    except ModuleNotFoundError:
        from .inference.models import MODEL_DIR, REQUIRED_MODEL_FILES  # type: ignore

    required = tuple(REQUIRED_MODEL_FILES)
    missing = [name for name in required if not (MODEL_DIR / name).exists()]
    return MODEL_DIR, missing


async def _restore_trading_state() -> None:
    from app.trading.trading_state import load_trading_state

    await asyncio.to_thread(load_trading_state)


async def _initialize_redis() -> str:
    redis_client = await get_redis()
    return "redis" if redis_client is not None else "fallback"


async def _load_instruments_cached() -> dict[str, int]:
    # Prefer cached Redis/DB snapshot and only hit OpenAPI when cache is cold.
    await refresh_instruments_daily(force=False)
    return get_bootstrap_counts()


async def _start_websocket_stream() -> None:
    await asyncio.to_thread(start_smartapi_ws, DEFAULT_WATCHLIST)
    if not is_ws_streaming():
        raise RuntimeError("WebSocket stream did not reach CONNECTED state")


async def _warmup_model() -> dict[str, float | str]:
    model_dir, missing = _resolve_model_artifacts()
    if missing:
        raise RuntimeError(
            f"Model files missing in {model_dir}: {', '.join(missing)}"
        )

    try:
        from app.inference.runner import predict_symbol
    except ModuleNotFoundError:
        from .inference.runner import predict_symbol

    warmup_result = await asyncio.to_thread(
        predict_symbol,
        symbol="RELIANCE",
        timeframe="15m",
        latest_ltp=1400.0,
    )
    return {
        "signal": str(warmup_result.signal),
        "confidence": float(warmup_result.confidence),
    }


async def _prewarm_bundle_cache() -> dict:
    from app.services.bundle_service import DEFAULT_PREWARM_SYMBOLS, prewarm_bundle_cache

    report = await prewarm_bundle_cache(
        list(DEFAULT_PREWARM_SYMBOLS),
        allow_live=False,
    )
    report = report or {}
    requested = int(report.get("requested", 0) or 0)
    succeeded = int(report.get("succeeded", 0) or 0)
    if requested > 0 and succeeded <= 0:
        raise RuntimeError("Bundle cache prewarm failed for all requested symbols")
    return report


async def _initialize_database_schema() -> None:
    await init_db()
    db_ok = await check_db_connection(retries=2, delay=1.0)
    if not db_ok:
        raise RuntimeError("Database connection verification failed")


def _start_scheduler() -> None:
    start_scheduler()


def _abort_cleanup() -> None:
    try:
        stop_scheduler()
    except Exception:
        pass

    connector = get_ws_connector()
    if connector:
        try:
            connector.stop_ws()
        except Exception:
            pass
        try:
            connector.terminate_session()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle with deterministic boot ordering."""
    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    def _loop_exception_handler(_loop: asyncio.AbstractEventLoop, context: dict):
        msg = context.get("message", "Unhandled event loop exception")
        err = context.get("exception")
        logger.error("[LOOP] %s | exception=%s", msg, err)

    loop.set_exception_handler(_loop_exception_handler)

    startup = StartupManager(app=app, logger=logger)
    logger.info("")
    logger.info("[STARTUP] Booting system...")

    connector = get_or_create_ws_connector()
    set_ws_connector(connector)

    try:
        await startup.run_step(
            number=1,
            component="db-schema",
            label="Initializing database schema",
            runner=_initialize_database_schema,
            success_message="Database schema ensured",
        )
        await startup.run_step(
            number=2,
            component="trading-state",
            label="Restoring trading state",
            runner=_restore_trading_state,
            success_message="Trading state restored",
        )
        redis_backend = await startup.run_step(
            number=3,
            component="redis",
            label="Initializing Redis cache",
            runner=_initialize_redis,
            success_message=lambda backend: (
                "Redis connected"
                if backend == "redis"
                else "Redis unavailable; using in-memory fallback"
            ),
        )
        await startup.run_step(
            number=4,
            component="smartapi-login",
            label="SmartAPI broker login",
            runner=lambda: asyncio.to_thread(connector.login),
            success_message="SmartAPI logged in successfully",
            abort_message="Startup aborted. Please check broker/session credentials.",
        )
        instrument_counts = await startup.run_step(
            number=5,
            component="instrument-master",
            label="Loading instrument master",
            runner=_load_instruments_cached,
            success_message=lambda counts: (
                f"Loaded {int(counts.get('nse_eq', 0))} NSE EQ instruments"
            ),
        )

        if ENABLE_WS:
            await startup.run_step(
                number=6,
                component="websocket",
                label="Connecting live WebSocket stream for watchlist",
                runner=_start_websocket_stream,
                success_message="SmartAPI WebSocket startup initiated",
            )
        else:
            startup.skip_step(
                number=6,
                component="websocket",
                label="Connecting live WebSocket stream for watchlist",
                reason="ENABLE_WS=false",
            )

        await startup.run_step(
            number=7,
            component="scheduler",
            label="Starting scheduler jobs",
            runner=_start_scheduler,
            success_message="Scheduler started",
        )
        model_warmup = await startup.run_step(
            number=8,
            component="model-warmup",
            label="Loading ML model and warming up first prediction",
            runner=_warmup_model,
            success_message=lambda result: (
                "Model warmup complete: "
                f"signal={result['signal']} confidence={float(result['confidence']) * 100.0:.1f}%"
            ),
            abort_message="Startup aborted. Please ensure model artifacts are available.",
        )
        startup.mark_ready(
            number=9,
            message="Server startup sequence completed",
        )
        logger.info("[DB] Connected [OK]")
        logger.info(
            "[REDIS] %s",
            "Connected [OK]"
            if redis_backend == "redis"
            else "Connected [FAIL] (fallback)",
        )
        logger.info(
            "[INSTRUMENTS] Loaded %d symbols [OK]",
            int(instrument_counts.get("nse_eq", 0)),
        )
        logger.info("")
        logger.info("[SMARTAPI]")
        logger.info(
            "  -> Token: %s",
            "GENERATED [OK]" if connector.is_logged_in else "MISSING [FAIL]",
        )
        logger.info("")
        logger.info("[WS]")
        logger.info("  -> Connected: %s", "TRUE" if is_ws_streaming() else "FALSE")
        logger.info("")
        logger.info("[SYSTEM]")
        logger.info("  -> Scheduler: Running")
        logger.info("  -> ML Model: Loaded")
        logger.info("  -> Trading Mode: %s", TRADING_MODE)
        if model_warmup:
            logger.debug(
                "[SYSTEM] Model warmup detail: signal=%s confidence=%.1f%%",
                str(model_warmup.get("signal", "n/a")),
                float(model_warmup.get("confidence", 0.0)) * 100.0,
            )
        logger.info("")
        logger.info("===================================")
        logger.info("SYSTEM READY (ALL SERVICES UP)")
        logger.info("===================================")
        logger.info("")
    except Exception:
        startup.mark_stopping()
        _abort_cleanup()
        raise

    yield

    logger.info("[SHUTDOWN] Stopping services...")
    startup.mark_stopping()

    try:
        stop_scheduler()
        logger.info("[SHUTDOWN] Scheduler stopped")
    except Exception as exc:
        logger.warning("[SHUTDOWN] Scheduler stop failed: %s", exc)

    ws_connector = get_ws_connector()
    if ws_connector:
        logger.info("[SHUTDOWN] Stopping WebSocket...")
        try:
            ws_connector.stop_ws()
            logger.info("[SHUTDOWN] WebSocket stopped")
        except Exception as exc:
            logger.warning("[SHUTDOWN] WebSocket stop failed: %s", exc)

        try:
            ws_connector.terminate_session()
            logger.info("[SHUTDOWN] SmartAPI session terminated")
        except Exception as exc:
            logger.warning("[SHUTDOWN] Session termination failed: %s", exc)

    logger.info("[SHUTDOWN] Clean shutdown complete")
