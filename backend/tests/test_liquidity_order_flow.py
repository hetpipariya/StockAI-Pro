"""Tests for Liquidity & Order Flow Proxy Engine."""

from __future__ import annotations

import pandas as pd

from app.inference.liquidity_order_flow import compute_liquidity_order_flow


def _base_frame(rows: int = 60) -> pd.DataFrame:
    data = {
        "open": [100.0 + (i * 0.05) for i in range(rows)],
        "high": [100.4 + (i * 0.05) for i in range(rows)],
        "low": [99.6 + (i * 0.05) for i in range(rows)],
        "close": [100.1 + (i * 0.05) for i in range(rows)],
        "volume": [1500 + (i * 10) for i in range(rows)],
    }
    return pd.DataFrame(data)


def test_liquidity_output_contract_and_bounds():
    result = compute_liquidity_order_flow(_base_frame())

    required = {
        "liquidity_score",
        "price_impact",
        "jump_flag",
        "gap_flag",
        "liquidity_sweep",
        "sweep_type",
        "flow_state",
    }
    assert required.issubset(result.keys())
    assert 0 <= result["liquidity_score"] <= 1


def test_jump_flag_detects_sudden_price_change():
    frame = _base_frame()
    frame.loc[len(frame) - 2, "close"] = 100.0
    frame.loc[len(frame) - 1, "close"] = 102.3  # 2.3% jump
    frame.loc[len(frame) - 1, "high"] = 102.6
    frame.loc[len(frame) - 1, "low"] = 100.8
    frame.loc[len(frame) - 1, "volume"] = 4000

    result = compute_liquidity_order_flow(frame)

    assert result["jump_flag"] is True


def test_gap_up_continuation_classifies_breakout():
    day1 = pd.date_range("2026-04-01 09:15:00", periods=20, freq="15min")
    day2 = pd.date_range("2026-04-02 09:15:00", periods=20, freq="15min")

    day1_frame = pd.DataFrame(
        {
            "time": day1,
            "open": [99.5 + i * 0.02 for i in range(20)],
            "high": [100.0 + i * 0.02 for i in range(20)],
            "low": [99.2 + i * 0.02 for i in range(20)],
            "close": [99.8 + i * 0.02 for i in range(20)],
            "volume": [1400 + i * 8 for i in range(20)],
        }
    )
    day2_frame = pd.DataFrame(
        {
            "time": day2,
            "open": [103.0 + i * 0.03 for i in range(20)],
            "high": [103.4 + i * 0.03 for i in range(20)],
            "low": [102.6 + i * 0.03 for i in range(20)],
            "close": [103.2 + i * 0.05 for i in range(20)],
            "volume": [1900 + i * 12 for i in range(20)],
        }
    )

    frame = pd.concat([day1_frame, day2_frame], ignore_index=True)
    result = compute_liquidity_order_flow(frame)

    assert result["gap_flag"] == "GAP_UP"
    assert result["gap_continuation"] is True


def test_gap_rejection_classifies_trap():
    day1 = pd.date_range("2026-04-01 09:15:00", periods=20, freq="15min")
    day2 = pd.date_range("2026-04-02 09:15:00", periods=20, freq="15min")

    day1_frame = pd.DataFrame(
        {
            "time": day1,
            "open": [99.5 + i * 0.02 for i in range(20)],
            "high": [100.0 + i * 0.02 for i in range(20)],
            "low": [99.2 + i * 0.02 for i in range(20)],
            "close": [99.8 + i * 0.02 for i in range(20)],
            "volume": [1400 + i * 8 for i in range(20)],
        }
    )
    day2_frame = pd.DataFrame(
        {
            "time": day2,
            "open": [103.0 - i * 0.05 for i in range(20)],
            "high": [103.4 - i * 0.05 for i in range(20)],
            "low": [98.8 - i * 0.02 for i in range(20)],
            "close": [100.2 - i * 0.07 for i in range(20)],
            "volume": [1700 + i * 6 for i in range(20)],
        }
    )

    frame = pd.concat([day1_frame, day2_frame], ignore_index=True)
    result = compute_liquidity_order_flow(frame)

    assert result["gap_flag"] == "GAP_UP"
    assert result["gap_rejection"] is True
    assert result["flow_state"] == "TRAP"


def test_liquidity_sweep_detects_long_wick_reversal():
    frame = _base_frame(rows=50)

    # Keep prior lows above 99 and force a stop-hunt style lower wick on the last candle.
    frame.loc[45:48, "low"] = [99.6, 99.7, 99.5, 99.8]
    frame.loc[49, "open"] = 100.0
    frame.loc[49, "high"] = 101.3
    frame.loc[49, "low"] = 97.4
    frame.loc[49, "close"] = 101.0
    frame.loc[49, "volume"] = 3200

    result = compute_liquidity_order_flow(frame)

    assert result["liquidity_sweep"] is True
    assert result["sweep_type"] == "BULLISH_SWEEP"
