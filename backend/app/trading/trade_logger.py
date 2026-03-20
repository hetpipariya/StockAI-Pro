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
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Ensure log directory exists
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_TRADE_LOG_FILE = _LOG_DIR / "trades.jsonl"


def _write_jsonl(entry: dict):
    """Append a single JSON line to the trades log file."""
    try:
        with open(_TRADE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        logger.error(f"[TRADE-LOG] Failed to write JSONL: {e}")


def _write_db(entry: dict):
    """Insert a trade log row into the database (sync session)."""
    try:
        from app.services.db import get_sync_db_session, TradeLogModel

        db_gen = get_sync_db_session()
        session = next(db_gen)
        if session is None:
            return
        try:
            row = TradeLogModel(
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
                extra=json.dumps({
                    k: v for k, v in entry.items()
                    if k not in {
                        "order_id", "event", "symbol", "direction", "quantity",
                        "price", "stop_loss", "target", "confidence", "reason",
                        "mode", "status", "pnl", "error", "timestamp",
                    }
                }, default=str) if entry else None,
            )
            session.add(row)
            session.commit()
        finally:
            session.close()
    except Exception as e:
        logger.error(f"[TRADE-LOG] Failed to write DB: {e}")


def log_trade(
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
):
    """
    Log a trade event to both file and database.

    Events: SIGNAL, PLACED, CONFIRMED, FILLED, PARTIAL, FAILED, REJECTED, EXIT
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event": event,
        "order_id": order_id,
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

    # Add optional signal metadata
    if atr is not None:
        entry["atr"] = atr
    if rsi is not None:
        entry["rsi"] = rsi
    if ml_prediction is not None:
        entry["ml_prediction"] = ml_prediction

    # Write to both sinks
    _write_jsonl(entry)
    _write_db(entry)

    logger.info(
        f"[TRADE-LOG] {event} | {direction} {symbol} x{quantity} @ ₹{price:.2f} "
        f"| mode={mode} status={status} | {reason or ''}"
    )
