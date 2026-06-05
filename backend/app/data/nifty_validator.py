from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationReport:
    row_count: int
    duplicate_count: int
    invalid_row_count: int
    gap_count: int
    first_timestamp: pd.Timestamp | None
    last_timestamp: pd.Timestamp | None
    strict: bool


def _normalize_timestamp_series(series: pd.Series, target_timezone: str = "Asia/Kolkata") -> pd.Series:
    series = pd.to_datetime(series, errors="coerce")
    if series.dt.tz is None:
        return series.dt.tz_localize(ZoneInfo(target_timezone))
    return series.dt.tz_convert(ZoneInfo(target_timezone))


def _normalize_ohlcv_frame(data: Any, require_timestamp: bool = False, target_timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    if data is None:
        return pd.DataFrame()

    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, dict):
        frame = pd.DataFrame(data)
    else:
        frame = pd.DataFrame(list(data))

    if frame.empty:
        return frame

    frame.columns = [str(column).strip().lower() for column in frame.columns]
    aliases = {"datetime": "timestamp", "date": "timestamp", "time": "timestamp", "ticker": "symbol"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})

    required = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        if require_timestamp:
            raise ValueError(f"OHLCV frame missing required columns: {missing}")
        return pd.DataFrame()

    if "timestamp" in frame.columns:
        frame["timestamp"] = _normalize_timestamp_series(frame["timestamp"], target_timezone)
    elif require_timestamp:
        raise ValueError("OHLCV frame requires a timestamp column for training/offline computation.")

    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(subset=required + (["timestamp"] if "timestamp" in frame.columns else []))

    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")

    if "high" in frame.columns and "low" in frame.columns:
        valid_mask = (
            (frame["open"] > 0)
            & (frame["high"] > 0)
            & (frame["low"] > 0)
            & (frame["close"] > 0)
            & (frame["volume"] >= 0)
            & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
            & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
        )
        if not valid_mask.all():
            invalid = int((~valid_mask).sum())
            frame = frame.loc[valid_mask].copy()
            logger.debug("Dropped %d invalid OHLCV rows", invalid)

    if "timestamp" in frame.columns:
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    else:
        frame = frame.reset_index(drop=True)

    return frame


def detect_gaps(
    frame: pd.DataFrame,
    max_allowed_gap_days: int = 4,
    expected_frequency: str = "1D",
) -> int:
    if frame.empty or "timestamp" not in frame.columns:
        return 0

    ordered = frame.sort_values("timestamp").copy()
    diffs = ordered["timestamp"].diff().dt.total_seconds().fillna(0.0)
    if expected_frequency == "1D":
        threshold_seconds = max_allowed_gap_days * 24 * 60 * 60
    elif expected_frequency == "1H":
        threshold_seconds = max_allowed_gap_days * 60 * 60
    elif expected_frequency in {"5min", "5T"}:
        threshold_seconds = max_allowed_gap_days * 5 * 60
    else:
        threshold_seconds = max_allowed_gap_days * 24 * 60 * 60

    gap_count = int((diffs > threshold_seconds).sum())
    return gap_count


def validate_ohlcv_frame(
    data: Any,
    target_timezone: str = "Asia/Kolkata",
    strict: bool = True,
    max_allowed_gap_days: int = 4,
) -> tuple[pd.DataFrame, ValidationReport]:
    frame = _normalize_ohlcv_frame(
        data, require_timestamp=True, target_timezone=target_timezone
    )
    if frame.empty:
        raise ValueError("OHLCV frame could not be normalized")

    row_count = len(frame)
    duplicate_count = int(frame["timestamp"].duplicated().sum())
    if duplicate_count > 0:
        frame = frame.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    invalid_rows = 0
    if "high" in frame.columns and "low" in frame.columns:
        valid_mask = (
            (frame["open"] > 0)
            & (frame["high"] > 0)
            & (frame["low"] > 0)
            & (frame["close"] > 0)
            & (frame["volume"] >= 0)
            & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
            & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
        )
        invalid_rows = int((~valid_mask).sum())
        if invalid_rows > 0:
            if strict:
                raise ValueError(f"Invalid OHLCV rows detected: {invalid_rows}")
            frame = frame.loc[valid_mask].reset_index(drop=True)

    gap_count = detect_gaps(frame, max_allowed_gap_days=max_allowed_gap_days)
    if strict and gap_count > 0:
        raise ValueError(
            f"Suspicious gap count found: {gap_count} gaps > {max_allowed_gap_days} days"
        )

    report = ValidationReport(
        row_count=row_count,
        duplicate_count=duplicate_count,
        invalid_row_count=invalid_rows,
        gap_count=gap_count,
        first_timestamp=frame["timestamp"].iloc[0] if not frame.empty else None,
        last_timestamp=frame["timestamp"].iloc[-1] if not frame.empty else None,
        strict=strict,
    )
    return frame, report


def validate_nifty_history(
    frame: pd.DataFrame,
    target_timezone: str = "Asia/Kolkata",
    strict: bool = True,
    max_allowed_gap_days: int = 4,
) -> tuple[pd.DataFrame, ValidationReport]:
    if frame.empty:
        raise ValueError("NIFTY history frame is empty")

    return validate_ohlcv_frame(
        frame,
        target_timezone=target_timezone,
        strict=strict,
        max_allowed_gap_days=max_allowed_gap_days,
    )
