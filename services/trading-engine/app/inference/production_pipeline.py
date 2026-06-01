"""
Production Inference Pipeline
==============================

Complete end-to-end inference pipeline for production:
1. Feature computation or retrieval
2. Redis caching (asynchronous)
3. Model prediction
4. Signal generation with filtering
5. Async-compatible execution (ProcessPoolExecutor GIL bypass)
6. Production logging and monitoring

Designed for:
- Sub-100ms inference latency
- Multi-user scalability
- Cache-first architecture
- Graceful degradation
- Comprehensive monitoring

Version: v2.0
Updated: 2026-05-25
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor
import os

import numpy as np
import pandas as pd

from app.inference.feature_engineering import FEATURE_COLUMNS, compute_features
from app.inference.label_generation import get_label_stats
from app.inference.signal_engine_v2 import (
    BlockReason,
    SignalType,
    TradeSignal,
    convert_model_prediction_to_signal,
    detect_trend_state,
)
from app.services.feature_cache import InMemoryFeatureCache, RedisFeatureCache

logger = logging.getLogger(__name__)

# Persistent ProcessPoolExecutor to offload CPU-intensive Pandas calculations
_cpu_count = os.cpu_count() or 4
_max_workers = max(1, min(4, _cpu_count - 1))
_process_executor = None

def get_process_executor() -> ProcessPoolExecutor:
    global _process_executor
    if _process_executor is None:
        _process_executor = ProcessPoolExecutor(max_workers=_max_workers)
        logger.info("[MLOPS] Persistent ProcessPoolExecutor initialized with %d workers", _max_workers)
    return _process_executor

def shutdown_process_executor():
    global _process_executor
    if _process_executor is not None:
        _process_executor.shutdown(wait=True)
        _process_executor = None
        logger.info("[MLOPS] ProcessPoolExecutor shut down successfully.")


# ────────────────────────────────────────────────────────────────────────────
# INFERENCE PIPELINE
# ────────────────────────────────────────────────────────────────────────────


class ProductionInferencePipeline:
    """
    Production-grade inference pipeline.
    
    Handles complete feature → prediction → signal pipeline with:
    - Caching at multiple levels (asynchronous Redis)
    - Async execution (offloading heavy feature math to ProcessPoolExecutor)
    - Error recovery
    - Monitoring
    """

    def __init__(
        self,
        model: Any = None,  # XGBoost model or similar
        redis_cache: Optional[RedisFeatureCache] = None,
        use_feature_cache: bool = True,
    ):
        """
        Initialize pipeline.
        
        Args:
            model: Trained XGBoost/sklearn model with predict_proba()
            redis_cache: Redis cache (optional, uses in-memory fallback)
            use_feature_cache: Whether to use caching layer
        """
        self.model = model
        self.redis_cache = redis_cache
        self.use_feature_cache = use_feature_cache

        # Fallback cache if no Redis
        if redis_cache is None or not redis_cache.available:
            self.cache = InMemoryFeatureCache()
        else:
            self.cache = redis_cache

        # Metrics
        self.cache_hits = 0
        self.cache_misses = 0
        self.inference_count = 0
        self.total_latency = 0.0

    # ────────────────────────────────────────────────────────────────
    # MAIN INFERENCE METHOD
    # ────────────────────────────────────────────────────────────────

    async def infer(
        self,
        symbol: str,
        ohlcv_5m: pd.DataFrame,
        ohlcv_15m: Optional[pd.DataFrame] = None,
        ohlcv_daily: Optional[pd.DataFrame] = None,
        nifty_data: Optional[pd.DataFrame] = None,
        capital: float = 100000.0,
        interval: str = "5m",
    ) -> TradeSignal:
        """
        Run complete inference pipeline: features → model → signal.
        """
        start_time = time.perf_counter()

        try:
            # Step 1: Get features (cached or computed asynchronously)
            features_dict = await self._get_features_async(
                symbol, ohlcv_5m, ohlcv_15m, ohlcv_daily, nifty_data, interval
            )

            if features_dict is None or len(features_dict) == 0:
                logger.warning(f"[INFER] No features computed for {symbol}")
                return self._create_fallback_hold_signal(symbol, ohlcv_5m)

            # Step 2: Get latest feature values
            latest_features = {k: v for k, v in features_dict.items()}

            # Step 3: Model prediction (asynchronous)
            if self.model is not None:
                prediction_class, confidence = await self._predict_async(latest_features)
            else:
                logger.warning("[INFER] No model loaded, defaulting to HOLD")
                prediction_class = 0
                confidence = 0.5

            # Step 4: Extract trend information
            ema_9 = latest_features.get("ema_9", 0.0)
            ema_21 = latest_features.get("ema_21", 0.0)
            ema_50 = latest_features.get("ema_50", 0.0)
            close = ohlcv_5m["close"].iloc[-1] if len(ohlcv_5m) > 0 else 0.0

            trend = detect_trend_state(ema_9, ema_21, ema_50, close)

            # Step 5: Multi-timeframe alignment
            ema_direction_15m = latest_features.get("ema_direction_15m", 0.0)
            mtf_alignment = "BULL" if ema_direction_15m > 0 else "BEAR"

            # Step 6: NIFTY context
            nifty_direction = latest_features.get("nifty_direction", 0.0)
            nifty_state = "BULL" if nifty_direction > 0 else "BEAR"

            # Step 7: Generate signal with filtering
            signal = convert_model_prediction_to_signal(
                model_class=prediction_class,
                confidence=confidence,
                entry_price=close,
                features=latest_features,
                trend=trend,
                mtf_alignment=mtf_alignment,
                nifty_state=nifty_state,
                capital=capital,
                timestamp=datetime.now(),
            )

            # Step 8: Cache signal asynchronously
            if self.use_feature_cache:
                await self.cache.set_signal(symbol, asdict(signal), interval)

            # Step 9: Record metrics
            latency = time.perf_counter() - start_time
            self.inference_count += 1
            self.total_latency += latency

            try:
                from stockai_shared.metrics.metrics import ML_INFERENCE_LATENCY
                ML_INFERENCE_LATENCY.labels(symbol=symbol).observe(latency)
            except Exception:
                pass

            logger.info(
                f"[INFER] {symbol}: {signal.signal.name} Conf={signal.confidence:.0%} "
                f"RR={signal.risk_reward_ratio:.2f}x Latency={latency*1000:.1f}ms"
            )

            return signal

        except Exception as exc:
            try:
                from stockai_shared.metrics.metrics import ML_FALLBACK_SIGNALS
                ML_FALLBACK_SIGNALS.inc()
            except Exception:
                pass
            logger.error(f"[INFER] Pipeline failed for {symbol}: {exc}", exc_info=True)
            return self._create_fallback_hold_signal(symbol, ohlcv_5m)


    # ────────────────────────────────────────────────────────────────
    # FEATURE RETRIEVAL (CACHED OR COMPUTED)
    # ────────────────────────────────────────────────────────────────

    async def _get_features_async(
        self,
        symbol: str,
        ohlcv_5m: pd.DataFrame,
        ohlcv_15m: Optional[pd.DataFrame] = None,
        ohlcv_daily: Optional[pd.DataFrame] = None,
        nifty_data: Optional[pd.DataFrame] = None,
        interval: str = "5m",
    ) -> Optional[dict]:
        """
        Get features with caching asynchronously.
        """
        # Try cache first
        if self.use_feature_cache:
            cached = await self.cache.get_features(symbol, interval)
            if cached is not None:
                self.cache_hits += 1
                return cached

            self.cache_misses += 1

        # Compute features using the ProcessPoolExecutor
        features_df = await self._compute_features_async(
            ohlcv_5m, ohlcv_15m, ohlcv_daily, nifty_data
        )

        if features_df is None or len(features_df) == 0:
            return None

        # Get latest row as dict
        latest_features = features_df.iloc[-1].to_dict()

        # Store in cache asynchronously
        if self.use_feature_cache:
            await self.cache.set_features(symbol, latest_features, interval)

        return latest_features

    async def _compute_features_async(
        self,
        ohlcv_5m: pd.DataFrame,
        ohlcv_15m: Optional[pd.DataFrame] = None,
        ohlcv_daily: Optional[pd.DataFrame] = None,
        nifty_data: Optional[pd.DataFrame] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Compute features asynchronously.
        
        Offloads heavy Pandas/numpy feature computation to persistent ProcessPoolExecutor
        to bypass the Python GIL and prevent blocking FastAPI event loop thread.
        """
        from stockai_shared.metrics.metrics import ML_ACTIVE_WORKERS, ML_WORKER_HEARTBEAT, ML_FALLBACK_SIGNALS
        
        # Report status to SRE metrics
        try:
            ML_WORKER_HEARTBEAT.set(1)
            ML_ACTIVE_WORKERS.set(_max_workers)
        except Exception:
            pass

        loop = asyncio.get_event_loop()
        try:
            # Enforce a strict 2.0-second execution guardrail to isolate computing latency
            features_df = await asyncio.wait_for(
                loop.run_in_executor(
                    get_process_executor(),
                    compute_features,
                    ohlcv_5m,
                    ohlcv_15m,
                    ohlcv_daily,
                    nifty_data,
                ),
                timeout=2.0
            )
            return features_df
        except asyncio.TimeoutError:
            logger.error("[MLOPS] Feature computation timed out (>2.0s)!")
            try:
                ML_FALLBACK_SIGNALS.inc()
            except Exception:
                pass
            return None
        except Exception as exc:
            exc_name = type(exc).__name__
            logger.error("[MLOPS] Feature computation executor crash or failure: %s", exc)
            
            try:
                ML_WORKER_HEARTBEAT.set(0)
                ML_FALLBACK_SIGNALS.inc()
            except Exception:
                pass
                
            # Circuit breaker: automatically shut down pool if workers died or pool is broken
            if "BrokenProcessPool" in exc_name or "BrokenExecutor" in exc_name or "TerminatedWorkerError" in exc_name:
                logger.warning("[MLOPS] Recreating broken ProcessPoolExecutor...")
                shutdown_process_executor()
                
            return None


    # ────────────────────────────────────────────────────────────────
    # MODEL PREDICTION
    # ────────────────────────────────────────────────────────────────

    async def _predict_async(
        self, features_dict: dict
    ) -> Tuple[int, float]:
        """
        Run model prediction asynchronously.
        """
        if self.model is None:
            return 0, 0.5  # Default to HOLD

        try:
            # Extract feature vector in canonical order
            X = np.array([[features_dict.get(col, 0.0) for col in FEATURE_COLUMNS]])

            # Offload prediction to thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._predict_sync, X
            )
            return result

        except Exception as exc:
            logger.warning(f"[PREDICT] Prediction failed: {exc}")
            return 0, 0.5

    def _predict_sync(self, X: np.ndarray) -> Tuple[int, float]:
        """Synchronous prediction (runs in thread pool)."""
        try:
            # Get class probabilities
            proba = self.model.predict_proba(X)[0]

            # Classes are typically ordered [-1, 0, 1] or [0, 1, 2]
            # Assuming: index 0 = SELL (-1), 1 = HOLD (0), 2 = BUY (1)
            predicted_class_idx = np.argmax(proba)
            confidence = float(proba[predicted_class_idx])

            # Map to our signal classes
            class_map = {0: -1, 1: 0, 2: 1}  # Adjust if model uses different classes
            predicted_class = class_map.get(predicted_class_idx, 0)

            return predicted_class, confidence

        except Exception as exc:
            logger.warning(f"[PREDICT] Prediction failed: {exc}")
            return 0, 0.5

    # ────────────────────────────────────────────────────────────────
    # FALLBACK & UTILITIES
    # ────────────────────────────────────────────────────────────────

    def _create_fallback_hold_signal(
        self, symbol: str, ohlcv: pd.DataFrame
    ) -> TradeSignal:
        """Create safe fallback HOLD signal when pipeline fails."""
        close = ohlcv["close"].iloc[-1] if len(ohlcv) > 0 else 0.0

        return TradeSignal(
            signal=SignalType.HOLD,
            confidence=0.0,
            entry_price=close,
            stop_loss=close,
            target=close,
            position_size=0,
            position_size_pct=0.0,
            risk_reward_ratio=0.0,
            timestamp=datetime.now(),
            reason="Pipeline error: defaulting to HOLD",
            blocked_by=BlockReason.NONE,
        )

    def get_metrics(self) -> dict:
        """Get pipeline performance metrics."""
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        avg_latency = (
            self.total_latency / self.inference_count * 1000
            if self.inference_count > 0
            else 0
        )

        return {
            "inference_count": self.inference_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate_pct": hit_rate,
            "avg_latency_ms": avg_latency,
            "cache_available": self.cache.health_check(),
        }

    def reset_metrics(self):
        """Reset performance metrics."""
        self.cache_hits = 0
        self.cache_misses = 0
        self.inference_count = 0
        self.total_latency = 0.0


# ────────────────────────────────────────────────────────────────────────────
# BATCH INFERENCE
# ────────────────────────────────────────────────────────────────────────────


async def infer_batch_symbols(
    pipeline: ProductionInferencePipeline,
    symbols_data: dict[str, dict[str, Any]],
    capital: float = 100000.0,
) -> dict[str, TradeSignal]:
    """
    Run inference on multiple symbols concurrently.
    """
    tasks = {}
    for symbol, data in symbols_data.items():
        task = pipeline.infer(
            symbol=symbol,
            ohlcv_5m=data.get("ohlcv_5m"),
            ohlcv_15m=data.get("ohlcv_15m"),
            ohlcv_daily=data.get("ohlcv_daily"),
            nifty_data=data.get("nifty_data"),
            capital=capital,
        )
        tasks[symbol] = task

    # Run all concurrently
    results = await asyncio.gather(*tasks.values())

    # Map back to symbols
    signals = {}
    for symbol, result in zip(tasks.keys(), results):
        signals[symbol] = result

    return signals


# ────────────────────────────────────────────────────────────────────────────
# MONITORING & LOGGING
# ────────────────────────────────────────────────────────────────────────────


def log_signal_generation(signal: TradeSignal, symbol: str):
    """Log signal generation for monitoring."""
    logger.info(
        json.dumps(
            {
                "event": "signal_generated",
                "symbol": symbol,
                "signal": signal.signal.name,
                "confidence": round(signal.confidence, 3),
                "entry": round(signal.entry_price, 2),
                "stop_loss": round(signal.stop_loss, 2),
                "target": round(signal.target, 2),
                "rr_ratio": round(signal.risk_reward_ratio, 2),
                "position_size": round(signal.position_size, 0),
                "blocked_by": signal.blocked_by.value if signal.blocked_by else None,
                "timestamp": signal.timestamp.isoformat(),
            }
        )
    )


def log_prediction_outcome(
    symbol: str,
    signal: TradeSignal,
    actual_return: float,
    timestamp: datetime,
):
    """Log prediction outcome for accuracy tracking."""
    correct = False
    if signal.signal == SignalType.BUY and actual_return > 0:
        correct = True
    elif signal.signal == SignalType.SELL and actual_return < 0:
        correct = True
    elif signal.signal == SignalType.HOLD:
        correct = True  # HOLD is always "safe"

    logger.info(
        json.dumps(
            {
                "event": "prediction_outcome",
                "symbol": symbol,
                "signal": signal.signal.name,
                "confidence": round(signal.confidence, 3),
                "actual_return_pct": round(actual_return * 100, 2),
                "correct": correct,
                "timestamp": timestamp.isoformat(),
            }
        )
    )
