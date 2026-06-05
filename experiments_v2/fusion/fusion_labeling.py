from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

LABEL_TO_CLASS = {"SELL": -1, "HOLD": 0, "BUY": 1}
CLASS_TO_LABEL = {value: key for key, value in LABEL_TO_CLASS.items()}


@dataclass(frozen=True)
class TripleBarrierConfig:
    """Volatility-adaptive triple barrier configuration.

    Barriers are computed from ATR and scaled by local volatility regime,
    then clipped to a practical return band to avoid excessive HOLD labels.
    """

    profit_atr_mult: float = 1.15
    stop_atr_mult: float = 0.95
    min_barrier_pct: float = 0.005
    max_barrier_pct: float = 0.010
    volatility_column: str = "realized_vol_20"
    volatility_lookback: int = 64
    volatility_floor_scale: float = 0.60
    volatility_cap_scale: float = 1.40
    time_limit_1m: int = 30
    time_limit_1h: int = 4
    time_limit_5m: int = 12
    default_time_limit: int = 8
    atr_column: str = "atr_14"
    neutral_band_atr_mult: float = 0.20
    neutral_band_min_pct: float = 0.0015
    neutral_band_max_pct: float = 0.0040


def _time_limit_for_timeframe(timeframe: str, config: TripleBarrierConfig) -> int:
    token = str(timeframe).strip().lower()
    if token == "1m":
        return config.time_limit_1m
    if token == "1h":
        return config.time_limit_1h
    if token == "5m":
        return config.time_limit_5m

    match = re.fullmatch(r"(\d+)([mh])", token)
    if not match:
        return config.default_time_limit

    value = max(1, int(match.group(1)))
    unit = match.group(2)
    minutes = value * 60 if unit == "h" else value

    # 4h horizon for unknown intervals.
    return max(1, int(round(240 / minutes)))


def _fallback_atr(group: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(group.get("high"), errors="coerce")
    low = pd.to_numeric(group.get("low"), errors="coerce")
    close = pd.to_numeric(group.get("close"), errors="coerce")

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(14, min_periods=5).mean()
    return atr


def _resolve_volatility_series(group: pd.DataFrame, close: pd.Series, config: TripleBarrierConfig) -> pd.Series:
    if config.volatility_column in group.columns:
        vol = pd.to_numeric(group[config.volatility_column], errors="coerce")
    else:
        log_return = np.log(close / close.shift(1).replace(0.0, np.nan))
        vol = log_return.rolling(20, min_periods=5).std()

    vol = vol.replace([np.inf, -np.inf], np.nan)
    vol = vol.ffill()
    fallback = float(np.nanmedian(vol.to_numpy(dtype=float))) if len(vol) else np.nan
    if not np.isfinite(fallback) or fallback <= 0.0:
        fallback = 0.01
    vol = vol.fillna(fallback)
    vol = vol.clip(lower=1e-6)
    return vol


def _dynamic_barrier_returns(
    entry: float,
    atr_now: float,
    vol_now: float,
    atr_pct_anchor: float,
    vol_anchor: float,
    config: TripleBarrierConfig,
) -> tuple[float, float, float]:
    atr_pct_now = atr_now / max(entry, 1e-9)
    atr_regime = atr_pct_now / max(atr_pct_anchor, 1e-9)
    vol_regime = vol_now / max(vol_anchor, 1e-9)
    regime_scale = 0.5 * atr_regime + 0.5 * vol_regime
    regime_scale = float(
        np.clip(
            regime_scale,
            config.volatility_floor_scale,
            config.volatility_cap_scale,
        )
    )

    raw_up = float(config.profit_atr_mult * atr_pct_now * regime_scale)
    raw_down = float(config.stop_atr_mult * atr_pct_now * regime_scale)

    up_ret = float(np.clip(raw_up, config.min_barrier_pct, config.max_barrier_pct))
    down_ret = float(np.clip(raw_down, config.min_barrier_pct, config.max_barrier_pct))
    return up_ret, down_ret, regime_scale


def _label_group(group: pd.DataFrame, config: TripleBarrierConfig) -> pd.DataFrame:
    g = group.sort_values("timestamp").reset_index(drop=True).copy()

    close = pd.to_numeric(g["close"], errors="coerce")
    high = pd.to_numeric(g.get("high", close), errors="coerce").fillna(close)
    low = pd.to_numeric(g.get("low", close), errors="coerce").fillna(close)

    if config.atr_column in g.columns:
        atr = pd.to_numeric(g[config.atr_column], errors="coerce")
    else:
        atr = _fallback_atr(g)

    atr = atr.replace([np.inf, -np.inf], np.nan)
    atr = atr.ffill()
    atr = atr.fillna(close.abs() * 0.005)
    atr = atr.clip(lower=close.abs() * 0.0001)

    vol = _resolve_volatility_series(g, close=close, config=config)

    atr_pct = atr / close.abs().replace(0.0, np.nan)
    atr_pct = atr_pct.replace([np.inf, -np.inf], np.nan).ffill()
    atr_pct = atr_pct.fillna(float(np.nanmedian(atr_pct.to_numpy(dtype=float))) if len(atr_pct) else 0.01)
    atr_pct = atr_pct.clip(lower=1e-6)

    lookback = max(8, int(config.volatility_lookback))
    min_periods = max(4, lookback // 4)

    atr_anchor = atr_pct.rolling(lookback, min_periods=min_periods).median().ffill()
    vol_anchor = vol.rolling(lookback, min_periods=min_periods).median().ffill()

    atr_anchor = atr_anchor.fillna(float(np.nanmedian(atr_pct.to_numpy(dtype=float))) if len(atr_pct) else 0.01)
    vol_anchor = vol_anchor.fillna(float(np.nanmedian(vol.to_numpy(dtype=float))) if len(vol) else 0.01)

    atr_anchor = atr_anchor.clip(lower=1e-6)
    vol_anchor = vol_anchor.clip(lower=1e-6)

    n_rows = len(g)
    target_class = np.full(n_rows, np.nan)
    target_signal = np.array(["HOLD"] * n_rows, dtype=object)
    tb_event = np.array(["none"] * n_rows, dtype=object)
    pt_levels = np.full(n_rows, np.nan)
    sl_levels = np.full(n_rows, np.nan)
    up_ret_pcts = np.full(n_rows, np.nan)
    down_ret_pcts = np.full(n_rows, np.nan)
    regime_scales = np.full(n_rows, np.nan)
    tb_steps = np.full(n_rows, np.nan)

    for idx in range(n_rows):
        steps = _time_limit_for_timeframe(g.loc[idx, "timeframe"], config)
        if idx + 1 >= n_rows:
            continue

        end_idx = min(n_rows - 1, idx + steps)
        if end_idx <= idx:
            continue

        entry = float(close.iloc[idx])
        atr_now = float(atr.iloc[idx])
        vol_now = float(vol.iloc[idx])
        atr_anchor_now = float(atr_anchor.iloc[idx])
        vol_anchor_now = float(vol_anchor.iloc[idx])
        if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr_now) or atr_now <= 0:
            continue

        up_ret, down_ret, regime_scale = _dynamic_barrier_returns(
            entry=entry,
            atr_now=atr_now,
            vol_now=vol_now,
            atr_pct_anchor=atr_anchor_now,
            vol_anchor=vol_anchor_now,
            config=config,
        )

        profit_barrier = entry * (1.0 + up_ret)
        stop_barrier = entry * (1.0 - down_ret)

        label = 0
        event = "time"
        for future_idx in range(idx + 1, end_idx + 1):
            future_high = float(high.iloc[future_idx])
            future_low = float(low.iloc[future_idx])
            hit_profit = np.isfinite(future_high) and future_high >= profit_barrier
            hit_stop = np.isfinite(future_low) and future_low <= stop_barrier

            # Same-candle dual touch uses candle-close side relative to entry.
            if hit_profit and hit_stop:
                future_close = float(close.iloc[future_idx])
                if np.isfinite(future_close) and future_close >= entry:
                    label = 1
                    event = "both_hit_close_above_entry"
                else:
                    label = -1
                    event = "both_hit_close_below_entry"
                break
            if hit_profit:
                label = 1
                event = "profit"
                break
            if hit_stop:
                label = -1
                event = "stop"
                break

        if event == "time":
            expiry_close = float(close.iloc[end_idx])
            expiry_return = (expiry_close - entry) / max(entry, 1e-9)
            neutral_band_raw = config.neutral_band_atr_mult * (atr_now / max(entry, 1e-9))
            neutral_band = float(
                np.clip(
                    neutral_band_raw,
                    config.neutral_band_min_pct,
                    config.neutral_band_max_pct,
                )
            )
            if expiry_return > neutral_band:
                label = 1
                event = "time_profit"
            elif expiry_return < -neutral_band:
                label = -1
                event = "time_loss"
            else:
                label = 0
                event = "time_hold"

        target_class[idx] = int(label)
        target_signal[idx] = CLASS_TO_LABEL[int(label)]
        tb_event[idx] = event
        pt_levels[idx] = profit_barrier
        sl_levels[idx] = stop_barrier
        up_ret_pcts[idx] = up_ret
        down_ret_pcts[idx] = down_ret
        regime_scales[idx] = regime_scale
        tb_steps[idx] = int(steps)

    g["tb_profit_barrier"] = pt_levels
    g["tb_stop_barrier"] = sl_levels
    g["tb_up_return_pct"] = up_ret_pcts
    g["tb_down_return_pct"] = down_ret_pcts
    g["tb_regime_scale"] = regime_scales
    g["tb_time_steps"] = tb_steps
    g["tb_event"] = tb_event
    g["target_class"] = target_class
    g["target_signal"] = target_signal

    g = g.dropna(subset=["target_class"]).copy()
    g["target_class"] = g["target_class"].astype(int)
    return g


def generate_triple_barrier_targets(
    df: pd.DataFrame,
    config: TripleBarrierConfig = TripleBarrierConfig(),
) -> pd.DataFrame:
    """Create volatility-aware labels using Triple Barrier Method (TBM)."""
    required = {"timestamp", "symbol", "timeframe", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Triple barrier labeling needs columns: {missing}")

    ordered = df.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    blocks = [
        _label_group(group, config=config)
        for _, group in ordered.groupby(["symbol", "timeframe"], sort=False)
    ]
    if not blocks:
        return ordered.iloc[0:0].copy()

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    out["label_method"] = "triple_barrier_dynamic"
    return out


def build_shifted_targets(df: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """Backward-compatible wrapper; now delegates to TBM labeling."""
    _ = horizon
    return generate_triple_barrier_targets(df)


@dataclass(frozen=True)
class FusionThresholds:
    """Backward compatibility shim for old callers."""

    trend_strong: float = 0.002
    momentum_strong: float = 0.002
    volume_high: float = 1.20


def generate_fusion_signal(
    df: pd.DataFrame,
    thresholds: FusionThresholds = FusionThresholds(),
) -> pd.DataFrame:
    """Backward-compatible API now returning TBM labels for callers expecting fusion output."""
    _ = thresholds
    out = generate_triple_barrier_targets(df)
    out["fusion_signal"] = out["target_signal"]
    return out
