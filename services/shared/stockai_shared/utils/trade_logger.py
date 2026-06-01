"""
Trade Logger — structured JSON audit trail for every trade action.

Writes to:
  1. File: logs/trades.jsonl (append-only, one JSON object per line)
  2. DB:   trade_logs table via TradeLogModel

Every action (signal, place, confirm, fill, fail, exit) is logged with
full context so trades can be reconstructed after the fact.
"""

from __future__ import annotations

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Ensure log directory exists
_LOG_DIR = Path(__file__).resolve().parents[4] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_TRADE_LOG_FILE = _LOG_DIR / "trades.jsonl"


async def _write_jsonl_async(entry: dict):
    """Append a single JSON line asynchronously to the trades log file."""
    try:
        import aiofiles
        async with aiofiles.open(_TRADE_LOG_FILE, "a", encoding="utf-8") as f:
            await f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        logger.error(f"[TRADE-LOG] Failed to write JSONL asynchronously: {e}")


async def _write_db_async(entry: dict):
    """Insert a trade log row into the database asynchronously."""
    try:
        from stockai_shared.db.db import TradeLogModel, AsyncSessionLocal

        user_id = entry.get("user_id")
        if user_id is None:
            logger.debug("[TRADE-LOG] Skipping DB write: missing user_id")
            return

        async with AsyncSessionLocal() as session:
            row = TradeLogModel(
                user_id=user_id,
                order_id=entry.get("order_id", ""),
                event=entry.get("event", ""),
                symbol=entry.get("symbol", ""),
                direction=entry.get("direction", ""),
                quantity=entry.get("quantity", 0),
                price=entry.get("price", 0.0),
                stop_loss=entry.get("stop_loss"),
                target=entry.get("target"),
                confidence=entry.get("confidence", 0),
                reason=entry.get("reason"),
                mode=entry.get("mode", ""),
                status=entry.get("status"),
                pnl=entry.get("pnl"),
                error=entry.get("error"),
                extra=(
                    json.dumps(
                        {
                            k: v
                            for k, v in entry.items()
                            if k
                            not in {
                                "order_id",
                                "event",
                                "symbol",
                                "direction",
                                "quantity",
                                "price",
                                "stop_loss",
                                "target",
                                "confidence",
                                "reason",
                                "mode",
                                "status",
                                "pnl",
                                "error",
                                "timestamp",
                            }
                        },
                        default=str,
                    )
                    if entry
                    else None
                ),
            )
            session.add(row)
            await session.commit()
    except Exception as e:
        logger.error(f"[TRADE-LOG] Failed to write DB asynchronously: {e}")


def _write_sync_fallback_worker(entry: dict):
    """Fallback worker to execute database and file operations in a background thread."""
    try:
        # Write to JSONL
        try:
            with open(_TRADE_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error(f"[TRADE-LOG] Sync fallback JSONL write failed: {e}")

        # Write to DB
        from stockai_shared.db.db import TradeLogModel, get_sync_db_session
        user_id = entry.get("user_id")
        if user_id is None:
            return

        db_gen = get_sync_db_session()
        session = next(db_gen)
        if session is not None:
            try:
                row = TradeLogModel(
                    user_id=user_id,
                    order_id=entry.get("order_id", ""),
                    event=entry.get("event", ""),
                    symbol=entry.get("symbol", ""),
                    direction=entry.get("direction", ""),
                    quantity=entry.get("quantity", 0),
                    price=entry.get("price", 0.0),
                    stop_loss=entry.get("stop_loss"),
                    target=entry.get("target"),
                    confidence=entry.get("confidence", 0),
                    reason=entry.get("reason"),
                    mode=entry.get("mode", ""),
                    status=entry.get("status"),
                    pnl=entry.get("pnl"),
                    error=entry.get("error"),
                    extra=(
                        json.dumps(
                            {
                                k: v
                                for k, v in entry.items()
                                if k
                                not in {
                                    "order_id",
                                    "event",
                                    "symbol",
                                    "direction",
                                    "quantity",
                                    "price",
                                    "stop_loss",
                                    "target",
                                    "confidence",
                                    "reason",
                                    "mode",
                                    "status",
                                    "pnl",
                                    "error",
                                    "timestamp",
                                }
                            },
                            default=str,
                        )
                        if entry
                        else None
                    ),
                )
                session.add(row)
                session.commit()
            finally:
                session.close()
    except Exception as exc:
        logger.error(f"[TRADE-LOG] Sync fallback DB write failed: {exc}")


class AwaitableLogTask:
    """Awaitable wrapper for background logging tasks to support dual sync/async calls."""

    def __init__(self, entry: dict):
        self.entry = entry
        self._task: Optional[asyncio.Task] = None
        
        try:
            loop = asyncio.get_running_loop()
            # If in async loop, schedule async operations in background immediately
            self._task = loop.create_task(self._run_async())
        except RuntimeError:
            # If not in async loop, run on a daemon fallback thread
            import threading
            threading.Thread(target=_write_sync_fallback_worker, args=(self.entry,), daemon=True).start()

    async def _run_async(self):
        await _write_jsonl_async(self.entry)
        await _write_db_async(self.entry)

    def __await__(self):
        if self._task is not None:
            return self._task.__await__()
        # If no active task (sync thread fallback), return a completed future
        async def dummy():
            return None
        return dummy().__await__()


class SmartLogTrade:
    """Smart logger that implements both async awaitable and sync callable styles."""

    def __call__(
        self,
        event: str,
        order_id: str,
        symbol: str,
        direction: str,
        *,
        quantity: int = 0,
        price: float = 0.0,
        stop_loss: Optional[float] = None,
        target: Optional[float] = None,
        confidence: int = 0,
        reason: Optional[str] = None,
        mode: str = "",
        status: Optional[str] = None,
        pnl: Optional[float] = None,
        error: Optional[str] = None,
        atr: Optional[float] = None,
        rsi: Optional[float] = None,
        ml_prediction: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> AwaitableLogTask:
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": event,
            "order_id": order_id,
            "user_id": user_id,
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "stop_loss": stop_loss,
            "target": target,
            "confidence": confidence,
            "reason": reason,
            "mode": mode,
            "status": status,
            "pnl": pnl,
            "error": error,
        }

        if atr is not None:
            entry["atr"] = atr
        if rsi is not None:
            entry["rsi"] = rsi
        if ml_prediction is not None:
            entry["ml_prediction"] = ml_prediction

        task = AwaitableLogTask(entry)

        logger.info(
            f"[TRADE-LOG] {event} | {direction} {symbol} x{quantity} @ ₹{price:.2f} "
            f"| mode={mode} status={status} | {reason or ''}"
        )
        return task


log_trade = SmartLogTrade()

