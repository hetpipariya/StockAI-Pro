"""Volume Intelligence Engine for StockAI Pro.

This module computes production-safe volume features that can be appended to the
existing price-based feature matrix.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

EPSILON = 1e-9


def _to_numeric(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan)
    return out


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_cols = [
        col
        for col in out.columns
        if out[col].dtype.kind in {"i", "u", "f", "b"} or out[col].dtype == object
    ]
    for col in numeric_cols:
        if out[col].dtype == object and out[col].dropna().map(type).eq(str).all():
            continue
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.ffill(inplace=True)
    out.fillna(0, inplace=True)
    return out


def _safe_minmax(series: pd.Series) -> pd.Series:
    values = _to_numeric(series).fillna(0.0)
    min_val = float(values.min())
    max_val = float(values.max())
    denom = max_val - min_val
    if not np.isfinite(denom) or abs(denom) <= EPSILON:
        return pd.Series(np.zeros(len(values)), index=values.index, dtype=float)
    return (values - min_val) / (denom + EPSILON)


def _safe_zscore(series: pd.Series) -> pd.Series:
    values = _to_numeric(series).fillna(0.0)
    mean_val = float(values.mean())
    std_val = float(values.std())
    if not np.isfinite(std_val) or std_val <= EPSILON:
        return pd.Series(np.zeros(len(values)), index=values.index, dtype=float)
    return (values - mean_val) / (std_val + EPSILON)


def _augment_with_derived_ai_features(
    frame: pd.DataFrame,
    close: pd.Series,
    rolling_window: int = 20,
    smoothing_span: int = 5,
) -> pd.DataFrame:
    """Build a richer derived feature surface for model consumption.

    Includes feature interactions, min-max normalization (0-1), z-score columns,
    rolling statistics, and smoothing-based stability features.
    """
    out = frame.copy()
    idx = out.index

    ema_source = out.get("ema_20")
    if ema_source is None:
        ema_source = out.get("ema_12")
    if ema_source is None:
        ema_source = pd.Series(np.zeros(len(out)), index=idx, dtype=float)
    else:
        ema_source = _to_numeric(ema_source).fillna(0.0)

    rsi_source = out.get("rsi_14")
    if rsi_source is None:
        rsi_source = out.get("rsi")
    if rsi_source is None:
        rsi_source = pd.Series(np.zeros(len(out)), index=idx, dtype=float)
    else:
        rsi_source = _to_numeric(rsi_source).fillna(0.0)

    macd_source = out.get("macd")
    if macd_source is None:
        macd_source = pd.Series(np.zeros(len(out)), index=idx, dtype=float)
    else:
        macd_source = _to_numeric(macd_source).fillna(0.0)

    volume_ratio_source = out.get("volume_ratio")
    if volume_ratio_source is None:
        volume_ratio_source = pd.Series(np.ones(len(out)), index=idx, dtype=float)
    else:
        volume_ratio_source = _to_numeric(volume_ratio_source).fillna(1.0)

    close_series = _to_numeric(close).fillna(0.0)
    if len(close_series) != len(out):
        close_series = close_series.reindex(range(len(out))).ffill().fillna(0.0)
        close_series.index = idx
    else:
        close_series.index = idx

    # 1) Feature interactions.
    out["ema_rsi"] = ema_source * rsi_source
    out["macd_volume"] = macd_source * volume_ratio_source

    # 4) Rolling statistics with 20-length context.
    out["rolling_mean_20"] = close_series.rolling(rolling_window, min_periods=1).mean()
    out["rolling_std_20"] = close_series.rolling(rolling_window, min_periods=2).std()

    numeric_cols = [
        col
        for col in out.columns
        if pd.api.types.is_numeric_dtype(out[col])
    ]
    numeric_source = out[numeric_cols].copy()

    # 2) Min-max normalization across numeric feature set (0-1).
    norm_block = pd.DataFrame(
        {
            f"{col}_norm": _safe_minmax(numeric_source[col])
            for col in numeric_cols
        },
        index=out.index,
    )
    existing_norm_cols = [col for col in norm_block.columns if col in out.columns]
    if existing_norm_cols:
        out = out.drop(columns=existing_norm_cols)

    # 3) Z-score transformation across numeric feature set.
    z_block = pd.DataFrame(
        {
            f"{col}_z": _safe_zscore(numeric_source[col])
            for col in numeric_cols
        },
        index=out.index,
    )
    existing_z_cols = [col for col in z_block.columns if col in out.columns]
    if existing_z_cols:
        out = out.drop(columns=existing_z_cols)

    # 5) Smoothing to improve stability and reduce noise.
    smooth_targets = ["ema_rsi", "macd_volume", "rolling_mean_20", "rolling_std_20"]
    smooth_block = pd.DataFrame(index=out.index)
    for col in smooth_targets:
        smoothed_col = f"{col}_smoothed"
        if col in out.columns:
            smooth_block[smoothed_col] = _to_numeric(out[col]).fillna(0.0).ewm(
                span=max(2, int(smoothing_span)),
                adjust=False,
            ).mean()
    existing_smooth_cols = [col for col in smooth_block.columns if col in out.columns]
    if existing_smooth_cols:
        out = out.drop(columns=existing_smooth_cols)

    out = pd.concat([out, norm_block, z_block, smooth_block], axis=1)

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.ffill(inplace=True)
    out.fillna(0.0, inplace=True)
    return out


def compute_volume_ratio(volume: pd.Series, window: int = 20) -> pd.DataFrame:
    """Relative volume against rolling average volume."""
    vol = _to_numeric(volume).fillna(0.0)
    avg_volume = vol.rolling(window, min_periods=1).mean()
    ratio = vol / (avg_volume + EPSILON)

    ratio_flag = np.where(ratio > 1.5, "HIGH", np.where(ratio < 0.7, "LOW", "NORMAL"))
    ratio_flag_score = np.where(ratio > 1.5, 1.0, np.where(ratio < 0.7, -1.0, 0.0))

    return pd.DataFrame(
        {
            "avg_volume_20": avg_volume,
            "volume_ratio": ratio,
            "volume_ratio_norm": np.clip(ratio / 2.0, 0.0, 2.0),
            "volume_ratio_flag": ratio_flag,
            "volume_ratio_flag_score": ratio_flag_score,
        },
        index=vol.index,
    )


def detect_volume_spike(
    volume: pd.Series,
    avg_volume: Optional[pd.Series] = None,
    window: int = 20,
    ratio_threshold: float = 2.0,
    z_threshold: float = 2.0,
) -> pd.DataFrame:
    """Detect abnormal volume bursts with ratio and z-score checks."""
    vol = _to_numeric(volume).fillna(0.0)
    avg = avg_volume if avg_volume is not None else vol.rolling(window, min_periods=1).mean()
    avg = _to_numeric(avg).fillna(0.0)

    std = vol.rolling(window, min_periods=3).std().fillna(0.0)
    ratio = vol / (avg + EPSILON)
    zscore = (vol - avg) / (std + EPSILON)

    spike_flag = (ratio >= ratio_threshold) | (zscore >= z_threshold)
    spike_strength = np.maximum(ratio / max(ratio_threshold, EPSILON), zscore / max(z_threshold, EPSILON))
    spike_strength = np.clip(spike_strength, 0.0, 4.0)

    return pd.DataFrame(
        {
            "volume_spike": spike_flag.astype(int),
            "volume_spike_strength": spike_strength,
            "volume_zscore": zscore,
            "volume_ratio_rolling": ratio,
        },
        index=vol.index,
    )


def compute_vwap_deviation(
    close: pd.Series,
    volume: pd.Series,
    neutral_band: float = 0.0025,
) -> pd.DataFrame:
    """Compute VWAP and price deviation from VWAP."""
    c = _to_numeric(close).fillna(0.0)
    v = _to_numeric(volume).fillna(0.0)

    cumulative_notional = (c * v).cumsum()
    cumulative_volume = v.cumsum()
    vwap = cumulative_notional / (cumulative_volume + EPSILON)

    deviation = (c - vwap) / (vwap + EPSILON)
    bias = np.where(
        deviation > neutral_band,
        "ABOVE",
        np.where(deviation < -neutral_band, "BELOW", "NEUTRAL"),
    )
    bias_score = np.where(deviation > neutral_band, 1.0, np.where(deviation < -neutral_band, -1.0, 0.0))

    return pd.DataFrame(
        {
            "vwap": vwap,
            "vwap_deviation": deviation,
            "vwap_bias": bias,
            "vwap_bias_score": bias_score,
        },
        index=c.index,
    )


def compute_obv_features(
    close: pd.Series,
    volume: pd.Series,
    ema_span: int = 20,
    divergence_window: int = 10,
) -> pd.DataFrame:
    """Compute OBV trend and divergence between price and OBV movement."""
    c = _to_numeric(close).fillna(0.0)
    v = _to_numeric(volume).fillna(0.0)

    direction = np.sign(c.diff().fillna(0.0))
    obv = (direction * v).cumsum()
    obv_ema = obv.ewm(span=ema_span, adjust=False).mean()
    obv_slope = obv_ema.diff().fillna(0.0)

    volume_scale = v.rolling(ema_span, min_periods=1).mean()
    obv_slope_norm = np.tanh(obv_slope / (volume_scale + EPSILON))

    price_delta = c.diff(divergence_window).fillna(0.0)
    obv_delta = obv.diff(divergence_window).fillna(0.0)
    divergence = ((price_delta > 0) & (obv_delta < 0)) | ((price_delta < 0) & (obv_delta > 0))

    return pd.DataFrame(
        {
            "obv": obv,
            "obv_ema": obv_ema,
            "obv_slope": obv_slope,
            "obv_slope_norm": obv_slope_norm,
            "obv_divergence": divergence.astype(int),
        },
        index=c.index,
    )


def compute_volume_trend_slope(
    volume: pd.Series,
    window: int = 20,
    flat_threshold: float = 0.03,
) -> pd.DataFrame:
    """Volume trend slope using fast/slow EMA comparison."""
    vol = _to_numeric(volume).fillna(0.0)
    fast_span = max(3, window // 2)

    ema_fast = vol.ewm(span=fast_span, adjust=False).mean()
    ema_slow = vol.ewm(span=max(window, fast_span + 1), adjust=False).mean()

    slope = (ema_fast - ema_slow) / (ema_slow + EPSILON)
    direction = np.where(slope > flat_threshold, "UP", np.where(slope < -flat_threshold, "DOWN", "FLAT"))
    direction_score = np.where(slope > flat_threshold, 1.0, np.where(slope < -flat_threshold, -1.0, 0.0))

    return pd.DataFrame(
        {
            "volume_trend_slope": slope,
            "volume_trend_direction": direction,
            "volume_trend_direction_score": direction_score,
        },
        index=vol.index,
    )


def build_feature_vector(
    ohlcv_df: pd.DataFrame,
    base_features: Optional[pd.DataFrame] = None,
    volume_window: int = 20,
) -> pd.DataFrame:
    """Compatibility wrapper that returns the enhanced feature vector."""
    return build_enhanced_feature_vector(
        ohlcv_df=ohlcv_df,
        base_features=base_features,
        volume_window=volume_window,
    )


def build_enhanced_feature_vector(
    ohlcv_df: pd.DataFrame,
    base_features: Optional[pd.DataFrame] = None,
    volume_window: int = 20,
    rolling_window: int = 20,
    smoothing_span: int = 5,
) -> pd.DataFrame:
    """Merge base features and return an enhanced_feature_vector.

    Output includes:
    - feature interactions: ema_rsi, macd_volume
    - min-max normalized variants: *_norm
    - z-score variants: *_z
    - rolling stats: rolling_mean_20, rolling_std_20
    - stability-smoothed variants: *_smoothed
    """
    if ohlcv_df is None or len(ohlcv_df) == 0:
        return pd.DataFrame() if base_features is None else base_features.copy()

    df = ohlcv_df.copy()
    df.columns = [str(col).lower() for col in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        return pd.DataFrame() if base_features is None else base_features.copy()

    close = _to_numeric(df["close"]).fillna(0.0).reset_index(drop=True)
    volume = _to_numeric(df["volume"]).fillna(0.0).reset_index(drop=True)

    ratio_df = compute_volume_ratio(volume, window=volume_window).reset_index(drop=True)
    spike_df = detect_volume_spike(
        volume,
        avg_volume=ratio_df["avg_volume_20"],
        window=volume_window,
    ).reset_index(drop=True)
    vwap_df = compute_vwap_deviation(close, volume).reset_index(drop=True)
    obv_df = compute_obv_features(close, volume).reset_index(drop=True)
    slope_df = compute_volume_trend_slope(volume, window=volume_window).reset_index(drop=True)

    parts = []
    if base_features is not None and not base_features.empty:
        parts.append(base_features.reset_index(drop=True).copy())

    parts.extend([ratio_df, spike_df, vwap_df, obv_df, slope_df])

    merged = pd.concat(parts, axis=1)
    merged = merged.loc[:, ~merged.columns.duplicated(keep="last")]

    numeric_cols = [
        col
        for col in merged.columns
        if col not in {"volume_ratio_flag", "vwap_bias", "volume_trend_direction"}
    ]
    merged[numeric_cols] = merged[numeric_cols].apply(pd.to_numeric, errors="coerce")
    merged[numeric_cols] = merged[numeric_cols].replace([np.inf, -np.inf], np.nan)
    merged[numeric_cols] = merged[numeric_cols].ffill().fillna(0.0)

    merged["volume_ratio_flag"] = merged["volume_ratio_flag"].fillna("NORMAL")
    merged["vwap_bias"] = merged["vwap_bias"].fillna("NEUTRAL")
    merged["volume_trend_direction"] = merged["volume_trend_direction"].fillna("FLAT")

    merged = _normalize_frame(merged)

    enhanced_feature_vector = _augment_with_derived_ai_features(
        merged,
        close=close,
        rolling_window=rolling_window,
        smoothing_span=smoothing_span,
    )
    return _normalize_frame(enhanced_feature_vector)
