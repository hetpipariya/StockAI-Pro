"""
multi_timeframe_dataset.py
==========================
High-quality multi-timeframe ML dataset builder for trading prediction.

Dataset Structure
-----------------
- Base timeframe  : 5m candles (prediction target)
- 1m aggregated   : last-5m return, intra-bar volatility, volume spike
- 1h context      : trend direction, higher-timeframe RSI/EMA/ATR

Labeling (no data leakage)
--------------------------
ATR-based dynamic barriers:
    BUY  (label=1) : future_return > atr_barrier_pct
    SELL (label=-1): future_return < -atr_barrier_pct
    HOLD (label=0) : otherwise

Data Filtering
--------------
Low-movement bars (ATR below minimum threshold) are removed to keep
only high-confidence, tradeable samples.

Feature Selection
-----------------
Strong features only:
  5m base   : log_return, log_return_5, log_return_20, rsi_14,
              ema_9, ema_21, ema_spread, macd, macd_hist,
              atr_pct, bb_width, volume_ratio, vwap_dev, obv_slope
  1m agg    : ret_1m_last, vol_1m, volume_spike_1m
  1h ctx    : h1_trend_dir, h1_rsi, h1_ema_spread, h1_atr_pct, h1_macd

Removed weak features
---------------------
- minute_of_day, hour_of_day, day_of_week (time-based encodings)
- raw candle color flags (strong_green_candle, strong_red_candle)
- raw price lag levels (lag_1, lag_2, lag_3 — replaced by log returns)
- rolling price means (replaced by EMA / normalised deviations)

Usage
-----
    from app.services.multi_timeframe_dataset import MultiTimeframeDatasetBuilder

    builder = MultiTimeframeDatasetBuilder()
    df = builder.build(df_5m, df_1m=df_1m, df_1h=df_1h)
    X, y = builder.get_Xy(df)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EPSILON = 1e-9

# Canonical feature columns produced by this builder (ORDER MATTERS)
MTF_FEATURE_COLUMNS: list[str] = [
    # 5m base — returns
    "log_return",
    "log_return_5",
    "log_return_20",
    # 5m base — momentum / trend
    "rsi_14",
    "ema_9",
    "ema_21",
    "ema_spread",
    # 5m base — MACD
    "macd",
    "macd_hist",
    # 5m base — volatility / risk
    "atr_pct",
    "bb_width",
    # 5m base — volume
    "volume_ratio",
    "vwap_dev",
    "obv_slope",
    # 1m aggregated — intra-bar microstructure
    "ret_1m_last",
    "vol_1m",
    "volume_spike_1m",
    # 1h context — higher-timeframe regime
    "h1_trend_dir",
    "h1_rsi",
    "h1_ema_spread",
    "h1_atr_pct",
    "h1_macd",
]

# Label constants
LABEL_BUY = 1
LABEL_SELL = -1
LABEL_HOLD = 0

# Defaults
DEFAULT_LABEL_HORIZON = 3        # bars ahead to look for the label (3 × 5m = 15 min)
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_BARRIER_MULT = 0.5   # fraction of ATR used as barrier
DEFAULT_FIXED_BARRIER_PCT = 0.02 # 2% fixed threshold (fallback)
DEFAULT_MIN_ATR_PCT = 0.001      # 0.1% — filter out ultra-low volatility bars
MIN_ROWS = 60                    # minimum rows for reliable feature computation


# ---------------------------------------------------------------------------
# Low-level indicator helpers (pure pandas/numpy — no external TA library)
# ---------------------------------------------------------------------------

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + EPSILON)
    return 100 - 100 / (1 + rs)


def _macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series]:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _bollinger_width(close: pd.Series, period: int = 20) -> pd.Series:
    sma = close.rolling(period, min_periods=5).mean()
    std = close.rolling(period, min_periods=5).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    return (upper - lower) / (sma + EPSILON)


def _vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    return (typical * df["volume"]).cumsum() / (df["volume"].cumsum() + EPSILON)


def _obv_slope(df: pd.DataFrame, ema_span: int = 10) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    obv = (direction * df["volume"]).cumsum()
    obv_ema = obv.ewm(span=ema_span, adjust=False).mean()
    vol_ma = df["volume"].rolling(20, min_periods=1).mean()
    return np.tanh(obv_ema.diff() / (vol_ma + EPSILON))


# ---------------------------------------------------------------------------
# 5m base features
# ---------------------------------------------------------------------------

def _compute_5m_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute strong features on the 5m base candles.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with columns [open, high, low, close, volume].

    Returns
    -------
    pd.DataFrame
        Feature frame aligned to the same index as *df*.
    """
    close = df["close"]
    feat = pd.DataFrame(index=df.index)

    # Log returns (no look-ahead — strictly past data)
    log_ret = np.log(close / close.shift(1).replace(0, np.nan))
    feat["log_return"] = log_ret
    feat["log_return_5"] = np.log(close / close.shift(5).replace(0, np.nan))
    feat["log_return_20"] = np.log(close / close.shift(20).replace(0, np.nan))

    # RSI
    feat["rsi_14"] = _rsi(close)

    # EMA
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    feat["ema_9"] = ema9
    feat["ema_21"] = ema21
    feat["ema_spread"] = (ema9 - ema21) / (close + EPSILON)

    # MACD
    macd_line, macd_signal = _macd(close)
    feat["macd"] = macd_line / (close + EPSILON)          # normalised
    feat["macd_hist"] = (macd_line - macd_signal) / (close + EPSILON)

    # ATR (normalised as % of close)
    atr = _atr(df)
    feat["atr_pct"] = atr / (close + EPSILON)

    # Bollinger Band width
    feat["bb_width"] = _bollinger_width(close)

    # Volume ratio (vs. 20-bar rolling average)
    vol_ma = df["volume"].rolling(20, min_periods=1).mean()
    feat["volume_ratio"] = df["volume"] / (vol_ma + EPSILON)

    # VWAP deviation
    vwap = _vwap(df)
    feat["vwap_dev"] = (close - vwap) / (vwap + EPSILON)

    # OBV slope (normalised)
    feat["obv_slope"] = _obv_slope(df)

    return feat


# ---------------------------------------------------------------------------
# 1m aggregated features
# ---------------------------------------------------------------------------

def _aggregate_1m_features(
    df_5m: pd.DataFrame, df_1m: pd.DataFrame
) -> pd.DataFrame:
    """Aggregate 1m bars into per-5m-bar microstructure features.

    For every 5m timestamp *t* we use the five 1m bars that make up that
    5m bar (i.e. the five 1m bars whose timestamp falls in (t-5m, t]).

    Parameters
    ----------
    df_5m : pd.DataFrame
        5m base DataFrame (DatetimeIndex).
    df_1m : pd.DataFrame
        1m DataFrame (DatetimeIndex).

    Returns
    -------
    pd.DataFrame
        Feature frame with index = df_5m.index.
        Columns: ret_1m_last, vol_1m, volume_spike_1m.
    """
    result = pd.DataFrame(
        {
            "ret_1m_last": 0.0,
            "vol_1m": 0.0,
            "volume_spike_1m": 0.0,
        },
        index=df_5m.index,
    )

    if df_1m is None or df_1m.empty:
        return result

    # Rolling 20-bar volume mean on 1m for spike detection
    vol_ma_1m = df_1m["volume"].rolling(20, min_periods=1).mean()
    vol_spike_flag = (df_1m["volume"] > vol_ma_1m * 2.0).astype(float)

    for ts in df_5m.index:
        # window: strictly past 5 minutes — half-open interval (ts-5min, ts]
        # This captures exactly the five 1m bars that compose the 5m bar
        # ending at ts, without including bars from the previous 5m period.
        window_start = ts - pd.Timedelta(minutes=5)
        mask = (df_1m.index > window_start) & (df_1m.index <= ts)
        bars_1m = df_1m[mask]

        if len(bars_1m) == 0:
            continue

        close_1m = bars_1m["close"]
        # last 1-minute return (most recent 1m bar in the window)
        if len(close_1m) >= 2:
            last_ret = float(
                np.log(close_1m.iloc[-1] / (close_1m.iloc[-2] + EPSILON))
            )
        else:
            last_ret = 0.0

        # intra-bar return volatility (std of 1m log returns in the window)
        log_rets_1m = np.log(
            close_1m / close_1m.shift(1).replace(0, np.nan)
        ).dropna()
        vol_1m = float(log_rets_1m.std()) if len(log_rets_1m) > 1 else 0.0

        # volume spike: max spike flag in the 5m window
        spike_val = float(vol_spike_flag[mask].max()) if mask.any() else 0.0

        result.at[ts, "ret_1m_last"] = last_ret
        result.at[ts, "vol_1m"] = vol_1m
        result.at[ts, "volume_spike_1m"] = spike_val

    return result


# ---------------------------------------------------------------------------
# 1h context features
# ---------------------------------------------------------------------------

def _compute_1h_context(
    df_5m: pd.DataFrame, df_1h: pd.DataFrame
) -> pd.DataFrame:
    """Compute higher-timeframe context from 1h candles.

    Features are forward-filled so each 5m bar has the most recent 1h
    snapshot available **before** its timestamp (no look-ahead).

    Parameters
    ----------
    df_5m : pd.DataFrame
        5m base DataFrame (DatetimeIndex).
    df_1h : pd.DataFrame
        1h DataFrame (DatetimeIndex).

    Returns
    -------
    pd.DataFrame
        Feature frame with index = df_5m.index.
        Columns: h1_trend_dir, h1_rsi, h1_ema_spread, h1_atr_pct, h1_macd.
    """
    zero_ctx = pd.DataFrame(
        {
            "h1_trend_dir": 0.0,
            "h1_rsi": 50.0,
            "h1_ema_spread": 0.0,
            "h1_atr_pct": 0.0,
            "h1_macd": 0.0,
        },
        index=df_5m.index,
    )

    if df_1h is None or df_1h.empty or len(df_1h) < 10:
        return zero_ctx

    close_1h = df_1h["close"]

    # 1h indicators
    ema9_1h = _ema(close_1h, 9)
    ema21_1h = _ema(close_1h, 21)
    rsi_1h = _rsi(close_1h)
    macd_1h, _ = _macd(close_1h)
    atr_1h = _atr(df_1h)

    # Trend direction: +1 bullish, -1 bearish, 0 neutral
    trend_dir_1h = pd.Series(0.0, index=df_1h.index)
    trend_dir_1h[ema9_1h > ema21_1h] = 1.0
    trend_dir_1h[ema9_1h < ema21_1h] = -1.0

    ema_spread_1h = (ema9_1h - ema21_1h) / (close_1h + EPSILON)
    atr_pct_1h = atr_1h / (close_1h + EPSILON)
    macd_norm_1h = macd_1h / (close_1h + EPSILON)

    h1_df = pd.DataFrame(
        {
            "h1_trend_dir": trend_dir_1h,
            "h1_rsi": rsi_1h,
            "h1_ema_spread": ema_spread_1h,
            "h1_atr_pct": atr_pct_1h,
            "h1_macd": macd_norm_1h,
        }
    )

    # Merge-asof: for each 5m bar, use the latest 1h bar BEFORE it
    # This prevents look-ahead (future 1h bar not yet closed)
    h1_df_sorted = h1_df.sort_index()
    df_5m_temp = pd.DataFrame(index=df_5m.index)

    merged = pd.merge_asof(
        df_5m_temp,
        h1_df_sorted,
        left_index=True,
        right_index=True,
        direction="backward",
    )
    merged.index = df_5m.index
    result = merged.reindex(columns=list(zero_ctx.columns)).fillna(
        {"h1_trend_dir": 0.0, "h1_rsi": 50.0, "h1_ema_spread": 0.0, "h1_atr_pct": 0.0, "h1_macd": 0.0}
    )
    return result


# ---------------------------------------------------------------------------
# Labeling
# ---------------------------------------------------------------------------

def _atr_barrier_labels(
    close: pd.Series,
    atr: pd.Series,
    horizon: int = DEFAULT_LABEL_HORIZON,
    barrier_mult: float = DEFAULT_ATR_BARRIER_MULT,
) -> pd.Series:
    """ATR-based dynamic barrier labeling.

    For bar *t* the future return is computed as:
        future_return = (close[t+horizon] - close[t]) / close[t]

    The barrier is set as:
        barrier = barrier_mult * atr[t] / close[t]

    Labels:
        BUY  ( 1) if future_return >  barrier
        SELL (-1) if future_return < -barrier
        HOLD ( 0) otherwise
        NaN      for the last *horizon* bars (future not yet known)

    **Only past data** (atr[t]) is used for barrier sizing;
    **only future data** (close[t+horizon]) is used for the label.
    No leakage.
    """
    future_close = close.shift(-horizon)
    future_ret = future_close / close - 1
    barrier = barrier_mult * atr / (close + EPSILON)

    # Start with NaN (unknown label)
    labels = pd.Series(np.nan, index=close.index, dtype=float)

    # Only label rows where future data is available
    known = future_ret.notna()
    labels[known & (future_ret > barrier)] = float(LABEL_BUY)
    labels[known & (future_ret < -barrier)] = float(LABEL_SELL)
    labels[known & (future_ret >= -barrier) & (future_ret <= barrier)] = float(LABEL_HOLD)

    return labels


def _fixed_barrier_labels(
    close: pd.Series,
    horizon: int = DEFAULT_LABEL_HORIZON,
    threshold: float = DEFAULT_FIXED_BARRIER_PCT,
) -> pd.Series:
    """Fixed-threshold labeling.

    BUY  if future_return > threshold  (e.g. > 2%)
    SELL if future_return < -threshold (e.g. < -2%)
    HOLD otherwise
    NaN  for the last *horizon* bars (future not yet known)
    """
    future_ret = close.shift(-horizon) / close - 1

    labels = pd.Series(np.nan, index=close.index, dtype=float)
    known = future_ret.notna()
    labels[known & (future_ret > threshold)] = float(LABEL_BUY)
    labels[known & (future_ret < -threshold)] = float(LABEL_SELL)
    labels[known & (future_ret >= -threshold) & (future_ret <= threshold)] = float(LABEL_HOLD)
    return labels


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

class MultiTimeframeDatasetBuilder:
    """Build a clean, labelled multi-timeframe feature dataset.

    Parameters
    ----------
    label_horizon : int
        Number of 5m bars ahead for the label (default: 3 → 15 min).
    atr_barrier_mult : float
        ATR multiplier for barrier labeling (default: 0.5).
    use_fixed_barrier : bool
        If True, use fixed ±2% threshold instead of ATR barrier.
    fixed_barrier_pct : float
        Fixed threshold for BUY/SELL when *use_fixed_barrier* is True.
    min_atr_pct : float
        Minimum ATR/close ratio below which bars are filtered out as noise.
    atr_period : int
        Period for ATR computation (default: 14).
    """

    def __init__(
        self,
        label_horizon: int = DEFAULT_LABEL_HORIZON,
        atr_barrier_mult: float = DEFAULT_ATR_BARRIER_MULT,
        use_fixed_barrier: bool = False,
        fixed_barrier_pct: float = DEFAULT_FIXED_BARRIER_PCT,
        min_atr_pct: float = DEFAULT_MIN_ATR_PCT,
        atr_period: int = DEFAULT_ATR_PERIOD,
    ) -> None:
        self.label_horizon = label_horizon
        self.atr_barrier_mult = atr_barrier_mult
        self.use_fixed_barrier = use_fixed_barrier
        self.fixed_barrier_pct = fixed_barrier_pct
        self.min_atr_pct = min_atr_pct
        self.atr_period = atr_period

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        df_5m: pd.DataFrame,
        df_1m: Optional[pd.DataFrame] = None,
        df_1h: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Build the full labelled dataset.

        Parameters
        ----------
        df_5m : pd.DataFrame
            5m OHLCV DataFrame with DatetimeIndex and columns
            [open, high, low, close, volume].
        df_1m : pd.DataFrame, optional
            1m OHLCV DataFrame.  When provided, intra-bar microstructure
            features are computed and merged.
        df_1h : pd.DataFrame, optional
            1h OHLCV DataFrame.  When provided, higher-timeframe context
            features are computed and merged.

        Returns
        -------
        pd.DataFrame
            Cleaned dataset with columns = MTF_FEATURE_COLUMNS + ["label"].
            Rows with NaN labels (tail due to horizon shift) are dropped.
            Low-volatility rows are removed.
        """
        df_5m = self._validate_and_clean(df_5m, "5m")
        if df_5m is None:
            return pd.DataFrame(columns=MTF_FEATURE_COLUMNS + ["label"])

        # ── 5m base features ──────────────────────────────────────────
        base_feats = _compute_5m_features(df_5m)

        # ── 1m aggregated features ────────────────────────────────────
        if df_1m is not None and not df_1m.empty:
            df_1m = self._validate_and_clean(df_1m, "1m")
        agg_1m = _aggregate_1m_features(df_5m, df_1m)

        # ── 1h context features ───────────────────────────────────────
        if df_1h is not None and not df_1h.empty:
            df_1h = self._validate_and_clean(df_1h, "1h")
        ctx_1h = _compute_1h_context(df_5m, df_1h)

        # ── Merge all feature blocks ──────────────────────────────────
        dataset = pd.concat(
            [base_feats, agg_1m, ctx_1h],
            axis=1,
        ).reindex(columns=MTF_FEATURE_COLUMNS)

        # ── ATR (for labeling and filtering) ─────────────────────────
        atr = _atr(df_5m, self.atr_period)
        atr_pct = atr / (df_5m["close"] + EPSILON)

        # ── Labels ───────────────────────────────────────────────────
        if self.use_fixed_barrier:
            labels = _fixed_barrier_labels(
                df_5m["close"],
                horizon=self.label_horizon,
                threshold=self.fixed_barrier_pct,
            )
        else:
            labels = _atr_barrier_labels(
                df_5m["close"],
                atr,
                horizon=self.label_horizon,
                barrier_mult=self.atr_barrier_mult,
            )
        dataset["label"] = labels.values

        # ── Drop tail rows where label is NaN (future not yet known) ─
        dataset = dataset.dropna(subset=["label"])

        # ── Filter out NaN rows from feature computation ──────────────
        dataset = dataset.replace([np.inf, -np.inf], np.nan)
        dataset = dataset.dropna()

        # ── Noise filter: remove ultra-low volatility bars ────────────
        atr_pct_aligned = atr_pct.reindex(dataset.index)
        noise_mask = atr_pct_aligned >= self.min_atr_pct
        before = len(dataset)
        dataset = dataset[noise_mask]
        removed = before - len(dataset)
        if removed > 0:
            logger.info(
                "[MTF] Noise filter removed %d low-volatility rows "
                "(atr_pct < %.4f)",
                removed,
                self.min_atr_pct,
            )

        # ── Final column alignment ────────────────────────────────────
        dataset = dataset.fillna(0.0)

        label_dist = dataset["label"].value_counts().to_dict()
        logger.info(
            "[MTF] Dataset built: %d rows, label distribution: %s",
            len(dataset),
            label_dist,
        )
        return dataset

    def get_Xy(
        self, dataset: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Split dataset into features *X* and labels *y*.

        Parameters
        ----------
        dataset : pd.DataFrame
            Output of :meth:`build`.

        Returns
        -------
        X : pd.DataFrame
            Feature matrix with columns = MTF_FEATURE_COLUMNS.
        y : pd.Series
            Integer labels: 1 (BUY), -1 (SELL), 0 (HOLD).
        """
        X = dataset[MTF_FEATURE_COLUMNS].copy()
        y = dataset["label"].astype(int)
        return X, y

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_clean(
        df: pd.DataFrame, tf_label: str
    ) -> Optional[pd.DataFrame]:
        """Validate, lowercase columns, and drop invalid OHLCV rows."""
        if df is None or len(df) < MIN_ROWS:
            logger.warning(
                "[MTF] %s DataFrame too short (%d rows, need %d)",
                tf_label,
                0 if df is None else len(df),
                MIN_ROWS,
            )
            return None

        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]

        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            logger.error(
                "[MTF] %s DataFrame missing required columns: %s",
                tf_label,
                sorted(missing),
            )
            return None

        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows with invalid prices
        valid = (
            df["open"].gt(0)
            & df["high"].gt(0)
            & df["low"].gt(0)
            & df["close"].gt(0)
            & df["volume"].ge(0)
            & df["high"].ge(df["low"])
            & df[list(required)].notna().all(axis=1)
        )
        cleaned = df[valid].copy()
        dropped = len(df) - len(cleaned)
        if dropped > 0:
            logger.warning(
                "[MTF] %s: dropped %d invalid OHLCV rows", tf_label, dropped
            )
        return cleaned


# ---------------------------------------------------------------------------
# Convenience: build from yfinance (useful for training scripts)
# ---------------------------------------------------------------------------

def build_mtf_dataset_from_yfinance(
    symbol: str,
    period: str = "60d",
    builder: Optional[MultiTimeframeDatasetBuilder] = None,
) -> pd.DataFrame:
    """Fetch 5m, 1m, and 1h data from yfinance and build the MTF dataset.

    Parameters
    ----------
    symbol : str
        Yahoo Finance ticker symbol (e.g. "RELIANCE.NS").
    period : str
        History period supported by yfinance (e.g. "60d", "30d").
        Note: yfinance limits 1m data to the last 7 days.
    builder : MultiTimeframeDatasetBuilder, optional
        Custom builder instance; defaults to one with default parameters.

    Returns
    -------
    pd.DataFrame
        Labelled multi-timeframe feature dataset.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance is required: pip install yfinance")

    if builder is None:
        builder = MultiTimeframeDatasetBuilder()

    ticker = yf.Ticker(symbol)

    # 5m — up to 60 days
    df_5m = ticker.history(period=period, interval="5m")
    df_5m.columns = [c.lower() for c in df_5m.columns]
    df_5m = df_5m[["open", "high", "low", "close", "volume"]].dropna()

    # 1m — limited to last 7 days by yfinance
    try:
        df_1m = ticker.history(period="7d", interval="1m")
        df_1m.columns = [c.lower() for c in df_1m.columns]
        df_1m = df_1m[["open", "high", "low", "close", "volume"]].dropna()
    except Exception as exc:
        logger.warning("[MTF] Could not fetch 1m data for %s: %s", symbol, exc)
        df_1m = None

    # 1h — up to 60 days
    try:
        df_1h = ticker.history(period=period, interval="1h")
        df_1h.columns = [c.lower() for c in df_1h.columns]
        df_1h = df_1h[["open", "high", "low", "close", "volume"]].dropna()
    except Exception as exc:
        logger.warning("[MTF] Could not fetch 1h data for %s: %s", symbol, exc)
        df_1h = None

    if df_5m.empty or len(df_5m) < MIN_ROWS:
        logger.warning(
            "[MTF] Insufficient 5m data for %s (%d rows)", symbol, len(df_5m)
        )
        return pd.DataFrame(columns=MTF_FEATURE_COLUMNS + ["label"])

    logger.info(
        "[MTF] %s — 5m rows: %d, 1m rows: %d, 1h rows: %d",
        symbol,
        len(df_5m),
        len(df_1m) if df_1m is not None else 0,
        len(df_1h) if df_1h is not None else 0,
    )

    return builder.build(df_5m, df_1m=df_1m, df_1h=df_1h)
