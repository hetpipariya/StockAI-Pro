"""Tests for the multi-timeframe alignment engine."""

import numpy as np
import pandas as pd

import app.inference.multi_timeframe_alignment as mtf_mod


def _sample_ohlcv(rows: int = 300) -> pd.DataFrame:
    close = np.linspace(100.0, 102.0, rows)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": np.full(rows, 1000.0),
        }
    )


def test_mtf_alignment_fallback_for_missing_input():
    result = mtf_mod.compute_multi_timeframe_alignment(None)

    assert result["mtf_alignment"] == "MISSING"
    assert result["mtf_score"] == 0.0
    assert result["conflict"] is True
    assert result["htf_confirmed"] is False
    assert result["ltf_entry_confirmed"] is False


def test_mtf_alignment_strong_when_all_timeframes_bullish(monkeypatch):
    outputs = iter(
        [
            ("BULLISH", 0.95),
            ("BULLISH", 0.90),
            ("BULLISH", 0.88),
            ("BULLISH", 0.92),
        ]
    )

    def _mock_classify_tf_direction(*_args, **_kwargs):
        return next(outputs)

    monkeypatch.setattr(mtf_mod, "_classify_tf_direction", _mock_classify_tf_direction)

    result = mtf_mod.compute_multi_timeframe_alignment(_sample_ohlcv())

    assert result["mtf_alignment"] == "STRONG"
    assert result["direction"] == "BULLISH"
    assert result["htf_confirmed"] is True
    assert result["ltf_entry_confirmed"] is True
    assert result["conflict"] is False
    assert result["mtf_score"] >= 0.9


def test_mtf_alignment_conflict_for_mixed_timeframes(monkeypatch):
    outputs = iter(
        [
            ("BULLISH", 0.80),
            ("BEARISH", 0.75),
            ("BULLISH", 0.70),
            ("BEARISH", 0.65),
        ]
    )

    def _mock_classify_tf_direction(*_args, **_kwargs):
        return next(outputs)

    monkeypatch.setattr(mtf_mod, "_classify_tf_direction", _mock_classify_tf_direction)

    result = mtf_mod.compute_multi_timeframe_alignment(_sample_ohlcv())

    assert result["mtf_alignment"] == "CONFLICTING"
    assert result["direction"] == "MIXED"
    assert result["conflict"] is True
    assert result["mtf_score"] <= 0.35
