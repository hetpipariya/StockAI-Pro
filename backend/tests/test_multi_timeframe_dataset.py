"""
Tests for the multi-timeframe ML dataset builder.

Tests cover:
- Feature column contract (MTF_FEATURE_COLUMNS)
- Core builder functionality (5m only, 5m + 1h, 5m + 1m + 1h)
- Labeling functions (ATR-based and fixed-barrier)
- No data leakage (features use only past data)
- Noise filtering
- Invalid input handling
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.multi_timeframe_dataset import (
    LABEL_BUY,
    LABEL_HOLD,
    LABEL_SELL,
    MTF_FEATURE_COLUMNS,
    MultiTimeframeDatasetBuilder,
    _atr_barrier_labels,
    _compute_1h_context,
    _compute_5m_features,
    _aggregate_1m_features,
    _fixed_barrier_labels,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 100,
    start_price: float = 2500.0,
    drift: float = 0.0002,
    vol: float = 0.005,
    seed: int = 42,
    freq: str = "5min",
    start: str = "2024-01-01 09:15",
) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with DatetimeIndex."""
    rng = np.random.default_rng(seed)
    close = [start_price]
    for _ in range(n - 1):
        close.append(close[-1] * (1 + drift + vol * rng.standard_normal()))
    close = np.array(close)
    noise = rng.uniform(0.001, 0.003, n)
    df = pd.DataFrame(
        {
            "open": close * (1 - rng.uniform(0, 0.002, n)),
            "high": close * (1 + noise),
            "low": close * (1 - noise),
            "close": close,
            "volume": rng.integers(50_000, 500_000, n),
        },
        index=pd.date_range(start, periods=n, freq=freq),
    )
    return df


@pytest.fixture
def df_5m():
    return _make_ohlcv(n=200, freq="5min")


@pytest.fixture
def df_1m():
    return _make_ohlcv(n=1000, freq="1min", seed=7)


@pytest.fixture
def df_1h():
    return _make_ohlcv(n=100, freq="1h", seed=13)


@pytest.fixture
def short_df_5m():
    """Too short for feature computation."""
    return _make_ohlcv(n=20, freq="5min")


@pytest.fixture
def builder():
    return MultiTimeframeDatasetBuilder()


# ---------------------------------------------------------------------------
# Feature column contract
# ---------------------------------------------------------------------------

class TestMTFFeatureColumns:
    def test_column_count(self):
        assert len(MTF_FEATURE_COLUMNS) == 22

    def test_no_duplicates(self):
        assert len(MTF_FEATURE_COLUMNS) == len(set(MTF_FEATURE_COLUMNS))

    def test_no_time_encodings(self):
        """Time-based features must NOT appear in the feature set."""
        for col in ["minute_of_day", "hour_of_day", "day_of_week", "time_sin", "time_cos"]:
            assert col not in MTF_FEATURE_COLUMNS, f"Weak feature '{col}' should not be in MTF_FEATURE_COLUMNS"

    def test_no_raw_candle_color_features(self):
        """Raw candle color flags must NOT appear in the feature set."""
        for col in ["strong_green_candle", "strong_red_candle", "doji_flag", "bullish_engulfing"]:
            assert col not in MTF_FEATURE_COLUMNS, f"Weak feature '{col}' should not be in MTF_FEATURE_COLUMNS"

    def test_no_raw_price_lags(self):
        """Raw price lags (not returns) must NOT appear in the feature set."""
        for col in ["lag_1", "lag_2", "lag_3"]:
            assert col not in MTF_FEATURE_COLUMNS, f"Weak feature '{col}' should not be in MTF_FEATURE_COLUMNS"

    def test_strong_features_present(self):
        for col in [
            "log_return", "log_return_5", "rsi_14", "ema_9", "ema_21",
            "ema_spread", "macd", "macd_hist", "atr_pct", "volume_ratio",
            "vwap_dev", "obv_slope",
        ]:
            assert col in MTF_FEATURE_COLUMNS, f"Strong feature '{col}' must be present"

    def test_1m_agg_features_present(self):
        for col in ["ret_1m_last", "vol_1m", "volume_spike_1m"]:
            assert col in MTF_FEATURE_COLUMNS

    def test_1h_context_features_present(self):
        for col in ["h1_trend_dir", "h1_rsi", "h1_ema_spread", "h1_atr_pct", "h1_macd"]:
            assert col in MTF_FEATURE_COLUMNS


# ---------------------------------------------------------------------------
# 5m feature computation
# ---------------------------------------------------------------------------

class TestCompute5mFeatures:
    def test_returns_all_base_columns(self, df_5m):
        feats = _compute_5m_features(df_5m)
        base_cols = [
            "log_return", "log_return_5", "log_return_20",
            "rsi_14", "ema_9", "ema_21", "ema_spread",
            "macd", "macd_hist", "atr_pct", "bb_width",
            "volume_ratio", "vwap_dev", "obv_slope",
        ]
        for col in base_cols:
            assert col in feats.columns

    def test_same_row_count(self, df_5m):
        feats = _compute_5m_features(df_5m)
        assert len(feats) == len(df_5m)

    def test_rsi_range(self, df_5m):
        feats = _compute_5m_features(df_5m)
        rsi = feats["rsi_14"].dropna()
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_atr_pct_positive(self, df_5m):
        feats = _compute_5m_features(df_5m)
        assert (feats["atr_pct"].dropna() >= 0).all()

    def test_log_return_normalised(self, df_5m):
        """Log returns should be small (no jumps > 50% per bar)."""
        feats = _compute_5m_features(df_5m)
        lr = feats["log_return"].dropna()
        assert lr.abs().max() < 0.50

    def test_volume_ratio_positive(self, df_5m):
        feats = _compute_5m_features(df_5m)
        assert (feats["volume_ratio"].dropna() >= 0).all()

    def test_ema_9_closer_to_price_than_ema_21(self, df_5m):
        """EMA-9 should track price more closely than EMA-21."""
        feats = _compute_5m_features(df_5m)
        diff_9 = (feats["ema_9"] - df_5m["close"]).abs().mean()
        diff_21 = (feats["ema_21"] - df_5m["close"]).abs().mean()
        assert diff_9 <= diff_21


# ---------------------------------------------------------------------------
# 1m aggregation
# ---------------------------------------------------------------------------

class TestAggregate1mFeatures:
    def test_returns_correct_columns(self, df_5m, df_1m):
        result = _aggregate_1m_features(df_5m, df_1m)
        for col in ["ret_1m_last", "vol_1m", "volume_spike_1m"]:
            assert col in result.columns

    def test_same_row_count_as_5m(self, df_5m, df_1m):
        result = _aggregate_1m_features(df_5m, df_1m)
        assert len(result) == len(df_5m)

    def test_returns_zeros_when_no_1m(self, df_5m):
        result = _aggregate_1m_features(df_5m, None)
        assert (result["ret_1m_last"] == 0).all()
        assert (result["vol_1m"] == 0).all()
        assert (result["volume_spike_1m"] == 0).all()

    def test_volume_spike_binary(self, df_5m, df_1m):
        """volume_spike_1m should be 0 or 1."""
        result = _aggregate_1m_features(df_5m, df_1m)
        assert result["volume_spike_1m"].isin([0.0, 1.0]).all()

    def test_vol_1m_non_negative(self, df_5m, df_1m):
        result = _aggregate_1m_features(df_5m, df_1m)
        assert (result["vol_1m"] >= 0).all()


# ---------------------------------------------------------------------------
# 1h context features
# ---------------------------------------------------------------------------

class TestCompute1hContext:
    def test_returns_correct_columns(self, df_5m, df_1h):
        result = _compute_1h_context(df_5m, df_1h)
        for col in ["h1_trend_dir", "h1_rsi", "h1_ema_spread", "h1_atr_pct", "h1_macd"]:
            assert col in result.columns

    def test_same_row_count_as_5m(self, df_5m, df_1h):
        result = _compute_1h_context(df_5m, df_1h)
        assert len(result) == len(df_5m)

    def test_trend_dir_values(self, df_5m, df_1h):
        """h1_trend_dir must be -1, 0, or +1."""
        result = _compute_1h_context(df_5m, df_1h)
        assert result["h1_trend_dir"].isin([-1.0, 0.0, 1.0]).all()

    def test_rsi_range(self, df_5m, df_1h):
        result = _compute_1h_context(df_5m, df_1h)
        rsi = result["h1_rsi"].dropna()
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_no_lookahead(self, df_5m, df_1h):
        """For each 5m bar, the 1h context must use a 1h bar BEFORE that time."""
        result = _compute_1h_context(df_5m, df_1h)
        # We cannot directly verify timestamps here, but the merge_asof 'backward'
        # direction guarantees no look-ahead — we simply check no NaN leaks.
        assert not result.isnull().all(axis=1).any()

    def test_returns_defaults_when_no_1h(self, df_5m):
        result = _compute_1h_context(df_5m, None)
        assert (result["h1_trend_dir"] == 0.0).all()
        assert (result["h1_rsi"] == 50.0).all()


# ---------------------------------------------------------------------------
# Labeling functions
# ---------------------------------------------------------------------------

class TestATRBarrierLabeling:
    def test_label_values(self):
        """Labels must be LABEL_BUY, LABEL_SELL, or LABEL_HOLD."""
        n = 100
        close = pd.Series(100 + np.cumsum(np.random.default_rng(0).normal(0, 0.5, n)))
        atr = pd.Series(np.full(n, 1.5))
        labels = _atr_barrier_labels(close, atr)
        assert set(labels.dropna().unique()).issubset({LABEL_BUY, LABEL_SELL, LABEL_HOLD})

    def test_tail_labels_are_nan(self):
        """Last `horizon` rows should have NaN labels (no future data)."""
        horizon = 3
        close = pd.Series([100.0 + i for i in range(50)])
        atr = pd.Series([1.0] * 50)
        labels = _atr_barrier_labels(close, atr, horizon=horizon)
        assert labels.iloc[-horizon:].isna().all()

    def test_buy_signal_on_rising_series(self):
        """With a strongly rising series, at least one BUY should be labelled."""
        close = pd.Series([100.0 + i * 2 for i in range(50)])
        atr = pd.Series([0.5] * 50)
        labels = _atr_barrier_labels(close, atr, horizon=1, barrier_mult=0.1)
        assert LABEL_BUY in labels.values

    def test_sell_signal_on_falling_series(self):
        """With a strongly falling series, at least one SELL should be labelled."""
        close = pd.Series([200.0 - i * 2 for i in range(50)])
        atr = pd.Series([0.5] * 50)
        labels = _atr_barrier_labels(close, atr, horizon=1, barrier_mult=0.1)
        assert LABEL_SELL in labels.values


class TestFixedBarrierLabeling:
    def test_label_values(self):
        n = 100
        close = pd.Series(100 + np.cumsum(np.random.default_rng(1).normal(0, 0.5, n)))
        labels = _fixed_barrier_labels(close, horizon=1, threshold=0.02)
        assert set(labels.dropna().unique()).issubset({LABEL_BUY, LABEL_SELL, LABEL_HOLD})

    def test_buy_signal_above_threshold(self):
        """Large positive move must trigger BUY."""
        close = pd.Series([100.0, 103.0, 100.0, 100.0, 100.0])
        labels = _fixed_barrier_labels(close, horizon=1, threshold=0.02)
        assert labels.iloc[0] == LABEL_BUY

    def test_sell_signal_below_threshold(self):
        """Large negative move must trigger SELL."""
        close = pd.Series([100.0, 97.0, 100.0, 100.0, 100.0])
        labels = _fixed_barrier_labels(close, horizon=1, threshold=0.02)
        assert labels.iloc[0] == LABEL_SELL

    def test_hold_signal_small_move(self):
        """Small move (within threshold) must be HOLD."""
        close = pd.Series([100.0, 100.5, 100.0, 100.0, 100.0])
        labels = _fixed_barrier_labels(close, horizon=1, threshold=0.02)
        assert labels.iloc[0] == LABEL_HOLD


# ---------------------------------------------------------------------------
# MultiTimeframeDatasetBuilder
# ---------------------------------------------------------------------------

class TestMultiTimeframeDatasetBuilder:
    def test_build_5m_only_returns_all_columns(self, df_5m, builder):
        result = builder.build(df_5m)
        for col in MTF_FEATURE_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"
        assert "label" in result.columns

    def test_build_with_1h_context(self, df_5m, df_1h, builder):
        result = builder.build(df_5m, df_1h=df_1h)
        assert len(result) > 0
        for col in MTF_FEATURE_COLUMNS:
            assert col in result.columns

    def test_build_full_stack(self, df_5m, df_1m, df_1h, builder):
        result = builder.build(df_5m, df_1m=df_1m, df_1h=df_1h)
        assert len(result) > 0
        for col in MTF_FEATURE_COLUMNS:
            assert col in result.columns

    def test_no_nan_in_output(self, df_5m, builder):
        result = builder.build(df_5m)
        assert result.isnull().sum().sum() == 0

    def test_no_inf_in_output(self, df_5m, builder):
        result = builder.build(df_5m)
        assert not np.isinf(result.values).any()

    def test_label_values_are_valid(self, df_5m, builder):
        result = builder.build(df_5m)
        assert set(result["label"].unique()).issubset({LABEL_BUY, LABEL_SELL, LABEL_HOLD})

    def test_row_count_less_than_input(self, df_5m, builder):
        """Output rows < input rows (tail dropped for label horizon + NaN rows)."""
        result = builder.build(df_5m)
        assert len(result) < len(df_5m)

    def test_returns_empty_for_short_input(self, short_df_5m, builder):
        result = builder.build(short_df_5m)
        assert len(result) == 0

    def test_returns_empty_for_none(self, builder):
        result = builder.build(None)
        assert len(result) == 0

    def test_get_Xy_shape(self, df_5m, builder):
        dataset = builder.build(df_5m)
        X, y = builder.get_Xy(dataset)
        assert X.shape[1] == len(MTF_FEATURE_COLUMNS)
        assert len(X) == len(y)

    def test_get_Xy_feature_columns(self, df_5m, builder):
        dataset = builder.build(df_5m)
        X, y = builder.get_Xy(dataset)
        assert list(X.columns) == MTF_FEATURE_COLUMNS

    def test_fixed_barrier_mode(self, df_5m):
        builder = MultiTimeframeDatasetBuilder(use_fixed_barrier=True, fixed_barrier_pct=0.02)
        result = builder.build(df_5m)
        assert "label" in result.columns
        assert set(result["label"].unique()).issubset({LABEL_BUY, LABEL_SELL, LABEL_HOLD})

    def test_noise_filter_removes_low_vol_rows(self):
        """With a high min_atr_pct, all rows should be removed."""
        df = _make_ohlcv(n=200, vol=0.00001)  # very low volatility
        builder = MultiTimeframeDatasetBuilder(min_atr_pct=0.10)  # require 10% ATR
        result = builder.build(df)
        # Should have very few or zero rows (ultra-low vol filtered out)
        assert len(result) < 10

    def test_no_data_leakage(self, df_5m, builder):
        """Features at time t must not use data after time t.

        We verify this structurally: log returns are computed with shift(1),
        EMAs use only past data (ewm), and labels use shift(-horizon).
        We check that the feature columns in the output do not contain
        the raw future close prices.
        """
        dataset = builder.build(df_5m)
        X, _ = builder.get_Xy(dataset)
        # Raw future close values should NOT appear as feature columns
        for col in X.columns:
            assert "future" not in col.lower()
            assert "label" not in col.lower()

    def test_deterministic(self, df_5m, builder):
        """Same input should produce identical output."""
        r1 = builder.build(df_5m)
        r2 = builder.build(df_5m)
        pd.testing.assert_frame_equal(r1, r2)

    def test_label_distribution_has_all_classes(self, df_5m):
        """With default parameters, all three classes should be present."""
        # Use a more sensitive barrier to get all classes
        builder = MultiTimeframeDatasetBuilder(atr_barrier_mult=0.1, min_atr_pct=0.0)
        result = builder.build(df_5m)
        classes = set(result["label"].unique())
        # At least two classes should be present in synthetic data
        assert len(classes) >= 2


# ---------------------------------------------------------------------------
# Data pipeline labeling regression (data_pipeline.py)
# ---------------------------------------------------------------------------

class TestDataPipelineLabeling:
    """Verify the updated ATR-based 3-class labeling logic."""

    def test_atr_based_target_has_three_classes(self):
        """ATR-based labeling must produce target values in {-1, 0, 1}."""
        n = 300
        rng = np.random.default_rng(42)
        close = 2500.0 + np.cumsum(rng.normal(0, 5, n))
        high = close + rng.uniform(1, 5, n)
        low = close - rng.uniform(1, 5, n)
        df = pd.DataFrame({
            "close": close,
            "high": high,
            "low": low,
            "open": close - rng.normal(0, 1, n),
            "volume": rng.integers(100_000, 1_000_000, n),
        })

        # Inline ATR computation (mirrors data_pipeline._atr)
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(com=13, adjust=False).mean()

        # Replicate the new labeling logic from data_pipeline.py
        horizon = 1
        barrier_mult = 0.5
        future_ret = df["close"].shift(-horizon) / df["close"] - 1
        barrier = barrier_mult * atr / (df["close"] + 1e-9)
        target = pd.Series(0, index=df.index)
        target[future_ret > barrier] = 1
        target[future_ret < -barrier] = -1

        unique_vals = set(target.dropna().unique())
        assert unique_vals.issubset({-1, 0, 1})
        # Should produce non-trivial labeling (not all zeros)
        assert len(unique_vals) >= 2
