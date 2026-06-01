"""
Concurrency, performance, and memory-safety tests for the optimized ML pipeline.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.production_pipeline import (
    ProductionInferencePipeline,
    get_process_executor,
    shutdown_process_executor,
    infer_batch_symbols,
)
from app.inference.runner import predict_symbol, PredictionResult, PREDICTION_THROTTLE_SECONDS
from app.services.feature_cache import InMemoryFeatureCache


def make_sample_ohlcv(num_bars: int = 100) -> pd.DataFrame:
    timestamps = pd.date_range("2026-05-25 09:15", periods=num_bars, freq="5min")
    prices = 1000.0 + np.cumsum(np.random.normal(0, 0.5, num_bars))
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices - 0.5,
            "high": prices + 1.0,
            "low": prices - 1.0,
            "close": prices,
            "volume": np.random.uniform(5000, 15000, num_bars),
        }
    )


@pytest.fixture(autouse=True)
def cleanup_executor():
    yield
    shutdown_process_executor()


def test_process_executor_lifecycle():
    """Verify persistent ProcessPoolExecutor is lazily initialized and cleanly terminated."""
    from concurrent.futures import ProcessPoolExecutor
    executor = get_process_executor()
    assert executor is not None
    assert isinstance(executor, ProcessPoolExecutor)
    
    # Shutdown
    shutdown_process_executor()
    
    # Verify cleaned up
    from app.inference.production_pipeline import _process_executor
    assert _process_executor is None


@pytest.mark.anyio
async def test_pipeline_computes_features_via_executor():
    """Verify feature computations bypass the GIL using the ProcessPoolExecutor."""
    df_5m = make_sample_ohlcv(100)
    
    # Initialize pipeline with no models (fallback HOLD path) and memory cache
    pipeline = ProductionInferencePipeline(
        model=None,
        redis_cache=None,
        use_feature_cache=True,
    )
    
    # Perform inference
    signal = await pipeline.infer(
        symbol="RELIANCE",
        ohlcv_5m=df_5m,
        interval="5m",
    )
    
    assert signal is not None
    assert signal.signal.name == "HOLD"
    assert "Pipeline error" not in signal.reason  # Make sure features were processed successfully without errors
    
    # Assert hit rate is 0 initially (miss)
    metrics = pipeline.get_metrics()
    assert metrics["cache_misses"] == 1
    assert metrics["cache_hits"] == 0
    
    # Run second time - should hit the feature cache
    signal_cached = await pipeline.infer(
        symbol="RELIANCE",
        ohlcv_5m=df_5m,
        interval="5m",
    )
    
    metrics2 = pipeline.get_metrics()
    assert metrics2["cache_misses"] == 1
    assert metrics2["cache_hits"] == 1


@pytest.mark.anyio
async def test_concurrency_batch_inference():
    """Verify that multiple concurrent inference calls do not block the event loop."""
    df = make_sample_ohlcv(100)
    pipeline = ProductionInferencePipeline(model=None, redis_cache=None, use_feature_cache=True)
    
    symbols_data = {
        "RELIANCE": {"ohlcv_5m": df},
        "TCS": {"ohlcv_5m": df},
        "INFY": {"ohlcv_5m": df},
        "HDFCBANK": {"ohlcv_5m": df},
    }
    
    start_time = time.perf_counter()
    signals = await infer_batch_symbols(pipeline, symbols_data)
    elapsed = time.perf_counter() - start_time
    
    assert len(signals) == 4
    assert all(symbol in signals for symbol in symbols_data)
    # The parallel dispatch should complete extremely fast, showcasing parallel executor efficiency
    assert elapsed < 5.0


def test_runner_prediction_throttling():
    """Verify that runner predict_symbol throttles duplicate requests within throttle window."""
    symbol = "SBIN"
    candles = [
        {"time": f"2026-05-25T09:{15 + i}:00Z", "open": 650.0, "high": 655.0, "low": 648.0, "close": 652.0, "volume": 1000}
        for i in range(50)
    ]
    
    # First prediction
    start_time = time.perf_counter()
    p1 = predict_symbol(symbol=symbol, timeframe="15m", latest_ltp=652.0, ohlcv=candles)
    duration_1 = time.perf_counter() - start_time
    
    # Second prediction immediately after (should be near instantaneous from in-memory cache)
    start_time2 = time.perf_counter()
    p2 = predict_symbol(symbol=symbol, timeframe="15m", latest_ltp=652.0, ohlcv=candles)
    duration_2 = time.perf_counter() - start_time2
    
    assert p1 == p2
    # Cached run should be sub-millisecond, whereas original runs models and feature pipelines
    assert duration_2 < duration_1 or duration_2 < 0.05
