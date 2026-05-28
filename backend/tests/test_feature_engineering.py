"""Tests for the canonical 20-feature C++ bridge."""

from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.feature_engineering import (  # noqa: E402
    EXPECTED_FEATURE_COUNT,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    align_feature_frame,
    build_canonical_nifty_daily_dataset,
    compute_features,
    get_feature_summary,
    validate_feature_contract,
    validate_features,
)


EXPECTED_COLUMNS = [
    "ema9",
    "ema21",
    "ema50",
    "ema_ratio",
    "linreg_slope",
    "rsi14",
    "macd_hist",
    "roc10",
    "cci20",
    "vwap_distance",
    "volume_ratio",
    "mfi14",
    "atr14",
    "bb_width",
    "bb_percent_b",
    "adx14",
    "candle_body_ratio",
    "mtf_15m_direction",
    "daily_alignment",
    "nifty_direction",
]


class TestFeatureColumns:
    def test_feature_count(self):
        assert len(FEATURE_COLUMNS) == EXPECTED_FEATURE_COUNT == 20

    def test_feature_names_match_cpp_contract(self):
        assert FEATURE_COLUMNS == EXPECTED_COLUMNS

    def test_no_duplicate_columns(self):
        assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))

    def test_feature_version_exists(self):
        assert isinstance(FEATURE_VERSION, str)
        assert FEATURE_VERSION


class TestComputeFeatures:
    def test_returns_canonical_columns(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert list(result.columns) == FEATURE_COLUMNS

    def test_returns_expected_row_count(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert 0 < len(result) <= len(mock_ohlcv_df) - 49

    def test_too_short_returns_empty(self, short_ohlcv_df):
        result = compute_features(short_ohlcv_df)
        assert result.empty
        assert list(result.columns) == FEATURE_COLUMNS

    def test_none_returns_empty(self):
        result = compute_features(None)
        assert result.empty
        assert list(result.columns) == FEATURE_COLUMNS

    def test_no_nan_in_output(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert int(result.isna().sum().sum()) == 0

    def test_no_inf_in_output(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert not np.isinf(result.to_numpy(dtype=float)).any()

    def test_handles_string_prices(self):
        n = 60
        df = pd.DataFrame(
            {
                "open": [str(100 + i * 0.1) for i in range(n)],
                "high": [str(101 + i * 0.1) for i in range(n)],
                "low": [str(99 + i * 0.1) for i in range(n)],
                "close": [str(100.5 + i * 0.1) for i in range(n)],
                "volume": [str(10000)] * n,
            }
        )
        result = compute_features(df)
        assert len(result) == n - 49
        assert result.isna().sum().sum() == 0

    def test_bullish_momentum_reflects_in_trend_fields(self, bullish_ohlcv_df):
        result = compute_features(bullish_ohlcv_df)
        latest = result.iloc[-1]
        assert latest["ema_ratio"] > 1.0
        assert latest["linreg_slope"] > 0.0

    def test_missing_ohlcv_columns_returns_empty(self):
        df = pd.DataFrame({"foo": [1, 2, 3] * 10, "bar": [4, 5, 6] * 10})
        result = compute_features(df)
        assert result.empty
        assert list(result.columns) == FEATURE_COLUMNS

    def test_deterministic(self, mock_ohlcv_df):
        pd.testing.assert_frame_equal(compute_features(mock_ohlcv_df), compute_features(mock_ohlcv_df))


class TestValidateFeatures:
    def test_matching_passes(self):
        validate_features(FEATURE_COLUMNS, FEATURE_COLUMNS, "test")

    def test_missing_column_raises(self):
        with pytest.raises(RuntimeError, match="Missing"):
            validate_features(FEATURE_COLUMNS[:-1], FEATURE_COLUMNS, "test")

    def test_extra_column_raises(self):
        with pytest.raises(RuntimeError, match="Extra"):
            validate_features(FEATURE_COLUMNS + ["extra_col"], FEATURE_COLUMNS, "test")

    def test_wrong_order_raises(self):
        with pytest.raises(RuntimeError, match="Order mismatch"):
            validate_features(list(reversed(FEATURE_COLUMNS)), FEATURE_COLUMNS, "test")

    def test_frame_nan_rows_raise(self):
        frame = pd.DataFrame([[0.0] * len(FEATURE_COLUMNS)], columns=FEATURE_COLUMNS)
        frame.iloc[0, 0] = np.nan
        with pytest.raises(RuntimeError, match="NaN rows"):
            validate_feature_contract(frame, FEATURE_COLUMNS, context="test_frame")


class TestAlignAndSummary:
    def test_align_feature_frame_keeps_order(self):
        shuffled = pd.DataFrame([[1.0] * len(FEATURE_COLUMNS)], columns=list(reversed(FEATURE_COLUMNS)))
        aligned = align_feature_frame(shuffled[list(FEATURE_COLUMNS)], FEATURE_COLUMNS, context="align")
        assert list(aligned.columns) == FEATURE_COLUMNS

    def test_summary_contains_latest_features(self, mock_ohlcv_df):
        features = compute_features(mock_ohlcv_df)
        summary = get_feature_summary(features)
        for column in FEATURE_COLUMNS:
            assert column in summary
            assert isinstance(summary[column], float)
        assert summary["_rows_used"] == len(features)
        assert summary["_feature_version"] == FEATURE_VERSION

    def test_empty_summary_returns_error(self):
        summary = get_feature_summary(pd.DataFrame())
        assert "error" in summary


class TestNiftyDatasetPipeline:
    def test_build_canonical_nifty_daily_dataset_writes_csv(self, tmp_path):
        data = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-03"],
                "open": [100, 101, 101, 102],
                "high": [101, 102, 102, 103],
                "low": [99, 100, 100, 101],
                "close": [100.5, 101.5, 101.5, 102.5],
                "volume": [1000, 1100, 1100, 1200],
            }
        )
        source_file = tmp_path / "nifty_sample.csv"
        data.to_csv(source_file, index=False)
        output_file = tmp_path / "nifty_canonical.csv"

        result = build_canonical_nifty_daily_dataset(
            source=source_file,
            output_path=output_file,
            target_timezone="Asia/Kolkata",
            strict=True,
        )

        assert output_file.exists()
        assert result["timestamp"].dt.tz == ZoneInfo("Asia/Kolkata")
        assert result["timestamp"].iloc[0] < result["timestamp"].iloc[1]
        assert result["timestamp"].nunique() == len(result)
        assert result["close"].tolist() == [100.5, 101.5, 102.5]

    def test_build_canonical_nifty_daily_dataset_rejects_invalid_rows(self, tmp_path):
        data = pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02"],
                "open": [100, -1],
                "high": [101, 102],
                "low": [99, 100],
                "close": [100.5, 101.5],
                "volume": [1000, 1100],
            }
        )
        source_file = tmp_path / "nifty_invalid.csv"
        data.to_csv(source_file, index=False)

        with pytest.raises(RuntimeError, match="invalid OHLCV rows"):
            build_canonical_nifty_daily_dataset(
                source=source_file,
                target_timezone="Asia/Kolkata",
                strict=True,
            )
