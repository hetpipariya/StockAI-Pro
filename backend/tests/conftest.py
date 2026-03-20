"""
Shared test fixtures for StockAI Pro backend tests.
"""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def mock_ohlcv_df():
    """Generate a realistic 100-row OHLCV DataFrame for testing."""
    np.random.seed(42)
    n = 100
    base_price = 2500.0
    prices = [base_price]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0, 0.005)))

    df = pd.DataFrame({
        "open": [p * (1 - np.random.uniform(0, 0.003)) for p in prices],
        "high": [p * (1 + np.random.uniform(0.001, 0.005)) for p in prices],
        "low": [p * (1 - np.random.uniform(0.001, 0.005)) for p in prices],
        "close": prices,
        "volume": np.random.randint(50000, 500000, n),
    })
    return df


@pytest.fixture
def mock_ohlcv_list(mock_ohlcv_df):
    """Convert OHLCV DataFrame to list of dicts (API format)."""
    records = []
    for i, row in mock_ohlcv_df.iterrows():
        records.append({
            "time": f"2026-03-19T10:{i:02d}:00Z",
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
        })
    return records


@pytest.fixture
def short_ohlcv_df():
    """10-row DataFrame — too short for meaningful features."""
    np.random.seed(99)
    n = 10
    prices = [100 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "open": prices,
        "high": [p + 0.3 for p in prices],
        "low": [p - 0.3 for p in prices],
        "close": prices,
        "volume": [1000] * n,
    })


@pytest.fixture
def bullish_ohlcv_df():
    """50-row strongly uptrending DataFrame."""
    np.random.seed(7)
    n = 50
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] + np.random.uniform(0.1, 0.6))

    return pd.DataFrame({
        "open": [p - 0.2 for p in prices],
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.3 for p in prices],
        "close": prices,
        "volume": [50000 + i * 500 for i in range(n)],
    })


@pytest.fixture
def bearish_ohlcv_df():
    """50-row strongly downtrending DataFrame."""
    np.random.seed(13)
    n = 50
    prices = [200.0]
    for _ in range(n - 1):
        prices.append(prices[-1] - np.random.uniform(0.1, 0.6))

    return pd.DataFrame({
        "open": [p + 0.2 for p in prices],
        "high": [p + 0.3 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": prices,
        "volume": [50000 + i * 500 for i in range(n)],
    })
