from __future__ import annotations

from datetime import time
import re
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

REQUIRED_COLUMNS: Sequence[str] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
    "timeframe",
)

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
IST_TIMEZONE = "Asia/Kolkata"

TIMEFRAME_TO_FREQ = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
}


def _infer_frequency(timeframe: str) -> str:
    token = str(timeframe).strip().lower()
    if token in TIMEFRAME_TO_FREQ:
        return TIMEFRAME_TO_FREQ[token]

    match = re.fullmatch(r"(\d+)([mh])", token)
    if not match:
        return "5min"

    value = max(1, int(match.group(1)))
    unit = match.group(2)
    if unit == "m":
        return f"{value}min"
    return f"{value}h"


def _normalize_timestamp_column(series: pd.Series) -> pd.Series:
    # Keep everything in IST wall-clock for market session filtering.
    parsed = pd.to_datetime(series, errors="coerce")
    if getattr(parsed.dt, "tz", None) is None:
        return parsed.dt.tz_localize(IST_TIMEZONE, ambiguous="NaT", nonexistent="shift_forward").dt.tz_localize(None)
    return parsed.dt.tz_convert(IST_TIMEZONE).dt.tz_localize(None)


def _session_reindex(group: pd.DataFrame) -> pd.DataFrame:
    if group.empty:
        return group

    timeframe = str(group["timeframe"].iloc[0]).lower()
    freq = _infer_frequency(timeframe)

    g = group.sort_values("timestamp").copy()
    symbol = str(g["symbol"].iloc[0])
    source = str(g["source_file"].dropna().iloc[0]) if "source_file" in g.columns and g["source_file"].notna().any() else ""

    g = g.set_index("timestamp")
    session_days = g.index.normalize().unique().sort_values()

    idx_parts: list[pd.DatetimeIndex] = []
    for day in session_days:
        start = pd.Timestamp.combine(day, MARKET_OPEN)
        end = pd.Timestamp.combine(day, MARKET_CLOSE)
        idx_parts.append(pd.date_range(start=start, end=end, freq=freq))

    if not idx_parts:
        return g.reset_index()

    full_index = idx_parts[0]
    for part in idx_parts[1:]:
        full_index = full_index.union(part)

    expanded = g.reindex(full_index)

    missing_rows = expanded[["open", "high", "low", "close", "volume"]].isna().all(axis=1)
    expanded["is_gap_filled"] = missing_rows.astype(int)

    # No look-ahead: synthetic bars only borrow state from prior observed close.
    prior_close = expanded["close"].ffill()
    expanded = expanded[prior_close.notna()].copy()
    prior_close = prior_close.loc[expanded.index]

    for col in ["open", "high", "low", "close"]:
        expanded[col] = pd.to_numeric(expanded[col], errors="coerce").fillna(prior_close)

    expanded["volume"] = pd.to_numeric(expanded["volume"], errors="coerce").fillna(0.0)
    expanded.loc[expanded["volume"] < 0, "volume"] = 0.0

    row_max = expanded[["open", "high", "low", "close"]].max(axis=1)
    row_min = expanded[["open", "high", "low", "close"]].min(axis=1)
    expanded["high"] = row_max
    expanded["low"] = row_min

    expanded["symbol"] = symbol
    expanded["timeframe"] = timeframe
    if "source_file" in group.columns:
        expanded["source_file"] = source

    expanded.index.name = "timestamp"
    out = expanded.reset_index()
    return out


def clean_ohlcv_frame(df: pd.DataFrame, fill_missing_gaps: bool = True) -> pd.DataFrame:
    """Clean OHLCV data in a model-safe way.

    - Enforces NSE/BSE session boundaries (09:15-15:30 IST, weekdays).
    - Removes raw zero-volume bars and duplicate bars.
    - Reindexes missing intraday gaps per symbol/timeframe and forward-fills from prior close only.
    - Enforces OHLC consistency (high >= low and encloses open/close).
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Input data missing required columns: {missing}")

    out = df.copy()
    out["timestamp"] = _normalize_timestamp_column(out["timestamp"])
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip().str.replace(".NS", "", regex=False)
    out["timeframe"] = out["timeframe"].astype(str).str.lower().str.strip()

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["timestamp", "symbol", "timeframe"])

    out = out[out["timestamp"].dt.dayofweek < 5]
    in_session = (out["timestamp"].dt.time >= MARKET_OPEN) & (out["timestamp"].dt.time <= MARKET_CLOSE)
    out = out[in_session]

    # Drop bad market prints before gap-filling.
    out = out[out["volume"] > 0]
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]

    out = out.sort_values(["symbol", "timeframe", "timestamp"]).drop_duplicates(
        subset=["symbol", "timeframe", "timestamp"], keep="last"
    )

    def _fix_group(group: pd.DataFrame) -> pd.DataFrame:
        g = group.sort_values("timestamp").copy()
        if fill_missing_gaps:
            g = _session_reindex(g)

        for col in ["open", "high", "low", "close"]:
            g[col] = pd.to_numeric(g[col], errors="coerce")
        g["volume"] = pd.to_numeric(g["volume"], errors="coerce")

        g[["open", "high", "low", "close"]] = g[["open", "high", "low", "close"]].ffill()
        g["volume"] = g["volume"].fillna(0.0)

        row_max = g[["open", "high", "low", "close"]].max(axis=1)
        row_min = g[["open", "high", "low", "close"]].min(axis=1)
        g["high"] = np.maximum(row_max, g["high"].fillna(row_max))
        g["low"] = np.minimum(row_min, g["low"].fillna(row_min))
        return g

    blocks = [_fix_group(group) for _, group in out.groupby(["symbol", "timeframe"], sort=False)]
    if blocks:
        out = pd.concat(blocks, ignore_index=True)
    else:
        out = out.iloc[0:0].copy()

    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float32")

    return out.reset_index(drop=True)


def clean_symbol_timeframe_frames(
    frames_by_timeframe: Mapping[str, pd.DataFrame],
    fill_missing_gaps: bool = True,
) -> dict[str, pd.DataFrame]:
    """Clean each timeframe frame independently for a single symbol batch."""
    cleaned: dict[str, pd.DataFrame] = {}

    for timeframe, frame in frames_by_timeframe.items():
        if frame is None or frame.empty:
            continue

        working = frame.copy()
        working["timeframe"] = str(timeframe).lower()
        out = clean_ohlcv_frame(working, fill_missing_gaps=fill_missing_gaps)
        if out.empty:
            continue
        cleaned[str(timeframe).lower()] = out

    return cleaned
