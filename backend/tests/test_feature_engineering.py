"""
Tests for the canonical feature engineering module.
Ensures feature computation is deterministic, correct, and aligned.
"""
import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.feature_engineering import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    MIN_ROWS_FOR_FEATURES,
    compute_features,
    validate_features,
    get_feature_summary,
)


class TestFeatureColumns:
    """Test the canonical feature column definitions."""

    def test_feature_count(self):
        assert len(FEATURE_COLUMNS) == 19

    def test_feature_version_exists(self):
        assert FEATURE_VERSION is not None
        assert isinstance(FEATURE_VERSION, str)

    def test_no_duplicate_columns(self):
        assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))

    def test_required_ohlcv_present(self):
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in FEATURE_COLUMNS

    def test_key_indicators_present(self):
        for col in ["ema_20", "ema_50", "rsi_14", "macd", "macd_signal", "vwap"]:
            assert col in FEATURE_COLUMNS


class TestComputeFeatures:
    """Test compute_features() function."""

    def test_returns_correct_columns(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert list(result.columns) == FEATURE_COLUMNS

    def test_returns_correct_column_count(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert result.shape[1] == 19

    def test_row_count_preserved(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert len(result) == len(mock_ohlcv_df)

    def test_too_short_returns_empty(self, short_ohlcv_df):
        result = compute_features(short_ohlcv_df)
        assert len(result) == 0
        assert list(result.columns) == FEATURE_COLUMNS

    def test_none_returns_empty(self):
        result = compute_features(None)
        assert len(result) == 0
        assert list(result.columns) == FEATURE_COLUMNS

    def test_no_nan_in_output(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert result.isna().sum().sum() == 0

    def test_no_inf_in_output(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        assert not np.isinf(result.values).any()

    def test_ema_values_reasonable(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        # EMAs should be close to price
        close_mean = result["close"].mean()
        assert abs(result["ema_20"].mean() - close_mean) < close_mean * 0.1
        assert abs(result["ema_50"].mean() - close_mean) < close_mean * 0.1

    def test_rsi_range(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        # After backfill, RSI should be in reasonable range (may have 0s from fill)
        rsi = result["rsi_14"]
        assert rsi.max() <= 100
        assert rsi.min() >= 0

    def test_missing_columns_returns_empty(self):
        """DataFrame missing required OHLCV columns should return empty."""
        df = pd.DataFrame({"foo": [1, 2, 3] * 10, "bar": [4, 5, 6] * 10})
        result = compute_features(df)
        assert len(result) == 0

    def test_handles_string_prices(self):
        """Should handle string values via pd.to_numeric(errors='coerce')."""
        n = 30
        df = pd.DataFrame({
            "open": [str(100 + i * 0.1) for i in range(n)],
            "high": [str(101 + i * 0.1) for i in range(n)],
            "low": [str(99 + i * 0.1) for i in range(n)],
            "close": [str(100.5 + i * 0.1) for i in range(n)],
            "volume": [str(10000)] * n,
        })
        result = compute_features(df)
        assert len(result) == n
        assert result.isna().sum().sum() == 0

    def test_bullish_trend_strength_positive(self, bullish_ohlcv_df):
        result = compute_features(bullish_ohlcv_df)
        # In a strong uptrend, trend_strength should be positive at the end
        assert result["trend_strength"].iloc[-1] > 0

    def test_deterministic(self, mock_ohlcv_df):
        """Same input should produce identical output."""
        r1 = compute_features(mock_ohlcv_df)
        r2 = compute_features(mock_ohlcv_df)
        pd.testing.assert_frame_equal(r1, r2)


class TestValidateFeatures:
    """Test validate_features() function."""

    def test_matching_passes(self):
        validate_features(FEATURE_COLUMNS, FEATURE_COLUMNS, "test")

    def test_missing_column_raises(self):
        wrong = FEATURE_COLUMNS[:-1]  # Drop last column
        with pytest.raises(RuntimeError, match="Missing"):
            validate_features(wrong, FEATURE_COLUMNS, "test")

    def test_extra_column_raises(self):
        wrong = FEATURE_COLUMNS + ["extra_col"]
        with pytest.raises(RuntimeError, match="Extra"):
            validate_features(wrong, FEATURE_COLUMNS, "test")

    def test_wrong_order_raises(self):
        wrong = list(reversed(FEATURE_COLUMNS))
        with pytest.raises(RuntimeError, match="Order mismatch"):
            validate_features(wrong, FEATURE_COLUMNS, "test")

    def test_completely_different_raises(self):
        wrong = ["a", "b", "c"]
        with pytest.raises(RuntimeError):
            validate_features(wrong, FEATURE_COLUMNS, "test")


class TestGetFeatureSummary:
    """Test get_feature_summary() function."""

    def test_returns_all_features(self, mock_ohlcv_df):
        features = compute_features(mock_ohlcv_df)
        summary = get_feature_summary(features)
        for col in FEATURE_COLUMNS:
            assert col in summary

    def test_empty_returns_error(self):
        summary = get_feature_summary(pd.DataFrame())
        assert "error" in summary

    def test_none_returns_error(self):
        summary = get_feature_summary(None)
        assert "error" in summary

    def test_metadata_present(self, mock_ohlcv_df):
        features = compute_features(mock_ohlcv_df)
        summary = get_feature_summary(features)
        assert "_rows_used" in summary
        assert "_nan_count" in summary
        assert "_inf_count" in summary
        assert "_feature_version" in summary

    def test_values_are_floats(self, mock_ohlcv_df):
        features = compute_features(mock_ohlcv_df)
        summary = get_feature_summary(features)
        for col in FEATURE_COLUMNS:
            assert isinstance(summary[col], float)
