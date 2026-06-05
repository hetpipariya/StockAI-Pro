"""Canonical feature-engineering bridge around the native C++ engine.

This module is the single feature source for both backend inference and
`experiments_v2` training. The only indicator math happens inside the compiled
C++ engine; Python is limited to causal data preparation, resampling, and
schema validation.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.cpp_engine import compute_features as cpp_compute_features
from app.cpp_engine import stockai_cpp_engine
from app.inference.feature_contract import (
    CPP_TO_CANONICAL,
    EXPECTED_FEATURE_COUNT,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    align_feature_frame,
    check_inference_compatibility,
    get_feature_summary,
    validate_feature_contract,
    validate_features,
)

logger = logging.getLogger(__name__)

BASE_5M_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
ENTRY_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
TREND_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
CONTEXT_1H_FEATURE_COLUMNS: list[str] = []
_FEATURE_MATRIX_CACHE: dict[str, pd.DataFrame] = {}

CANONICAL_NIFTY_DAILY_PATHS = (
    Path("data/nifty/daily/nifty_daily.csv"),
    Path("data/nifty/daily"),
    Path("experiments_v2/data/raw/nifty_daily.csv"),
    Path("experiments_v2/data/raw/nifty/NIFTY_50_daily.csv"),
    Path("experiments_v2/data/raw/index/NIFTY_50_daily.csv"),
)


@dataclass(frozen=True)
class DataConfig:
    timeframe: str
    min_rows_per_symbol: int = 50
    fill_missing_timestamps: bool = True
    drop_gap_filled_rows: bool = True
    max_files: int | None = None
    require_nifty_context: bool = False
    nifty_daily_path: Path | None = None


def _empty_feature_frame(index: pd.Index | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(columns=FEATURE_COLUMNS)
    if index is not None:
        frame.index = index
    return frame


def _zero_feature_row() -> pd.DataFrame:
    return pd.DataFrame([[0.0] * len(FEATURE_COLUMNS)], columns=FEATURE_COLUMNS)


def _normalize_timestamp_series(series: pd.Series, target_timezone: str = "Asia/Kolkata") -> pd.Series:
    series = pd.to_datetime(series, errors="coerce")
    if series.dt.tz is None:
        return series.dt.tz_localize(ZoneInfo(target_timezone))
    return series.dt.tz_convert(ZoneInfo(target_timezone))


def _frame_cache_token(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "empty"
    normalized = frame.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    payload = normalized.to_json(orient="split", date_format="iso")
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _normalize_ohlcv_frame(data: Any, require_timestamp: bool = False, target_timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    if data is None:
        return pd.DataFrame()

    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, dict):
        frame = pd.DataFrame(data)
    else:
        frame = pd.DataFrame(list(data))

    if frame.empty:
        return frame

    frame.columns = [str(column).strip().lower() for column in frame.columns]
    aliases = {"datetime": "timestamp", "date": "timestamp", "time": "timestamp", "ticker": "symbol"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})

    required = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        if require_timestamp:
            raise ValueError(f"OHLCV frame missing required columns: {missing}")
        return pd.DataFrame()

    if "timestamp" in frame.columns:
        frame["timestamp"] = _normalize_timestamp_series(frame["timestamp"], target_timezone)
    elif require_timestamp:
        raise ValueError("OHLCV frame requires a timestamp column for training/offline computation.")

    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.replace([np.inf, -np.inf], np.nan)
    drop_columns = required + (["timestamp"] if "timestamp" in frame.columns else [])
    frame = frame.dropna(subset=drop_columns)

    if "high" in frame.columns and "low" in frame.columns:
        frame = frame[
            (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
            & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
            & (frame["open"] > 0)
            & (frame["high"] > 0)
            & (frame["low"] > 0)
            & (frame["close"] > 0)
            & (frame["volume"] >= 0)
        ].copy()

    sort_columns = ["timestamp"] if "timestamp" in frame.columns else []
    if "symbol" in frame.columns:
        sort_columns.insert(0, "symbol")
    if sort_columns:
        frame = frame.sort_values(sort_columns)

    frame = frame.reset_index(drop=True)
    return frame


def _load_nifty_daily_series(path: Path | None = None) -> pd.DataFrame:
    candidate_paths = [path] if path is not None else list(CANONICAL_NIFTY_DAILY_PATHS)
    for candidate in candidate_paths:
        if candidate is None:
            continue
        resolved = Path(candidate)
        if not resolved.exists():
            continue
        frame = pd.read_csv(resolved, low_memory=False)
        normalized = _normalize_ohlcv_frame(frame, require_timestamp=True)
        if normalized.empty:
            continue
        out = normalized[["timestamp", "close"]].copy()
        out = out.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        return out.reset_index(drop=True)
    return pd.DataFrame(columns=["timestamp", "close"])


def _normalize_nifty_frame(frame: pd.DataFrame, target_timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    normalized = _normalize_ohlcv_frame(frame, require_timestamp=True, target_timezone=target_timezone)
    if normalized.empty:
        return normalized
    normalized = normalized[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    normalized = normalized.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    return normalized.reset_index(drop=True)


def build_canonical_nifty_daily_dataset(
    source: Path | str,
    output_path: Path | str | None = None,
    target_timezone: str = "Asia/Kolkata",
    strict: bool = True,
    max_allowed_gap_days: int = 4,
) -> pd.DataFrame:
    source = Path(source)
    candidates: list[Path] = []
    if source.is_dir():
        candidates = sorted(source.rglob("*.csv"))
    else:
        candidates = [source]

    if not candidates:
        raise FileNotFoundError(f"NIFTY source path not found: {source}")

    fragments: list[pd.DataFrame] = []
    for candidate in candidates:
        if not candidate.exists():
            continue

        frame = pd.read_csv(candidate, low_memory=False)

        cleaned = _normalize_ohlcv_frame(frame, require_timestamp=True, target_timezone=target_timezone)
        if cleaned.empty:
            continue

        invalid_rows = len(frame) - len(cleaned)
        if strict and invalid_rows > 0:
            raise RuntimeError(
                f"NIFTY dataset contains invalid OHLCV rows: {invalid_rows}"
            )

        cleaned = cleaned.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        if cleaned.empty:
            continue

        fragments.append(cleaned)

    if not fragments:
        raise RuntimeError(f"No valid NIFTY data could be loaded from {source}")

    combined = pd.concat(fragments, ignore_index=True)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    duplicate_count = int(combined["timestamp"].duplicated().sum())
    if duplicate_count > 0:
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")

    # Validate OHLCV and currency values
    combined, errors = _drop_corrupted_ohlcv_rows(combined)
    if strict and errors["invalid_ohlcv_rows"] > 0:
        raise RuntimeError(
            f"NIFTY dataset contains invalid OHLCV rows: {errors['invalid_ohlcv_rows']}"
        )

    # Detect suspicious daily gaps beyond typical weekend/holiday windows
    if len(combined) >= 2 and max_allowed_gap_days is not None:
        delta_days = combined["timestamp"].diff().dt.days.fillna(0).astype(int)
        gap_count = int((delta_days > max_allowed_gap_days).sum())
        if strict and gap_count > 0:
            raise RuntimeError(
                f"NIFTY dataset contains {gap_count} suspicious daily gaps > {max_allowed_gap_days} days"
            )

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(output_path, index=False)

    return combined


def _normalize_close_context(data: Any) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame(columns=["timestamp", "close"])
    if isinstance(data, pd.DataFrame):
        frame = data.copy()
    elif isinstance(data, dict):
        frame = pd.DataFrame(data)
    else:
        frame = pd.DataFrame(list(data))
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "close"])
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    aliases = {"datetime": "timestamp", "date": "timestamp", "time": "timestamp"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "close" not in frame.columns:
        return pd.DataFrame(columns=["timestamp", "close"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp", "close"])
        return frame[["timestamp", "close"]].sort_values("timestamp").reset_index(drop=True)
    frame = frame.dropna(subset=["close"])
    return frame[["close"]].reset_index(drop=True)


def _resample_close_context(frame: pd.DataFrame, rule: str, shift_periods: int = 1) -> pd.DataFrame:
    if frame.empty or "timestamp" not in frame.columns:
        return pd.DataFrame(columns=["timestamp", "close"])
    indexed = frame[["timestamp", "close"]].dropna().copy()
    indexed = indexed.sort_values("timestamp").set_index("timestamp")
    resampled = indexed["close"].resample(rule, label="right", closed="right").last().dropna()
    if shift_periods:
        resampled = resampled.shift(shift_periods)
    resampled = resampled.dropna()
    out = resampled.reset_index()
    out.columns = ["timestamp", "close"]
    return out


def _slice_close_values(context: pd.DataFrame, ts: pd.Timestamp | None) -> np.ndarray:
    if context.empty:
        return np.array([], dtype=np.float64)
    if ts is None or "timestamp" not in context.columns:
        values = context["close"].to_numpy(dtype=np.float64)
        return np.ascontiguousarray(values)
    series = context.loc[context["timestamp"] <= ts, "close"]
    if series.empty:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(series.to_numpy(dtype=np.float64))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").ewm(span=span, adjust=False, min_periods=max(2, span // 2)).mean()


def _python_compute_latest_row(
    ohlcv_5m: pd.DataFrame,
    ohlcv_15m: pd.DataFrame | None = None,
    ohlcv_daily: pd.DataFrame | None = None,
    nifty_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pure-Python canonical 20-feature fallback used when native C++ is unavailable."""

    base = ohlcv_5m.copy().reset_index(drop=True)
    close = pd.to_numeric(base["close"], errors="coerce")
    high = pd.to_numeric(base["high"], errors="coerce")
    low = pd.to_numeric(base["low"], errors="coerce")
    open_ = pd.to_numeric(base["open"], errors="coerce")
    volume = pd.to_numeric(base["volume"], errors="coerce")

    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)

    ratio = np.divide(
        ema9.to_numpy(dtype=float),
        np.maximum(ema21.to_numpy(dtype=float), 1e-12),
    )
    ema_ratio = pd.Series(ratio - 1.0, index=base.index)

    linreg = (close - close.shift(20)) / 20.0
    linreg_slope = np.divide(
        linreg.to_numpy(dtype=float),
        np.maximum(np.abs(close.to_numpy(dtype=float)), 1e-9),
    )

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(14, min_periods=14).mean()
    avg_loss = loss.rolling(14, min_periods=14).mean()
    rs = np.divide(avg_gain.to_numpy(dtype=float), np.maximum(avg_loss.to_numpy(dtype=float), 1e-12))
    rsi14 = 100.0 - (100.0 / (1.0 + rs))

    macd = _ema(close, 12) - _ema(close, 26)
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd - signal

    roc10 = np.divide(close.to_numpy(dtype=float), np.maximum(close.shift(10).to_numpy(dtype=float), 1e-12)) - 1.0

    typical = (high + low + close) / 3.0
    sma_tp = typical.rolling(20, min_periods=20).mean()
    mad_tp = typical.rolling(20, min_periods=20).apply(lambda x: float(np.mean(np.abs(x - np.mean(x)))), raw=False)
    cci20 = np.divide((typical - sma_tp).to_numpy(dtype=float), np.maximum((0.015 * mad_tp).to_numpy(dtype=float), 1e-12))

    tpv = typical * volume
    vwap = np.divide(tpv.cumsum().to_numpy(dtype=float), np.maximum(volume.cumsum().to_numpy(dtype=float), 1e-12))
    vwap_distance = np.divide(close.to_numpy(dtype=float) - vwap, np.maximum(vwap, 1e-12))

    volume_ratio = np.divide(volume.to_numpy(dtype=float), np.maximum(volume.rolling(20, min_periods=20).mean().to_numpy(dtype=float), 1e-12))

    raw_money = typical.to_numpy(dtype=float) * volume.to_numpy(dtype=float)
    pos_flow = np.where(typical.diff().to_numpy(dtype=float) > 0, raw_money, 0.0)
    neg_flow = np.where(typical.diff().to_numpy(dtype=float) < 0, raw_money, 0.0)
    pos_roll = pd.Series(pos_flow).rolling(14, min_periods=14).sum().to_numpy(dtype=float)
    neg_roll = pd.Series(neg_flow).rolling(14, min_periods=14).sum().to_numpy(dtype=float)
    mfr = np.divide(pos_roll, np.maximum(neg_roll, 1e-12))
    mfi14 = 100.0 - (100.0 / (1.0 + mfr))

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = tr.rolling(14, min_periods=14).mean()

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    bb_up = bb_mid + (2.0 * bb_std)
    bb_lo = bb_mid - (2.0 * bb_std)
    bb_width = np.divide((bb_up - bb_lo).to_numpy(dtype=float), np.maximum(bb_mid.to_numpy(dtype=float), 1e-12))
    bb_percent_b = np.divide(close.to_numpy(dtype=float) - bb_lo.to_numpy(dtype=float), np.maximum((bb_up - bb_lo).to_numpy(dtype=float), 1e-12))

    up_move = high.diff().fillna(0.0)
    down_move = (-low.diff()).fillna(0.0)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr14 = tr.rolling(14, min_periods=14).sum().to_numpy(dtype=float)
    plus_di = 100.0 * np.divide(pd.Series(plus_dm).rolling(14, min_periods=14).sum().to_numpy(dtype=float), np.maximum(tr14, 1e-12))
    minus_di = 100.0 * np.divide(pd.Series(minus_dm).rolling(14, min_periods=14).sum().to_numpy(dtype=float), np.maximum(tr14, 1e-12))
    dx = 100.0 * np.divide(np.abs(plus_di - minus_di), np.maximum(plus_di + minus_di, 1e-12))
    adx14 = pd.Series(dx).rolling(14, min_periods=14).mean().to_numpy(dtype=float)

    candle_body_ratio = np.divide(
        np.abs(close.to_numpy(dtype=float) - open_.to_numpy(dtype=float)),
        np.maximum((high.to_numpy(dtype=float) - low.to_numpy(dtype=float)), 1e-12),
    )

    def _trend_dir(ctx: pd.DataFrame | None, short_span: int, long_span: int) -> float:
        if ctx is None or ctx.empty or "close" not in ctx.columns:
            return 0.0
        c = pd.to_numeric(ctx["close"], errors="coerce").dropna()
        if len(c) < max(short_span, long_span):
            return 0.0
        return float(np.sign(_ema(c, short_span).iloc[-1] - _ema(c, long_span).iloc[-1]))

    mtf_15m_direction = _trend_dir(ohlcv_15m, 9, 21)
    daily_alignment = _trend_dir(ohlcv_daily, 21, 50)
    nifty_direction = _trend_dir(nifty_daily, 21, 50)

    row = pd.DataFrame(
        [
            [
                float(ema9.iloc[-1]) if len(ema9) else 0.0,
                float(ema21.iloc[-1]) if len(ema21) else 0.0,
                float(ema50.iloc[-1]) if len(ema50) else 0.0,
                float(ema_ratio.iloc[-1]) if len(ema_ratio) else 0.0,
                float(linreg_slope[-1]) if len(linreg_slope) else 0.0,
                float(rsi14[-1]) if len(rsi14) else 0.0,
                float(macd_hist.iloc[-1]) if len(macd_hist) else 0.0,
                float(roc10[-1]) if len(roc10) else 0.0,
                float(cci20[-1]) if len(cci20) else 0.0,
                float(vwap_distance[-1]) if len(vwap_distance) else 0.0,
                float(volume_ratio[-1]) if len(volume_ratio) else 0.0,
                float(mfi14[-1]) if len(mfi14) else 0.0,
                float(atr14.iloc[-1]) if len(atr14) else 0.0,
                float(bb_width[-1]) if len(bb_width) else 0.0,
                float(bb_percent_b[-1]) if len(bb_percent_b) else 0.0,
                float(adx14[-1]) if len(adx14) else 0.0,
                float(candle_body_ratio[-1]) if len(candle_body_ratio) else 0.0,
                float(mtf_15m_direction),
                float(daily_alignment),
                float(nifty_direction),
            ]
        ],
        columns=FEATURE_COLUMNS,
    )
    row = row.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    row = row.mask(row.abs() > 1e6, 0.0)
    return align_feature_frame(row, FEATURE_COLUMNS, context="python_feature_fallback")


def _context_direction_series(ctx: pd.DataFrame, short_span: int, long_span: int) -> pd.DataFrame:
    if ctx is None or ctx.empty or "close" not in ctx.columns or "timestamp" not in ctx.columns:
        return pd.DataFrame(columns=["timestamp", "direction"])
    c = pd.to_numeric(ctx["close"], errors="coerce")
    if c.empty:
        return pd.DataFrame(columns=["timestamp", "direction"])
    short = _ema(c, short_span)
    long = _ema(c, long_span)
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(ctx["timestamp"], errors="coerce"),
        "direction": np.sign((short - long).to_numpy(dtype=float)),
    })
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return out


def _python_compute_feature_matrix(
    frame_5m: pd.DataFrame,
    frame_15m: pd.DataFrame,
    frame_daily: pd.DataFrame,
    frame_nifty: pd.DataFrame,
    has_timestamp: bool,
    min_candles: int,
) -> pd.DataFrame:
    close = pd.to_numeric(frame_5m["close"], errors="coerce")
    high = pd.to_numeric(frame_5m["high"], errors="coerce")
    low = pd.to_numeric(frame_5m["low"], errors="coerce")
    open_ = pd.to_numeric(frame_5m["open"], errors="coerce")
    volume = pd.to_numeric(frame_5m["volume"], errors="coerce")

    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)
    ema_ratio = np.divide(ema9.to_numpy(dtype=float), np.maximum(ema21.to_numpy(dtype=float), 1e-12)) - 1.0

    linreg = (close - close.shift(20)) / 20.0
    linreg_slope = np.divide(
        linreg.to_numpy(dtype=float),
        np.maximum(np.abs(close.to_numpy(dtype=float)), 1e-9),
    )

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(14, min_periods=14).mean()
    avg_loss = loss.rolling(14, min_periods=14).mean()
    rs = np.divide(avg_gain.to_numpy(dtype=float), np.maximum(avg_loss.to_numpy(dtype=float), 1e-12))
    rsi14 = 100.0 - (100.0 / (1.0 + rs))

    macd = _ema(close, 12) - _ema(close, 26)
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd.to_numpy(dtype=float) - signal.to_numpy(dtype=float)

    roc10 = np.divide(close.to_numpy(dtype=float), np.maximum(close.shift(10).to_numpy(dtype=float), 1e-12)) - 1.0

    typical = (high + low + close) / 3.0
    sma_tp = typical.rolling(20, min_periods=20).mean()
    mad_tp = typical.rolling(20, min_periods=20).apply(lambda x: float(np.mean(np.abs(x - np.mean(x)))), raw=False)
    cci20 = np.divide((typical - sma_tp).to_numpy(dtype=float), np.maximum((0.015 * mad_tp).to_numpy(dtype=float), 1e-12))

    tpv = typical * volume
    vwap = np.divide(tpv.cumsum().to_numpy(dtype=float), np.maximum(volume.cumsum().to_numpy(dtype=float), 1e-12))
    vwap_distance = np.divide(close.to_numpy(dtype=float) - vwap, np.maximum(vwap, 1e-12))

    volume_ratio = np.divide(volume.to_numpy(dtype=float), np.maximum(volume.rolling(20, min_periods=20).mean().to_numpy(dtype=float), 1e-12))

    raw_money = typical.to_numpy(dtype=float) * volume.to_numpy(dtype=float)
    pos_flow = np.where(typical.diff().to_numpy(dtype=float) > 0, raw_money, 0.0)
    neg_flow = np.where(typical.diff().to_numpy(dtype=float) < 0, raw_money, 0.0)
    pos_roll = pd.Series(pos_flow).rolling(14, min_periods=14).sum().to_numpy(dtype=float)
    neg_roll = pd.Series(neg_flow).rolling(14, min_periods=14).sum().to_numpy(dtype=float)
    mfr = np.divide(pos_roll, np.maximum(neg_roll, 1e-12))
    mfi14 = 100.0 - (100.0 / (1.0 + mfr))

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = tr.rolling(14, min_periods=14).mean().to_numpy(dtype=float)

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    bb_up = bb_mid + (2.0 * bb_std)
    bb_lo = bb_mid - (2.0 * bb_std)
    bb_width = np.divide((bb_up - bb_lo).to_numpy(dtype=float), np.maximum(bb_mid.to_numpy(dtype=float), 1e-12))
    bb_percent_b = np.divide(close.to_numpy(dtype=float) - bb_lo.to_numpy(dtype=float), np.maximum((bb_up - bb_lo).to_numpy(dtype=float), 1e-12))

    up_move = high.diff().fillna(0.0)
    down_move = (-low.diff()).fillna(0.0)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr14 = tr.rolling(14, min_periods=14).sum().to_numpy(dtype=float)
    plus_di = 100.0 * np.divide(pd.Series(plus_dm).rolling(14, min_periods=14).sum().to_numpy(dtype=float), np.maximum(tr14, 1e-12))
    minus_di = 100.0 * np.divide(pd.Series(minus_dm).rolling(14, min_periods=14).sum().to_numpy(dtype=float), np.maximum(tr14, 1e-12))
    dx = 100.0 * np.divide(np.abs(plus_di - minus_di), np.maximum(plus_di + minus_di, 1e-12))
    adx14 = pd.Series(dx).rolling(14, min_periods=14).mean().to_numpy(dtype=float)

    candle_body_ratio = np.divide(
        np.abs(close.to_numpy(dtype=float) - open_.to_numpy(dtype=float)),
        np.maximum((high.to_numpy(dtype=float) - low.to_numpy(dtype=float)), 1e-12),
    )

    mtf_15m_direction = np.zeros(len(frame_5m), dtype=float)
    daily_alignment = np.zeros(len(frame_5m), dtype=float)
    nifty_direction = np.zeros(len(frame_5m), dtype=float)
    if has_timestamp:
        base_time = pd.DataFrame({"timestamp": pd.to_datetime(frame_5m["timestamp"], errors="coerce")})

        d15 = _context_direction_series(frame_15m, 9, 21)
        if not d15.empty:
            joined = pd.merge_asof(base_time.sort_values("timestamp"), d15, on="timestamp", direction="backward")
            mtf_15m_direction = joined["direction"].fillna(0.0).to_numpy(dtype=float)

        dd = _context_direction_series(frame_daily, 21, 50)
        if not dd.empty:
            joined = pd.merge_asof(base_time.sort_values("timestamp"), dd, on="timestamp", direction="backward")
            daily_alignment = joined["direction"].fillna(0.0).to_numpy(dtype=float)

        nd = _context_direction_series(frame_nifty, 21, 50)
        if not nd.empty:
            joined = pd.merge_asof(base_time.sort_values("timestamp"), nd, on="timestamp", direction="backward")
            nifty_direction = joined["direction"].fillna(0.0).to_numpy(dtype=float)

    all_rows = pd.DataFrame(
        {
            "ema9": ema9.to_numpy(dtype=float),
            "ema21": ema21.to_numpy(dtype=float),
            "ema50": ema50.to_numpy(dtype=float),
            "ema_ratio": ema_ratio,
            "linreg_slope": linreg_slope,
            "rsi14": rsi14,
            "macd_hist": macd_hist,
            "roc10": roc10,
            "cci20": cci20,
            "vwap_distance": vwap_distance,
            "volume_ratio": volume_ratio,
            "mfi14": mfi14,
            "atr14": atr14,
            "bb_width": bb_width,
            "bb_percent_b": bb_percent_b,
            "adx14": adx14,
            "candle_body_ratio": candle_body_ratio,
            "mtf_15m_direction": mtf_15m_direction,
            "daily_alignment": daily_alignment,
            "nifty_direction": nifty_direction,
        }
    )

    start = max(0, int(min_candles) - 1)
    out = all_rows.iloc[start:].copy()
    out = out.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out = out.mask(out.abs() > 1e6, 0.0)
    out.index = frame_5m.index[start:]
    return align_feature_frame(out, FEATURE_COLUMNS, context="python_feature_fallback_matrix")


def _compute_latest_native_row(
    ohlcv_5m: pd.DataFrame,
    ohlcv_15m: pd.DataFrame | None = None,
    ohlcv_daily: pd.DataFrame | None = None,
    nifty_daily: pd.DataFrame | None = None,
) -> pd.DataFrame:
    ctx_15m = ohlcv_15m if ohlcv_15m is not None else pd.DataFrame()
    ctx_daily = ohlcv_daily if ohlcv_daily is not None else pd.DataFrame()
    ctx_nifty = nifty_daily if nifty_daily is not None else pd.DataFrame()
    native_available = stockai_cpp_engine is not None and hasattr(stockai_cpp_engine, "compute_all_features")
    if not native_available:
        return _python_compute_latest_row(ohlcv_5m, ctx_15m, ctx_daily, ctx_nifty)

    if ctx_15m.empty and ctx_daily.empty and ctx_nifty.empty:
        base = cpp_compute_features(ohlcv_5m)
        base = base.rename(columns=CPP_TO_CANONICAL)
        return align_feature_frame(base, FEATURE_COLUMNS, context="compute_latest_native_row")
    result = stockai_cpp_engine.compute_all_features(
        np.ascontiguousarray(ohlcv_5m["open"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["high"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["low"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["close"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ohlcv_5m["volume"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_15m.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_daily.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
        np.ascontiguousarray(ctx_nifty.get("close", pd.Series(dtype=float)).to_numpy(dtype=np.float64)),
    )
    status = int(result.get("status", -1))
    if status != 0:
        raise RuntimeError(result.get("error_message") or f"C++ feature computation failed: status={status}")
    feature_values = result.get("features") or {}
    row = [[float(feature_values[raw_name]) for raw_name in CPP_TO_CANONICAL]]
    out = pd.DataFrame(row, columns=FEATURE_COLUMNS)
    out = out.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out = out.mask(out.abs() > 1e6, 0.0)
    return align_feature_frame(out, FEATURE_COLUMNS, context="compute_latest_native_row")


def compute_features(
    candles_5m: Any,
    candles_15m: Any = None,
    candles_daily: Any = None,
    nifty_daily: Any = None,
    include_legacy: bool = False,
) -> pd.DataFrame:
    del include_legacy

    frame_5m = _normalize_ohlcv_frame(candles_5m, require_timestamp=False)
    if frame_5m.empty:
        return _empty_feature_frame()

    min_candles = int(getattr(stockai_cpp_engine, "MIN_CANDLES_FOR_FEATURES", 50))
    if len(frame_5m) < min_candles:
        return _empty_feature_frame()

    has_timestamp = "timestamp" in frame_5m.columns
    frame_15m = _normalize_close_context(candles_15m) if candles_15m is not None else pd.DataFrame()
    frame_daily = _normalize_close_context(candles_daily) if candles_daily is not None else pd.DataFrame()
    frame_nifty = _normalize_close_context(nifty_daily) if nifty_daily is not None else pd.DataFrame()

    if has_timestamp and frame_15m.empty:
        frame_15m = _resample_close_context(frame_5m, "15min")
    if has_timestamp and frame_daily.empty:
        frame_daily = _resample_close_context(frame_5m, "1D")
    if has_timestamp and frame_nifty.empty:
        frame_nifty = _load_nifty_daily_series()
        if not frame_nifty.empty:
            frame_nifty = _resample_close_context(frame_nifty, "1D")

    native_available = stockai_cpp_engine is not None and hasattr(stockai_cpp_engine, "compute_all_features")

    cache_key = "|".join(
        [
            _frame_cache_token(frame_5m),
            _frame_cache_token(frame_15m),
            _frame_cache_token(frame_daily),
            _frame_cache_token(frame_nifty),
        ]
    )
    cached = _FEATURE_MATRIX_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    if not native_available:
        out = _python_compute_feature_matrix(
            frame_5m=frame_5m,
            frame_15m=frame_15m,
            frame_daily=frame_daily,
            frame_nifty=frame_nifty,
            has_timestamp=has_timestamp,
            min_candles=min_candles,
        )
        _FEATURE_MATRIX_CACHE[cache_key] = out.copy()
        return out

    rows: list[list[float]] = []
    row_indices: list[int] = []
    for end_idx in range(min_candles, len(frame_5m) + 1):
        window = frame_5m.iloc[:end_idx].copy()
        latest_ts = window["timestamp"].iloc[-1] if has_timestamp else None

        ctx_15m = frame_15m
        ctx_daily = frame_daily
        ctx_nifty = frame_nifty
        if has_timestamp:
            if not frame_15m.empty:
                ctx_15m = pd.DataFrame({"close": _slice_close_values(frame_15m, latest_ts)})
            if not frame_daily.empty:
                ctx_daily = pd.DataFrame({"close": _slice_close_values(frame_daily, latest_ts)})
            if not frame_nifty.empty:
                ctx_nifty = pd.DataFrame({"close": _slice_close_values(frame_nifty, latest_ts)})

        latest_features = _compute_latest_native_row(
            window,
            ctx_15m,
            ctx_daily,
            ctx_nifty,
        )

        rows.append([float(latest_features.iloc[-1][column]) for column in FEATURE_COLUMNS])
        row_indices.append(end_idx - 1)

    if not rows:
        return _empty_feature_frame()

    out = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    if has_timestamp:
        out.index = frame_5m.index[row_indices]
    _FEATURE_MATRIX_CACHE[cache_key] = out.copy()
    return out


def _expected_frequency(timeframe: str) -> str:
    tf = str(timeframe).strip().lower()
    if tf == "5m":
        return "5min"
    if tf == "15m":
        return "15min"
    if tf == "1h":
        return "1h"
    if tf == "1d":
        return "1D"
    return tf


def _fill_missing_timestamps(group: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if group.empty or "timestamp" not in group.columns:
        return group
    freq = _expected_frequency(timeframe)
    ordered = group.sort_values("timestamp").copy()
    full_index = pd.date_range(
        start=ordered["timestamp"].iloc[0],
        end=ordered["timestamp"].iloc[-1],
        freq=freq,
    )
    reindexed = ordered.set_index("timestamp").reindex(full_index)
    reindexed["symbol"] = ordered["symbol"].iloc[0]
    reindexed["timeframe"] = ordered["timeframe"].iloc[0]
    reindexed["source_file"] = ordered["source_file"].iloc[0] if "source_file" in ordered.columns else "generated"
    reindexed["is_gap_filled"] = reindexed["open"].isna().astype(int)
    for column in ["open", "high", "low", "close"]:
        if column in reindexed.columns:
            reindexed[column] = reindexed[column].ffill()
    if "volume" in reindexed.columns:
        reindexed["volume"] = reindexed["volume"].fillna(0.0)
    reindexed = reindexed.reset_index().rename(columns={"index": "timestamp"})
    return reindexed


def _drop_corrupted_ohlcv_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if frame.empty:
        return frame, {"dropped_rows": 0, "duplicate_timestamps": 0, "invalid_ohlcv_rows": 0}

    out = frame.copy()
    duplicate_subset = ["timestamp"] if "symbol" not in out.columns else ["symbol", "timestamp"]
    if "timestamp" in out.columns:
        duplicates = int(out.duplicated(subset=duplicate_subset, keep="last").sum())
        out = out.drop_duplicates(subset=duplicate_subset, keep="last")
    else:
        duplicates = 0

    valid_mask = (
        (out["open"] > 0)
        & (out["high"] > 0)
        & (out["low"] > 0)
        & (out["close"] > 0)
        & (out["volume"] >= 0)
        & (out["high"] >= out[["open", "close", "low"]].max(axis=1))
        & (out["low"] <= out[["open", "close", "high"]].min(axis=1))
    )
    invalid = int((~valid_mask).sum())
    out = out.loc[valid_mask].copy()

    return out.reset_index(drop=True), {
        "dropped_rows": duplicates + invalid,
        "duplicate_timestamps": duplicates,
        "invalid_ohlcv_rows": invalid,
    }


def load_timeframe_csv_folder(folder: Path | str, config: DataConfig) -> pd.DataFrame:
    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(f"Timeframe data folder not found: {root}")

    csv_files = sorted(root.rglob("*.csv"))
    if config.max_files:
        csv_files = csv_files[: int(config.max_files)]
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found under {root}")

    blocks: list[pd.DataFrame] = []
    for csv_path in csv_files:
        frame = pd.read_csv(csv_path, low_memory=False)
        normalized = _normalize_ohlcv_frame(frame, require_timestamp=True)
        if normalized.empty:
            continue

        symbol = (
            normalized["symbol"].astype(str).str.upper().str.strip()
            if "symbol" in normalized.columns
            else pd.Series([csv_path.stem.upper()] * len(normalized))
        )
        normalized["symbol"] = symbol.replace("", csv_path.stem.upper())
        normalized["timeframe"] = str(config.timeframe).lower()
        normalized["source_file"] = csv_path.name

        cleaned, _ = _drop_corrupted_ohlcv_rows(normalized)
        if cleaned.empty:
            continue
        blocks.append(cleaned)

    if not blocks:
        raise RuntimeError(f"No valid OHLCV rows were loaded from {root}")

    merged = pd.concat(blocks, ignore_index=True, copy=False)
    merged = merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if config.fill_missing_timestamps:
        repaired_blocks = []
        for _, group in merged.groupby("symbol", sort=False):
            repaired_blocks.append(_fill_missing_timestamps(group, config.timeframe))
        merged = pd.concat(repaired_blocks, ignore_index=True, copy=False)

    if config.drop_gap_filled_rows and "is_gap_filled" in merged.columns:
        merged = merged[merged["is_gap_filled"].fillna(0).astype(int) == 0].copy()

    counts = merged.groupby("symbol")["timestamp"].transform("count")
    merged = merged[counts >= int(config.min_rows_per_symbol)].copy()
    if merged.empty:
        raise RuntimeError(
            f"No symbols have >= {config.min_rows_per_symbol} rows in {root}"
        )
    return merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def compute_base_features(
    frame: pd.DataFrame,
    nifty_daily_path: Path | None = None,
) -> pd.DataFrame:
    normalized = _normalize_ohlcv_frame(frame, require_timestamp=True)
    if normalized.empty:
        return pd.DataFrame()

    passthrough_columns = [
        column
        for column in ["timestamp", "symbol", "timeframe", "source_file", "is_gap_filled", "open", "high", "low", "close", "volume"]
        if column in normalized.columns
    ]
    nifty_context = _load_nifty_daily_series(nifty_daily_path)
    nifty_context = _resample_close_context(nifty_context, "1D") if not nifty_context.empty else nifty_context

    blocks: list[pd.DataFrame] = []
    min_candles = int(getattr(stockai_cpp_engine, "MIN_CANDLES_FOR_FEATURES", 50))
    for symbol, group in normalized.groupby("symbol", sort=False):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        features = compute_features(ordered, nifty_daily=nifty_context)
        if features.empty:
            continue
        meta = ordered.iloc[min_candles - 1 : min_candles - 1 + len(features)][passthrough_columns].reset_index(drop=True)
        block = pd.concat([meta, features.reset_index(drop=True)], axis=1)
        block = block.loc[:, ~block.columns.duplicated(keep="first")]
        blocks.append(block)

    if not blocks:
        return pd.DataFrame(columns=passthrough_columns + FEATURE_COLUMNS)

    out = pd.concat(blocks, ignore_index=True, copy=False)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out


def finalize_feature_matrix(
    frame: pd.DataFrame,
    required_features: Sequence[str],
) -> pd.DataFrame:
    expected = list(required_features)
    if set(expected) == set(FEATURE_COLUMNS):
        expected = list(FEATURE_COLUMNS)

    if frame.empty:
        metadata_columns = [column for column in frame.columns if column not in FEATURE_COLUMNS]
        return pd.DataFrame(columns=metadata_columns + expected)

    out = frame.copy()
    for column in expected:
        if column not in out.columns:
            raise RuntimeError(f"finalize_feature_matrix: missing required feature '{column}'")
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out = out.dropna(subset=expected).copy()
    validate_feature_contract(out[expected], expected, context="finalize_feature_matrix")
    metadata_columns = [column for column in out.columns if column not in FEATURE_COLUMNS]
    return out.loc[:, metadata_columns + expected].reset_index(drop=True)


def build_1h_context(frame_1h: pd.DataFrame) -> pd.DataFrame:
    if frame_1h.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", *TREND_FEATURE_COLUMNS])

    blocks: list[pd.DataFrame] = []
    for symbol, group in frame_1h.groupby("symbol", sort=False):
        ordered = group.sort_values("timestamp").copy()
        shifted = ordered[["timestamp", "symbol", *TREND_FEATURE_COLUMNS]].copy()
        shifted[TREND_FEATURE_COLUMNS] = shifted[TREND_FEATURE_COLUMNS].shift(1)
        shifted = shifted.dropna(subset=[TREND_FEATURE_COLUMNS[0]])
        shifted["symbol"] = symbol
        blocks.append(shifted)

    if not blocks:
        return pd.DataFrame(columns=["timestamp", "symbol", *TREND_FEATURE_COLUMNS])
    return pd.concat(blocks, ignore_index=True, copy=False).sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def merge_5m_with_1h_context(
    frame_5m: pd.DataFrame,
    context_1h: pd.DataFrame,
) -> pd.DataFrame:
    if frame_5m.empty:
        return frame_5m.copy()
    if context_1h.empty:
        return frame_5m.copy()

    merged_blocks: list[pd.DataFrame] = []
    meta_columns = [column for column in frame_5m.columns if column not in FEATURE_COLUMNS]
    for symbol, left_group in frame_5m.groupby("symbol", sort=False):
        left_sorted = left_group.sort_values("timestamp").copy()
        right_sorted = context_1h[context_1h["symbol"] == symbol].sort_values("timestamp").copy()
        if right_sorted.empty:
            merged_blocks.append(left_sorted)
            continue

        right_columns = [column for column in TREND_FEATURE_COLUMNS if column in right_sorted.columns]
        joined = pd.merge_asof(
            left_sorted[["timestamp", *meta_columns, *FEATURE_COLUMNS]],
            right_sorted[["timestamp", *right_columns]],
            on="timestamp",
            direction="backward",
            allow_exact_matches=False,
        )
        # Preserve the canonical 20-feature schema from the 5m feature builder.
        for column in right_columns:
            if column in FEATURE_COLUMNS:
                continue
            joined[column] = pd.to_numeric(joined[column], errors="coerce")
        joined["symbol"] = symbol
        merged_blocks.append(joined)

    merged = pd.concat(merged_blocks, ignore_index=True, copy=False)
    merged = merged.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return merged


__all__ = [
    "BASE_5M_FEATURE_COLUMNS",
    "CONTEXT_1H_FEATURE_COLUMNS",
    "DataConfig",
    "ENTRY_FEATURE_COLUMNS",
    "EXPECTED_FEATURE_COUNT",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "TREND_FEATURE_COLUMNS",
    "align_feature_frame",
    "build_1h_context",
    "check_inference_compatibility",
    "compute_base_features",
    "compute_features",
    "compute_technical_features",
    "finalize_feature_matrix",
    "get_feature_summary",
    "load_timeframe_csv_folder",
    "merge_5m_with_1h_context",
    "validate_feature_contract",
    "validate_features",
]

compute_technical_features = compute_base_features
UNIFIED_FEATURE_COLUMNS = list(FEATURE_COLUMNS)
