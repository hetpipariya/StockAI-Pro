from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
from zoneinfo import ZoneInfo

import pandas as pd

from .nifty_cache import canonical_path, ensure_nifty_dirs, validation_report_path, write_metadata, write_validation_report
from .nifty_data_loader import NiftyDataLoader, DEFAULT_HISTORICAL_DAYS
from .nifty_validator import validate_nifty_history

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _round_to_granularity_start(date: datetime, granularity: str) -> datetime:
    if date.tzinfo is None:
        date = date.replace(tzinfo=IST)
    else:
        date = date.astimezone(IST)
    if granularity == "daily":
        return datetime(date.year, date.month, date.day, tzinfo=IST)
    if granularity == "1h":
        return datetime(date.year, date.month, date.day, date.hour, tzinfo=IST)
    if granularity == "5m":
        minute = (date.minute // 5) * 5
        return datetime(date.year, date.month, date.day, date.hour, minute, tzinfo=IST)
    return date


def _round_to_granularity_end(date: datetime, granularity: str) -> datetime:
    return date


class NiftyUpdater:
    def __init__(
        self,
        symbol: str = "NIFTY 50",
        exchange: str = "NSE",
        symbol_token: str | None = None,
    ) -> None:
        self.loader = NiftyDataLoader(
            symbol=symbol,
            exchange=exchange,
            symbol_token=symbol_token,
        )
        ensure_nifty_dirs()

    def update(
        self,
        granularity: str = "daily",
        backfill_days: int | None = None,
        force: bool = False,
        strict: bool = True,
        max_allowed_gap_days: int = 4,
    ) -> pd.DataFrame:
        if granularity not in {"daily", "1h", "5m"}:
            raise ValueError(f"Unsupported granularity: {granularity}")

        target_path = canonical_path(granularity)
        existing = self.loader.load_existing_canonical(granularity)
        now = datetime.now(tz=timezone.utc).astimezone(IST)

        if existing.empty or force:
            if backfill_days is not None:
                start = now - timedelta(days=backfill_days)
            else:
                start = now - timedelta(days=DEFAULT_HISTORICAL_DAYS[granularity])
        else:
            last_ts = existing["timestamp"].max()
            start = last_ts + timedelta(minutes=1)

        start = _round_to_granularity_start(start, granularity)
        end = _round_to_granularity_end(now, granularity)
        if start >= end:
            logger.info("[NIFTY] Canonical %s dataset already up to date", granularity)
            cleaned, report = validate_nifty_history(
                existing,
                strict=strict,
                max_allowed_gap_days=max_allowed_gap_days,
            )
            write_validation_report(granularity, report.__dict__)
            return cleaned

        logger.info("[NIFTY] Updating %s from %s to %s", granularity, start, end)
        try:
            new_data = self.loader.fetch_range(granularity, start, end)
        except Exception as exc:
            if not existing.empty:
                logger.warning(
                    "[NIFTY] Live fetch failed for %s; continuing with existing canonical data only: %s",
                    granularity,
                    exc,
                )
                new_data = pd.DataFrame()
            else:
                raise

        if new_data.empty and existing.empty:
            raise RuntimeError("No NIFTY data could be fetched for update")

        combined = pd.concat([existing, new_data], ignore_index=True) if not existing.empty else new_data
        combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

        cleaned, report = validate_nifty_history(
            combined,
            strict=strict,
            max_allowed_gap_days=max_allowed_gap_days,
        )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned.to_csv(target_path, index=False)

        write_validation_report(granularity, report.__dict__)
        write_metadata(
            granularity,
            {
                "granularity": granularity,
                "source_symbol": self.loader.symbol,
                "row_count": len(cleaned),
                "first_timestamp": cleaned["timestamp"].iloc[0].isoformat() if not cleaned.empty else None,
                "last_timestamp": cleaned["timestamp"].iloc[-1].isoformat() if not cleaned.empty else None,
                "strict": strict,
                "max_allowed_gap_days": max_allowed_gap_days,
            },
        )

        logger.info(
            "[NIFTY] Updated %s canonical dataset with %d rows", granularity, len(cleaned)
        )
        return cleaned
