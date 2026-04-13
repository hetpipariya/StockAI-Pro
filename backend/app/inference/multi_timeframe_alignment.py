"""Multi-Timeframe Alignment Engine for directional confirmation and entry timing."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


EPSILON = 1e-9
TIMEFRAME_STEPS = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
}
TIMEFRAME_WEIGHTS = {
    "1m": 0.20,
    "5m": 0.25,
    "15m": 0.25,
    "1h": 0.30,
}


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(df[column], errors="coerce")
    series = series.replace([np.inf, -np.inf], np.nan)
    return series.dropna().reset_index(drop=True)


def _resample_close(close: pd.Series, step: int) -> pd.Series:
    if close.empty:
        return close
    if step <= 1:
        return close.reset_index(drop=True)
    buckets = np.arange(len(close)) // step
    return close.groupby(buckets).last().reset_index(drop=True)


def _direction_to_sign(direction: str) -> int:
    if direction == "BULLISH":
        return 1
    if direction == "BEARISH":
        return -1
    return 0


def _classify_tf_direction(
    close: pd.Series,
    fast_span: int = 21,
    slow_span: int = 50,
) -> tuple[str, float]:
    if close.empty or len(close) < max(8, fast_span // 2):
        return "MISSING", 0.0

    ema_fast = close.ewm(span=fast_span, adjust=False).mean()
    ema_slow = close.ewm(span=slow_span, adjust=False).mean()

    last_close = float(close.iloc[-1])
    last_fast = float(ema_fast.iloc[-1])
    last_slow = float(ema_slow.iloc[-1])

    spread = (last_fast - last_slow) / max(abs(last_close), EPSILON)
    strength = _clip01(float(np.tanh(abs(spread) * 250.0)))

    if last_fast > last_slow and last_close >= last_fast:
        return "BULLISH", strength
    if last_fast < last_slow and last_close <= last_fast:
        return "BEARISH", strength
    if last_fast > last_slow:
        return "BULLISH", _clip01(strength * 0.80)
    if last_fast < last_slow:
        return "BEARISH", _clip01(strength * 0.80)
    return "NEUTRAL", 0.0


def compute_multi_timeframe_alignment(
    ohlcv_df: pd.DataFrame | None,
) -> dict[str, Any]:
    """Compute MTF alignment state and score for 1m/5m/15m/1h stacks."""

    fallback = {
        "mtf_alignment": "MISSING",
        "mtf_score": 0.0,
        "direction": "NEUTRAL",
        "htf_confirmed": False,
        "ltf_entry_confirmed": False,
        "conflict": True,
        "timeframes": {},
        "timeframe_strength": {},
        "components": {
            "consensus": 0.0,
            "strength": 0.0,
            "htf_confirmation": 0.0,
            "ltf_confirmation": 0.0,
            "conflict_penalty": 1.0,
        },
    }

    if ohlcv_df is None or "close" not in ohlcv_df.columns:
        return fallback

    close = _numeric_series(ohlcv_df, "close")
    if close.empty or len(close) < 10:
        return fallback

    timeframe_direction: dict[str, str] = {}
    timeframe_strength: dict[str, float] = {}

    for tf, step in TIMEFRAME_STEPS.items():
        tf_close = _resample_close(close, step)
        direction, strength = _classify_tf_direction(tf_close)
        timeframe_direction[tf] = direction
        timeframe_strength[tf] = round(float(_clip01(strength)), 4)

    bullish_count = sum(1 for value in timeframe_direction.values() if value == "BULLISH")
    bearish_count = sum(1 for value in timeframe_direction.values() if value == "BEARISH")
    conflict = bool(bullish_count > 0 and bearish_count > 0)

    consensus = 0.0
    for tf, weight in TIMEFRAME_WEIGHTS.items():
        consensus += weight * _direction_to_sign(timeframe_direction.get(tf, "NEUTRAL"))

    if consensus > 0.10:
        majority_direction = "BULLISH"
    elif consensus < -0.10:
        majority_direction = "BEARISH"
    else:
        majority_direction = "NEUTRAL"

    all_bullish = all(timeframe_direction.get(tf) == "BULLISH" for tf in TIMEFRAME_STEPS)
    all_bearish = all(timeframe_direction.get(tf) == "BEARISH" for tf in TIMEFRAME_STEPS)

    htf_confirmed = bool(
        majority_direction in {"BULLISH", "BEARISH"}
        and timeframe_direction.get("1h", "MISSING") == majority_direction
    )
    ltf_entry_confirmed = bool(
        majority_direction in {"BULLISH", "BEARISH"}
        and timeframe_direction.get("1m", "MISSING") == majority_direction
        and timeframe_direction.get("5m", "MISSING") == majority_direction
    )

    if all_bullish:
        mtf_alignment = "STRONG"
        direction = "BULLISH"
    elif all_bearish:
        mtf_alignment = "STRONG"
        direction = "BEARISH"
    elif conflict:
        mtf_alignment = "CONFLICTING"
        direction = "MIXED"
    elif (
        htf_confirmed
        and ltf_entry_confirmed
        and timeframe_direction.get("15m", "NEUTRAL") == majority_direction
    ):
        mtf_alignment = "WEAK"
        direction = majority_direction
    elif htf_confirmed:
        mtf_alignment = "WEAK"
        direction = majority_direction
    else:
        mtf_alignment = "NEUTRAL"
        direction = majority_direction

    consensus_abs = abs(float(consensus))
    mean_strength = float(np.mean(list(timeframe_strength.values()))) if timeframe_strength else 0.0
    score = _clip01(
        0.20
        + (0.40 * consensus_abs)
        + (0.20 * mean_strength)
        + (0.15 if htf_confirmed else 0.0)
        + (0.10 if ltf_entry_confirmed else 0.0)
        - (0.30 if conflict else 0.0)
    )

    if mtf_alignment == "STRONG":
        score = max(score, 0.90)
    elif mtf_alignment == "CONFLICTING":
        score = min(score, 0.35)

    return {
        "mtf_alignment": mtf_alignment,
        "mtf_score": round(float(score), 4),
        "direction": direction,
        "htf_confirmed": htf_confirmed,
        "ltf_entry_confirmed": ltf_entry_confirmed,
        "conflict": conflict,
        "timeframes": timeframe_direction,
        "timeframe_strength": timeframe_strength,
        "components": {
            "consensus": round(consensus_abs, 4),
            "strength": round(_clip01(mean_strength), 4),
            "htf_confirmation": 1.0 if htf_confirmed else 0.0,
            "ltf_confirmation": 1.0 if ltf_entry_confirmed else 0.0,
            "conflict_penalty": 1.0 if conflict else 0.0,
        },
    }
