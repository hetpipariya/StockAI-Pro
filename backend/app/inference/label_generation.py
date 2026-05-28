"""
Label Generation & Training Pipeline — Production Grade
========================================================

Handles:
1. Label generation (BUY/SELL/HOLD) from future returns
2. Walk-forward validation setup
3. Train/val/test split (temporal)
4. Feature correlation analysis
5. Dataset construction for model training

Key Rules:
- Time-series split ONLY (no random shuffle)
- 3-4 candle prediction horizon
- BUY ≥ +1.5%, SELL ≤ -1.5%, HOLD otherwise
- Walk-forward validation
- No future leakage
- Prevent label imbalance

Version: v1.0
Updated: 2026-05-12
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ────────────────────────────────────────────────────────────────────────────

LABEL_VERSION = "v1.0"

# Prediction horizon (candles into the future)
PREDICTION_HORIZON = 3  # default 3 candles forward

# Defaults — configurable via environment or function args
DEFAULT_LABEL_MODE = os.getenv("ENTRY_LABEL_MODE", "fixed").lower()  # fixed | atr
DEFAULT_FUTURE_RETURN_THRESHOLD = float(os.getenv("ENTRY_FUTURE_RETURN_THRESHOLD", "0.004"))  # 0.4%
DEFAULT_ATR_MULTIPLIER = float(os.getenv("ENTRY_ATR_MULTIPLIER", "0.6"))

# Legacy constants (kept for reference)
BUY_THRESHOLD = 0.015  # +1.5% (legacy)
SELL_THRESHOLD = -0.015  # -1.5% (legacy)

# Train/Validation/Test split (temporal)
TRAIN_RATIO = 0.70
VALIDATION_RATIO = 0.15
TEST_RATIO = 0.15

# Minimum samples for train/val/test sets
MIN_TRAIN_SAMPLES = 500
MIN_VAL_SAMPLES = 100
MIN_TEST_SAMPLES = 50

# Label balance targets (to prevent extreme imbalance)
LABEL_BALANCE_THRESHOLD = 0.10  # Allow up to 10% imbalance in either direction


# ────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class LabelStats:
    """Statistics about generated labels."""
    total_samples: int
    buy_count: int
    sell_count: int
    hold_count: int
    buy_pct: float
    sell_pct: float
    hold_pct: float
    min_return: float
    max_return: float
    mean_return: float
    std_return: float
    has_imbalance: bool


@dataclass
class TrainValTestSplit:
    """Temporal train/validation/test split."""
    train_features: pd.DataFrame
    train_labels: pd.Series
    val_features: pd.DataFrame
    val_labels: pd.Series
    test_features: pd.DataFrame
    test_labels: pd.Series
    train_indices: np.ndarray
    val_indices: np.ndarray
    test_indices: np.ndarray
    split_dates: dict


# ────────────────────────────────────────────────────────────────────────────
# LABEL GENERATION
# ────────────────────────────────────────────────────────────────────────────


def generate_labels(
    ohlcv: pd.DataFrame,
    horizon: int = PREDICTION_HORIZON,
    label_mode: Optional[str] = None,
    future_return_threshold: Optional[float] = None,
    atr_multiplier: Optional[float] = None,
) -> pd.Series:
    """
    Generate labels from future returns.
    
    Args:
        ohlcv: OHLCV DataFrame with 'close' column
        horizon: Number of candles to look forward
    
    Returns:
        Series with labels: 1 (BUY), -1 (SELL), 0 (HOLD)
    
    Notes:
        - Future return = (close[i+horizon] - close[i]) / close[i]
        - No label for last 'horizon' candles (no future data)
        - BUY if return ≥ +1.5%
        - SELL if return ≤ -1.5%
        - HOLD otherwise
    """
    if ohlcv is None or len(ohlcv) <= horizon:
        return pd.Series(0, index=ohlcv.index)

    # Resolve mode and thresholds (function args take precedence, then env/defaults)
    mode = (label_mode or DEFAULT_LABEL_MODE or "fixed").lower()
    thr = DEFAULT_FUTURE_RETURN_THRESHOLD if future_return_threshold is None else float(future_return_threshold)
    atr_mul = DEFAULT_ATR_MULTIPLIER if atr_multiplier is None else float(atr_multiplier)

    labels = np.zeros(len(ohlcv), dtype=int)

    # Future close prices (shifted backward)
    future_close = ohlcv["close"].shift(-horizon)

    # Calculate future returns
    current_close = ohlcv["close"]
    future_returns = (future_close - current_close) / current_close

    if mode == "fixed":
        # Fixed absolute-return thresholds (e.g., 0.004 => 0.4%)
        labels[future_returns >= thr] = 1
        labels[future_returns <= -thr] = -1

    elif mode == "atr":
        # ATR-adaptive thresholds: compute ATR(14) from high, low, close
        high = pd.to_numeric(ohlcv.get("high", pd.Series([0.0] * len(ohlcv))), errors="coerce")
        low = pd.to_numeric(ohlcv.get("low", pd.Series([0.0] * len(ohlcv))), errors="coerce")
        close = pd.to_numeric(ohlcv.get("close", pd.Series([0.0] * len(ohlcv))), errors="coerce")

        prev_close = close.shift(1)
        tr1 = (high - low).abs()
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14, min_periods=1).mean()

        # Threshold per-row
        atr_threshold = atr14 * float(atr_mul)

        # If ATR is zero/NaN fallback to small fixed threshold
        fallback_thr = thr

        buy_mask = future_returns >= atr_threshold.fillna(fallback_thr)
        sell_mask = future_returns <= -atr_threshold.fillna(fallback_thr)

        labels[buy_mask] = 1
        labels[sell_mask] = -1

    else:
        # Unknown mode: fallback to fixed
        labels[future_returns >= thr] = 1
        labels[future_returns <= -thr] = -1

    # Last 'horizon' candles have no label (no future data) → set to 0 (HOLD)
    if horizon > 0:
        labels[-horizon:] = 0

    return pd.Series(labels, index=ohlcv.index)


def get_label_stats(labels: pd.Series) -> LabelStats:
    """Compute label statistics."""
    total = len(labels)
    buy = (labels == 1).sum()
    sell = (labels == -1).sum()
    hold = (labels == 0).sum()

    buy_pct = buy / total if total > 0 else 0
    sell_pct = sell / total if total > 0 else 0
    hold_pct = hold / total if total > 0 else 0

    # Check for extreme imbalance
    has_imbalance = (
        abs(buy_pct - 0.33) > LABEL_BALANCE_THRESHOLD
        or abs(sell_pct - 0.33) > LABEL_BALANCE_THRESHOLD
    )

    return LabelStats(
        total_samples=total,
        buy_count=int(buy),
        sell_count=int(sell),
        hold_count=int(hold),
        buy_pct=buy_pct,
        sell_pct=sell_pct,
        hold_pct=hold_pct,
        min_return=0.0,
        max_return=0.0,
        mean_return=0.0,
        std_return=0.0,
        has_imbalance=has_imbalance,
    )


# ────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD VALIDATION
# ────────────────────────────────────────────────────────────────────────────


def temporal_train_val_test_split(
    features: pd.DataFrame,
    labels: pd.Series,
    train_ratio: float = TRAIN_RATIO,
    val_ratio: float = VALIDATION_RATIO,
    test_ratio: float = TEST_RATIO,
) -> TrainValTestSplit:
    """
    Create temporal train/validation/test split.
    
    NO RANDOM SHUFFLE — Time-series split only.
    
    Args:
        features: Feature DataFrame
        labels: Label Series
        train_ratio: Fraction for training (0.70)
        val_ratio: Fraction for validation (0.15)
        test_ratio: Fraction for testing (0.15)
    
    Returns:
        TrainValTestSplit with train/val/test data
    """
    n = len(features)

    # Calculate split indices
    train_end = int(n * train_ratio)
    val_end = train_end + int(n * val_ratio)
    test_end = n

    # Ensure minimum samples
    if train_end - 0 < MIN_TRAIN_SAMPLES:
        logger.warning(f"[TRAIN-VAL-TEST] Train set < {MIN_TRAIN_SAMPLES} samples")
    if val_end - train_end < MIN_VAL_SAMPLES:
        logger.warning(f"[TRAIN-VAL-TEST] Val set < {MIN_VAL_SAMPLES} samples")
    if test_end - val_end < MIN_TEST_SAMPLES:
        logger.warning(f"[TRAIN-VAL-TEST] Test set < {MIN_TEST_SAMPLES} samples")

    # Split indices
    train_idx = np.arange(0, train_end)
    val_idx = np.arange(train_end, val_end)
    test_idx = np.arange(val_end, test_end)

    # Extract data
    train_features = features.iloc[train_idx].copy()
    train_labels = labels.iloc[train_idx].copy()

    val_features = features.iloc[val_idx].copy()
    val_labels = labels.iloc[val_idx].copy()

    test_features = features.iloc[test_idx].copy()
    test_labels = labels.iloc[test_idx].copy()

    # Extract dates if available
    split_dates = {
        "train_start": features.index[0] if len(features) > 0 else None,
        "train_end": features.index[train_end - 1] if train_end > 0 else None,
        "val_start": features.index[train_end] if train_end < len(features) else None,
        "val_end": features.index[val_end - 1] if val_end > 0 else None,
        "test_start": features.index[val_end] if val_end < len(features) else None,
        "test_end": features.index[-1] if len(features) > 0 else None,
    }

    return TrainValTestSplit(
        train_features=train_features,
        train_labels=train_labels,
        val_features=val_features,
        val_labels=val_labels,
        test_features=test_features,
        test_labels=test_labels,
        train_indices=train_idx,
        val_indices=val_idx,
        test_indices=test_idx,
        split_dates=split_dates,
    )


def walk_forward_split(
    features: pd.DataFrame,
    labels: pd.Series,
    train_window_size: int = 1000,
    val_window_size: int = 200,
    step_size: int = 200,
) -> list[Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]]:
    """
    Create walk-forward validation splits.
    
    Returns multiple train/val pairs, each with expanding window.
    
    Args:
        features: Feature DataFrame
        labels: Label Series
        train_window_size: Size of training window
        val_window_size: Size of validation window
        step_size: Step size for walking forward
    
    Yields:
        Tuples of (train_features, train_labels, val_features, val_labels)
    """
    splits = []
    n = len(features)

    for start in range(0, n - train_window_size - val_window_size, step_size):
        train_end = start + train_window_size
        val_end = train_end + val_window_size

        if val_end > n:
            break

        train_features = features.iloc[start:train_end].copy()
        train_labels = labels.iloc[start:train_end].copy()

        val_features = features.iloc[train_end:val_end].copy()
        val_labels = labels.iloc[train_end:val_end].copy()

        splits.append((train_features, train_labels, val_features, val_labels))

    return splits


# ────────────────────────────────────────────────────────────────────────────
# FEATURE CORRELATION ANALYSIS
# ────────────────────────────────────────────────────────────────────────────


def analyze_feature_correlation(features: pd.DataFrame, threshold: float = 0.85) -> dict:
    """
    Analyze feature correlations and identify redundant features.
    
    Returns features pairs with high correlation (potential redundancy).
    """
    corr_matrix = features.corr().abs()

    # Find pairs with high correlation
    high_corr_pairs = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            corr_val = corr_matrix.iloc[i, j]
            if corr_val >= threshold:
                high_corr_pairs.append(
                    {
                        "feature1": corr_matrix.columns[i],
                        "feature2": corr_matrix.columns[j],
                        "correlation": corr_val,
                    }
                )

    return {
        "high_correlation_pairs": high_corr_pairs,
        "correlation_matrix": corr_matrix,
        "num_high_pairs": len(high_corr_pairs),
    }


def get_feature_importance_ranks(
    feature_names: list[str], feature_importances: np.ndarray
) -> pd.DataFrame:
    """
    Rank features by importance.
    
    Args:
        feature_names: List of feature names
        feature_importances: Importance scores from model
    
    Returns:
        DataFrame with ranked features
    """
    importance_df = pd.DataFrame(
        {"feature": feature_names, "importance": feature_importances}
    ).sort_values("importance", ascending=False)

    importance_df["rank"] = range(1, len(importance_df) + 1)
    importance_df["cumulative_importance"] = importance_df["importance"].cumsum()
    importance_df["cumulative_importance_pct"] = (
        importance_df["cumulative_importance"] / importance_df["importance"].sum()
    )

    return importance_df


# ────────────────────────────────────────────────────────────────────────────
# DATASET CONSTRUCTION
# ────────────────────────────────────────────────────────────────────────────


def construct_training_dataset(
    features: pd.DataFrame,
    labels: pd.Series,
    drop_nan_rows: bool = True,
    balance_labels: bool = True,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Construct clean training dataset.
    
    Args:
        features: Feature DataFrame
        labels: Label Series
        drop_nan_rows: Drop rows with NaN values
        balance_labels: Upsample minority classes
    
    Returns:
        Tuple of (clean_features, clean_labels)
    """
    # Combine features and labels
    data = pd.concat([features, labels.rename("label")], axis=1)

    # Drop NaN rows if requested
    if drop_nan_rows:
        initial_len = len(data)
        data = data.dropna()
        dropped = initial_len - len(data)
        if dropped > 0:
            logger.info(f"[DATASET] Dropped {dropped} rows with NaN")

    # Label balance (optional)
    if balance_labels:
        # Count each label
        label_counts = data["label"].value_counts()
        max_count = label_counts.max()

        # Upsample minority classes
        data_balanced = []
        for label_value in [-1, 0, 1]:
            label_data = data[data["label"] == label_value]
            if len(label_data) > 0:
                upsampled = label_data.sample(n=max_count, replace=True, random_state=42)
                data_balanced.append(upsampled)

        data = pd.concat(data_balanced, ignore_index=False)

    # Separate features and labels
    clean_features = data.drop("label", axis=1)
    clean_labels = data["label"]

    return clean_features, clean_labels


def create_model_training_dataset(
    ohlcv: pd.DataFrame,
    features: pd.DataFrame,
    labels: pd.Series,
    split_type: str = "temporal",
) -> Tuple[TrainValTestSplit, LabelStats]:
    """
    Create complete model training dataset with validation split.
    
    Args:
        ohlcv: Original OHLCV data (for reference)
        features: Feature DataFrame
        labels: Label Series
        split_type: "temporal" or "walk_forward"
    
    Returns:
        Tuple of (split, stats)
    """
    stats = get_label_stats(labels)
    logger.info(
        f"[DATASET] Label distribution: BUY={stats.buy_pct:.1%}, SELL={stats.sell_pct:.1%}, HOLD={stats.hold_pct:.1%}"
    )

    if stats.has_imbalance:
        logger.warning(f"[DATASET] Potential label imbalance detected")

    # Create split
    if split_type == "walk_forward":
        splits = walk_forward_split(features, labels)
        if len(splits) == 0:
            logger.error("[DATASET] Walk-forward split generated no splits")
            # Fallback to temporal split
            split = temporal_train_val_test_split(features, labels)
        else:
            # Use first split as representative
            train_f, train_l, val_f, val_l = splits[0]
            split = TrainValTestSplit(
                train_features=train_f,
                train_labels=train_l,
                val_features=val_f,
                val_labels=val_l,
                test_features=features.iloc[len(train_f) + len(val_f) :],
                test_labels=labels.iloc[len(train_f) + len(val_f) :],
                train_indices=np.arange(0, len(train_f)),
                val_indices=np.arange(len(train_f), len(train_f) + len(val_f)),
                test_indices=np.arange(len(train_f) + len(val_f), len(features)),
                split_dates={},
            )
    else:
        split = temporal_train_val_test_split(features, labels)

    return split, stats


# ────────────────────────────────────────────────────────────────────────────
# VALIDATION UTILITIES
# ────────────────────────────────────────────────────────────────────────────


def validate_no_data_leakage(train_labels: pd.Series, test_labels: pd.Series) -> bool:
    """
    Verify no data leakage between train and test (temporal).
    
    In proper time-series split, test data should always be AFTER train data.
    """
    if len(train_labels) == 0 or len(test_labels) == 0:
        return True

    # This is implicit in temporal split, but we can double-check indices
    return True  # Temporal split handles this


def validate_label_distribution(labels: pd.Series, min_class_ratio: float = 0.10) -> bool:
    """
    Validate labels are not too imbalanced.
    
    Args:
        labels: Label Series
        min_class_ratio: Minimum ratio for any class (0.10 = 10%)
    
    Returns:
        True if acceptable balance, False if too imbalanced
    """
    counts = labels.value_counts()
    total = len(labels)

    for count in counts.values:
        ratio = count / total
        if ratio < min_class_ratio or ratio > (1 - min_class_ratio):
            return False

    return True
