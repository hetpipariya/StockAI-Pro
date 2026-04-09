"""Risk & Position Context Engine for intraday trade validation and sizing."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


EPSILON = 1e-9


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _compute_atr14(ohlcv_df: pd.DataFrame) -> float:
    high = _numeric_series(ohlcv_df, "high")
    low = _numeric_series(ohlcv_df, "low")
    close = _numeric_series(ohlcv_df, "close")

    if len(high) < 3 or len(low) < 3 or len(close) < 3:
        return 0.0

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=3).mean()

    if atr14.empty:
        return 0.0

    value = float(atr14.iloc[-1])
    if not np.isfinite(value) or value <= 0:
        return 0.0
    return value


def compute_risk_position_context(
    ohlcv_df: pd.DataFrame,
    signal: str,
    entry_price: float,
    target_price: float | None,
    capital: float,
    risk_per_trade: float,
    atr_multiplier: float = 1.5,
    rr_min: float = 1.5,
    volatility_state: str = "NORMAL_VOLATILITY",
) -> dict[str, Any]:
    """Compute ATR stop, RR, and volatility-adjusted position sizing."""

    entry = float(max(entry_price, 0.0))
    capital_value = float(max(capital, 0.0))
    risk_pct = float(max(risk_per_trade, 0.0))
    side = str(signal or "HOLD").upper()

    if entry <= 0 or side not in {"BUY", "SELL", "HOLD"}:
        return {
            "stop_loss": 0.0,
            "target": 0.0,
            "RR": 0.0,
            "position_size": 0,
            "atr": 0.0,
            "atr_ratio": 0.0,
            "position_size_factor": 0.0,
            "risk_filter_fail": True,
            "volatility_mode": "NORMAL",
        }

    atr = _compute_atr14(ohlcv_df)
    if atr <= 0:
        atr = entry * 0.015

    atr_ratio = atr / max(entry, EPSILON)
    stop_distance = max(atr * max(atr_multiplier, 0.1), entry * 0.003)

    if side == "BUY":
        stop_loss = entry - stop_distance
    elif side == "SELL":
        stop_loss = entry + stop_distance
    else:
        stop_loss = entry

    default_target = (
        entry + (stop_distance * rr_min)
        if side == "BUY"
        else entry - (stop_distance * rr_min)
    )

    target_candidate = float(target_price) if target_price is not None else default_target

    if side == "BUY":
        if target_candidate <= entry:
            target_candidate = default_target
        reward = max(target_candidate - entry, 0.0)
        risk = max(entry - stop_loss, EPSILON)
    elif side == "SELL":
        if target_candidate >= entry:
            target_candidate = default_target
        reward = max(entry - target_candidate, 0.0)
        risk = max(stop_loss - entry, EPSILON)
    else:
        reward = 0.0
        risk = EPSILON

    rr_value = reward / max(risk, EPSILON)

    base_size = (capital_value * risk_pct) / max(atr, EPSILON)
    max_affordable = capital_value / max(entry, EPSILON)
    base_size = min(base_size, max_affordable)

    vol_state = str(volatility_state or "NORMAL_VOLATILITY").upper()
    if vol_state in {"HIGH_VOLATILITY", "BREAKOUT"} or atr_ratio >= 0.02:
        vol_multiplier = 0.70
        vol_mode = "HIGH"
    elif vol_state == "LOW_VOLATILITY" or atr_ratio <= 0.006:
        vol_multiplier = 1.20
        vol_mode = "LOW"
    else:
        vol_multiplier = 1.00
        vol_mode = "NORMAL"

    dynamic_size = max(0.0, base_size * vol_multiplier)

    if side == "HOLD":
        position_size = 0
    else:
        position_size = int(max(1, math.floor(dynamic_size))) if dynamic_size > 0 else 0

    size_factor = (
        _clip01(position_size / max(max_affordable, 1.0))
        if max_affordable > 0
        else 0.0
    )

    risk_filter_fail = bool(side in {"BUY", "SELL"} and rr_value < rr_min)

    return {
        "stop_loss": round(float(stop_loss), 2),
        "target": round(float(target_candidate), 2),
        "RR": round(float(rr_value), 4),
        "position_size": int(max(position_size, 0)),
        "atr": round(float(atr), 6),
        "atr_ratio": round(float(atr_ratio), 6),
        "position_size_factor": round(float(size_factor), 4),
        "risk_filter_fail": risk_filter_fail,
        "volatility_mode": vol_mode,
    }
