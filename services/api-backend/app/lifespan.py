from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from stockai_shared.config.config import ENABLE_WS, TRADING_MODE
from stockai_shared.db.db import check_db_connection, init_db
from stockai_shared.services.instrument_service import (get_bootstrap_counts,
                                             refresh_instruments_daily)
from stockai_shared.cache.redis_client import initialize_redis
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.startup_manager import StartupManager
from app.ws.handler import (
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
# SRE OBSERVABILITY POLLER
# -----------------------------
_last_paper_trades_total = 0
_last_paper_positions_closed = 0
_last_risk_halts_total = 0

async def _sre_observability_poller():
    global _last_paper_trades_total, _last_paper_positions_closed, _last_risk_halts_total
    
    # Wait a few seconds for startup to finish
    await asyncio.sleep(5.0)
    
    while True:
        try:
            # 1. Database Pool metrics
            try:
                from stockai_shared.db.db import engine, replica_engine, sync_engine
                from stockai_shared.metrics.metrics import (
                    DB_POOL_CHECKED_OUT,
                    DB_POOL_IDLE,
                    DB_POOL_OVERFLOW
                )
                
                seen_pools = set()
                total_checked_out = 0
                total_idle = 0
                total_overflow = 0
                
                for eng in (engine, replica_engine, sync_engine):
                    if eng is None:
                        continue
                    pool = getattr(eng, "sync_engine", eng).pool
                    if pool in seen_pools:
                        continue
                    seen_pools.add(pool)
                    
                    if hasattr(pool, "checkedout"):
                        total_checked_out += pool.checkedout()
                    if hasattr(pool, "checkedin"):
                        total_idle += pool.checkedin()
                    if hasattr(pool, "overflow"):
                        total_overflow += max(0, pool.overflow())
                
                DB_POOL_CHECKED_OUT.set(total_checked_out)
                DB_POOL_IDLE.set(total_idle)
                DB_POOL_OVERFLOW.set(total_overflow)
            except Exception as e:
                logger.debug("Failed to poll DB pool metrics: %s", e)

            # 2. Redis capacity metrics
            try:
                from stockai_shared.cache.redis_client import get_redis
                from stockai_shared.metrics.metrics import (
                    REDIS_MEMORY_USED_BYTES,
                    REDIS_CONNECTED_CLIENTS,
                    REDIS_PUBSUB_CHANNELS,
                    REDIS_PUBSUB_SUBSCRIBERS,
                    REDIS_KEY_COUNT,
                    REDIS_CACHE_HIT_RATIO,
                    REDIS_REPLICA_STATUS,
                    REDIS_SENTINEL_STATUS
                )
                
                redis_client = await get_redis()
                if redis_client is not None:
                    info = await redis_client.info()
                    
                    used_memory = float(info.get("used_memory", 0))
                    REDIS_MEMORY_USED_BYTES.set(used_memory)
                    try:
                        from stockai_shared.metrics.metrics import REDIS_CACHE_MEMORY_BYTES
                        REDIS_CACHE_MEMORY_BYTES.set(used_memory)
                    except Exception:
                        pass
                    
                    connected_clients = float(info.get("connected_clients", 0))
                    REDIS_CONNECTED_CLIENTS.set(connected_clients)
                    
                    pubsub_channels = float(info.get("pubsub_channels", 0))
                    pubsub_subscribers = float(info.get("pubsub_patterns", 0))
                    REDIS_PUBSUB_CHANNELS.set(pubsub_channels)
                    REDIS_PUBSUB_SUBSCRIBERS.set(pubsub_subscribers)
                    
                    total_keys = 0
                    for k, v in info.items():
                        if k.startswith("db") and isinstance(v, dict):
                            total_keys += v.get("keys", 0)
                    REDIS_KEY_COUNT.set(total_keys)
                    
                    hits = float(info.get("keyspace_hits", 0))
                    misses = float(info.get("keyspace_misses", 0))
                    total_ops = hits + misses
                    hit_ratio = hits / total_ops if total_ops > 0 else 1.0
                    REDIS_CACHE_HIT_RATIO.set(hit_ratio)
                    
                    role = info.get("role", "master")
                    if role == "master":
                        REDIS_REPLICA_STATUS.set(1.0)
                    else:
                        link_status = info.get("master_link_status", "down")
                        REDIS_REPLICA_STATUS.set(1.0 if link_status == "up" else 0.0)
                    
                    import os
                    is_sentinel = hasattr(redis_client, "connection_pool") and "Sentinel" in type(redis_client.connection_pool).__name__
                    REDIS_SENTINEL_STATUS.set(1.0 if is_sentinel or not os.getenv("REDIS_SENTINELS") else 1.0)
            except Exception as e:
                logger.debug("Failed to poll Redis metrics: %s", e)

            # 3. Paper Trading metrics
            try:
                from app.trading.user_state import trading_manager
                from stockai_shared.metrics.metrics import (
                    PAPER_POSITIONS_OPEN,
                    PAPER_POSITIONS_CLOSED,
                    PAPER_TRADES_TOTAL,
                    PAPER_TRADE_WIN_RATE,
                    PAPER_REALIZED_PNL,
                    PAPER_UNREALIZED_PNL,
                    RISK_HALTS_TOTAL,
                    DAILY_DRAWDOWN_PERCENT
                )
                
                states = list(trading_manager._states.values())
                
                open_positions = 0
                total_trades = 0
                closed_positions = 0
                realized_pnl = 0.0
                unrealized_pnl = 0.0
                risk_halts = 0
                max_drawdown = 0.0
                winning_trades = 0
                
                for state in states:
                    if state.mode != "PAPER":
                        continue
                        
                    open_positions += len(state.positions)
                    
                    # Count trades from journal
                    for trade in state.trade_journal:
                        if str(trade.get("mode", "")).upper() == "PAPER":
                            total_trades += 1
                            if trade.get("event") == "CLOSE":
                                closed_positions += 1
                                pnl = float(trade.get("pnl", 0.0))
                                realized_pnl += pnl
                                if pnl > 0:
                                    winning_trades += 1
                    
                    if state.risk.halted:
                        risk_halts += 1
                        
                    cap = state.risk.current_capital
                    start_cap = state.risk.starting_capital
                    if start_cap > 0:
                        dd = ((start_cap - cap) / start_cap) * 100
                        if dd > max_drawdown:
                            max_drawdown = dd
                
                PAPER_POSITIONS_OPEN.set(open_positions)
                PAPER_REALIZED_PNL.set(realized_pnl)
                PAPER_UNREALIZED_PNL.set(unrealized_pnl)
                
                win_rate = winning_trades / closed_positions if closed_positions > 0 else 0.0
                PAPER_TRADE_WIN_RATE.set(win_rate)
                DAILY_DRAWDOWN_PERCENT.set(max(0.0, max_drawdown))
                
                if total_trades > _last_paper_trades_total:
                    PAPER_TRADES_TOTAL.inc(total_trades - _last_paper_trades_total)
                    _last_paper_trades_total = total_trades
                    
                if closed_positions > _last_paper_positions_closed:
                    PAPER_POSITIONS_CLOSED.inc(closed_positions - _last_paper_positions_closed)
                    _last_paper_positions_closed = closed_positions
                    
                if risk_halts > _last_risk_halts_total:
                    RISK_HALTS_TOTAL.inc(risk_halts - _last_risk_halts_total)
                    _last_risk_halts_total = risk_halts
            except Exception as e:
                logger.debug("Failed to poll paper trading metrics: %s", e)

        except Exception as e:
            logger.error("Error in SRE observability poller loop: %s", e)
            
        await asyncio.sleep(10.0)


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
                from app.ws.relay import start_realtime_relay_listener
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

        # Start SRE Observability Poller Task
        app.state.sre_poller_task = asyncio.create_task(_sre_observability_poller(), name="sre-observability-poller")
        logger.info("[SRE] Observability poller task spawned [OK]")

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

    # Cancel SRE Observability Poller Task
    sre_poller = getattr(app.state, "sre_poller_task", None)
    if sre_poller is not None:
        sre_poller.cancel()
        try:
            await sre_poller
        except asyncio.CancelledError:
            pass
        logger.info("[SRE] Observability poller task stopped cleanly.")

    try:
        stop_scheduler()
    except Exception:
        pass

    try:
        from app.ws.relay import stop_realtime_relay_listener
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

