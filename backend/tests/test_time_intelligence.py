"""Tests for the Time Intelligence Engine."""

from __future__ import annotations

import pandas as pd

from app.inference.time_intelligence import compute_time_intelligence


def _frame(ts: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [ts] * 60,
            "open": [100.0] * 60,
            "high": [101.0] * 60,
            "low": [99.0] * 60,
            "close": [100.5] * 60,
            "volume": [1000] * 60,
        }
    )


def test_classifies_open_session_and_opening_spike_bucket():
    info = compute_time_intelligence(_frame("2026-04-01T09:20:00+05:30"))

    assert info["session"] == "OPEN"
    assert info["time_bucket"] == "OPENING_SPIKE"
    assert info["day_of_week"] == 2
    assert info["expiry_flag"] is False
    assert 0 <= info["time_score"] <= 1


def test_classifies_mid_session_sideways_bucket():
    info = compute_time_intelligence(_frame("2026-04-01T11:45:00+05:30"))

    assert info["session"] == "MID"
    assert info["time_bucket"] == "SIDEWAYS"
    assert info["time_bias"] in {"LOW_VOLATILITY", "NEUTRAL"}


def test_classifies_close_session_breakout_bucket():
    info = compute_time_intelligence(_frame("2026-04-01T15:05:00+05:30"))

    assert info["session"] == "CLOSE"
    assert info["time_bucket"] == "BREAKOUT_REVERSAL"
    assert info["trade_mode"] == "TREND_CONTINUATION"


def test_detects_weekly_and_monthly_expiry():
    weekly = compute_time_intelligence(_frame("2026-04-23T14:45:00+05:30"))
    monthly = compute_time_intelligence(_frame("2026-04-30T14:45:00+05:30"))

    assert weekly["expiry_flag"] is True
    assert weekly["expiry_type"] == "WEEKLY"

    assert monthly["expiry_flag"] is True
    assert monthly["expiry_type"] == "MONTHLY"


def test_time_output_contract_keys_present():
    info = compute_time_intelligence(_frame("2026-04-01T10:10:00+05:30"))

    required = {
        "session",
        "time_bucket",
        "day_of_week",
        "day_bias_score",
        "expiry_flag",
        "time_score",
        "time_bias",
    }
    assert required.issubset(set(info.keys()))
