from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import config
from app.services.instrument_service import refresh_instruments_daily
from app.websocket.handler import auto_start_ws, get_or_create_ws_connector
from app.services.redis_client import distributed_job_lock

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    job_defaults={
        "coalesce": True,
        "max_instances": max(1, config.SCHEDULER_JOB_MAX_INSTANCES),
        "misfire_grace_time": 45,
    }
)


async def _run_job_with_retry(
    job_name: str,
    runner: Callable[[], Awaitable[None]],
    retries: int = 3,
) -> None:
    timeout_seconds = max(10.0, float(config.SCHEDULER_JOB_TIMEOUT_SECONDS))
    for attempt in range(1, retries + 1):
        try:
            await asyncio.wait_for(runner(), timeout=timeout_seconds)
            if attempt > 1:
                logger.info("[SCHEDULER] %s recovered on attempt %d", job_name, attempt)
            return
        except asyncio.TimeoutError:
            if attempt < retries:
                logger.info(
                    "[SCHEDULER] %s timed out on attempt %d/%d (%.1fs)",
                    job_name,
                    attempt,
                    retries,
                    timeout_seconds,
                )
            else:
                logger.error(
                    "[SCHEDULER] %s timed out on final attempt %d/%d (%.1fs)",
                    job_name,
                    attempt,
                    retries,
                    timeout_seconds,
                )
        except Exception as exc:
            if attempt < retries:
                logger.info(
                    "[SCHEDULER] %s failed on attempt %d/%d: %s",
                    job_name,
                    attempt,
                    retries,
                    exc,
                )
            else:
                logger.error(
                    "[SCHEDULER] %s failed on final attempt %d/%d: %s",
                    job_name,
                    attempt,
                    retries,
                    exc,
                )

        if attempt < retries:
            await asyncio.sleep(min(2 ** (attempt - 1), 10))


def start_scheduler() -> None:
    """Register and start all recurring jobs exactly once."""
    if scheduler.running:
        return

    scheduler.add_job(
        regen_token,
        "cron",
        id="regen_token",
        hour=8,
        minute=30,
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_instruments,
        "cron",
        id="refresh_instruments",
        hour=max(0, min(23, int(config.INSTRUMENT_REFRESH_HOUR))),
        minute=max(0, min(59, int(config.INSTRUMENT_REFRESH_MINUTE))),
        replace_existing=True,
    )
    scheduler.add_job(
        prewarm_predictions,
        "cron",
        id="prewarm_predictions",
        minute="*/15",
        replace_existing=True,
    )
    if config.ENABLE_WS:
        scheduler.add_job(
            auto_start_ws_job,
            "cron",
            id="auto_start_ws",
            minute="*/1",
            replace_existing=True,
        )
    else:
        logger.info("[SCHEDULER] ENABLE_WS=false; skipping websocket jobs")
    scheduler.add_job(
        sync_broker_positions,
        "cron",
        id="sync_broker_positions",
        minute="*/5",
        hour="9-15",
        day_of_week="mon-fri",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[SCHEDULER] Started recurring jobs")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")


async def auto_start_ws_job():
    """Wrapper to run auto_start_ws with a distributed lock."""
    from app.websocket.handler import get_ws_state
    state = get_ws_state()
    if state == "CONNECTED":
        logger.info("[SCHEDULER_SKIP] [WS_SKIP_ALREADY_CONNECTED] auto_start_ws_job skipped because WebSocket is CONNECTED")
        return
    if state == "RECONNECTING":
        logger.info("[SCHEDULER_SKIP] [WS_SKIP_RECONNECTING] auto_start_ws_job skipped because WebSocket is RECONNECTING")
        return

    async with distributed_job_lock("auto_start_ws", lock_ttl_seconds=50) as acquired:
        if not acquired:
            logger.info("[SCHEDULER] auto_start_ws skipped: lock already acquired by another instance")
            return
        await auto_start_ws()


async def regen_token():
    """Re-login SmartAPI every morning at 08:30 IST."""
    async with distributed_job_lock("regen_token", lock_ttl_seconds=50) as acquired:
        if not acquired:
            logger.info("[SCHEDULER] regen_token skipped: lock already acquired by another instance")
            return
        logger.info("[SCHEDULER] Regenerating SmartAPI token")
        connector = get_or_create_ws_connector()
        await _run_job_with_retry(
            "regen_token",
            lambda: asyncio.to_thread(connector.login, force=True),
            retries=3,
        )


async def refresh_instruments():
    """Refresh instrument cache daily from OpenAPI with persistence fallback."""
    async with distributed_job_lock("refresh_instruments", lock_ttl_seconds=50) as acquired:
        if not acquired:
            logger.info("[SCHEDULER] refresh_instruments skipped: lock already acquired by another instance")
            return
        logger.info("[SCHEDULER] Refreshing instrument master")

        async def _refresh_runner() -> None:
            count = await refresh_instruments_daily(force=True)
            logger.info("[SCHEDULER] Instrument refresh complete: %d symbols", count)

        await _run_job_with_retry(
            "refresh_instruments",
            _refresh_runner,
            retries=3,
        )


async def prewarm_predictions():
    """Pre-compute predictions every 15 minutes."""
    async with distributed_job_lock("prewarm_predictions", lock_ttl_seconds=50) as acquired:
        if not acquired:
            logger.info("[SCHEDULER] prewarm_predictions skipped: lock already acquired by another instance")
            return
        from app.services.bundle_service import (DEFAULT_PREWARM_SYMBOLS,
                                                 get_prediction,
                                                 prewarm_bundle_cache)

        logger.info("[SCHEDULER] Pre-warming predictions")
        concurrency = max(1, min(config.BUNDLE_PREWARM_CONCURRENCY, 6))
        sem = asyncio.Semaphore(concurrency)

        async def _prewarm_prediction_symbol(symbol: str) -> None:
            async with sem:
                await _run_job_with_retry(
                    f"prediction_prewarm:{symbol}",
                    lambda: get_prediction(symbol=symbol, horizon="15m"),
                    retries=2,
                )

        symbol_tasks = [
            asyncio.create_task(_prewarm_prediction_symbol(symbol))
            for symbol in ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
        ]
        await asyncio.gather(*symbol_tasks, return_exceptions=True)

        await _run_job_with_retry(
            "bundle_prewarm",
            lambda: prewarm_bundle_cache(list(DEFAULT_PREWARM_SYMBOLS)),
            retries=2,
        )


async def sync_broker_positions():
    """Periodically sync DB positions with broker (LIVE mode only)."""
    async with distributed_job_lock("sync_broker_positions", lock_ttl_seconds=50) as acquired:
        if not acquired:
            logger.info("[SCHEDULER] sync_broker_positions skipped: lock already acquired by another instance")
            return
        from app import config as _cfg

        if _cfg.TRADING_MODE != "LIVE":
            return

        try:
            from app.trading.live_executor import get_executor
            from app.trading.user_state import trading_manager

            summaries = await trading_manager.get_all_summaries()
            concurrency = max(1, min(config.BUNDLE_PREWARM_CONCURRENCY, 4))
            sem = asyncio.Semaphore(concurrency)

            async def _sync_user(summary: dict) -> None:
                async with sem:
                    try:
                        raw_user_id = summary.get("user_id")
                        if raw_user_id is None:
                            logger.warning("[SYNC] Skipping summary without user_id: %s", summary)
                            return

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
                                "[SYNC] user_id=%d mismatches: %s",
                                user_id,
                                report["mismatches"],
                            )
                    except Exception as user_exc:
                        logger.warning("[SYNC] Per-user sync skipped due to error: %s", user_exc)

            await _run_job_with_retry(
                "sync_broker_positions",
                lambda: asyncio.gather(
                    *[asyncio.create_task(_sync_user(summary)) for summary in summaries],
                    return_exceptions=True,
                ),
                retries=2,
            )
        except Exception as e:
            logger.error("[SYNC] Broker sync job failed: %s", e)
