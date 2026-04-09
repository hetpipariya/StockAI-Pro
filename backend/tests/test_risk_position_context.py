"""Tests for Risk & Position Context Engine."""

from __future__ import annotations

import pandas as pd

from app.inference.risk_position_context import compute_risk_position_context


def _ohlcv(rows: int = 60) -> pd.DataFrame:
    close = [100.0 + (i * 0.1) for i in range(rows)]
    return pd.DataFrame(
        {
            "open": [c - 0.2 for c in close],
            "high": [c + 1.0 for c in close],
            "low": [c - 1.0 for c in close],
            "close": close,
            "volume": [2000 + (i * 5) for i in range(rows)],
        }
    )


def test_risk_context_output_contract():
    result = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=100.0,
        target_price=106.0,
        capital=100000.0,
        risk_per_trade=0.01,
    )

    assert "stop_loss" in result
    assert "target" in result
    assert "RR" in result
    assert "position_size" in result


def test_atr_stop_distance_formula_for_buy():
    result = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=100.0,
        target_price=106.0,
        capital=100000.0,
        risk_per_trade=0.01,
        atr_multiplier=2.0,
    )

    # With synthetic ATR near 2.0 and multiplier 2.0, stop should be around 96.
    assert abs(result["stop_loss"] - 96.0) < 0.35


def test_rr_ratio_calculation_and_filter_flag():
    pass_case = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=100.0,
        target_price=106.0,
        capital=100000.0,
        risk_per_trade=0.01,
        atr_multiplier=2.0,
    )
    fail_case = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=100.0,
        target_price=103.0,
        capital=100000.0,
        risk_per_trade=0.01,
        atr_multiplier=2.0,
    )

    assert 1.45 <= pass_case["RR"] <= 1.55
    assert pass_case["risk_filter_fail"] is False
    assert fail_case["RR"] < 1.5
    assert fail_case["risk_filter_fail"] is True


def test_position_size_formula_matches_atr_rule():
    result = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=150.0,
        target_price=156.0,
        capital=100000.0,
        risk_per_trade=0.01,
    )

    # Base formula: capital * risk_per_trade / ATR ~= 1000 / 2 = 500 shares.
    assert 480 <= result["position_size"] <= 520


def test_dynamic_position_adjusts_with_volatility_state():
    normal = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=150.0,
        target_price=156.0,
        capital=100000.0,
        risk_per_trade=0.01,
        volatility_state="NORMAL_VOLATILITY",
    )
    high_vol = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=150.0,
        target_price=156.0,
        capital=100000.0,
        risk_per_trade=0.01,
        volatility_state="HIGH_VOLATILITY",
    )
    low_vol = compute_risk_position_context(
        ohlcv_df=_ohlcv(),
        signal="BUY",
        entry_price=150.0,
        target_price=156.0,
        capital=100000.0,
        risk_per_trade=0.01,
        volatility_state="LOW_VOLATILITY",
    )

    assert high_vol["position_size"] < normal["position_size"]
    assert low_vol["position_size"] > normal["position_size"]
