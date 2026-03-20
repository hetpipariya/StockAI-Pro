"""
Candle Store — persists OHLCV candles to SQLite and provides DB-first reads.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select, and_

from app.services.db import async_session, CandleModel

logger = logging.getLogger(__name__)


def _parse_time(t) -> Optional[datetime]:
    """Parse various timestamp formats to datetime."""
    if isinstance(t, datetime):
        return t
    if isinstance(t, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(t.split("+")[0].strip(), fmt.replace("%z", ""))
            except ValueError:
                continue
    return None


async def store_candles(symbol: str, timeframe: str, candles: list[dict]) -> int:
    """
    Bulk upsert candles into DB. Returns count of stored rows.
    candles: [{"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]
    """
    if not async_session or not candles:
        return 0

    stored = 0
    try:
        async with async_session() as session:
            for c in candles:
                ts = _parse_time(c.get("time"))
                if not ts:
                    continue

                # Check if exists (upsert)
                existing = await session.execute(
                    select(CandleModel).where(
                        and_(
                            CandleModel.symbol == symbol,
                            CandleModel.timeframe == timeframe,
                            CandleModel.timestamp == ts,
                        )
                    )
                )
                row = existing.scalar_one_or_none()

                if row:
                    # Update existing
                    row.open = float(c["open"])
                    row.high = float(c["high"])
                    row.low = float(c["low"])
                    row.close = float(c["close"])
                    row.volume = int(c.get("volume", 0))
                else:
                    # Insert new
                    session.add(CandleModel(
                        symbol=symbol,
                        timeframe=timeframe,
                        open=float(c["open"]),
                        high=float(c["high"]),
                        low=float(c["low"]),
                        close=float(c["close"]),
                        volume=int(c.get("volume", 0)),
                        timestamp=ts,
                    ))
                stored += 1

            await session.commit()
        logger.info(f"[DB] Stored {stored} candles for {symbol}/{timeframe}")
    except Exception as e:
        logger.error(f"[DB] store_candles error: {e}")
    return stored


async def get_candles(
    symbol: str,
    timeframe: str,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    limit: int = 500,
) -> list[dict]:
    """
    Read candles from DB. Returns list of dicts with time/open/high/low/close/volume.
    """
    if not async_session:
        return []

    try:
        async with async_session() as session:
            query = select(CandleModel).where(
                and_(
                    CandleModel.symbol == symbol,
                    CandleModel.timeframe == timeframe,
                )
            )
            if from_dt:
                query = query.where(CandleModel.timestamp >= from_dt)
            if to_dt:
                query = query.where(CandleModel.timestamp <= to_dt)

            query = query.order_by(CandleModel.timestamp.desc()).limit(limit)
            result = await session.execute(query)
            rows = result.scalars().all()

            # Return in ascending order
            candles = [
                {
                    "time": r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in reversed(rows)
            ]
            return candles
    except Exception as e:
        logger.error(f"[DB] get_candles error: {e}")
        return []


async def get_latest_candle(symbol: str, timeframe: str) -> Optional[dict]:
    """Get the most recent candle for gap detection."""
    candles = await get_candles(symbol, timeframe, limit=1)
    return candles[0] if candles else None


# Alias for convenience
get_last_candle = get_latest_candle


async def get_candle_count(symbol: str, timeframe: str) -> int:
    """Return count of stored candles."""
    if not async_session:
        return 0
    try:
        from sqlalchemy import func
        async with async_session() as session:
            result = await session.execute(
                select(func.count()).where(
                    and_(
                        CandleModel.symbol == symbol,
                        CandleModel.timeframe == timeframe,
                    )
                )
            )
            return result.scalar() or 0
    except Exception as e:
        logger.error(f"[DB] get_candle_count error: {e}")
        return 0
