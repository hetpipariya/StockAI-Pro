from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DatasetValidationReport:
    input_rows: int
    output_rows: int
    dropped_duplicate_timestamps: int
    dropped_invalid_ohlcv_rows: int
    dropped_nan_inf_feature_rows: int
    missing_candle_gaps: int

    def as_dict(self) -> dict[str, int]:
        return {
            "input_rows": int(self.input_rows),
            "output_rows": int(self.output_rows),
            "dropped_duplicate_timestamps": int(self.dropped_duplicate_timestamps),
            "dropped_invalid_ohlcv_rows": int(self.dropped_invalid_ohlcv_rows),
            "dropped_nan_inf_feature_rows": int(self.dropped_nan_inf_feature_rows),
            "missing_candle_gaps": int(self.missing_candle_gaps),
        }


def _expected_freq(timeframe: str) -> str:
    tf = str(timeframe).strip().lower()
    if tf == "5m":
        return "5min"
    if tf == "15m":
        return "15min"
    if tf == "1h":
        return "1h"
    if tf == "1d":
        return "1D"
    return "5min"


def _count_missing_candle_gaps(frame: pd.DataFrame, timeframe: str) -> int:
    if frame.empty or "timestamp" not in frame.columns:
        return 0

    freq = _expected_freq(timeframe)
    gaps = 0
    grouped = frame.groupby("symbol", sort=False) if "symbol" in frame.columns else [("_", frame)]
    for _, group in grouped:
        ordered = group.sort_values("timestamp")
        if len(ordered) < 2:
            continue
        expected = pd.date_range(
            start=ordered["timestamp"].iloc[0],
            end=ordered["timestamp"].iloc[-1],
            freq=freq,
        )
        observed = pd.DatetimeIndex(ordered["timestamp"].dropna().unique())
        if len(expected) > len(observed):
            gaps += int(len(expected.difference(observed)))
    return gaps


def validate_and_clean_ohlcv(
    frame: pd.DataFrame,
    timeframe: str,
) -> tuple[pd.DataFrame, DatasetValidationReport]:
    if frame is None or frame.empty:
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        return empty, DatasetValidationReport(0, 0, 0, 0, 0, 0)

    out = frame.copy()
    input_rows = len(out)

    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")

    dup_subset = ["timestamp"] if "symbol" not in out.columns else ["symbol", "timestamp"]
    duplicate_count = int(out.duplicated(subset=dup_subset, keep="last").sum()) if "timestamp" in out.columns else 0
    if "timestamp" in out.columns:
        out = out.drop_duplicates(subset=dup_subset, keep="last")

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.replace([np.inf, -np.inf], np.nan)
    valid_mask = (
        out[required].notna().all(axis=1)
        & (out["open"] > 0)
        & (out["high"] > 0)
        & (out["low"] > 0)
        & (out["close"] > 0)
        & (out["volume"] >= 0)
        & (out["high"] >= out[["open", "close", "low"]].max(axis=1))
        & (out["low"] <= out[["open", "close", "high"]].min(axis=1))
    )
    if "timestamp" in out.columns:
        valid_mask = valid_mask & out["timestamp"].notna()

    invalid_ohlcv = int((~valid_mask).sum())
    out = out.loc[valid_mask].copy()

    sort_cols = ["symbol", "timestamp"] if "symbol" in out.columns and "timestamp" in out.columns else ["timestamp"]
    if all(col in out.columns for col in sort_cols):
        out = out.sort_values(sort_cols)

    out = out.reset_index(drop=True)
    missing_gaps = _count_missing_candle_gaps(out, timeframe=timeframe)

    report = DatasetValidationReport(
        input_rows=input_rows,
        output_rows=len(out),
        dropped_duplicate_timestamps=duplicate_count,
        dropped_invalid_ohlcv_rows=invalid_ohlcv,
        dropped_nan_inf_feature_rows=0,
        missing_candle_gaps=missing_gaps,
    )
    return out, report


def validate_and_clean_feature_rows(
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    timeframe: str,
) -> tuple[pd.DataFrame, DatasetValidationReport]:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(feature_columns)), DatasetValidationReport(0, 0, 0, 0, 0, 0)

    out = frame.copy()
    input_rows = len(out)
    missing_cols = [col for col in feature_columns if col not in out.columns]
    if missing_cols:
        raise ValueError(f"Missing required feature columns: {missing_cols}")

    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")

    dup_subset = ["timestamp"] if "symbol" not in out.columns else ["symbol", "timestamp"]
    duplicate_count = int(out.duplicated(subset=dup_subset, keep="last").sum()) if "timestamp" in out.columns else 0
    if "timestamp" in out.columns:
        out = out.drop_duplicates(subset=dup_subset, keep="last")

    numeric = out[list(feature_columns)].apply(pd.to_numeric, errors="coerce")
    inf_mask = np.isinf(numeric.to_numpy(dtype=float)).any(axis=1)
    nan_mask = numeric.isna().any(axis=1)
    bad_mask = np.asarray(inf_mask) | np.asarray(nan_mask)
    dropped_feature_rows = int(bad_mask.sum())

    out = out.loc[~bad_mask].copy()
    out.loc[:, list(feature_columns)] = numeric.loc[~bad_mask, list(feature_columns)].astype(float)

    sort_cols = ["symbol", "timestamp"] if "symbol" in out.columns and "timestamp" in out.columns else ["timestamp"]
    if all(col in out.columns for col in sort_cols):
        out = out.sort_values(sort_cols)
    out = out.reset_index(drop=True)

    missing_gaps = _count_missing_candle_gaps(out, timeframe=timeframe)

    report = DatasetValidationReport(
        input_rows=input_rows,
        output_rows=len(out),
        dropped_duplicate_timestamps=duplicate_count,
        dropped_invalid_ohlcv_rows=0,
        dropped_nan_inf_feature_rows=dropped_feature_rows,
        missing_candle_gaps=missing_gaps,
    )
    return out, report
