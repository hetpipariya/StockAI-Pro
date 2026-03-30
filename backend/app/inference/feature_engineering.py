"""
feature_engineering.py — Single Source of Truth for ML Features
================================================================

Both training and inference MUST import from this module.
Any change to feature computation happens HERE and only here.

Feature set version: v1.1 (19 columns)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Canonical Feature Columns (ORDER MATTERS) ────────────────────────────────
# This is the ONLY definition of the feature set. Training saves this list
# as features.pkl; inference validates against it at load time.
FEATURE_COLUMNS: list[str] = [
    "ema_9",
    "ema_20",
    "ema_21",
    "ema_50",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "vwap",
    "atr_14",
    "volume_spike",
    "price_change",
    "volatility",
    "momentum",
    "rolling_mean_5",
    "rolling_std_5",
    "pct_change_1d",
    "roll_std_5d",
    "trend_strength",
]

FEATURE_VERSION = "v1.1"
MIN_ROWS_FOR_FEATURES = 25


def compute_features(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the canonical 19-feature set from a raw OHLCV DataFrame.

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        Must contain columns: open, high, low, close, volume.
        Should have at least MIN_ROWS_FOR_FEATURES rows for meaningful
        indicator values.

    Returns
    -------
    pd.DataFrame
        DataFrame with exactly the columns in FEATURE_COLUMNS, in order.
        Returns empty DataFrame (with correct columns) if input is too short.
    """
    empty = pd.DataFrame(columns=FEATURE_COLUMNS)

    if ohlcv_df is None or len(ohlcv_df) < MIN_ROWS_FOR_FEATURES:
        return empty

    df = ohlcv_df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Validate required columns
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        logger.warning("[FEATURES] Missing required columns: %s", missing)
        return empty

    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    c = df["close"]
    h = df["high"]
    low_series = df["low"]
    v = df["volume"]

    # ── Exponential Moving Averages ─────────────────────────────────────────
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_20"] = c.ewm(span=20, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()

    # ── RSI 14 ──────────────────────────────────────────────────────────────
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # ── MACD (12, 26, 9) ───────────────────────────────────────────────────
    exp_fast = c.ewm(span=12, adjust=False).mean()
    exp_slow = c.ewm(span=26, adjust=False).mean()
    df["macd"] = exp_fast - exp_slow
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # ── VWAP ────────────────────────────────────────────────────────────────
    typical_price = (h + low_series + c) / 3
    cum_vol = v.cumsum()
    df["vwap"] = (typical_price * v).cumsum() / (cum_vol + 1e-9)

    # ── ATR 14 ───────────────────────────────────────────────────────────────
    tr1 = h - low_series
    tr2 = (h - c.shift(1)).abs()
    tr3 = (low_series - c.shift(1)).abs()
    df["true_range"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr_14"] = df["true_range"].rolling(14).mean()

    # ── Volume Spike ─────────────────────────────────────────────────────────
    vol_ma = v.rolling(20, min_periods=1).mean()
    df["volume_spike"] = (v > (vol_ma * 2.0)).astype(int)

    # ── Momentum & Rolling Statistics ───────────────────────────────────────
    df["price_change"] = c - df["open"]
    safe_c = c.clip(lower=1e-9)
    df["volatility"] = (h - low_series) / safe_c
    df["momentum"] = c - c.shift(3)
    df["rolling_mean_5"] = c.rolling(5, min_periods=1).mean()
    df["rolling_std_5"] = c.rolling(5, min_periods=2).std()
    df["pct_change_1d"] = c.pct_change(1)
    df["roll_std_5d"] = df["pct_change_1d"].rolling(5).std()

    # ── Trend Strength ───────────────────────────────────────────────────────
    df["trend_strength"] = (c - df["ema_20"]) / (df["ema_20"] + 1e-9)

    # ── Cleanup ─────────────────────────────────────────────────────────────
    df.drop(columns=["true_range"], errors="ignore", inplace=True)
    df.bfill(inplace=True)
    df.fillna(0, inplace=True)
    df.replace([np.inf, -np.inf], 0, inplace=True)

    # Return only canonical columns, in canonical order
    return df[FEATURE_COLUMNS].copy()


def validate_features(
    feature_names: list[str],
    expected: Optional[list[str]] = None,
    context: str = "",
) -> None:
    """
    Validate that feature_names exactly matches the expected canonical list.

    Raises RuntimeError with a detailed diff on mismatch.
    """
    expected = expected or FEATURE_COLUMNS

    if list(feature_names) == list(expected):
        return  # All good

    # Build detailed error message
    got_set = set(feature_names)
    exp_set = set(expected)
    missing = sorted(exp_set - got_set)
    extra = sorted(got_set - exp_set)

    parts = [f"[FEATURES] Feature mismatch detected ({context})"]
    parts.append(f"  Expected {len(expected)} features, got {len(feature_names)}")
    if missing:
        parts.append(f"  Missing: {missing}")
    if extra:
        parts.append(f"  Extra:   {extra}")

    # Check order mismatch (same set, different order)
    if not missing and not extra:
        for i, (a, b) in enumerate(zip(feature_names, expected)):
            if a != b:
                parts.append(
                    f"  Order mismatch at index {i}: got '{a}', expected '{b}'"
                )
                break

    msg = "\n".join(parts)
    logger.error(msg)
    raise RuntimeError(msg)


def get_feature_summary(df: pd.DataFrame) -> dict:
    """
    Return a debug summary of feature values for the latest row.
    Used in debug mode for prediction transparency.
    """
    if df is None or len(df) == 0:
        return {"error": "empty dataframe"}

    latest = df.iloc[-1]
    summary = {}
    for col in FEATURE_COLUMNS:
        val = latest.get(col, None)
        if val is not None:
            summary[col] = round(float(val), 6)
        else:
            summary[col] = None

    # Add metadata
    summary["_rows_used"] = len(df)
    summary["_nan_count"] = int(df[FEATURE_COLUMNS].isna().sum().sum())
    summary["_inf_count"] = int(np.isinf(df[FEATURE_COLUMNS].values).sum())
    summary["_feature_version"] = FEATURE_VERSION

    return summary
