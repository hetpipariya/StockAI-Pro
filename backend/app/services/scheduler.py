from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import config
from app.services.instrument_master import load_instruments
from app.websocket.handler import auto_start_ws, get_or_create_ws_connector

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    """Register and start all recurring jobs exactly once."""
    if scheduler.running:
        return

    scheduler.add_job(regen_token, "cron", hour=8, minute=30)
    scheduler.add_job(refresh_instruments, "cron", hour=8, minute=0)
    scheduler.add_job(prewarm_predictions, "cron", minute="*/15")
    if config.ENABLE_WS:
        scheduler.add_job(auto_start_ws, "cron", minute="*/1")
    else:
        logger.info("[SCHEDULER] ENABLE_WS=false; skipping websocket jobs")
    scheduler.add_job(
        sync_broker_positions, "cron", minute="*/5", hour="9-15", day_of_week="mon-fri"
    )
    scheduler.start()
    logger.info("[SCHEDULER] Started recurring jobs")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")


async def regen_token():
    """Re-login SmartAPI every morning at 08:30 IST."""
    logger.info("[SCHEDULER] Regenerating SmartAPI token")
    connector = get_or_create_ws_connector()
    try:
        connector.login(force=True)
    except Exception as e:
        logger.error("[SCHEDULER] Token regen failed: %s", e)


async def refresh_instruments():
    """Reload instrument master daily at 08:00 IST."""
    logger.info("[SCHEDULER] Refreshing instrument master")
    load_instruments(force=True)


async def prewarm_predictions():
    """Pre-compute predictions every 15 minutes."""
    from app.routes.predict import get_predict

    logger.info("[SCHEDULER] Pre-warming predictions")
    for symbol in ["RELIANCE", "TCS", "INFY", "HDFCBANK"]:
        try:
            await get_predict(symbol=symbol, horizon="15m")
        except Exception as e:
            logger.warning("[SCHEDULER] Pre-warm failed for %s: %s", symbol, e)


async def sync_broker_positions():
    """Periodically sync DB positions with broker (LIVE mode only)."""
    from app import config as _cfg

    if _cfg.TRADING_MODE != "LIVE":
        return

    try:
        from app.trading.live_executor import get_executor
        from app.trading.user_state import trading_manager

        summaries = trading_manager.get_all_summaries()
        for summary in summaries:
            try:
                raw_user_id = summary.get("user_id")
                if raw_user_id is None:
                    logger.warning("[SYNC] Skipping summary without user_id: %s", summary)
                    continue

                user_id = int(raw_user_id)
                executor = await asyncio.to_thread(
                    get_executor,
                    user_id=user_id,
                    mode=summary.get("mode", _cfg.TRADING_MODE),
                    capital=float(summary.get("starting_capital", _cfg.STARTING_CAPITAL)),
                )
                report = await asyncio.to_thread(
                    executor.router.sync_positions_with_broker,
                    user_id=user_id,
                )

                if report.get("mismatches"):
                    logger.warning(
                        "[SYNC] user_id=%d mismatches: %s", user_id, report["mismatches"]
                    )
            except Exception as user_exc:
                logger.warning("[SYNC] Per-user sync skipped due to error: %s", user_exc)
    except Exception as e:
        logger.error("[SYNC] Broker sync job failed: %s", e)
