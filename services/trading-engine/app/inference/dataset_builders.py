from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from app.data.nifty_cache import canonical_path, ensure_nifty_dirs
from app.inference.feature_engineering import (
    FEATURE_COLUMNS,
    DataConfig,
    build_canonical_nifty_daily_dataset,
    compute_base_features,
    finalize_feature_matrix,
    load_timeframe_csv_folder,
)
from app.inference.dataset_validation import (
    validate_and_clean_feature_rows,
    validate_and_clean_ohlcv,
)
from app.inference.label_generation import generate_labels

logger = logging.getLogger(__name__)


def _dataset_metadata(path: Path, frame: pd.DataFrame, extra: dict[str, object] | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {
        "generated_at": datetime.now().isoformat(),
        "row_count": len(frame),
        "columns": list(frame.columns),
    }
    if extra:
        metadata.update(extra)
    if path is not None:
        metadata["output_path"] = str(path)
    return metadata


def build_nifty_daily_dataset(
    source: Path | str,
    output_path: Path | str | None = None,
    strict: bool = True,
    max_allowed_gap_days: int = 4,
) -> pd.DataFrame:
    output_path = Path(output_path) if output_path is not None else canonical_path("daily")
    ensure_nifty_dirs()
    frame = build_canonical_nifty_daily_dataset(
        source=source,
        output_path=output_path,
        strict=strict,
        max_allowed_gap_days=max_allowed_gap_days,
    )
    report = _dataset_metadata(output_path, frame, {"dataset_type": "nifty_daily"})
    logger.info("[DATASET] Built NIFTY daily dataset (%d rows)", len(frame))
    return frame


def _build_feature_dataset(
    timeframe: str,
    raw_folder: Path | str,
    output_path: Path | str,
    nifty_daily_path: Path | str | None = None,
    min_rows_per_symbol: int = 100,
    max_files: int | None = None,
    max_rows_per_symbol: int | None = None,
) -> pd.DataFrame:
    config = DataConfig(
        timeframe=timeframe,
        min_rows_per_symbol=min_rows_per_symbol,
        fill_missing_timestamps=True,
        drop_gap_filled_rows=True,
        max_files=max_files,
    )
    raw_data = load_timeframe_csv_folder(raw_folder, config)
    raw_data, raw_validation = validate_and_clean_ohlcv(raw_data, timeframe=timeframe)
    logger.info("[DATASET] %s raw validation: %s", timeframe, raw_validation.as_dict())
    if max_rows_per_symbol is not None and max_rows_per_symbol > 0 and not raw_data.empty:
        raw_data = (
            raw_data.sort_values(["symbol", "timestamp"])
            .groupby("symbol", sort=False, group_keys=False)
            .head(int(max_rows_per_symbol))
            .reset_index(drop=True)
        )
    features = compute_base_features(raw_data, nifty_daily_path=Path(nifty_daily_path) if nifty_daily_path else None)
    features = finalize_feature_matrix(features, FEATURE_COLUMNS)
    features, feature_validation = validate_and_clean_feature_rows(features, FEATURE_COLUMNS, timeframe=timeframe)
    logger.info("[DATASET] %s feature validation: %s", timeframe, feature_validation.as_dict())
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(output_path, index=False)
    logger.info(
        "[DATASET] Built %s feature dataset: %s rows, output=%s",
        timeframe,
        len(features),
        output_path,
    )
    return features


def build_entry_5m_dataset(
    raw_folder: Path | str,
    output_path: Path | str,
    nifty_daily_path: Path | str | None = None,
    min_rows_per_symbol: int = 150,
    max_files: int | None = None,
    max_rows_per_symbol: int | None = None,
) -> pd.DataFrame:
    return _build_feature_dataset(
        timeframe="5m",
        raw_folder=raw_folder,
        output_path=output_path,
        nifty_daily_path=nifty_daily_path,
        min_rows_per_symbol=min_rows_per_symbol,
        max_files=max_files,
        max_rows_per_symbol=max_rows_per_symbol,
    )


def build_trend_1h_dataset(
    raw_folder: Path | str,
    output_path: Path | str,
    nifty_daily_path: Path | str | None = None,
    min_rows_per_symbol: int = 120,
    max_files: int | None = None,
    max_rows_per_symbol: int | None = None,
) -> pd.DataFrame:
    return _build_feature_dataset(
        timeframe="1h",
        raw_folder=raw_folder,
        output_path=output_path,
        nifty_daily_path=nifty_daily_path,
        min_rows_per_symbol=min_rows_per_symbol,
        max_files=max_files,
        max_rows_per_symbol=max_rows_per_symbol,
    )


def attach_labels_to_features(
    features: pd.DataFrame,
    raw_ohlcv: pd.DataFrame,
    horizon: int = 3,
) -> pd.DataFrame:
    if features.empty:
        raise ValueError("Empty feature frame cannot be labeled")
    if raw_ohlcv.empty:
        raise ValueError("Raw OHLCV data required to generate labels")

    raw = raw_ohlcv.copy()
    if "timestamp" in raw.columns:
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw = raw.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    labeled_frames: list[pd.DataFrame] = []
    for symbol, group in raw.groupby("symbol", sort=False):
        ordered = group.reset_index(drop=True)
        label_series = generate_labels(ordered, horizon=horizon)
        ordered = ordered.assign(label=label_series.values)
        labeled_frames.append(ordered[["symbol", "timestamp", "label"]])

    if not labeled_frames:
        raise RuntimeError("Unable to generate label frame from raw data")

    label_frame = pd.concat(labeled_frames, ignore_index=True)
    merged = features.merge(label_frame, on=["symbol", "timestamp"], how="inner")
    if merged.empty:
        raise RuntimeError("No label rows could be aligned with the feature matrix")

    merged = merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    logger.info("[DATASET] Appended labels to feature matrix (%d rows)", len(merged))
    return merged


def build_entry_5m_training_dataset(
    raw_folder: Path | str,
    output_path: Path | str,
    nifty_daily_path: Path | str | None = None,
    horizon: int = 3,
    min_rows_per_symbol: int = 150,
    max_files: int | None = None,
    max_rows_per_symbol: int | None = None,
) -> pd.DataFrame:
    features = build_entry_5m_dataset(
        raw_folder=raw_folder,
        output_path=output_path,
        nifty_daily_path=nifty_daily_path,
        min_rows_per_symbol=min_rows_per_symbol,
        max_files=max_files,
        max_rows_per_symbol=max_rows_per_symbol,
    )
    raw_data = load_timeframe_csv_folder(raw_folder, DataConfig(timeframe="5m", min_rows_per_symbol=min_rows_per_symbol, max_files=max_files))
    if max_rows_per_symbol is not None and max_rows_per_symbol > 0 and not raw_data.empty:
        raw_data = (
            raw_data.sort_values(["symbol", "timestamp"])
            .groupby("symbol", sort=False, group_keys=False)
            .head(int(max_rows_per_symbol))
            .reset_index(drop=True)
        )
    return attach_labels_to_features(features, raw_data, horizon=horizon)


def build_trend_1h_training_dataset(
    raw_folder: Path | str,
    output_path: Path | str,
    nifty_daily_path: Path | str | None = None,
    horizon: int = 3,
    min_rows_per_symbol: int = 120,
    max_files: int | None = None,
    max_rows_per_symbol: int | None = None,
) -> pd.DataFrame:
    features = build_trend_1h_dataset(
        raw_folder=raw_folder,
        output_path=output_path,
        nifty_daily_path=nifty_daily_path,
        min_rows_per_symbol=min_rows_per_symbol,
        max_files=max_files,
        max_rows_per_symbol=max_rows_per_symbol,
    )
    raw_data = load_timeframe_csv_folder(raw_folder, DataConfig(timeframe="1h", min_rows_per_symbol=min_rows_per_symbol, max_files=max_files))
    if max_rows_per_symbol is not None and max_rows_per_symbol > 0 and not raw_data.empty:
        raw_data = (
            raw_data.sort_values(["symbol", "timestamp"])
            .groupby("symbol", sort=False, group_keys=False)
            .head(int(max_rows_per_symbol))
            .reset_index(drop=True)
        )
    return attach_labels_to_features(features, raw_data, horizon=horizon)
