from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from experiments_v2.features.feature_engineering import FEATURE_VERSION
from experiments_v2.pipeline.cleaner import clean_symbol_timeframe_frames
from experiments_v2.pipeline.data_loader import iter_symbol_timeframe_batches
from experiments_v2.pipeline.feature_builder import build_features
from experiments_v2.pipeline.production_validation import compute_config_hash

BASE_TIMEFRAME = "5m"
REQUIRED_TIMEFRAMES = ("1m", "5m", "1h")

# Keep only the strongest and most stable predictors for directional modeling.
STRONG_5M_FEATURES = [
    "price_change",
    "log_return_1",
    "log_return_3",
    "log_return_6",
    "momentum",
    "momentum_3",
    "return_zscore_20",
    "rolling_zscore_20",
    "rolling_zscore_50",
    "rsi",
    "rsi_x_trend",
    "ema_12",
    "ema_20",
    "ema_26",
    "ema_50",
    "ema_spread",
    "ema_spread_zscore_20",
    "macd",
    "macd_x_volume",
    "atr_14",
    "atr_pct",
    "atr_norm_body",
    "atr_norm_range",
    "atr_x_rvol",
    "true_range",
    "volatility",
    "volatility_x_volume",
    "realized_vol_20",
    "realized_vol_50",
    "vol_regime_score",
    "volume",
    "volume_change",
    "volume_ratio_20",
    "volume_zscore_20",
    "rvol_10",
    "rvol_20",
    "volume_delta",
    "cmf_20",
    "money_flow_multiplier",
    "money_flow_volume",
    "obv",
    "obv_ema_10",
    "obv_slope_5",
    "buy_pressure_proxy",
    "sell_pressure_proxy",
]

STRONG_1H_CONTEXT_BASE = [
    "ema_20",
    "ema_50",
    "ema_spread",
    "rsi",
    "macd",
    "atr_14",
    "atr_pct",
    "realized_vol_20",
    "vol_regime_score",
    "trend_strength",
]

M1_AGG_COLUMNS = [
    "m1_last_5m_return",
    "m1_volatility_std",
    "m1_volume_spike",
]

WEAK_FEATURE_EXAMPLES = [
    "minute_of_day",
    "minute_of_session",
    "session_progress",
    "sin_time_1",
    "cos_time_1",
    "sin_time_2",
    "cos_time_2",
    "day_of_week",
    "sin_dow",
    "cos_dow",
    "green_candle",
    "red_candle",
    "green_streak",
    "red_streak",
    "doji_ratio_flag",
    "candle_range",
    "body",
    "body_to_range",
    "upper_wick",
    "lower_wick",
]


@dataclass(frozen=True)
class StrongLabelConfig:
    method: str = "atr_dynamic"  # atr_dynamic or fixed_threshold
    horizon_bars: int = 12
    fixed_return_threshold: float = 0.02
    atr_column: str = "atr_14"
    atr_mult: float = 1.8
    min_barrier_pct: float = 0.008
    max_barrier_pct: float = 0.04
    min_abs_future_return: float = 0.004
    min_move_atr_mult: float = 0.35
    hold_confidence_min: float = 0.75
    keep_only_high_confidence: bool = True


@dataclass
class DatasetBuildConfig:
    raw_dir: Path
    processed_dir: Path
    timeframe_folders: tuple[str, ...] = REQUIRED_TIMEFRAMES
    symbol_allowlist: tuple[str, ...] | None = None
    max_files_per_timeframe: int | None = None
    max_symbols: int | None = None
    warmup_rows_to_drop: int = 96
    label_config: StrongLabelConfig = field(default_factory=StrongLabelConfig)
    parquet_compression: str = "snappy"
    partition_by_symbol: bool = False
    dataset_name: str = "labeled_5m_signal"
    overwrite: bool = True


def _ensure_pyarrow_available() -> None:
    try:
        import pyarrow  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "pyarrow is required for Parquet pipeline execution. Install pyarrow>=16."
        ) from exc


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _safe_symbol_token(symbol: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", str(symbol).strip())
    return token or "unknown"


def _validate_compression(codec: str) -> str:
    normalized = str(codec).strip().lower()
    if normalized not in {"snappy", "zstd"}:
        raise ValueError("Parquet compression must be one of: snappy, zstd")
    return normalized


def _downcast_numeric(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    out = df.copy()
    float_cols = out.select_dtypes(include=["float64"]).columns.tolist()
    if float_cols:
        out[float_cols] = out[float_cols].astype("float32")

    int_cols = out.select_dtypes(include=["int64"]).columns.tolist()
    for col in int_cols:
        series = out[col]
        if series.empty:
            continue
        min_val = int(series.min())
        max_val = int(series.max())
        if (
            np.iinfo(np.int32).min <= min_val <= np.iinfo(np.int32).max
            and np.iinfo(np.int32).min <= max_val <= np.iinfo(np.int32).max
        ):
            out[col] = series.astype("int32")

    return out


def _prepare_partition_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out = out.dropna(subset=["timestamp"])
    out["timeframe"] = out["timeframe"].astype(str).str.lower().str.strip()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["year"] = out["timestamp"].dt.year.astype("int32")
    out = _downcast_numeric(out)
    return out


def _write_partitioned_parquet(
    df: pd.DataFrame,
    root: Path,
    compression: str,
    partition_by_symbol: bool,
    file_prefix: str,
) -> int:
    if df.empty:
        return 0

    prepared = _prepare_partition_frame(df)
    if prepared.empty:
        return 0

    partition_cols = ["timeframe", "year"]
    if partition_by_symbol:
        partition_cols.append("symbol")

    files_written = 0
    for keys, group in prepared.groupby(partition_cols, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_map = {partition_cols[idx]: keys[idx] for idx in range(len(partition_cols))}

        partition_path = root / f"timeframe={key_map['timeframe']}" / f"year={int(key_map['year'])}"
        if partition_by_symbol:
            partition_path = partition_path / f"symbol={_safe_symbol_token(str(key_map['symbol']))}"

        partition_path.mkdir(parents=True, exist_ok=True)
        file_name = f"{file_prefix}_{uuid4().hex}.parquet"

        payload = group.drop(columns=["year"], errors="ignore")
        payload.to_parquet(
            partition_path / file_name,
            index=False,
            engine="pyarrow",
            compression=compression,
        )
        files_written += 1

    return files_written


def _drop_group_warmup_rows(df: pd.DataFrame, warmup_rows: int) -> pd.DataFrame:
    if df.empty or int(warmup_rows) <= 0:
        return df.copy()

    out = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True).copy()
    rank = out.groupby(["symbol"], sort=False).cumcount()
    out = out[rank >= int(warmup_rows)].copy()
    return out.reset_index(drop=True)


def _sanitize_5m_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    if df.empty:
        return df.copy(), 0, 0

    out = df.copy()
    before = len(out)
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out = out.dropna(subset=["timestamp"])
    null_timestamp_dropped = int(before - len(out))

    before = len(out)
    out = out.sort_values(["symbol", "timestamp"]).drop_duplicates(
        subset=["symbol", "timestamp"],
        keep="last",
    )
    duplicate_rows_dropped = int(before - len(out))
    return out.reset_index(drop=True), null_timestamp_dropped, duplicate_rows_dropped


def _assign_walk_forward_split(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    out = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True).copy()
    years = pd.to_datetime(out["timestamp"], errors="coerce").dt.year

    out["split"] = np.where(years <= 2024, "train", "test")
    if (out["split"] == "test").sum() == 0:
        ordered = out.sort_values("timestamp").reset_index(drop=True)
        cut_idx = max(1, int(len(ordered) * 0.80)) - 1
        cutoff_ts = ordered.loc[cut_idx, "timestamp"]
        out["split"] = np.where(out["timestamp"] <= cutoff_ts, "train", "test")

    out["wf_fold"] = "none"
    out.loc[years == 2022, "wf_fold"] = "fold_2022"
    out.loc[years == 2023, "wf_fold"] = "fold_2023"
    out.loc[years == 2024, "wf_fold"] = "fold_2024"
    out.loc[years >= 2025, "wf_fold"] = "holdout_2025_plus"
    return out


def _merge_asof_by_symbol(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    if left.empty:
        return left.copy()
    if right.empty:
        return left.copy()

    value_cols = [col for col in right.columns if col not in {"timestamp", "symbol"}]

    blocks: list[pd.DataFrame] = []
    for symbol, left_group in left.groupby("symbol", sort=False):
        l = left_group.sort_values("timestamp").copy()
        r = right[right["symbol"] == symbol].sort_values("timestamp").copy()

        if r.empty:
            for col in value_cols:
                l[col] = np.nan
            blocks.append(l)
            continue

        merged = pd.merge_asof(
            l,
            r.drop(columns=["symbol"]),
            on="timestamp",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["symbol"] = symbol
        blocks.append(merged)

    out = pd.concat(blocks, ignore_index=True) if blocks else left
    return out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def _build_1m_aggregates(frame_1m: pd.DataFrame) -> pd.DataFrame:
    if frame_1m.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", *M1_AGG_COLUMNS])

    blocks: list[pd.DataFrame] = []
    for symbol, group in frame_1m.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").copy()
        if g.empty:
            continue

        g["log_ret_1m"] = np.log(
            pd.to_numeric(g["close"], errors="coerce")
            / pd.to_numeric(g["close"], errors="coerce").shift(1).replace(0.0, np.nan)
        )
        g = g.set_index("timestamp")

        open_5m = pd.to_numeric(g["open"], errors="coerce").resample(
            "5min", label="right", closed="right"
        ).first()
        close_5m = pd.to_numeric(g["close"], errors="coerce").resample(
            "5min", label="right", closed="right"
        ).last()
        vol_sum_5m = pd.to_numeric(g["volume"], errors="coerce").resample(
            "5min", label="right", closed="right"
        ).sum()
        vol_std_5m = pd.to_numeric(g["log_ret_1m"], errors="coerce").resample(
            "5min", label="right", closed="right"
        ).std()

        agg = pd.DataFrame(
            {
                "timestamp": close_5m.index,
                "symbol": symbol,
                "m1_last_5m_return": (close_5m / open_5m.replace(0.0, np.nan)) - 1.0,
                "m1_volatility_std": vol_std_5m,
                "m1_volume_spike": vol_sum_5m
                / vol_sum_5m.rolling(20, min_periods=5).mean().replace(0.0, np.nan),
            }
        )
        blocks.append(agg.reset_index(drop=True))

    if not blocks:
        return pd.DataFrame(columns=["timestamp", "symbol", *M1_AGG_COLUMNS])

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    for col in M1_AGG_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)

    out[M1_AGG_COLUMNS] = out.groupby("symbol", sort=False)[M1_AGG_COLUMNS].ffill().fillna(0.0)
    out[M1_AGG_COLUMNS] = out[M1_AGG_COLUMNS].astype("float32")
    return out


def _attach_1m_aggregates(base_5m: pd.DataFrame, agg_1m: pd.DataFrame) -> pd.DataFrame:
    out = _merge_asof_by_symbol(base_5m, agg_1m)
    for col in M1_AGG_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)

    out[M1_AGG_COLUMNS] = out.groupby("symbol", sort=False)[M1_AGG_COLUMNS].ffill().fillna(0.0)
    out[M1_AGG_COLUMNS] = out[M1_AGG_COLUMNS].astype("float32")
    return out


def _attach_1h_context(base_5m: pd.DataFrame, feature_df_1h: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if base_5m.empty:
        return base_5m.copy(), []

    if feature_df_1h.empty:
        out = base_5m.copy()
        out["trend_direction_1h_ctx"] = 0
        return out, ["trend_direction_1h_ctx"]

    context_base = [col for col in STRONG_1H_CONTEXT_BASE if col in feature_df_1h.columns]
    if not context_base:
        out = base_5m.copy()
        out["trend_direction_1h_ctx"] = 0
        return out, ["trend_direction_1h_ctx"]

    ctx = feature_df_1h[["timestamp", "symbol", *context_base]].copy()
    rename_map = {col: f"{col}_1h_ctx" for col in context_base}
    ctx = ctx.rename(columns=rename_map)

    out = _merge_asof_by_symbol(base_5m, ctx)
    context_cols = [f"{col}_1h_ctx" for col in context_base]

    for col in context_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)

    out[context_cols] = out.groupby("symbol", sort=False)[context_cols].ffill().fillna(0.0)
    out[context_cols] = out[context_cols].astype("float32")

    if "ema_20_1h_ctx" in out.columns and "ema_50_1h_ctx" in out.columns:
        out["trend_direction_1h_ctx"] = np.sign(
            pd.to_numeric(out["ema_20_1h_ctx"], errors="coerce")
            - pd.to_numeric(out["ema_50_1h_ctx"], errors="coerce")
        ).astype("int8")
    elif "trend_strength_1h_ctx" in out.columns:
        out["trend_direction_1h_ctx"] = np.sign(
            pd.to_numeric(out["trend_strength_1h_ctx"], errors="coerce")
        ).astype("int8")
    else:
        out["trend_direction_1h_ctx"] = 0

    context_cols.append("trend_direction_1h_ctx")
    return out, context_cols


def _select_final_columns(frame: pd.DataFrame, context_columns: list[str]) -> list[str]:
    key_cols = [
        col
        for col in ["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume", "source_file"]
        if col in frame.columns
    ]

    strong_5m = [col for col in STRONG_5M_FEATURES if col in frame.columns]
    strong_1m = [col for col in M1_AGG_COLUMNS if col in frame.columns]
    strong_1h = [col for col in context_columns if col in frame.columns]

    selected = key_cols + strong_5m + strong_1m + strong_1h
    return list(dict.fromkeys(selected))


def _build_symbol_feature_frame(cleaned_frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[str], list[str]]:
    missing_required = [tf for tf in REQUIRED_TIMEFRAMES if tf not in cleaned_frames]
    if missing_required:
        return pd.DataFrame(), [], missing_required

    frame_5m = cleaned_frames["5m"].copy()
    frame_1m = cleaned_frames["1m"].copy()
    frame_1h = cleaned_frames["1h"].copy()

    feature_input = pd.concat([frame_5m, frame_1h], ignore_index=True)
    feature_df = build_features(feature_input)
    if feature_df.empty:
        return pd.DataFrame(), [], []

    feat_5m = feature_df[feature_df["timeframe"].astype(str).str.lower() == "5m"].copy()
    feat_1h = feature_df[feature_df["timeframe"].astype(str).str.lower() == "1h"].copy()

    if feat_5m.empty:
        return pd.DataFrame(), [], []

    agg_1m = _build_1m_aggregates(frame_1m)
    merged = _attach_1m_aggregates(feat_5m, agg_1m)
    merged, context_cols = _attach_1h_context(merged, feat_1h)

    merged["timeframe"] = BASE_TIMEFRAME
    selected_cols = _select_final_columns(merged, context_columns=context_cols)
    out = merged[selected_cols].copy()

    numeric_cols = [col for col in selected_cols if col not in {"timestamp", "symbol", "timeframe", "source_file"}]
    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)

    out[numeric_cols] = out.groupby("symbol", sort=False)[numeric_cols].ffill().fillna(0.0)
    out[numeric_cols] = out[numeric_cols].astype("float32")
    return out.reset_index(drop=True), context_cols, []


def _label_5m_rows(df: pd.DataFrame, config: StrongLabelConfig) -> tuple[pd.DataFrame, dict[str, int]]:
    if df.empty:
        return df.copy(), {
            "dropped_missing_future": 0,
            "dropped_low_movement": 0,
            "dropped_low_confidence": 0,
        }

    method = str(config.method).strip().lower()
    if method not in {"atr_dynamic", "fixed_threshold"}:
        raise ValueError("Label method must be one of: atr_dynamic, fixed_threshold")

    blocks: list[pd.DataFrame] = []
    dropped_missing_future = 0
    dropped_low_movement = 0
    dropped_low_confidence = 0

    for symbol, group in df.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True).copy()

        close = pd.to_numeric(g["close"], errors="coerce")
        future_close = close.shift(-int(config.horizon_bars))
        future_return = (future_close / close.replace(0.0, np.nan)) - 1.0

        if config.atr_column in g.columns:
            atr = pd.to_numeric(g[config.atr_column], errors="coerce")
            atr_pct = atr / close.replace(0.0, np.nan)
        else:
            atr_pct = close.pct_change().abs().rolling(14, min_periods=5).mean()

        atr_pct = atr_pct.replace([np.inf, -np.inf], np.nan)
        atr_pct = atr_pct.ffill().fillna(float(config.min_barrier_pct)).clip(lower=1e-6)

        if method == "fixed_threshold":
            barrier = pd.Series(float(config.fixed_return_threshold), index=g.index)
            method_name = "fixed_threshold"
        else:
            barrier = (float(config.atr_mult) * atr_pct).clip(
                lower=float(config.min_barrier_pct),
                upper=float(config.max_barrier_pct),
            )
            method_name = "atr_dynamic"

        target_class = np.where(
            future_return >= barrier,
            1,
            np.where(future_return <= (-barrier), -1, 0),
        )
        target_series = pd.Series(target_class, index=g.index)

        abs_return = future_return.abs()
        move_floor = np.maximum(
            float(config.min_abs_future_return),
            float(config.min_move_atr_mult) * atr_pct,
        )
        confidence = abs_return / barrier.clip(lower=1e-6)

        valid_future_mask = future_return.notna() & np.isfinite(future_return)
        movement_mask = abs_return >= move_floor
        confidence_mask = (target_class != 0) | (confidence >= float(config.hold_confidence_min))

        dropped_missing_future += int((~valid_future_mask).sum())
        dropped_low_movement += int((valid_future_mask & (~movement_mask)).sum())

        if bool(config.keep_only_high_confidence):
            keep_mask = valid_future_mask & movement_mask & confidence_mask
            dropped_low_confidence += int((valid_future_mask & movement_mask & (~confidence_mask)).sum())
        else:
            keep_mask = valid_future_mask & movement_mask

        g = g.loc[keep_mask].copy()
        if g.empty:
            continue

        g["future_return"] = pd.to_numeric(future_return.loc[g.index], errors="coerce").astype("float32")
        g["label_barrier_pct"] = pd.to_numeric(barrier.loc[g.index], errors="coerce").astype("float32")
        g["label_confidence"] = pd.to_numeric(confidence.loc[g.index], errors="coerce").astype("float32")
        g["target_class"] = target_series.loc[g.index].astype("int8")
        g["target_signal"] = g["target_class"].map({-1: "SELL", 0: "HOLD", 1: "BUY"})
        g["label_method"] = method_name
        blocks.append(g)

    if not blocks:
        return df.iloc[0:0].copy(), {
            "dropped_missing_future": int(dropped_missing_future),
            "dropped_low_movement": int(dropped_low_movement),
            "dropped_low_confidence": int(dropped_low_confidence),
        }

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out, {
        "dropped_missing_future": int(dropped_missing_future),
        "dropped_low_movement": int(dropped_low_movement),
        "dropped_low_confidence": int(dropped_low_confidence),
    }


def build_dataset(config: DatasetBuildConfig) -> dict[str, str]:
    _ensure_pyarrow_available()
    compression = _validate_compression(config.parquet_compression)

    config.processed_dir.mkdir(parents=True, exist_ok=True)

    dataset_root = config.processed_dir / "datasets_parquet"
    labeled_root = dataset_root / str(config.dataset_name).strip().lower()
    metadata_path = config.processed_dir / "dataset_metadata.json"

    if config.overwrite and labeled_root.exists() and labeled_root.is_dir():
        shutil.rmtree(labeled_root)
    labeled_root.mkdir(parents=True, exist_ok=True)

    rows = {
        "raw": 0,
        "featured_5m": 0,
        "labeled_5m": 0,
    }

    class_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    symbols_seen: set[str] = set()

    strong_feature_columns_seen: set[str] = set()
    context_columns_seen: set[str] = set()

    quality_counts = {
        "null_timestamp_rows_dropped": 0,
        "duplicate_rows_dropped": 0,
        "warmup_rows_dropped": 0,
        "dropped_missing_future": 0,
        "dropped_low_movement": 0,
        "dropped_low_confidence": 0,
        "symbols_missing_required_timeframes": 0,
    }

    file_counts = {
        "labeled": 0,
    }

    processed_symbols = 0

    for symbol_batch in iter_symbol_timeframe_batches(
        raw_root=config.raw_dir,
        timeframe_folders=config.timeframe_folders,
        symbol_allowlist=config.symbol_allowlist,
        max_files_per_timeframe=config.max_files_per_timeframe,
        required_timeframes=REQUIRED_TIMEFRAMES,
    ):
        if config.max_symbols is not None and processed_symbols >= int(config.max_symbols):
            break

        symbol = symbol_batch.symbol
        safe_symbol = _safe_symbol_token(symbol)

        rows["raw"] += int(sum(len(frame) for frame in symbol_batch.frames_by_timeframe.values()))

        cleaned_frames = clean_symbol_timeframe_frames(symbol_batch.frames_by_timeframe)
        symbol_feature_df, context_cols, missing_required = _build_symbol_feature_frame(cleaned_frames)

        if missing_required:
            quality_counts["symbols_missing_required_timeframes"] += 1
            continue
        if symbol_feature_df.empty:
            continue

        strong_feature_columns_seen.update(
            col
            for col in symbol_feature_df.columns
            if col in STRONG_5M_FEATURES or col in M1_AGG_COLUMNS
        )
        context_columns_seen.update(context_cols)

        before_warmup = len(symbol_feature_df)
        symbol_feature_df = _drop_group_warmup_rows(symbol_feature_df, warmup_rows=int(config.warmup_rows_to_drop))
        quality_counts["warmup_rows_dropped"] += int(before_warmup - len(symbol_feature_df))
        if symbol_feature_df.empty:
            continue

        rows["featured_5m"] += int(len(symbol_feature_df))

        labeled_df, label_drop_stats = _label_5m_rows(symbol_feature_df, config=config.label_config)
        quality_counts["dropped_missing_future"] += int(label_drop_stats["dropped_missing_future"])
        quality_counts["dropped_low_movement"] += int(label_drop_stats["dropped_low_movement"])
        quality_counts["dropped_low_confidence"] += int(label_drop_stats["dropped_low_confidence"])

        if labeled_df.empty:
            continue

        labeled_df, dropped_null_ts, dropped_dupes = _sanitize_5m_rows(labeled_df)
        quality_counts["null_timestamp_rows_dropped"] += int(dropped_null_ts)
        quality_counts["duplicate_rows_dropped"] += int(dropped_dupes)
        if labeled_df.empty:
            continue

        labeled_df = _assign_walk_forward_split(labeled_df)

        rows["labeled_5m"] += int(len(labeled_df))
        symbols_seen.add(symbol)

        if "target_signal" in labeled_df.columns:
            class_counts.update(labeled_df["target_signal"].astype(str).value_counts().to_dict())
        if "split" in labeled_df.columns:
            split_counts.update(labeled_df["split"].astype(str).value_counts().to_dict())

        file_counts["labeled"] += _write_partitioned_parquet(
            df=labeled_df,
            root=labeled_root,
            compression=compression,
            partition_by_symbol=config.partition_by_symbol,
            file_prefix=f"labeled_5m_{safe_symbol}",
        )

        processed_symbols += 1

    partition_cols = ["timeframe", "year"] + (["symbol"] if config.partition_by_symbol else [])

    metadata = {
        "rows": {
            "raw": int(rows["raw"]),
            "featured_5m": int(rows["featured_5m"]),
            "labeled_5m": int(rows["labeled_5m"]),
        },
        "symbols": sorted(symbols_seen),
        "target_timeframe": BASE_TIMEFRAME,
        "dataset_structure": {
            "base_timeframe": BASE_TIMEFRAME,
            "uses_raw_1m_rows_directly": False,
            "aggregated_1m_features": M1_AGG_COLUMNS,
            "context_1h_features": sorted(context_columns_seen),
            "weak_features_removed_examples": WEAK_FEATURE_EXAMPLES,
        },
        "feature_selection": {
            "feature_version": FEATURE_VERSION,
            "strong_feature_columns": sorted(strong_feature_columns_seen),
            "strong_5m_features_config": STRONG_5M_FEATURES,
            "strong_1h_context_base_config": STRONG_1H_CONTEXT_BASE,
        },
        "labeling": {
            "method": str(config.label_config.method),
            "horizon_bars": int(config.label_config.horizon_bars),
            "fixed_return_threshold": float(config.label_config.fixed_return_threshold),
            "atr_column": str(config.label_config.atr_column),
            "atr_mult": float(config.label_config.atr_mult),
            "min_barrier_pct": float(config.label_config.min_barrier_pct),
            "max_barrier_pct": float(config.label_config.max_barrier_pct),
            "min_abs_future_return": float(config.label_config.min_abs_future_return),
            "min_move_atr_mult": float(config.label_config.min_move_atr_mult),
            "hold_confidence_min": float(config.label_config.hold_confidence_min),
            "keep_only_high_confidence": bool(config.label_config.keep_only_high_confidence),
        },
        "class_counts": dict(class_counts),
        "split_counts": dict(split_counts),
        "quality": {
            "null_timestamp_rows_dropped": int(quality_counts["null_timestamp_rows_dropped"]),
            "duplicate_rows_dropped": int(quality_counts["duplicate_rows_dropped"]),
            "warmup_rows_dropped": int(quality_counts["warmup_rows_dropped"]),
            "dropped_missing_future": int(quality_counts["dropped_missing_future"]),
            "dropped_low_movement": int(quality_counts["dropped_low_movement"]),
            "dropped_low_confidence": int(quality_counts["dropped_low_confidence"]),
            "symbols_missing_required_timeframes": int(quality_counts["symbols_missing_required_timeframes"]),
            "warmup_rows_config": int(config.warmup_rows_to_drop),
        },
        "storage": {
            "format": "parquet",
            "compression": compression,
            "partition_columns": partition_cols,
            "labeled_root": str(labeled_root),
            "file_counts": {k: int(v) for k, v in file_counts.items()},
        },
    }

    metadata["dataset_signature"] = {
        "config_hash": compute_config_hash(
            {
                "dataset_structure": metadata["dataset_structure"],
                "feature_selection": metadata["feature_selection"],
                "labeling": metadata["labeling"],
                "quality": metadata["quality"],
                "storage": metadata["storage"],
            }
        )
    }

    with metadata_path.open("w", encoding="utf-8") as fp:
        json.dump(_to_native(metadata), fp, indent=2)

    return {
        "dataset_root": str(labeled_root),
        "metadata": str(metadata_path),
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build 5m target dataset with aggregated 1m features, 1h context, and strong leakage-safe labels"
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=root / "data" / "raw",
        help="Directory with timeframe folders 1m, 5m, 1h",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=root / "data" / "processed_parquet",
        help="Directory where partitioned Parquet datasets are written",
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="labeled_5m_signal",
        help="Dataset folder name under processed-dir/datasets_parquet",
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default="1m,5m,1h",
        help="Comma-separated timeframe folders to load",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Optional comma-separated symbol allowlist",
    )
    parser.add_argument(
        "--max-files-per-timeframe",
        type=int,
        default=None,
        help="Optional per-timeframe file cap",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Optional cap on number of symbols processed",
    )
    parser.add_argument(
        "--warmup-rows-to-drop",
        type=int,
        default=96,
        help="Rows dropped per symbol before labeling to stabilize rolling features",
    )
    parser.add_argument(
        "--label-method",
        type=str,
        default="atr_dynamic",
        choices=["atr_dynamic", "fixed_threshold"],
        help="Labeling strategy",
    )
    parser.add_argument(
        "--label-horizon-bars",
        type=int,
        default=12,
        help="Label horizon in 5m bars",
    )
    parser.add_argument(
        "--fixed-return-threshold",
        type=float,
        default=0.02,
        help="Absolute future-return threshold for fixed-threshold labels",
    )
    parser.add_argument(
        "--label-atr-column",
        type=str,
        default="atr_14",
        help="ATR-like column used for dynamic barriers",
    )
    parser.add_argument(
        "--label-atr-mult",
        type=float,
        default=1.8,
        help="ATR multiplier for dynamic barriers",
    )
    parser.add_argument(
        "--label-min-barrier-pct",
        type=float,
        default=0.008,
        help="Minimum dynamic barrier as decimal return",
    )
    parser.add_argument(
        "--label-max-barrier-pct",
        type=float,
        default=0.04,
        help="Maximum dynamic barrier as decimal return",
    )
    parser.add_argument(
        "--min-abs-future-return",
        type=float,
        default=0.004,
        help="Minimum absolute future return needed to keep a sample",
    )
    parser.add_argument(
        "--min-move-atr-mult",
        type=float,
        default=0.35,
        help="Minimum movement floor as ATR percentage multiplier",
    )
    parser.add_argument(
        "--hold-confidence-min",
        type=float,
        default=0.75,
        help="Minimum confidence ratio to keep HOLD rows",
    )
    parser.add_argument(
        "--disable-high-confidence-filter",
        action="store_true",
        help="Disable confidence gate and keep all non-noise rows",
    )
    parser.add_argument(
        "--parquet-compression",
        type=str,
        default="snappy",
        choices=["snappy", "zstd"],
        help="Parquet compression codec",
    )
    parser.add_argument(
        "--partition-by-symbol",
        action="store_true",
        help="Partition Parquet paths additionally by symbol",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Do not delete existing target Parquet dataset root before writing",
    )
    parser.add_argument(
        "--chunk-format",
        type=str,
        default="parquet",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if str(args.chunk_format).strip().lower() != "parquet":
        raise ValueError("CSV output is disabled. Use Parquet only.")

    output_paths = build_dataset(
        DatasetBuildConfig(
            raw_dir=args.raw_dir,
            processed_dir=args.processed_dir,
            timeframe_folders=tuple(
                tf.strip().lower()
                for tf in str(args.timeframes).split(",")
                if tf.strip()
            ),
            symbol_allowlist=tuple(
                sym.strip().upper()
                for sym in str(args.symbols).split(",")
                if sym.strip()
            )
            or None,
            max_files_per_timeframe=args.max_files_per_timeframe,
            max_symbols=args.max_symbols,
            warmup_rows_to_drop=int(args.warmup_rows_to_drop),
            label_config=StrongLabelConfig(
                method=str(args.label_method),
                horizon_bars=int(args.label_horizon_bars),
                fixed_return_threshold=float(args.fixed_return_threshold),
                atr_column=str(args.label_atr_column),
                atr_mult=float(args.label_atr_mult),
                min_barrier_pct=float(args.label_min_barrier_pct),
                max_barrier_pct=float(args.label_max_barrier_pct),
                min_abs_future_return=float(args.min_abs_future_return),
                min_move_atr_mult=float(args.min_move_atr_mult),
                hold_confidence_min=float(args.hold_confidence_min),
                keep_only_high_confidence=not bool(args.disable_high_confidence_filter),
            ),
            parquet_compression=args.parquet_compression,
            partition_by_symbol=bool(args.partition_by_symbol),
            dataset_name=str(args.dataset_name),
            overwrite=not bool(args.no_overwrite),
        )
    )

    print(json.dumps(output_paths, indent=2))
