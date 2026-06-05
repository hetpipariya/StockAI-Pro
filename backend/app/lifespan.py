from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import ENABLE_WS, TRADING_MODE
from app.services.db import check_db_connection, init_db
from app.services.instrument_service import (get_bootstrap_counts,
                                             refresh_instruments_daily)
from app.services.redis_client import initialize_redis
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.startup_manager import StartupManager
from app.websocket.handler import (
    get_or_create_ws_connector,
    get_ws_connector,
    set_event_loop,
    set_ws_connector,
)

logger = logging.getLogger(__name__)


# -----------------------------
# SMALL HELPERS
# -----------------------------
async def _initialize_database_schema() -> None:
    await init_db()
    db_ok = await check_db_connection(retries=2, delay=1.0)
    if not db_ok:
        raise RuntimeError("Database connection failed")


async def _initialize_redis() -> str:
    return await initialize_redis(max_attempts=3, retry_delay_seconds=1.0)


async def _initialize_instruments() -> dict[str, int]:
    try:
        loaded_count = await refresh_instruments_daily(force=False)
        counts = get_bootstrap_counts()
        return {
            "loaded": int(loaded_count),
            "total": int(counts.get("total", loaded_count)),
            "nse_eq": int(counts.get("nse_eq", 0)),
        }
    except Exception as exc:
        logger.warning("[INSTRUMENTS] Startup load failed; continuing in degraded mode: %s", exc)
        return {
            "loaded": 0,
            "total": 0,
            "nse_eq": 0,
        }


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


# -----------------------------
# MAIN LIFESPAN
# -----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    startup = StartupManager(app=app, logger=logger)

    logger.info("")
    logger.info("[STARTUP] Booting system...")

    connector = get_or_create_ws_connector()
    set_ws_connector(connector)

    instrument_counts = {"loaded": 0, "total": 0, "nse_eq": 0}
    redis_backend = "memory"

    try:
        # ✅ DB INIT
        await startup.run_step(
            number=1,
            component="db-schema",
            label="Initializing database schema",
            runner=_initialize_database_schema,
            success_message="Database ready",
        )

        # ✅ REDIS
        redis_backend = await startup.run_step(
            number=2,
            component="redis",
            label="Initializing Redis",
            runner=_initialize_redis,
            success_message=lambda backend: (
                "Redis connected"
                if backend == "redis"
                else "Redis memory-fallback mode"
            ),
        )

        # ✅ START REDIS RELAY LISTENER
        if redis_backend == "redis":
            try:
                from app.websocket.relay import start_realtime_relay_listener
                res = await start_realtime_relay_listener()
                logger.info("[WS-RELAY] Redis pub/sub relay listener initialized: %s", res)
            except Exception as relay_err:
                logger.error("[WS-RELAY] Failed to start Redis pub/sub relay listener: %s", relay_err)

        # ✅ INSTRUMENTS
        instrument_counts = await startup.run_step(
            number=3,
            component="instruments",
            label="Loading instrument master",
            runner=_initialize_instruments,
            critical=False,
            success_message=lambda counts: (
                f"Instrument master ready ({int(counts.get('total', 0))} mapped symbols)"
                if int(counts.get("total", 0)) > 0
                else "Instrument master unavailable; live token resolution degraded"
            ),
        )

        # ✅ SCHEDULER
        await startup.run_step(
            number=4,
            component="scheduler",
            label="Starting scheduler",
            runner=_start_scheduler,
            success_message="Scheduler started",
        )

        # ✅ READY
        startup.mark_ready(
            number=5,
            message="Server ready",
        )

        # ✅ LOAD BROKER SESSIONS ON STARTUP
        try:
            from app.services.broker_session_manager import broker_session_manager
            await broker_session_manager.load_sessions_on_startup()
        except Exception as session_err:
            logger.error("[STARTUP] Failed to load broker sessions on startup: %s", session_err)

        # ✅ PRE-WARM ML PROCESS EXECUTOR
        try:
            from app.inference.production_pipeline import get_process_executor
            get_process_executor()
            logger.info("[MLOPS] Persistent ProcessPoolExecutor initialized and pre-warmed successfully.")
        except Exception as exec_err:
            logger.warning("[MLOPS] Failed to pre-warm ProcessPoolExecutor: %s", exec_err)

        # ✅ LOGS
        logger.info("[DB] Connected [OK]")

        logger.info(
            "[REDIS] %s",
            "Connected [OK]"
            if redis_backend == "redis"
            else "Connected [DEGRADED] (memory fallback)",
        )

        loaded_symbols = int(instrument_counts.get("total", 0))
        if loaded_symbols > 0:
            logger.info("[INSTRUMENTS] Loaded %d symbols [OK]", loaded_symbols)
        else:
            logger.warning("[INSTRUMENTS] Loaded 0 symbols [DEGRADED]")

        logger.info("[SYSTEM] READY 🚀")

    except Exception as e:
        logger.error("Startup failed: %s", e)
        startup.mark_stopping()
        _abort_cleanup()
        raise

    yield

    # -----------------------------
    # SHUTDOWN
    # -----------------------------
    logger.info("[SHUTDOWN] Stopping services...")

    try:
        stop_scheduler()
    except Exception:
        pass

    try:
        from app.websocket.relay import stop_realtime_relay_listener
        await stop_realtime_relay_listener()
        logger.info("[WS-RELAY] Redis pub/sub relay listener stopped.")
    except Exception as relay_err:
        logger.warning("[WS-RELAY] Failed to stop Redis pub/sub relay listener cleanly: %s", relay_err)

    ws_connector = get_ws_connector()
    if ws_connector:
        try:
            ws_connector.stop_ws()
        except Exception:
            pass
        try:
            ws_connector.terminate_session()
        except Exception:
            pass

    try:
        from app.inference.production_pipeline import shutdown_process_executor
        shutdown_process_executor()
        logger.info("[MLOPS] Persistent ProcessPoolExecutor shut down successfully.")
    except Exception as exec_err:
        logger.warning("[MLOPS] Failed to shut down ProcessPoolExecutor: %s", exec_err)

    logger.info("[SHUTDOWN] Clean shutdown complete")

