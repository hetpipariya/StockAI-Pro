from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.cpp_engine import stockai_cpp_engine
from app.inference.feature_engineering import FEATURE_COLUMNS, align_feature_frame

import logging

logger = logging.getLogger(__name__)


def _load_native_module() -> Any | None:
    return None


def is_native_available() -> bool:
    return stockai_cpp_engine is not None


def _frame_from_ohlcv(ohlcv: pd.DataFrame | list[dict[str, Any]] | None) -> pd.DataFrame:
    if ohlcv is None:
        return pd.DataFrame()
    if isinstance(ohlcv, pd.DataFrame):
        frame = ohlcv.copy()
    else:
        frame = pd.DataFrame(ohlcv)

    if frame.empty:
        return frame

    frame = frame.copy()
    frame.columns = [str(col).lower() for col in frame.columns]
    for column in ["open", "high", "low", "close", "volume"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(
        subset=[column for column in ["open", "high", "low", "close", "volume"] if column in frame.columns]
    )
    return frame.reset_index(drop=True)


def _native_pack_to_frame(native_result: Any, *, index: pd.Index | None = None) -> pd.DataFrame | None:
    if not isinstance(native_result, dict) or not native_result:
        return None

    converted: dict[str, Any] = {}
    length: int | None = None

    for key, value in native_result.items():
        if value is None:
            continue

        if isinstance(value, (str, bytes)):
            converted[str(key)] = value
            continue

        array = np.asarray(value)
        if array.ndim == 0:
            converted[str(key)] = [array.item()]
            length = length or 1
            continue

        converted[str(key)] = array
        if length is None:
            length = int(array.shape[0])

    if not converted:
        return None

    frame = pd.DataFrame(converted)
    if index is not None and len(frame) == len(index):
        frame.index = index
    return frame


def compute_feature_frame(
    ohlcv: pd.DataFrame | list[dict[str, Any]] | None,
    include_legacy: bool = False,
) -> pd.DataFrame | None:
    del include_legacy
    if stockai_cpp_engine is None:
        return None

    frame = _frame_from_ohlcv(ohlcv)
    if frame.empty:
        return None

    try:
        result = stockai_cpp_engine.compute_features(frame)
    except Exception as exc:
        logger.debug("[NATIVE] C++ compute_features failed: %s", exc)
        return None

    try:
        return align_feature_frame(result, FEATURE_COLUMNS, context="native_accelerators")
    except Exception as exc:
        logger.debug("[NATIVE] C++ feature frame validation failed: %s", exc)
        return None


def compute_indicator_frame(
    ohlcv: pd.DataFrame | list[dict[str, Any]] | None,
) -> pd.DataFrame | None:
    return compute_feature_frame(ohlcv)


def get_native_candle_aggregator(timeframe_minutes: int, history_limit: int = 240) -> Any | None:
    del timeframe_minutes, history_limit
    return None


def compute_signal_filter(
    *,
    signal: str,
    confidence: float,
    trend_strength: float,
    volatility: float,
    volume_ratio: float,
    mtf_score: float,
    rr_ratio: float,
    market_open: bool,
    stale: bool,
) -> dict[str, Any] | None:
    native = _load_native_module()
    if native is None:
        return None

    try:
        result = native.compute_signal_filter(  # type: ignore[attr-defined]
            str(signal),
            float(confidence),
            float(trend_strength),
            float(volatility),
            float(volume_ratio),
            float(mtf_score),
            float(rr_ratio),
            bool(market_open),
            bool(stale),
        )
    except Exception as exc:
        logger.debug("[NATIVE] compute_signal_filter failed: %s", exc)
        return None

    if isinstance(result, dict):
        return result
    return None


def compute_confidence(
    *,
    ml_probability: float,
    fusion_score: float,
    regime_score: float,
    trend_strength: float,
    volume_ratio: float,
    mtf_score: float,
) -> float | None:
    native = _load_native_module()
    if native is None:
        return None

    try:
        value = native.compute_confidence(  # type: ignore[attr-defined]
            float(ml_probability),
            float(fusion_score),
            float(regime_score),
            float(trend_strength),
            float(volume_ratio),
            float(mtf_score),
        )
    except Exception as exc:
        logger.debug("[NATIVE] compute_confidence failed: %s", exc)
        return None

    try:
        return float(value)
    except Exception:
        return None


def compute_market_regime(
    *,
    ema_fast: float,
    ema_slow: float,
    rsi: float,
    atr_pct: float,
    adx: float,
    volume_ratio: float,
    mtf_score: float,
) -> dict[str, Any] | None:
    native = _load_native_module()
    if native is None:
        return None

    try:
        result = native.compute_market_regime(  # type: ignore[attr-defined]
            float(ema_fast),
            float(ema_slow),
            float(rsi),
            float(atr_pct),
            float(adx),
            float(volume_ratio),
            float(mtf_score),
        )
    except Exception as exc:
        logger.debug("[NATIVE] compute_market_regime failed: %s", exc)
        return None

    if isinstance(result, dict):
        return result
    return None


def compute_stochastic_k(
    ohlcv: pd.DataFrame | list[dict[str, Any]] | None,
    period: int = 14,
) -> np.ndarray | None:
    native = _load_native_module()
    if native is None:
        return None

    frame = _frame_from_ohlcv(ohlcv)
    if frame.empty:
        return None

    try:
        return np.asarray(native.compute_stochastic_k(
            frame["high"].to_numpy(dtype=np.float64, copy=False),
            frame["low"].to_numpy(dtype=np.float64, copy=False),
            frame["close"].to_numpy(dtype=np.float64, copy=False),
            int(period),
        ))
    except Exception as exc:
        logger.debug("[NATIVE] compute_stochastic_k failed: %s", exc)
        return None


def compute_cci(
    ohlcv: pd.DataFrame | list[dict[str, Any]] | None,
    period: int = 20,
) -> np.ndarray | None:
    native = _load_native_module()
    if native is None:
        return None

    frame = _frame_from_ohlcv(ohlcv)
    if frame.empty:
        return None

    try:
        return np.asarray(native.compute_cci(
            frame["high"].to_numpy(dtype=np.float64, copy=False),
            frame["low"].to_numpy(dtype=np.float64, copy=False),
            frame["close"].to_numpy(dtype=np.float64, copy=False),
            int(period),
        ))
    except Exception as exc:
        logger.debug("[NATIVE] compute_cci failed: %s", exc)
        return None


def compute_mfi(
    ohlcv: pd.DataFrame | list[dict[str, Any]] | None,
    period: int = 14,
) -> np.ndarray | None:
    native = _load_native_module()
    if native is None:
        return None

    frame = _frame_from_ohlcv(ohlcv)
    if frame.empty:
        return None

    try:
        return np.asarray(native.compute_mfi(
            frame["high"].to_numpy(dtype=np.float64, copy=False),
            frame["low"].to_numpy(dtype=np.float64, copy=False),
            frame["close"].to_numpy(dtype=np.float64, copy=False),
            frame["volume"].to_numpy(dtype=np.float64, copy=False),
            int(period),
        ))
    except Exception as exc:
        logger.debug("[NATIVE] compute_mfi failed: %s", exc)
        return None


def compute_bb_extended(
    ohlcv: pd.DataFrame | list[dict[str, Any]] | None,
    period: int = 20,
    multiplier: float = 2.0,
) -> dict[str, np.ndarray] | None:
    native = _load_native_module()
    if native is None:
        return None

    frame = _frame_from_ohlcv(ohlcv)
    if frame.empty:
        return None

    try:
        result = native.compute_bb_extended(
            frame["close"].to_numpy(dtype=np.float64, copy=False),
            int(period),
            float(multiplier),
        )
    except Exception as exc:
        logger.debug("[NATIVE] compute_bb_extended failed: %s", exc)
        return None

    if isinstance(result, dict):
        return {k: np.asarray(v) for k, v in result.items()}
    return None


def get_incremental_feature_engine(**kwargs: Any) -> Any | None:
    """Create a native IncrementalFeatureEngine for O(1) per-candle updates."""
    native = _load_native_module()
    if native is None:
        return None

    try:
        return native.IncrementalFeatureEngine(**kwargs)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.debug("[NATIVE] IncrementalFeatureEngine unavailable: %s", exc)
        return None
