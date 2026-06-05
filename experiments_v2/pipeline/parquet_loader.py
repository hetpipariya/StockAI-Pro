from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd


def _get_dataset_api():
    try:
        import pyarrow.dataset as ds
    except Exception as exc:
        raise RuntimeError(
            "pyarrow is required for Parquet dataset loading. Install pyarrow>=16."
        ) from exc
    return ds


def get_parquet_columns(dataset_root: Path) -> list[str]:
    ds = _get_dataset_api()
    if not dataset_root.exists() or not dataset_root.is_dir():
        raise FileNotFoundError(f"Parquet dataset root not found: {dataset_root}")

    dataset = ds.dataset(str(dataset_root), format="parquet", partitioning="hive")
    return [str(name) for name in dataset.schema.names]


def iter_parquet_batches(
    dataset_root: Path,
    columns: list[str],
    timeframes: tuple[str, ...],
    batch_size: int,
    year_min: int | None = None,
    year_max: int | None = None,
) -> Iterator[pd.DataFrame]:
    ds = _get_dataset_api()
    if not dataset_root.exists() or not dataset_root.is_dir():
        raise FileNotFoundError(f"Parquet dataset root not found: {dataset_root}")

    dataset = ds.dataset(str(dataset_root), format="parquet", partitioning="hive")
    available_names = [str(name) for name in dataset.schema.names]
    lower_to_actual = {name.lower(): name for name in available_names}

    selected_columns: list[str] = []
    for col in columns:
        token = str(col).strip().lower()
        actual = lower_to_actual.get(token)
        if actual and actual not in selected_columns:
            selected_columns.append(actual)

    if not selected_columns:
        raise RuntimeError("No requested columns are available in the Parquet dataset.")

    filter_expr = None
    requested_timeframes = [str(tf).strip().lower() for tf in timeframes if str(tf).strip()]
    timeframe_field = lower_to_actual.get("timeframe")
    year_field = lower_to_actual.get("year")

    if requested_timeframes and timeframe_field:
        filter_expr = ds.field(timeframe_field).isin(requested_timeframes)

    if year_field:
        if year_min is not None:
            expr = ds.field(year_field) >= int(year_min)
            filter_expr = expr if filter_expr is None else (filter_expr & expr)
        if year_max is not None:
            expr = ds.field(year_field) <= int(year_max)
            filter_expr = expr if filter_expr is None else (filter_expr & expr)

    scanner = dataset.scanner(
        columns=selected_columns,
        filter=filter_expr,
        batch_size=int(max(1, batch_size)),
        use_threads=True,
    )

    for record_batch in scanner.to_batches():
        frame = record_batch.to_pandas()
        if not frame.empty:
            yield frame
