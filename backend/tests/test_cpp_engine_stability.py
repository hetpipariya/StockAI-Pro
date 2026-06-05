"""Stability and stress tests for the native C++ feature engine."""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cpp_engine import compute_features as cpp_compute_features
from app.cpp_engine import is_available


def make_ohlcv_frame(num_bars: int, start_price: float = 100.0, drift: float = 0.001) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01 09:15", periods=num_bars, freq="5min")
    prices = np.linspace(start_price, start_price + drift * num_bars, num_bars, dtype=float)
    highs = prices + 0.1
    lows = prices - 0.1
    opens = prices - 0.02
    closes = prices
    volumes = np.full(num_bars, 10_000.0, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


@pytest.mark.skipif(not is_available(), reason="C++ engine DLL not loadable in this env")
def test_cpp_engine_large_historical_window_returns_safe_features():
    df = make_ohlcv_frame(100_000)
    result = cpp_compute_features(df)

    assert result.shape == (1, 20)
    assert result.isna().sum().sum() == 0
    assert not np.isinf(result.to_numpy(dtype=float)).any()
    assert np.all(np.isfinite(result.to_numpy(dtype=float)))


@pytest.mark.skipif(not is_available(), reason="C++ engine DLL not loadable in this env")
def test_cpp_engine_concurrent_inference_is_deterministic():
    frames = [make_ohlcv_frame(2500, start_price=100.0 + i * 5.0) for i in range(8)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cpp_compute_features, frame) for frame in frames]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    assert len(results) == 8
    for result in results:
        assert result.shape == (1, 20)
        assert result.isna().sum().sum() == 0
        assert not np.isinf(result.to_numpy(dtype=float)).any()


@pytest.mark.skipif(not is_available(), reason="C++ engine DLL not loadable in this env")
def test_cpp_engine_realtime_rolling_window_outputs_are_stable():
    frame = make_ohlcv_frame(300)
    rows = []
    for end_idx in range(50, len(frame) + 1):
        partial = frame.iloc[:end_idx]
        row = cpp_compute_features(partial).iloc[0].to_numpy(dtype=float)
        rows.append(row)

    matrix = np.vstack(rows)
    assert matrix.shape == (len(frame) - 49, 20)
    assert not np.isnan(matrix).any()
    assert not np.isinf(matrix).any()
    assert np.all(np.isfinite(matrix))

    # Confirm deterministic repeatability on the final window
    last_window = frame.iloc[:300]
    repeated = cpp_compute_features(last_window).iloc[0].to_numpy(dtype=float)
    assert np.allclose(matrix[-1], repeated, atol=1e-12)
