"""Tests for volume_intelligence feature module."""

import pandas as pd

from app.inference.feature_engineering import compute_features
from app.inference.volume_intelligence import (build_enhanced_feature_vector,
                                               build_feature_vector)


def test_build_feature_vector_adds_volume_features(mock_ohlcv_df):
    base = compute_features(mock_ohlcv_df, include_legacy=True)
    merged = build_feature_vector(mock_ohlcv_df, base_features=base)

    required = [
        "volume_ratio",
        "volume_ratio_flag",
        "volume_spike",
        "volume_spike_strength",
        "vwap",
        "vwap_deviation",
        "obv",
        "obv_slope",
        "obv_divergence",
        "volume_trend_slope",
        "volume_trend_direction",
    ]
    for col in required:
        assert col in merged.columns

    assert len(merged) == len(mock_ohlcv_df)


def test_build_feature_vector_handles_missing_columns_gracefully(mock_ohlcv_df):
    base = compute_features(mock_ohlcv_df, include_legacy=True)
    incomplete = mock_ohlcv_df.drop(columns=["volume"])

    merged = build_feature_vector(incomplete, base_features=base)

    assert not merged.empty
    assert "volume_ratio" not in merged.columns


def test_volume_ratio_flag_high_when_participation_spikes():
    rows = 80
    df = pd.DataFrame(
        {
            "open": [100 + i * 0.2 for i in range(rows)],
            "high": [100.4 + i * 0.2 for i in range(rows)],
            "low": [99.8 + i * 0.2 for i in range(rows)],
            "close": [100.2 + i * 0.2 for i in range(rows)],
            "volume": [1000] * (rows - 1) + [4000],
        }
    )

    merged = build_feature_vector(df)

    assert float(merged.iloc[-1]["volume_ratio"]) > 1.5
    assert merged.iloc[-1]["volume_ratio_flag"] == "HIGH"


def test_volume_spike_flag_detects_large_burst():
    rows = 80
    df = pd.DataFrame(
        {
            "open": [200 + i * 0.1 for i in range(rows)],
            "high": [200.2 + i * 0.1 for i in range(rows)],
            "low": [199.7 + i * 0.1 for i in range(rows)],
            "close": [200.0 + i * 0.1 for i in range(rows)],
            "volume": [1500] * (rows - 2) + [1600, 6000],
        }
    )

    merged = build_feature_vector(df)

    assert int(merged.iloc[-1]["volume_spike"]) == 1
    assert float(merged.iloc[-1]["volume_spike_strength"]) >= 1.0


def test_enhanced_feature_vector_contains_required_derived_columns(mock_ohlcv_df):
    base = compute_features(mock_ohlcv_df, include_legacy=True)
    enhanced = build_enhanced_feature_vector(mock_ohlcv_df, base_features=base)

    required = [
        "ema_rsi",
        "macd_volume",
        "rolling_mean_20",
        "rolling_std_20",
        "ema_rsi_smoothed",
        "macd_volume_smoothed",
        "ema_rsi_norm",
        "macd_volume_norm",
        "ema_rsi_z",
        "macd_volume_z",
    ]
    for col in required:
        assert col in enhanced.columns


def test_enhanced_feature_vector_normalized_columns_are_bounded(mock_ohlcv_df):
    base = compute_features(mock_ohlcv_df, include_legacy=True)
    enhanced = build_enhanced_feature_vector(mock_ohlcv_df, base_features=base)

    norm_cols = [col for col in enhanced.columns if col.endswith("_norm")]
    assert len(norm_cols) > 0

    for col in norm_cols:
        assert (enhanced[col] >= 0).all()
        assert (enhanced[col] <= 1).all()


def test_enhanced_feature_vector_zscore_columns_are_finite(mock_ohlcv_df):
    base = compute_features(mock_ohlcv_df, include_legacy=True)
    enhanced = build_enhanced_feature_vector(mock_ohlcv_df, base_features=base)

    z_cols = [col for col in enhanced.columns if col.endswith("_z")]
    assert len(z_cols) > 0
    assert enhanced[z_cols].isna().sum().sum() == 0


def test_smoothing_reduces_ema_rsi_noise_on_volatile_series():
    rows = 120
    close = [100 + ((-1) ** i) * (i % 7) * 0.8 + (i * 0.04) for i in range(rows)]
    df = pd.DataFrame(
        {
            "open": [c - 0.6 for c in close],
            "high": [c + 1.0 for c in close],
            "low": [c - 1.0 for c in close],
            "close": close,
            "volume": [1000 + (i % 9) * 120 for i in range(rows)],
        }
    )

    base = compute_features(df, include_legacy=True)
    enhanced = build_enhanced_feature_vector(df, base_features=base)

    raw_noise = float(enhanced["ema_rsi"].diff().abs().mean())
    smooth_noise = float(enhanced["ema_rsi_smoothed"].diff().abs().mean())

    assert smooth_noise <= raw_noise
