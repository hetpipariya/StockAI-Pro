"""Canonical feature-engineering bridge around the native C++ engine.

This module is the single feature source for both backend inference and
`experiments_v2` training. The only indicator math happens inside the compiled
C++ engine; Python is limited to causal data preparation, resampling, and
schema validation.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.cpp_engine import compute_features as cpp_compute_features
from app.cpp_engine import stockai_cpp_engine
from app.inference.feature_contract import (
    CPP_TO_CANONICAL,
    EXPECTED_FEATURE_COUNT,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    align_feature_frame,
    check_inference_compatibility,
    get_feature_summary,
    validate_feature_contract,
    validate_features,
)

logger = logging.getLogger(__name__)

BASE_5M_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
ENTRY_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
TREND_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
CONTEXT_1H_FEATURE_COLUMNS: list[str] = []
_FEATURE_MATRIX_CACHE: dict[str, pd.DataFrame] = {}

CANONICAL_NIFTY_DAILY_PATHS = (
    Path("data/nifty/daily/nifty_daily.csv"),
    Path("data/nifty/daily"),
    Path("experiments_v2/data/raw/nifty_daily.csv"),
    Path("experiments_v2/data/raw/nifty/NIFTY_50_daily.csv"),
    Path("experiments_v2/data/raw/index/NIFTY_50_daily.csv"),
)


@dataclass(frozen=True)
class DataConfig:
    timeframe: str
    min_rows_per_symbol: int = 50
    fill_missing_timestamps: bool = True
    drop_gap_filled_rows: bool = True
    max_files: int | None = None
    require_nifty_context: bool = False
    nifty_daily_path: Path | None = None


def _empty_feature_frame(index: pd.Index | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(columns=FEATURE_COLUMNS)
    if index is not None:
        frame.index = index
    return frame


def _zero_feature_row() -> pd.DataFrame:
    return pd.DataFrame([[0.0] * len(FEATURE_COLUMNS)], columns=FEATURE_COLUMNS)


def _normalize_timestamp_series(series: pd.Series, target_timezone: str = "Asia/Kolkata") -> pd.Series:
    series = pd.to_datetime(series, errors="coerce")
    if series.dt.tz is None:
        return series.dt.tz_localize(ZoneInfo(target_timezone))
    return series.dt.tz_convert(ZoneInfo(target_timezone))


def _frame_cache_token(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "empty"
    normalized = frame.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    payload = normalized.to_json(orient="split", date_format="iso")
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


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
    drop_columns = required + (["timestamp"] if "timestamp" in frame.columns else [])
    frame = frame.dropna(subset=drop_columns)

    if "high" in frame.columns and "low" in frame.columns:
        frame = frame[
            (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
            & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
            & (frame["open"] > 0)
            & (frame["high"] > 0)
            & (frame["low"] > 0)
            & (frame["close"] > 0)
            & (frame["volume"] >= 0)
        ].copy()

    sort_columns = ["timestamp"] if "timestamp" in frame.columns else []
    if "symbol" in frame.columns:
        sort_columns.insert(0, "symbol")
    if sort_columns:
        frame = frame.sort_values(sort_columns)

    frame = frame.reset_index(drop=True)
    return frame


def _load_nifty_daily_series(path: Path | None = None) -> pd.DataFrame:
    candidate_paths = [path] if path is not None else list(CANONICAL_NIFTY_DAILY_PATHS)
    for candidate in candidate_paths:
        if candidate is None:
            continue
        resolved = Path(candidate)
        if not resolved.exists():
            continue
        frame = pd.read_csv(resolved, low_memory=False)
        normalized = _normalize_ohlcv_frame(frame, require_timestamp=True)
        if normalized.empty:
            continue
        out = normalized[["timestamp", "close"]].copy()
        out = out.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        return out.reset_index(drop=True)
    return pd.DataFrame(columns=["timestamp", "close"])


def _normalize_nifty_frame(frame: pd.DataFrame, target_timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    normalized = _normalize_ohlcv_frame(frame, require_timestamp=True, target_timezone=target_timezone)
    if normalized.empty:
        return normalized
    normalized = normalized[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    normalized = normalized.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    return normalized.reset_index(drop=True)


def build_canonical_nifty_daily_dataset(
    source: Path | str,
    output_path: Path | str | None = None,
    target_timezone: str = "Asia/Kolkata",
    strict: bool = True,
    max_allowed_gap_days: int = 4,
) -> pd.DataFrame:
    source = Path(source)
    candidates: list[Path] = []
    if source.is_dir():
        candidates = sorted(source.rglob("*.csv"))
    else:
        candidates = [source]

    if not candidates:
        raise FileNotFoundError(f"NIFTY source path not found: {source}")

    fragments: list[pd.DataFrame] = []
    for candidate in candidates:
        if not candidate.exists():
            continue

        frame = pd.read_csv(candidate, low_memory=False)

        cleaned = _normalize_ohlcv_frame(frame, require_timestamp=True, target_timezone=target_timezone)
        if cleaned.empty:
            continue

        invalid_rows = len(frame) - len(cleaned)
        if strict and invalid_rows > 0:
            raise RuntimeError(
                f"NIFTY dataset contains invalid OHLCV rows: {invalid_rows}"
            )

        cleaned = cleaned.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        if cleaned.empty:
            continue

        fragments.append(cleaned)

    if not fragments:
        raise RuntimeError(f"No valid NIFTY data could be loaded from {source}")

    combined = pd.concat(fragments, ignore_index=True)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    duplicate_count = int(combined["timestamp"].duplicated().sum())
    if duplicate_count > 0:
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")

    # Validate OHLCV and currency values
    combined, errors = _drop_corrupted_ohlcv_rows(combined)
    if strict and errors["invalid_ohlcv_rows"] > 0:
        raise RuntimeError(
            f"NIFTY dataset contains invalid OHLCV rows: {errors['invalid_ohlcv_rows']}"
        )

    # Detect suspicious daily gaps beyond typical weekend/holiday windows
    if len(combined) >= 2 and max_allowed_gap_days is not None:
        delta_days = combined["timestamp"].diff().dt.days.fillna(0).astype(int)
        gap_count = int((delta_days > max_allowed_gap_days).sum())
        if strict and gap_count > 0:
            raise RuntimeError(
                f"NIFTY dataset contains {gap_count} suspicious daily gaps > {max_allowed_gap_days} days"
            )

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(output_path, index=False)

    return combined


def _normalize_close_context(data: Any) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame(columns=["timestamp", "close"])
    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, dict):
        frame = pd.DataFrame(data)
    else:
        frame = pd.DataFrame(list(data))
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "close"])
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    aliases = {"datetime": "timestamp", "date": "timestamp", "time": "timestamp"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "close" not in frame.columns:
        return pd.DataFrame(columns=["timestamp", "close"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "close"])
        return frame[["timestamp", "close"]].sort_values("timestamp").reset_index(drop=True)
    frame = frame.dropna(subset=["close"])
    return frame[["close"]].reset_index(drop=True)


def _resample_close_context(frame: pd.DataFrame, rule: str, shift_periods: int = 1) -> pd.DataFrame:
    if frame.empty or "timestamp" not in frame.columns:
        return pd.DataFrame(columns=["timestamp", "close"])
    indexed = frame[["timestamp", "close"]].dropna().copy()
    indexed = indexed.sort_values("timestamp").set_index("timestamp")
    resampled = indexed["close"].resample(rule, label="right", closed="right").last().dropna()
    if shift_periods:
        resampled = resampled.shift(shift_periods)
    resampled = resampled.dropna()
    out = resampled.reset_index()
    out.columns = ["timestamp", "close"]
    return out


def _slice_close_values(context: pd.DataFrame, ts: pd.Timestamp | None) -> np.ndarray:
    if context.empty:
        return np.array([], dtype=np.float64)
    if ts is None or "timestamp" not in context.columns:
        values = context["close"].to_numpy(dtype=np.float64)
        return np.ascontiguousarray(values)
    series = context.loc[context["timestamp"] <= ts, "close"]
    if series.empty:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(series.to_numpy(dtype=np.float64))


def _normalize_ohlc_context(data: Any) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    normalized = _normalize_ohlcv_frame(data, require_timestamp=True)
    if normalized.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    cols = [col for col in ["timestamp", "open", "high", "low", "close"] if col in normalized.columns]
    return normalized[cols].copy()


def _resample_ohlc_context(frame: pd.DataFrame, rule: str, shift_periods: int = 1) -> pd.DataFrame:
    if frame.empty or "timestamp" not in frame.columns:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    indexed = frame[["timestamp", "open", "high", "low", "close"]].dropna().copy()
    indexed = indexed.sort_values("timestamp").set_index("timestamp")
    resampled_open = indexed["open"].resample(rule, label="right", closed="right").first()
    resampled_high = indexed["high"].resample(rule, label="right", closed="right").max()
    resampled_low = indexed["low"].resample(rule, label="right", closed="right").min()
    resampled_close = indexed["close"].resample(rule, label="right", closed="right").last()
    resampled = pd.DataFrame({
        "open": resampled_open,
        "high": resampled_high,
        "low": resampled_low,
        "close": resampled_close
    }).dropna()
    if shift_periods:
        resampled = resampled.shift(shift_periods)
    resampled = resampled.dropna()
    out = resampled.reset_index()
    return out


def _slice_ohlc_values(context: pd.DataFrame, ts: pd.Timestamp | None, col: str) -> np.ndarray:
    if context.empty or col not in context.columns:
        return np.array([], dtype=np.float64)
    if ts is None or "timestamp" not in context.columns:
        values = context[col].to_numpy(dtype=np.float64)
        return np.ascontiguousarray(values)
    series = context.loc[context["timestamp"] <= ts, col]
    if series.empty:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(series.to_numpy(dtype=np.float64))



def _ema(series: pd.Series, span: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").ewm(span=span, adjust=False, min_periods=max(2, span // 2)).mean()


def _compute_latest_native_row(
    ohlcv_5m: pd.DataFrame,
    ohlcv_15m: pd.DataFrame | None = None,
    ohlcv_daily: pd.DataFrame | None = None,
    nifty_daily: pd.DataFrame | None = None,
    sector_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ctx_15m = ohlcv_15m if ohlcv_15m is not None else pd.DataFrame()
    ctx_daily = ohlcv_daily if ohlcv_daily is not None else pd.DataFrame()
    ctx_nifty = nifty_daily if nifty_daily is not None else pd.DataFrame()
    ctx_sector = sector_daily if sector_daily is not None else pd.DataFrame()
    native_available = stockai_cpp_engine is not None and hasattr(stockai_cpp_engine, "compute_all_features")
    if not native_available:
        raise RuntimeError("Native C++ engine is required but unavailable.")

    result = stockai_cpp_engine.compute_all_features(
        np.ascontiguousarray(ohlcv_5m["open"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["high"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["low"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["close"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["volume"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_15m.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_daily.get("open", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_daily.get("high", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_daily.get("low", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_daily.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_nifty.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_sector.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
    )
    status = int(result.get("status", -1))
    if status != 0:
        raise RuntimeError(result.get("error_message") or f"C++ feature computation failed: status={status}")
    feature_values = result.get("features") or {}
    row = [[float(feature_values[name]) for name in FEATURE_COLUMNS]]
    out = pd.DataFrame(row, columns=FEATURE_COLUMNS)
    out = out.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out = out.mask(out.abs() > 1e6, 0.0)
    return align_feature_frame(out, FEATURE_COLUMNS, context="compute_latest_native_row")


def compute_features(
    candles_5m: Any,
    candles_15m: Any = None,
    candles_daily: Any = None,
    nifty_daily: Any = None,
    sector_daily: Any = None,
    include_legacy: bool = False,
) -> pd.DataFrame:
    del include_legacy

    frame_5m = _normalize_ohlcv_frame(candles_5m, require_timestamp=False)
    if frame_5m.empty:
        return _empty_feature_frame()

    min_candles = int(getattr(stockai_cpp_engine, "MIN_CANDLES_FOR_FEATURES", 50))
    if len(frame_5m) < min_candles:
        return _empty_feature_frame()

    has_timestamp = "timestamp" in frame_5m.columns
    frame_15m = _normalize_close_context(candles_15m) if candles_15m is not None else pd.DataFrame()
    frame_daily = _normalize_ohlc_context(candles_daily) if candles_daily is not None else pd.DataFrame()
    frame_nifty = _normalize_close_context(nifty_daily) if nifty_daily is not None else pd.DataFrame()
    frame_sector = _normalize_close_context(sector_daily) if sector_daily is not None else pd.DataFrame()

    if has_timestamp and frame_15m.empty:
        frame_15m = _resample_close_context(frame_5m, "15min")
    if has_timestamp and frame_daily.empty:
        frame_daily = _resample_ohlc_context(frame_5m, "1D")
    if has_timestamp and frame_nifty.empty:
        frame_nifty = _load_nifty_daily_series()
        if not frame_nifty.empty:
            frame_nifty = _resample_close_context(frame_nifty, "1D")

    native_available = stockai_cpp_engine is not None and hasattr(stockai_cpp_engine, "compute_all_features")
    if not native_available:
        raise RuntimeError("Native C++ engine is required but unavailable.")

    cache_key = "|".join(
        [
            _frame_cache_token(frame_5m),
            _frame_cache_token(frame_15m),
            _frame_cache_token(frame_daily),
            _frame_cache_token(frame_nifty),
            _frame_cache_token(frame_sector),
        ]
    )
    cached = _FEATURE_MATRIX_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    rows: list[list[float]] = []
    row_indices: list[int] = []
    for end_idx in range(min_candles, len(frame_5m) + 1):
        window = frame_5m.iloc[:end_idx].copy()
        latest_ts = window["timestamp"].iloc[-1] if has_timestamp else None

        ctx_15m = frame_15m
        ctx_daily = frame_daily
        ctx_nifty = frame_nifty
        ctx_sector = frame_sector
        if has_timestamp:
            if not frame_15m.empty:
                ctx_15m = pd.DataFrame({"close": _slice_close_values(frame_15m, latest_ts)})
            if not frame_daily.empty:
                ctx_daily = pd.DataFrame({
                    "open": _slice_ohlc_values(frame_daily, latest_ts, "open"),
                    "high": _slice_ohlc_values(frame_daily, latest_ts, "high"),
                    "low": _slice_ohlc_values(frame_daily, latest_ts, "low"),
                    "close": _slice_ohlc_values(frame_daily, latest_ts, "close"),
                })
            if not frame_nifty.empty:
                ctx_nifty = pd.DataFrame({"close": _slice_close_values(frame_nifty, latest_ts)})
            if not frame_sector.empty:
                ctx_sector = pd.DataFrame({"close": _slice_close_values(frame_sector, latest_ts)})

        latest_features = _compute_latest_native_row(
            window,
            ctx_15m,
            ctx_daily,
            ctx_nifty,
            ctx_sector,
        )

        rows.append([float(latest_features.iloc[-1][column]) for column in FEATURE_COLUMNS])
        row_indices.append(end_idx - 1)

    if not rows:
        return _empty_feature_frame()

    out = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    if has_timestamp:
        out.index = frame_5m.index[row_indices]
    _FEATURE_MATRIX_CACHE[cache_key] = out.copy()
    return out


def _expected_frequency(timeframe: str) -> str:
    tf = str(timeframe).strip().lower()
    if tf == "5m":
        return "5min"
    if tf == "15m":
        return "15min"
    if tf == "1h":
        return "1h"
    if tf == "1d":
        return "1D"
    return tf


def _fill_missing_timestamps(group: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if group.empty or "timestamp" not in group.columns:
        return group
    freq = _expected_frequency(timeframe)
    ordered = group.sort_values("timestamp").copy()
    full_index = pd.date_range(
        start=ordered["timestamp"].iloc[0],
        end=ordered["timestamp"].iloc[-1],
        freq=freq,
    )
    reindexed = ordered.set_index("timestamp").reindex(full_index)
    reindexed["symbol"] = ordered["symbol"].iloc[0]
    reindexed["timeframe"] = ordered["timeframe"].iloc[0]
    reindexed["source_file"] = ordered["source_file"].iloc[0] if "source_file" in ordered.columns else "generated"
    reindexed["is_gap_filled"] = reindexed["open"].isna().astype(int)
    for column in ["open", "high", "low", "close"]:
        if column in reindexed.columns:
            reindexed[column] = reindexed[column].ffill()
    if "volume" in reindexed.columns:
        reindexed["volume"] = reindexed["volume"].fillna(0.0)
    reindexed = reindexed.reset_index().rename(columns={"index": "timestamp"})
    return reindexed


def _drop_corrupted_ohlcv_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if frame.empty:
        return frame, {"dropped_rows": 0, "duplicate_timestamps": 0, "invalid_ohlcv_rows": 0}

    out = frame.copy()
    duplicate_subset = ["timestamp"] if "symbol" not in out.columns else ["symbol", "timestamp"]
    if "timestamp" in out.columns:
        duplicates = int(out.duplicated(subset=duplicate_subset, keep="last").sum())
        out = out.drop_duplicates(subset=duplicate_subset, keep="last")
    else:
        duplicates = 0

    valid_mask = (
        (out["open"] > 0)
        & (out["high"] > 0)
        & (out["low"] > 0)
        & (out["close"] > 0)
        & (out["volume"] >= 0)
        & (out["high"] >= out[["open", "close", "low"]].max(axis=1))
        & (out["low"] <= out[["open", "close", "high"]].min(axis=1))
    )
    invalid = int((~valid_mask).sum())
    out = out.loc[valid_mask].copy()

    return out.reset_index(drop=True), {
        "dropped_rows": duplicates + invalid,
        "duplicate_timestamps": duplicates,
        "invalid_ohlcv_rows": invalid,
    }


def load_timeframe_csv_folder(folder: Path | str, config: DataConfig) -> pd.DataFrame:
    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(f"Timeframe data folder not found: {root}")

    csv_files = sorted(root.rglob("*.csv"))
    if config.max_files:
        csv_files = csv_files[: int(config.max_files)]
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found under {root}")

    blocks: list[pd.DataFrame] = []
    for csv_path in csv_files:
        frame = pd.read_csv(csv_path, low_memory=False)
        normalized = _normalize_ohlcv_frame(frame, require_timestamp=True)
        if normalized.empty:
            continue

        symbol = (
            normalized["symbol"].astype(str).str.upper().str.strip()
            if "symbol" in normalized.columns
            else pd.Series([csv_path.stem.upper()] * len(normalized))
        )
        normalized["symbol"] = symbol.replace("", csv_path.stem.upper())
        normalized["timeframe"] = str(config.timeframe).lower()
        normalized["source_file"] = csv_path.name

        cleaned, _ = _drop_corrupted_ohlcv_rows(normalized)
        if cleaned.empty:
            continue
        blocks.append(cleaned)

    if not blocks:
        raise RuntimeError(f"No valid OHLCV rows were loaded from {root}")

    merged = pd.concat(blocks, ignore_index=True, copy=False)
    merged = merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if config.fill_missing_timestamps:
        repaired_blocks = []
        for _, group in merged.groupby("symbol", sort=False):
            repaired_blocks.append(_fill_missing_timestamps(group, config.timeframe))
        merged = pd.concat(repaired_blocks, ignore_index=True, copy=False)

    if config.drop_gap_filled_rows and "is_gap_filled" in merged.columns:
        merged = merged[merged["is_gap_filled"].fillna(0).astype(int) == 0].copy()

    counts = merged.groupby("symbol")["timestamp"].transform("count")
    merged = merged[counts >= int(config.min_rows_per_symbol)].copy()
    if merged.empty:
        raise RuntimeError(
            f"No symbols have >= {config.min_rows_per_symbol} rows in {root}"
        )
    return merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def compute_base_features(
    frame: pd.DataFrame,
    nifty_daily_path: Path | None = None,
) -> pd.DataFrame:
    normalized = _normalize_ohlcv_frame(frame, require_timestamp=True)
    if normalized.empty:
        return pd.DataFrame()

    passthrough_columns = [
        column
        for column in ["timestamp", "symbol", "timeframe", "source_file", "is_gap_filled", "open", "high", "low", "close", "volume"]
        if column in normalized.columns
    ]
    nifty_context = _load_nifty_daily_series(nifty_daily_path)
    nifty_context = _resample_close_context(nifty_context, "1D") if not nifty_context.empty else nifty_context

    blocks: list[pd.DataFrame] = []
    min_candles = int(getattr(stockai_cpp_engine, "MIN_CANDLES_FOR_FEATURES", 50))
    for symbol, group in normalized.groupby("symbol", sort=False):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        features = compute_features(ordered, nifty_daily=nifty_context)
        if features.empty:
            continue
        meta = ordered.iloc[min_candles - 1 : min_candles - 1 + len(features)][passthrough_columns].reset_index(drop=True)
        block = pd.concat([meta, features.reset_index(drop=True)], axis=1)
        block = block.loc[:, ~block.columns.duplicated(keep="first")]
        blocks.append(block)

    if not blocks:
        return pd.DataFrame(columns=passthrough_columns + FEATURE_COLUMNS)

    out = pd.concat(blocks, ignore_index=True, copy=False)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out


def finalize_feature_matrix(
    frame: pd.DataFrame,
    required_features: Sequence[str],
) -> pd.DataFrame:
    expected = list(required_features)
    if set(expected) == set(FEATURE_COLUMNS):
        expected = list(FEATURE_COLUMNS)

    if frame.empty:
        metadata_columns = [column for column in frame.columns if column not in FEATURE_COLUMNS]
        return pd.DataFrame(columns=metadata_columns + expected)

    out = frame.copy()
    for column in expected:
        if column not in out.columns:
            raise RuntimeError(f"finalize_feature_matrix: missing required feature '{column}'")
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out = out.dropna(subset=expected).copy()
    validate_feature_contract(out[expected], expected, context="finalize_feature_matrix")
    metadata_columns = [column for column in out.columns if column not in FEATURE_COLUMNS]
    return out.loc[:, metadata_columns + expected].reset_index(drop=True)


def build_1h_context(frame_1h: pd.DataFrame) -> pd.DataFrame:
    if frame_1h.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", *TREND_FEATURE_COLUMNS])

    blocks: list[pd.DataFrame] = []
    for symbol, group in frame_1h.groupby("symbol", sort=False):
        ordered = group.sort_values("timestamp").copy()
        shifted = ordered[["timestamp", "symbol", *TREND_FEATURE_COLUMNS]].copy()
        shifted[TREND_FEATURE_COLUMNS] = shifted[TREND_FEATURE_COLUMNS].shift(1)
        shifted = shifted.dropna(subset=[TREND_FEATURE_COLUMNS[0]])
        shifted["symbol"] = symbol
        blocks.append(shifted)

    if not blocks:
        return pd.DataFrame(columns=["timestamp", "symbol", *TREND_FEATURE_COLUMNS])
    return pd.concat(blocks, ignore_index=True, copy=False).sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def merge_5m_with_1h_context(
    frame_5m: pd.DataFrame,
    context_1h: pd.DataFrame,
) -> pd.DataFrame:
    if frame_5m.empty:
        return frame_5m.copy()
    if context_1h.empty:
        return frame_5m.copy()

    merged_blocks: list[pd.DataFrame] = []
    meta_columns = [column for column in frame_5m.columns if column not in FEATURE_COLUMNS]
    for symbol, left_group in frame_5m.groupby("symbol", sort=False):
        left_sorted = left_group.sort_values("timestamp").copy()
        right_sorted = context_1h[context_1h["symbol"] == symbol].sort_values("timestamp").copy()
        if right_sorted.empty:
            merged_blocks.append(left_sorted)
            continue

        right_columns = [column for column in TREND_FEATURE_COLUMNS if column in right_sorted.columns]
        joined = pd.merge_asof(
            left_sorted[["timestamp", *meta_columns, *FEATURE_COLUMNS]],
            right_sorted[["timestamp", *right_columns]],
            on="timestamp",
            direction="backward",
            allow_exact_matches=False,
        )
        # Preserve the canonical 20-feature schema from the 5m feature builder.
        for column in right_columns:
            if column in FEATURE_COLUMNS:
                continue
            joined[column] = pd.to_numeric(joined[column], errors="coerce")
        joined["symbol"] = symbol
        merged_blocks.append(joined)

    merged = pd.concat(merged_blocks, ignore_index=True, copy=False)
    merged = merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return merged


__all__ = [
    "BASE_5M_FEATURE_COLUMNS",
    "CONTEXT_1H_FEATURE_COLUMNS",
    "DataConfig",
    "ENTRY_FEATURE_COLUMNS",
    "EXPECTED_FEATURE_COUNT",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "TREND_FEATURE_COLUMNS",
    "align_feature_frame",
    "build_1h_context",
    "check_inference_compatibility",
    "compute_base_features",
    "compute_features",
    "compute_technical_features",
    "finalize_feature_matrix",
    "get_feature_summary",
    "load_timeframe_csv_folder",
    "merge_5m_with_1h_context",
    "validate_feature_contract",
    "validate_features",
]

compute_technical_features = compute_base_features
UNIFIED_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
