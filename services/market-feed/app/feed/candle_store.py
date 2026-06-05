"""
Candle Store — persists OHLCV candles to the database.
Uses bulk upsert (INSERT ... ON CONFLICT DO UPDATE) for PostgreSQL,
falls back to row-by-row for SQLite dev environments.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from stockai_shared.config.config import DATABASE_URL
from stockai_shared.db.db import CandleModel, async_session, AsyncReplicaSessionLocal

logger = logging.getLogger(__name__)

_is_postgres = "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL
_MAX_DB_VOLUME = 2_147_483_647


def _parse_time(t) -> Optional[datetime]:
    """Parse various timestamp formats to datetime."""
    if isinstance(t, datetime):
        return t
    if isinstance(t, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
        ):
            try:
                return datetime.strptime(t.split("+")[0].strip(), fmt.replace("%z", ""))
            except ValueError:
                continue
    return None


async def store_candles(symbol: str, timeframe: str, candles: list[dict]) -> int:
    """
    Bulk upsert candles into DB. Returns count of stored rows.
    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE when available;
    falls back to row-by-row upsert on SQLite.
    """
    if not async_session or not candles:
        return 0

    # Parse and validate all candle data first
    rows = []
    clamped_volume_count = 0
    for c in candles:
        ts = _parse_time(c.get("time"))
        if not ts:
            continue

        raw_volume = int(c.get("volume", 0) or 0)
        if raw_volume < 0:
            raw_volume = 0
        volume = min(raw_volume, _MAX_DB_VOLUME)
        if volume != raw_volume:
            clamped_volume_count += 1

        rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": volume,
                "timestamp": ts,
            }
        )

    if not rows:
        return 0

    if clamped_volume_count:
        logger.warning(
            "[DB] Clamped %d candle volume value(s) to int32 max for %s/%s",
            clamped_volume_count,
            symbol,
            timeframe,
        )

    try:
        async with async_session() as session:
            if _is_postgres:
                stored = await bulk_upsert_candles(rows, session)
            else:
                stored = await _upsert_sqlite(session, rows)
                await session.commit()

        logger.debug(f"[DB] Stored {stored} candles for {symbol}/{timeframe}")
        return stored
    except Exception as e:
        logger.error(f"[DB] store_candles error: {e}")
        return 0


async def bulk_upsert_candles(candles: list[dict], session: AsyncSession) -> int:
    """Single-query bulk upsert using PostgreSQL ON CONFLICT DO UPDATE."""
    if not candles:
        return 0

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(CandleModel).values(candles)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "timeframe", "timestamp"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(candles)


async def _upsert_sqlite(session, rows: list[dict]) -> int:
    """SQLite fallback — uses INSERT OR REPLACE (dev only)."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    stored = 0
    # Batch in chunks of 100 to avoid excessively large statements
    for i in range(0, len(rows), 100):
        chunk = rows[i: i + 100]
        stmt = sqlite_insert(CandleModel).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "timestamp"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        await session.execute(stmt)
        stored += len(chunk)
    return stored
