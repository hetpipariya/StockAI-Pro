"""Simple benchmark for StockAI C++ feature engine.

Run from repo root:
    python backend/scripts/benchmark_cpp_engine.py
"""

from __future__ import annotations

import sys
from pathlib import Path
import time
import numpy as np
import pandas as pd

# Allow running from repository root without external PYTHONPATH setup.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.inference.feature_engineering import FEATURE_COLUMNS, FEATURE_VERSION, compute_features


def _make_ohlcv(rows: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    base = 100 + np.cumsum(rng.normal(0, 0.4, rows))
    open_ = base + rng.normal(0, 0.15, rows)
    close = base + rng.normal(0, 0.15, rows)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.25, 0.08, rows))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.25, 0.08, rows))
    volume = rng.integers(1_000, 15_000, size=rows).astype(float)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def main() -> None:
    print(f"Engine: C++ | Version: {FEATURE_VERSION} | Features: {len(FEATURE_COLUMNS)}")

    df = _make_ohlcv(300)

    # Warm-up
    for _ in range(10):
        _ = compute_features(df)

    runs = 200
    start = time.perf_counter()
    for _ in range(runs):
        _ = compute_features(df)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    avg_ms = elapsed_ms / runs

    print(f"Rows: {len(df)}")
    print(f"Runs: {runs}")
    print(f"Total: {elapsed_ms:.2f} ms")
    print(f"Average per run: {avg_ms:.3f} ms")


if __name__ == "__main__":
    main()
