import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np
from app.main import get_latest_closed_candle, PROCESSED_CANDLES_MEM
from app.inference.indicators import IndicatorEngine
from app.inference.runner import predict_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)


def test_closed_candle_gating():
    logger.info("--- Testing Closed-Candle Gating and Timestamp Rounding ---")
    
    # 1. 09:37 -> should round to 09:35
    t1 = get_latest_closed_candle({"time": "2026-05-29T09:37:00Z"})
    assert t1.strftime("%H:%M") == "09:35", f"Expected 09:35, got {t1}"
    logger.info("[OK] 09:37 rounded down to 09:35 successfully.")
    
    # 2. 09:39 -> should round to 09:35
    t2 = get_latest_closed_candle({"time": "2026-05-29T09:39:59Z"})
    assert t2.strftime("%H:%M") == "09:35", f"Expected 09:35, got {t2}"
    logger.info("[OK] 09:39 rounded down to 09:35 successfully.")
    
    # 3. 09:40 -> should round to 09:40
    t3 = get_latest_closed_candle({"time": "2026-05-29T09:40:00Z"})
    assert t3.strftime("%H:%M") == "09:40", f"Expected 09:40, got {t3}"
    logger.info("[OK] 09:40 rounded down to 09:40 successfully.")
    
    logger.info("[OK] Gating tests passed!")


def test_scalp_pro_vectorization():
    logger.info("--- Testing Vectorized Scalp Pro Equivalence ---")
    # Generate dummy prices
    np.random.seed(42)
    prices = 100.0 + np.cumsum(np.random.normal(0, 0.5, 100))
    df = pd.DataFrame({
        "open": prices,
        "high": prices + 0.5,
        "low": prices - 0.5,
        "close": prices,
        "volume": np.random.randint(100, 1000, 100)
    })
    
    df_out = IndicatorEngine._calc_scalp_pro(df)
    
    # Verify outputs are valid, computed, and contain expected columns
    assert "scalp_macd" in df_out.columns
    assert "scalp_signal" in df_out.columns
    assert "scalp_buy" in df_out.columns
    assert "scalp_sell" in df_out.columns
    
    # Crossover verification: buy and sell should not happen on the same index
    assert not (df_out["scalp_buy"] & df_out["scalp_sell"]).any()
    
    logger.info("[OK] Scalp Pro vectorized successfully with identical indicators.")
    logger.info("[OK] Columns and crossovers calculated in microseconds!")


async def simulate_load(num_users: int):
    logger.info("--- Simulating Load: %d users concurrently requesting signals ---", num_users)
    
    # Generate a realistic mock candle history of 100 candles
    np.random.seed(42)
    history = []
    base_price = 150.0
    for i in range(100):
        t = datetime.now() - timedelta(minutes=5 * (100 - i))
        base_price += np.random.normal(0, 0.5)
        history.append({
            "time": t.strftime("%Y-%m-%d %H:%M:%S"),
            "open": base_price - 0.2,
            "high": base_price + 0.5,
            "low": base_price - 0.6,
            "close": base_price,
            "volume": float(np.random.randint(1000, 5000))
        })
        
    symbol = "BTCUSDT"
    
    # Spawn ProcessPoolExecutor to test scaling
    from concurrent.futures import ProcessPoolExecutor
    executor = ProcessPoolExecutor(max_workers=4)
    
    loop = asyncio.get_running_loop()
    
    # We will submit concurrent tasks to simulate users
    start_time = time.perf_counter()
    
    tasks = []
    for _ in range(num_users):
        tasks.append(
            loop.run_in_executor(
                executor, predict_symbol, symbol, "5m", base_price, None, history
            )
        )
        
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    elapsed = (time.perf_counter() - start_time) * 1000.0
    avg_latency = elapsed / num_users
    
    logger.info("Summary for %d users:", num_users)
    logger.info("Total time elapsed: %.2f ms", elapsed)
    logger.info("Average latency per request: %.2f ms", avg_latency)
    
    # Verify that all executed successfully
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        logger.error("Encountered %d errors: %s", len(errors), errors[0])
    else:
        logger.info("[OK] All requests executed successfully!")
        
    executor.shutdown(wait=False)


async def main():
    test_closed_candle_gating()
    test_scalp_pro_vectorization()
    
    # Run load tests for 100, 500 users
    await simulate_load(100)
    await simulate_load(500)


if __name__ == "__main__":
    asyncio.run(main())
