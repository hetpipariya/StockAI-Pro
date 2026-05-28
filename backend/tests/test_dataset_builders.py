"""Tests for the dataset builder training scaffolds."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.dataset_builders import (
    build_entry_5m_dataset,
    build_entry_5m_training_dataset,
)
from app.inference.feature_engineering import FEATURE_COLUMNS


def make_raw_5m_csv(tmp_path: Path, rows: int = 100) -> Path:
    timestamps = pd.date_range("2026-03-01 09:15", periods=rows, freq="5min", tz="UTC")
    symbol = "NIFTY"  # symbol is case-insensitive in loader normalization
    prices = np.linspace(18000.0, 18200.0, rows)
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * rows,
            "open": prices * 0.999,
            "high": prices * 1.001,
            "low": prices * 0.998,
            "close": prices,
            "volume": np.arange(1000, 1000 + rows, dtype=int),
        }
    )
    csv_path = tmp_path / "nifty_5m.csv"
    frame.to_csv(csv_path, index=False)
    return csv_path


def test_build_entry_5m_dataset_writes_output(tmp_path: Path):
    raw_folder = tmp_path / "raw"
    raw_folder.mkdir()
    source_csv = make_raw_5m_csv(raw_folder)

    output_csv = tmp_path / "entry_5m_features.csv"
    result = build_entry_5m_dataset(
        raw_folder=raw_folder,
        output_path=output_csv,
        nifty_daily_path=None,
        min_rows_per_symbol=100,
    )

    assert output_csv.exists()
    assert not result.empty
    assert all(column in result.columns for column in FEATURE_COLUMNS)
    assert (result["symbol"].unique() == ["NIFTY"]).all() if "symbol" in result.columns else True
    assert output_csv.read_text(encoding="utf-8")


def test_build_entry_5m_training_dataset_attaches_labels(tmp_path: Path):
    raw_folder = tmp_path / "raw"
    raw_folder.mkdir()
    source_csv = make_raw_5m_csv(raw_folder)

    output_csv = tmp_path / "entry_5m_training.csv"
    result = build_entry_5m_training_dataset(
        raw_folder=raw_folder,
        output_path=output_csv,
        nifty_daily_path=None,
        horizon=3,
        min_rows_per_symbol=100,
    )

    assert output_csv.exists()
    assert not result.empty
    assert "label" in result.columns
    assert set(result["label"].unique()).issubset({-1, 0, 1})
    assert all(column in result.columns for column in FEATURE_COLUMNS)
    assert pd.api.types.is_datetime64_any_dtype(result["timestamp"])
    assert result["timestamp"].dt.tz is not None
