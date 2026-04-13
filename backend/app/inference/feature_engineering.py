"""
feature_engineering.py — Single Source of Truth for ML Features
================================================================

Both training and inference MUST import from this module.
Any change to feature computation happens HERE and only here.

Feature set version: v2.0 (19 columns)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Canonical Feature Columns (ORDER MATTERS) ────────────────────────────────
FEATURE_COLUMNS: list[str] = [
    "price_change",
    "volume_change",
    "high_low_diff",
    "open_close_diff",
    "rolling_mean_5",
    "rolling_std_5",
    "rolling_mean_10",
    "rolling_std_10",
    "momentum",
    "rsi",
    "ema_12",
    "ema_26",
    "macd",
    "bollinger_upper",
    "bollinger_lower",
    "volatility",
    "lag_1",
    "lag_2",
    "lag_3",
]

FEATURE_VERSION = "v2.0"
MIN_ROWS_FOR_FEATURES = 50
PRICE_ACTION_STREAK_WINDOW = 5
EPSILON = 1e-9


def _empty_feature_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=FEATURE_COLUMNS)


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _sanitize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with invalid OHLCV values.

    Invalid rows (NaN/null/negative/zero prices) are skipped rather than filled.
    """
    out = df.copy()
    required = ["open", "high", "low", "close", "volume"]

    valid = out[required].notna().all(axis=1)
    valid &= (out["open"] > 0)
    valid &= (out["high"] > 0)
    valid &= (out["low"] > 0)
    valid &= (out["close"] > 0)
    valid &= (out["volume"] >= 0)
    valid &= (out["high"] >= out["low"])

    cleaned = out.loc[valid].copy().reset_index(drop=True)
    dropped = len(out) - len(cleaned)
    if dropped > 0:
        logger.warning("[FEATURES] Dropped %d invalid OHLCV rows", dropped)
    return cleaned


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _consecutive_count(flags: pd.Series) -> pd.Series:
    counts: list[int] = []
    running = 0
    for value in flags.fillna(False).tolist():
        if bool(value):
            running += 1
        else:
            running = 0
        counts.append(running)
    return pd.Series(counts, index=flags.index)


def _compute_price_action_columns(
    raw_df: pd.DataFrame,
    streak_window: int = PRICE_ACTION_STREAK_WINDOW,
) -> pd.DataFrame:
    close = raw_df["close"]
    high = raw_df["high"]
    low = raw_df["low"]
    open_price = raw_df["open"]

    candle_range = (high - low).clip(lower=0.0)
    body = (close - open_price).abs()
    body_pct = body / (candle_range + EPSILON)

    max_open_close = pd.concat([open_price, close], axis=1).max(axis=1)
    min_open_close = pd.concat([open_price, close], axis=1).min(axis=1)

    upper_wick_pct = (high - max_open_close).clip(lower=0.0) / (candle_range + EPSILON)
    lower_wick_pct = (min_open_close - low).clip(lower=0.0) / (candle_range + EPSILON)

    prev_body = body.shift(1).fillna(0.0)
    prev_open = open_price.shift(1)
    prev_close = close.shift(1)

    bullish_engulfing = (
        (body > prev_body)
        & (close > prev_open)
        & (open_price < prev_close)
    ).astype(int)
    bearish_engulfing = (
        (body > prev_body)
        & (close < prev_open)
        & (open_price > prev_close)
    ).astype(int)

    doji_flag = (body < (candle_range * 0.10)).astype(int)

    green_flags = close > open_price
    red_flags = close < open_price
    consecutive_green = _consecutive_count(green_flags)
    consecutive_red = _consecutive_count(red_flags)
    streak_strength_score = (
        np.maximum(consecutive_green, consecutive_red) / max(int(streak_window), 1)
    ).clip(lower=0.0, upper=1.0)

    strong_green_candle = ((close > open_price) & (body_pct > 0.70)).astype(int)
    strong_red_candle = ((close < open_price) & (body_pct > 0.70)).astype(int)

    sentiment_raw = ((close - open_price) / (candle_range + EPSILON)) + (
        lower_wick_pct - upper_wick_pct
    )
    candle_sentiment_score = sentiment_raw.clip(lower=-1.0, upper=1.0)

    return pd.DataFrame(
        {
            "body_pct": body_pct,
            "body_strength_score": body_pct.clip(lower=0.0, upper=1.0),
            "upper_wick_pct": upper_wick_pct.clip(lower=0.0, upper=1.0),
            "lower_wick_pct": lower_wick_pct.clip(lower=0.0, upper=1.0),
            "bullish_engulfing": bullish_engulfing,
            "bearish_engulfing": bearish_engulfing,
            "doji_flag": doji_flag,
            "strong_green_candle": strong_green_candle,
            "strong_red_candle": strong_red_candle,
            "consecutive_green": consecutive_green,
            "consecutive_red": consecutive_red,
            "streak_strength_score": streak_strength_score,
            "candle_sentiment_score": candle_sentiment_score,
        },
        index=raw_df.index,
    )


def _add_legacy_aliases(feature_df: pd.DataFrame, raw_df: pd.DataFrame) -> pd.DataFrame:
    """Add legacy columns expected by older modules/models.

    This keeps existing trading/backtest paths stable while canonical features
    move to the v2.0 contract.
    """
    out = feature_df.copy()
    close = raw_df["close"]
    high = raw_df["high"]
    low = raw_df["low"]
    volume = raw_df["volume"]

    out["ema_9"] = close.ewm(span=9, adjust=False).mean()
    out["ema_20"] = close.ewm(span=20, adjust=False).mean()
    out["ema_21"] = close.ewm(span=21, adjust=False).mean()
    out["ema_50"] = close.ewm(span=50, adjust=False).mean()
    out["rsi_14"] = out.get("rsi", _compute_rsi(close))

    out["macd_signal"] = pd.to_numeric(out["macd"], errors="coerce").ewm(
        span=9,
        adjust=False,
    ).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    typical_price = (high + low + close) / 3
    out["vwap"] = (typical_price * volume).cumsum() / (volume.cumsum() + 1e-9)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    out["atr_14"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    vol_ma = volume.rolling(20, min_periods=1).mean()
    out["volume_spike"] = (volume > (vol_ma * 2.0)).astype(int)
    out["pct_change_1d"] = close.pct_change(1)
    out["roll_std_5d"] = out["pct_change_1d"].rolling(5).std()
    out["trend_strength"] = (close - out["ema_20"]) / (out["ema_20"] + 1e-9)

    price_action_df = _compute_price_action_columns(raw_df)
    for column in price_action_df.columns:
        out[column] = price_action_df[column]

    out["doji"] = out["doji_flag"].astype(int)

    out.replace([np.inf, -np.inf], 0, inplace=True)
    out.ffill(inplace=True)
    out.fillna(0, inplace=True)
    return out


def _aligned_raw_series(raw_df: pd.DataFrame, name: str, index: pd.Index) -> pd.Series:
    if name not in raw_df.columns:
        return pd.Series(np.zeros(len(index), dtype=float), index=index)

    series = pd.to_numeric(raw_df[name], errors="coerce").reset_index(drop=True)
    if len(series) < len(index):
        series = series.reindex(range(len(index)))
    elif len(series) > len(index):
        series = series.iloc[: len(index)]

    series.index = index
    return series.ffill().fillna(0.0)


def apply_feature_compatibility(
    feature_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    required_features: list[str],
) -> pd.DataFrame:
    """Expand feature matrix to legacy/high-dimensional contracts.

    This helper is used for backward compatibility with older model artifacts
    that expect significantly more than the canonical 19 features.
    Missing features are computed where possible and otherwise defaulted to 0.0.
    """
    out = feature_df.copy() if feature_df is not None else pd.DataFrame()
    if not required_features:
        return out

    if out.empty and (ohlcv_df is None or len(ohlcv_df) == 0):
        return out

    out = out.reset_index(drop=True)

    raw = ohlcv_df.copy() if ohlcv_df is not None else pd.DataFrame()
    raw.columns = [str(col).lower() for col in raw.columns]
    raw = raw.reset_index(drop=True)

    if out.empty:
        out = pd.DataFrame(index=raw.index)

    index = out.index

    close_series = _aligned_raw_series(raw, "close", index)
    open_series = _aligned_raw_series(raw, "open", index)
    high_series = _aligned_raw_series(raw, "high", index)
    low_series = _aligned_raw_series(raw, "low", index)
    volume_series = _aligned_raw_series(raw, "volume", index)

    ema9 = close_series.ewm(span=9, adjust=False).mean()
    ema12 = close_series.ewm(span=12, adjust=False).mean()
    ema20 = close_series.ewm(span=20, adjust=False).mean()
    ema21 = close_series.ewm(span=21, adjust=False).mean()
    ema26 = close_series.ewm(span=26, adjust=False).mean()
    ema50 = close_series.ewm(span=50, adjust=False).mean()
    macd_series = (
        pd.to_numeric(out["macd"], errors="coerce")
        if "macd" in out.columns
        else (ema12 - ema26)
    )
    macd_signal = macd_series.ewm(span=9, adjust=False).mean()

    delta = close_series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi14 = 100 - (100 / (1 + rs))

    tr1 = high_series - low_series
    tr2 = (high_series - close_series.shift(1)).abs()
    tr3 = (low_series - close_series.shift(1)).abs()
    atr14 = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    typical_price = (high_series + low_series + close_series) / 3
    vwap = (typical_price * volume_series).cumsum() / (volume_series.cumsum() + EPSILON)

    pct_change_1d = close_series.pct_change(1)
    vol_ma20 = volume_series.rolling(20, min_periods=1).mean()
    vol_std20 = volume_series.rolling(20, min_periods=3).std()
    volume_ratio_series = volume_series / (vol_ma20 + EPSILON)
    volume_zscore_series = (volume_series - vol_ma20) / (vol_std20 + EPSILON)
    volume_spike_strength_series = np.maximum(
        volume_ratio_series / 2.0,
        volume_zscore_series / 2.0,
    )
    vwap_dev_series = (close_series - vwap) / (vwap + EPSILON)

    obv_direction = np.sign(close_series.diff().fillna(0.0))
    obv_series = (obv_direction * volume_series).cumsum()
    obv_ema = obv_series.ewm(span=20, adjust=False).mean()
    obv_slope = obv_ema.diff()
    obv_slope_norm = np.tanh(obv_slope / (vol_ma20 + EPSILON))
    obv_divergence = (
        ((close_series.diff(10) > 0) & (obv_series.diff(10) < 0))
        | ((close_series.diff(10) < 0) & (obv_series.diff(10) > 0))
    ).astype(int)

    volume_fast = volume_series.ewm(span=10, adjust=False).mean()
    volume_slow = volume_series.ewm(span=20, adjust=False).mean()
    volume_trend_slope = (volume_fast - volume_slow) / (volume_slow + EPSILON)
    volume_trend_direction_score = np.where(
        volume_trend_slope > 0.03,
        1.0,
        np.where(volume_trend_slope < -0.03, -1.0, 0.0),
    )

    if {"open", "high", "low", "close"}.issubset(raw.columns):
        price_action = _compute_price_action_columns(raw)
        price_action = price_action.reset_index(drop=True).reindex(index)
    else:
        price_action = pd.DataFrame(index=index)

    compatibility_builders: dict[str, Any] = {
        "open": lambda: open_series,
        "high": lambda: high_series,
        "low": lambda: low_series,
        "close": lambda: close_series,
        "volume": lambda: volume_series,
        "ema_9": lambda: ema9,
        "ema_20": lambda: ema20,
        "ema_21": lambda: ema21,
        "ema_50": lambda: ema50,
        "ema_12": lambda: ema12,
        "ema_26": lambda: ema26,
        "rsi_14": lambda: rsi14,
        "rsi": lambda: rsi14,
        "macd": lambda: macd_series,
        "macd_signal": lambda: macd_signal,
        "macd_hist": lambda: macd_series - macd_signal,
        "vwap": lambda: vwap,
        "atr_14": lambda: atr14,
        "volume_spike": lambda: (volume_series > (vol_ma20 * 2.0)).astype(int),
        "avg_volume_20": lambda: vol_ma20,
        "volume_ratio": lambda: volume_ratio_series,
        "volume_ratio_norm": lambda: np.clip(volume_ratio_series / 2.0, 0.0, 2.0),
        "volume_ratio_flag_score": lambda: np.where(
            volume_ratio_series > 1.5,
            1.0,
            np.where(volume_ratio_series < 0.7, -1.0, 0.0),
        ),
        "volume_spike_strength": lambda: np.clip(volume_spike_strength_series, 0.0, 4.0),
        "volume_zscore": lambda: volume_zscore_series,
        "volume_ratio_rolling": lambda: volume_ratio_series,
        "vwap_deviation": lambda: vwap_dev_series,
        "vwap_bias_score": lambda: np.where(
            vwap_dev_series > 0.0025,
            1.0,
            np.where(vwap_dev_series < -0.0025, -1.0, 0.0),
        ),
        "obv": lambda: obv_series,
        "obv_ema": lambda: obv_ema,
        "obv_slope": lambda: obv_slope,
        "obv_slope_norm": lambda: obv_slope_norm,
        "obv_divergence": lambda: obv_divergence,
        "volume_trend_slope": lambda: volume_trend_slope,
        "volume_trend_direction_score": lambda: volume_trend_direction_score,
        "price_change": lambda: close_series.diff(),
        "volatility": lambda: close_series.pct_change().rolling(10, min_periods=3).std(),
        "momentum": lambda: close_series - close_series.shift(3),
        "rolling_mean_5": lambda: close_series.rolling(5, min_periods=1).mean(),
        "rolling_std_5": lambda: close_series.rolling(5, min_periods=2).std(),
        "rolling_mean_10": lambda: close_series.rolling(10, min_periods=1).mean(),
        "rolling_std_10": lambda: close_series.rolling(10, min_periods=2).std(),
        "pct_change_1d": lambda: pct_change_1d,
        "roll_std_5d": lambda: pct_change_1d.rolling(5, min_periods=2).std(),
        "trend_strength": lambda: (close_series - ema20) / (ema20 + EPSILON),
        "volume_change": lambda: volume_series.pct_change(),
        "high_low_diff": lambda: high_series - low_series,
        "open_close_diff": lambda: open_series - close_series,
        "bollinger_upper": lambda: close_series.rolling(20, min_periods=5).mean()
        + (2 * close_series.rolling(20, min_periods=5).std()),
        "bollinger_lower": lambda: close_series.rolling(20, min_periods=5).mean()
        - (2 * close_series.rolling(20, min_periods=5).std()),
        "lag_1": lambda: close_series.shift(1),
        "lag_2": lambda: close_series.shift(2),
        "lag_3": lambda: close_series.shift(3),
        "pct_change_5d": lambda: close_series.pct_change(5),
        "roll_mean_5d": lambda: close_series.rolling(5, min_periods=1).mean(),
        "roll_mean_20d": lambda: close_series.rolling(20, min_periods=1).mean(),
        "roll_std_20d": lambda: close_series.pct_change(1)
        .rolling(20, min_periods=2)
        .std(),
        "rsi_momentum": lambda: rsi14.diff(),
        "body_strength_score": lambda: price_action.get(
            "body_strength_score",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "upper_wick_pct": lambda: price_action.get(
            "upper_wick_pct",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "lower_wick_pct": lambda: price_action.get(
            "lower_wick_pct",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "bullish_engulfing": lambda: price_action.get(
            "bullish_engulfing",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "bearish_engulfing": lambda: price_action.get(
            "bearish_engulfing",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "doji_flag": lambda: price_action.get(
            "doji_flag",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "consecutive_green": lambda: price_action.get(
            "consecutive_green",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "consecutive_red": lambda: price_action.get(
            "consecutive_red",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "streak_strength_score": lambda: price_action.get(
            "streak_strength_score",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
        "candle_sentiment_score": lambda: price_action.get(
            "candle_sentiment_score",
            pd.Series(np.zeros(len(index), dtype=float), index=index),
        ),
    }

    missing_features: list[str] = []
    computed_additions: dict[str, Any] = {}
    zero_fill_features: list[str] = []
    for feature_name in required_features:
        if feature_name in out.columns:
            continue
        builder = compatibility_builders.get(feature_name)
        if builder is not None:
            computed_additions[feature_name] = builder()
        else:
            zero_fill_features.append(feature_name)
        missing_features.append(feature_name)

    frames_to_concat: list[pd.DataFrame] = [out]
    if computed_additions:
        computed_frame = pd.DataFrame(computed_additions, index=index)
        frames_to_concat.append(computed_frame)
    if zero_fill_features:
        zero_frame = pd.DataFrame(0.0, index=index, columns=zero_fill_features)
        frames_to_concat.append(zero_frame)

    if len(frames_to_concat) > 1:
        out = pd.concat(frames_to_concat, axis=1)

    for feature_name in required_features:
        out[feature_name] = pd.to_numeric(out[feature_name], errors="coerce").fillna(0.0)

    out.replace([np.inf, -np.inf], 0.0, inplace=True)
    out.fillna(0.0, inplace=True)

    if missing_features:
        logger.warning(
            "[FEATURES] Compatibility injected %d missing features; sample=%s",
            len(missing_features),
            missing_features[:15],
        )

    return out


def compute_features(
    ohlcv_df: pd.DataFrame,
    include_legacy: bool = False,
) -> pd.DataFrame:
    """Compute canonical 19-feature contract from raw OHLCV candles.

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        Must contain columns: open, high, low, close, volume.
    include_legacy : bool
        If True, appends legacy alias columns for older consumers.

    Returns
    -------
    pd.DataFrame
        Canonical feature matrix with the 19 columns in FEATURE_COLUMNS.
        If include_legacy=True, legacy columns are appended for compatibility.
    """
    empty = _empty_feature_frame()

    if ohlcv_df is None or len(ohlcv_df) < MIN_ROWS_FOR_FEATURES:
        return empty

    df = ohlcv_df.copy()
    df.columns = [str(c).lower() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        logger.warning("[FEATURES] Missing required columns: %s", sorted(missing))
        return empty

    df = _coerce_numeric(df, ["open", "high", "low", "close", "volume"])
    df = _sanitize_ohlcv(df)

    if len(df) < MIN_ROWS_FOR_FEATURES:
        logger.warning(
            "[FEATURES] Insufficient valid candles after sanitization: %d < %d",
            len(df),
            MIN_ROWS_FOR_FEATURES,
        )
        return empty

    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_price = df["open"]
    volume = df["volume"]

    features = pd.DataFrame(index=df.index)

    features["price_change"] = close.diff()
    features["volume_change"] = volume.pct_change()
    features["high_low_diff"] = high - low
    features["open_close_diff"] = open_price - close

    features["rolling_mean_5"] = close.rolling(5, min_periods=1).mean()
    features["rolling_std_5"] = close.rolling(5, min_periods=2).std()
    features["rolling_mean_10"] = close.rolling(10, min_periods=1).mean()
    features["rolling_std_10"] = close.rolling(10, min_periods=2).std()

    features["momentum"] = close - close.shift(3)
    features["rsi"] = _compute_rsi(close, period=14)

    features["ema_12"] = close.ewm(span=12, adjust=False).mean()
    features["ema_26"] = close.ewm(span=26, adjust=False).mean()
    features["macd"] = features["ema_12"] - features["ema_26"]

    bb_mid = close.rolling(20, min_periods=5).mean()
    bb_std = close.rolling(20, min_periods=5).std()
    features["bollinger_upper"] = bb_mid + 2 * bb_std
    features["bollinger_lower"] = bb_mid - 2 * bb_std

    features["volatility"] = close.pct_change().rolling(10, min_periods=3).std()

    features["lag_1"] = close.shift(1)
    features["lag_2"] = close.shift(2)
    features["lag_3"] = close.shift(3)

    features.replace([np.inf, -np.inf], np.nan, inplace=True)
    features.ffill(inplace=True)
    features.fillna(0, inplace=True)

    out = features[FEATURE_COLUMNS].copy()
    if include_legacy:
        out = _add_legacy_aliases(out, df)

    return out


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
