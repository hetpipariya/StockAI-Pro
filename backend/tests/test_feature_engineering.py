"""
Tests for the canonical feature engineering module.
Ensures feature computation is deterministic, correct, and aligned.
"""

from app.inference.feature_engineering import (FEATURE_COLUMNS,
                                               FEATURE_VERSION,
                                               compute_features,
                                               get_feature_summary,
                                               validate_features)
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestFeatureColumns:
    """Test the canonical feature column definitions."""

    def test_feature_count(self):
        assert len(FEATURE_COLUMNS) == 19

    def test_feature_version_exists(self):
        assert FEATURE_VERSION is not None
        assert isinstance(FEATURE_VERSION, str)

    def test_no_duplicate_columns(self):
        assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))

    def test_v20_contract_columns_present(self):
        for col in [
            "price_change",
            "volume_change",
            "rolling_mean_10",
            "ema_12",
            "ema_26",
            "bollinger_upper",
            "bollinger_lower",
            "lag_3",
        ]:
            assert col in FEATURE_COLUMNS

    def test_ohlcv_not_in_feature_vector(self):
        for col in ["open", "high", "low", "close", "volume"]:
            assert col not in FEATURE_COLUMNS

    def test_key_indicators_present(self):
        for col in [
            "rsi",
            "ema_12",
            "ema_26",
            "macd",
            "bollinger_upper",
            "bollinger_lower",
            "volatility",
            "lag_1",
        ]:
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
        close_mean = mock_ohlcv_df["close"].mean()
        assert abs(result["ema_12"].mean() - close_mean) < close_mean * 0.1
        assert abs(result["ema_26"].mean() - close_mean) < close_mean * 0.1

    def test_rsi_range(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df)
        # After backfill, RSI should be in reasonable range (may have 0s from fill)
        rsi = result["rsi"]
        assert rsi.max() <= 100
        assert rsi.min() >= 0

    def test_missing_columns_returns_empty(self):
        """DataFrame missing required OHLCV columns should return empty."""
        df = pd.DataFrame({"foo": [1, 2, 3] * 10, "bar": [4, 5, 6] * 10})
        result = compute_features(df)
        assert len(result) == 0

    def test_handles_string_prices(self):
        """Should handle string values via pd.to_numeric(errors='coerce')."""
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
        assert len(result) == n
        assert result.isna().sum().sum() == 0

    def test_bullish_momentum_positive(self, bullish_ohlcv_df):
        result = compute_features(bullish_ohlcv_df)
        # In a strong uptrend, momentum should be positive at the end.
        assert result["momentum"].iloc[-1] > 0

    def test_include_legacy_aliases(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df, include_legacy=True)
        for col in [
            "ema_50",
            "rsi_14",
            "atr_14",
            "volume_spike",
            "vwap",
            "body_strength_score",
            "upper_wick_pct",
            "lower_wick_pct",
            "bullish_engulfing",
            "bearish_engulfing",
            "doji_flag",
            "consecutive_green",
            "consecutive_red",
            "streak_strength_score",
        ]:
            assert col in result.columns

    def test_price_action_legacy_values_are_bounded(self, mock_ohlcv_df):
        result = compute_features(mock_ohlcv_df, include_legacy=True)

        assert ((result["body_strength_score"] >= 0) & (result["body_strength_score"] <= 1)).all()
        assert ((result["upper_wick_pct"] >= 0) & (result["upper_wick_pct"] <= 1)).all()
        assert ((result["lower_wick_pct"] >= 0) & (result["lower_wick_pct"] <= 1)).all()
        assert ((result["streak_strength_score"] >= 0) & (result["streak_strength_score"] <= 1)).all()

    def test_price_action_legacy_detects_bullish_engulfing(self):
        n = 60
        df = pd.DataFrame(
            {
                "open": [100.0] * n,
                "high": [101.0] * n,
                "low": [99.0] * n,
                "close": [100.2] * n,
                "volume": [10000] * n,
            }
        )

        # Previous candle (bearish, smaller body)
        df.loc[n - 2, "open"] = 101.0
        df.loc[n - 2, "high"] = 101.3
        df.loc[n - 2, "low"] = 99.9
        df.loc[n - 2, "close"] = 100.2

        # Current candle (bullish engulfing)
        df.loc[n - 1, "open"] = 99.9
        df.loc[n - 1, "high"] = 102.4
        df.loc[n - 1, "low"] = 99.8
        df.loc[n - 1, "close"] = 102.1

        result = compute_features(df, include_legacy=True)

        assert int(result["bullish_engulfing"].iloc[-1]) == 1
        assert int(result["bearish_engulfing"].iloc[-1]) == 0

    def test_price_action_legacy_detects_doji(self):
        n = 60
        df = pd.DataFrame(
            {
                "open": [100.0] * n,
                "high": [101.0] * n,
                "low": [99.0] * n,
                "close": [100.2] * n,
                "volume": [10000] * n,
            }
        )

        # Make the final candle a doji: body < 10% of range
        df.loc[n - 1, "open"] = 100.0
        df.loc[n - 1, "high"] = 101.0
        df.loc[n - 1, "low"] = 99.0
        df.loc[n - 1, "close"] = 100.05

        result = compute_features(df, include_legacy=True)

        assert int(result["doji_flag"].iloc[-1]) == 1

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
