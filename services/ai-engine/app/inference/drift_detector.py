import logging
import collections
from typing import Dict, List, Optional
import numpy as np
from scipy.stats import ks_2samp

logger = logging.getLogger(__name__)

# Baseline stats from training dataset (mean, std)
TRAINING_BASELINES = {
    "rsi14": {"mean": 50.05, "std": 14.8},
    "mfi14": {"mean": 49.95, "std": 15.2},
    "ema_ratio": {"mean": 1.0012, "std": 0.015},
    "vwap_distance": {"mean": 0.0002, "std": 0.008},
    "volume_ratio": {"mean": 1.05, "std": 0.48},
}


class DriftDetector:
    """Tracks real-time feature drift for critical technical indicators.
    
    Compares a rolling 200-sample live window against training baseline distributions.
    """
    
    def __init__(self, window_size: int = 200, p_value_threshold: float = 0.05):
        self.window_size = window_size
        self.p_value_threshold = p_value_threshold
        # Double-ended queue for rolling samples, per symbol and feature
        self.history: Dict[str, Dict[str, collections.deque]] = {}
        
        # Pre-generate synthetic reference baseline arrays for the KS test
        self.baselines: Dict[str, np.ndarray] = {}
        np.random.seed(42)  # For deterministic baseline generation
        for feature, stats in TRAINING_BASELINES.items():
            self.baselines[feature] = np.random.normal(stats["mean"], stats["std"], size=window_size)

    def add_sample(self, symbol: str, features: Dict[str, float]):
        """Add a new live feature sample and execute drift check if window is full."""
        if symbol not in self.history:
            self.history[symbol] = {feat: collections.deque(maxlen=self.window_size) for feat in TRAINING_BASELINES}
            
        # Add new values to history
        for feat in TRAINING_BASELINES:
            val = features.get(feat)
            if val is not None:
                self.history[symbol][feat].append(float(val))
                
        # If we have gathered enough samples, perform the KS test for drift detection
        first_feat = list(TRAINING_BASELINES.keys())[0]
        if len(self.history[symbol][first_feat]) >= self.window_size:
            self._check_drift(symbol)

    def _check_drift(self, symbol: str):
        """Perform Kolmogorov-Smirnov test to detect substantial distribution drift."""
        for feat in TRAINING_BASELINES:
            live_samples = np.array(self.history[symbol][feat])
            baseline_samples = self.baselines[feat]
            
            # KS test between live rolling window and training baseline reference
            stat, p_value = ks_2samp(live_samples, baseline_samples)
            
            try:
                from stockai_shared.metrics.metrics import (
                    AI_FEATURE_DRIFT_SCORE,
                    AI_FEATURE_DRIFT_PVALUE
                )
                AI_FEATURE_DRIFT_SCORE.labels(symbol=symbol, feature=feat).set(stat)
                AI_FEATURE_DRIFT_PVALUE.labels(symbol=symbol, feature=feat).set(p_value)
            except Exception:
                pass
            
            if p_value < self.p_value_threshold:
                logger.warning(
                    "[DRIFT-ALERT] Substantial feature drift detected for %s on feature '%s'! "
                    "KS stat: %.4f, p-value: %.6f (threshold: %.3f). Distribution differs from training baseline.",
                    symbol, feat, stat, p_value, self.p_value_threshold
                )
                try:
                    from stockai_shared.metrics.metrics import AI_FEATURE_DRIFT_ALERTS
                    AI_FEATURE_DRIFT_ALERTS.labels(symbol=symbol, feature=feat).inc()
                except Exception:
                    pass
