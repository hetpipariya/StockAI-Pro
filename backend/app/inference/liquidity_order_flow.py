"""Liquidity & Order Flow Proxy Engine for intraday signal quality."""

from __future__ import annotations

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


def _extract_session_open_and_prev_close(
    ohlcv_df: pd.DataFrame,
    open_series: pd.Series,
    close_series: pd.Series,
) -> tuple[float, float]:
    current_open = float(open_series.iloc[-1])
    prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else float(close_series.iloc[-1])

    for column in ("time", "timestamp", "datetime", "date"):
        if column not in ohlcv_df.columns:
            continue

        ts = pd.to_datetime(ohlcv_df[column], errors="coerce")
        if ts.isna().all():
            continue

        frame = pd.DataFrame(
            {
                "ts": ts,
                "open": open_series,
                "close": close_series,
            }
        ).dropna(subset=["ts", "open", "close"])

        if frame.empty:
            continue

        frame["day"] = frame["ts"].dt.date
        latest_day = frame["day"].iloc[-1]
        latest_day_rows = frame[frame["day"] == latest_day]
        if latest_day_rows.empty:
            continue

        session_open = float(latest_day_rows["open"].iloc[0])
        prior_rows = frame[frame["day"] < latest_day]
        if not prior_rows.empty:
            prior_close = float(prior_rows["close"].iloc[-1])
        elif len(frame) >= 2:
            prior_close = float(frame["close"].iloc[-2])
        else:
            prior_close = float(latest_day_rows["close"].iloc[-1])

        return session_open, prior_close

    return current_open, prev_close


def compute_liquidity_order_flow(
    ohlcv_df: pd.DataFrame | None,
    jump_threshold: float = 0.015,
    gap_threshold: float = 0.008,
    impact_window: int = 20,
    sweep_lookback: int = 20,
) -> dict[str, Any]:
    """Compute liquidity and order-flow proxy metrics from OHLCV candles."""

    def _fallback(reason: str) -> dict[str, Any]:
        return {
            "liquidity_score": 0.5,
            "price_impact": 0.0,
            "price_impact_ratio": 1.0,
            "jump_flag": False,
            "jump_magnitude": 0.0,
            "gap": 0.0,
            "gap_flag": "NO_GAP",
            "gap_continuation": False,
            "gap_rejection": False,
            "liquidity_sweep": False,
            "sweep_type": "NONE",
            "strong_move": False,
            "flow_state": "NEUTRAL",
            "volume_ratio": 1.0,
            "components": {
                "impact": 0.5,
                "jump": 0.45,
                "gap": 0.5,
                "sweep": 0.5,
                "volume": 0.5,
            },
            "reason": reason,
        }

    required = {"open", "high", "low", "close", "volume"}
    if ohlcv_df is None or not required.issubset(set(ohlcv_df.columns)):
        return _fallback("missing_columns")

    frame_cols = ["open", "high", "low", "close", "volume"]
    if "time" in ohlcv_df.columns:
        frame_cols = ["time", *frame_cols]
    elif "timestamp" in ohlcv_df.columns:
        frame_cols = ["timestamp", *frame_cols]
    elif "datetime" in ohlcv_df.columns:
        frame_cols = ["datetime", *frame_cols]
    elif "date" in ohlcv_df.columns:
        frame_cols = ["date", *frame_cols]

    frame = ohlcv_df[frame_cols].copy()
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=["open", "high", "low", "close", "volume"]).reset_index(drop=True)

    if len(frame) < 3:
        return _fallback("insufficient_candles")

    open_series = _numeric_series(frame, "open").dropna().reset_index(drop=True)
    high_series = _numeric_series(frame, "high").dropna().reset_index(drop=True)
    low_series = _numeric_series(frame, "low").dropna().reset_index(drop=True)
    close_series = _numeric_series(frame, "close").dropna().reset_index(drop=True)
    volume_series = _numeric_series(frame, "volume").dropna().reset_index(drop=True)

    if len(close_series) < 3 or len(volume_series) < 3:
        return _fallback("invalid_series")

    current_open = float(open_series.iloc[-1])
    current_high = float(high_series.iloc[-1])
    current_low = float(low_series.iloc[-1])
    current_close = float(close_series.iloc[-1])
    prev_close = float(close_series.iloc[-2])
    current_volume = float(max(volume_series.iloc[-1], 1.0))

    impact_series = close_series.diff().abs() / (volume_series.replace(0, np.nan) + EPSILON)
    impact_series = impact_series.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    price_impact = float(impact_series.iloc[-1])

    impact_baseline = float(impact_series.tail(max(impact_window, 5)).median())
    if impact_baseline <= 0:
        impact_baseline = max(float(impact_series.tail(max(impact_window, 5)).mean()), 1e-12)
    price_impact_ratio = price_impact / max(impact_baseline, 1e-12)

    jump_magnitude = abs(current_close - prev_close) / max(abs(prev_close), EPSILON)
    jump_flag = bool(jump_magnitude >= jump_threshold)

    avg_volume_20 = float(volume_series.tail(20).mean())
    volume_ratio = current_volume / max(avg_volume_20, EPSILON)
    volume_spike = bool(volume_ratio >= 1.4)
    strong_move = bool(jump_flag and volume_spike)

    session_open, reference_prev_close = _extract_session_open_and_prev_close(
        frame,
        open_series,
        close_series,
    )
    gap = (session_open - reference_prev_close) / max(abs(reference_prev_close), EPSILON)

    if gap >= gap_threshold:
        gap_flag = "GAP_UP"
    elif gap <= -gap_threshold:
        gap_flag = "GAP_DOWN"
    else:
        gap_flag = "NO_GAP"

    gap_continuation = False
    gap_rejection = False
    if gap_flag == "GAP_UP":
        gap_continuation = bool(current_close > session_open and current_close > reference_prev_close)
        gap_rejection = bool(current_close < reference_prev_close)
    elif gap_flag == "GAP_DOWN":
        gap_continuation = bool(current_close < session_open and current_close < reference_prev_close)
        gap_rejection = bool(current_close > reference_prev_close)

    candle_range = max(current_high - current_low, EPSILON)
    upper_wick_pct = max(current_high - max(current_open, current_close), 0.0) / candle_range
    lower_wick_pct = max(min(current_open, current_close) - current_low, 0.0) / candle_range

    lookback = int(max(3, min(sweep_lookback, len(frame) - 1)))
    prior_high = float(high_series.iloc[-(lookback + 1):-1].max()) if len(high_series) > 1 else current_high
    prior_low = float(low_series.iloc[-(lookback + 1):-1].min()) if len(low_series) > 1 else current_low

    bullish_sweep = bool(
        lower_wick_pct > 0.45
        and current_low < prior_low
        and current_close > current_open
    )
    bearish_sweep = bool(
        upper_wick_pct > 0.45
        and current_high > prior_high
        and current_close < current_open
    )

    liquidity_sweep = bool(bullish_sweep or bearish_sweep)
    if bullish_sweep:
        sweep_type = "BULLISH_SWEEP"
    elif bearish_sweep:
        sweep_type = "BEARISH_SWEEP"
    else:
        sweep_type = "NONE"

    gap_component = 0.5
    gap_setup = "NONE"
    if gap_continuation:
        gap_component = 0.85
        gap_setup = "BREAKOUT"
    elif gap_rejection:
        gap_component = 0.15
        gap_setup = "TRAP"

    jump_component = 1.0 if strong_move else (0.65 if jump_flag else 0.45)
    impact_component = _clip01(1.0 - max(0.0, price_impact_ratio - 1.0) / 2.5)
    sweep_component = 0.75 if liquidity_sweep else 0.5
    volume_component = _clip01((volume_ratio - 0.7) / 1.3)

    liquidity_score = _clip01(
        (0.25 * impact_component)
        + (0.25 * jump_component)
        + (0.20 * gap_component)
        + (0.15 * sweep_component)
        + (0.15 * volume_component)
    )

    if gap_setup == "TRAP":
        liquidity_score = min(liquidity_score, 0.35)
    if strong_move and gap_setup == "BREAKOUT":
        liquidity_score = _clip01(liquidity_score + 0.10)

    if gap_setup == "TRAP":
        flow_state = "TRAP"
    elif strong_move and gap_setup == "BREAKOUT":
        flow_state = "STRONG_BREAKOUT"
    elif strong_move:
        flow_state = "STRONG_MOVE"
    elif liquidity_sweep:
        flow_state = "LIQUIDITY_SWEEP"
    else:
        flow_state = "NEUTRAL"

    return {
        "liquidity_score": round(float(liquidity_score), 4),
        "price_impact": round(float(price_impact), 8),
        "price_impact_ratio": round(float(price_impact_ratio), 4),
        "jump_flag": jump_flag,
        "jump_magnitude": round(float(jump_magnitude), 6),
        "gap": round(float(gap), 6),
        "gap_flag": gap_flag,
        "gap_continuation": gap_continuation,
        "gap_rejection": gap_rejection,
        "liquidity_sweep": liquidity_sweep,
        "sweep_type": sweep_type,
        "strong_move": strong_move,
        "flow_state": flow_state,
        "volume_ratio": round(float(volume_ratio), 4),
        "components": {
            "impact": round(float(impact_component), 4),
            "jump": round(float(jump_component), 4),
            "gap": round(float(gap_component), 4),
            "sweep": round(float(sweep_component), 4),
            "volume": round(float(volume_component), 4),
        },
    }
