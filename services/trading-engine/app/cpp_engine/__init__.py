"""StockAI Pro native C++ engine package.

This package exposes the compiled pybind11 extension as a normal Python
subpackage entrypoint so backend code can import it directly via:

    from backend.app.cpp_engine import stockai_cpp_engine
"""

from __future__ import annotations

import logging
from types import ModuleType
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

stockai_cpp_engine: Optional[ModuleType]
_import_error: Optional[Exception]

try:
    from . import stockai_cpp_engine as stockai_cpp_engine

    _import_error = None
    __version__ = getattr(stockai_cpp_engine, "FEATURE_VERSION", "unknown")
    FEATURE_VERSION = __version__
    AVAILABLE = True
except Exception as exc:  # pragma: no cover - import failure path
    stockai_cpp_engine = None
    _import_error = exc
    __version__ = "unavailable"
    FEATURE_VERSION = __version__
    AVAILABLE = False
    logger.warning("Native C++ engine is unavailable: %s", exc)


def _normalize_ohlcv_frame(frame: Any) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    if isinstance(frame, pd.DataFrame):
        normalized = frame.copy()
    else:
        normalized = pd.DataFrame(frame)

    if normalized.empty:
        return normalized

    normalized.columns = [str(column).strip().lower() for column in normalized.columns]
    required = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in normalized.columns]
    if missing:
        raise ValueError(f"C++ feature input missing OHLCV columns: {missing}")

    for column in required:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.replace([np.inf, -np.inf], np.nan)
    normalized = normalized.dropna(subset=required)
    return normalized.reset_index(drop=True)


def _close_array(frame: Any) -> np.ndarray:
    if frame is None:
        return np.array([], dtype=np.float64)
    normalized = _normalize_ohlcv_frame(frame)
    if normalized.empty or "close" not in normalized.columns:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(normalized["close"].to_numpy(dtype=np.float64))


def _open_array(frame: Any) -> np.ndarray:
    if frame is None:
        return np.array([], dtype=np.float64)
    normalized = _normalize_ohlcv_frame(frame)
    if normalized.empty or "open" not in normalized.columns:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(normalized["open"].to_numpy(dtype=np.float64))


def _high_array(frame: Any) -> np.ndarray:
    if frame is None:
        return np.array([], dtype=np.float64)
    normalized = _normalize_ohlcv_frame(frame)
    if normalized.empty or "high" not in normalized.columns:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(normalized["high"].to_numpy(dtype=np.float64))


def _low_array(frame: Any) -> np.ndarray:
    if frame is None:
        return np.array([], dtype=np.float64)
    normalized = _normalize_ohlcv_frame(frame)
    if normalized.empty or "low" not in normalized.columns:
        return np.array([], dtype=np.float64)
    return np.ascontiguousarray(normalized["low"].to_numpy(dtype=np.float64))


def compute_features(
    ohlcv_5m: Any,
    ohlcv_15m: Any = None,
    ohlcv_daily: Any = None,
    nifty_data: Any = None,
    sector_data: Any = None,
) -> pd.DataFrame:
    """Compute the canonical v3 C++ feature vector as a single-row DataFrame."""

    if stockai_cpp_engine is None:
        raise RuntimeError(f"Native C++ feature engine is unavailable: {_import_error}")

    frame = _normalize_ohlcv_frame(ohlcv_5m)
    min_candles = int(getattr(stockai_cpp_engine, "MIN_CANDLES_FOR_FEATURES", 50))
    if len(frame) < min_candles:
        raise ValueError(f"Insufficient candles for C++ features: {len(frame)} < {min_candles}")

    result = stockai_cpp_engine.compute_all_features(
        np.ascontiguousarray(frame["open"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(frame["high"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(frame["low"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(frame["close"].to_numpy(dtype=np.float64)),
        np.ascontiguousarray(frame["volume"].to_numpy(dtype=np.float64)),
        _close_array(ohlcv_15m),
        _open_array(ohlcv_daily),
        _high_array(ohlcv_daily),
        _low_array(ohlcv_daily),
        _close_array(ohlcv_daily),
        _close_array(nifty_data),
        _close_array(sector_data),
    )

    status = int(result.get("status", -1))
    if status != 0:
        raise RuntimeError(result.get("error_message") or f"C++ feature computation failed: status={status}")

    feature_names = list(stockai_cpp_engine.get_feature_names())
    feature_values = result.get("features") or {}
    missing = [name for name in feature_names if name not in feature_values]
    if missing:
        raise RuntimeError(f"C++ engine omitted canonical features: {missing}")

    row = [float(feature_values[name]) for name in feature_names]
    matrix = np.nan_to_num(np.asarray([row], dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    return pd.DataFrame(matrix, columns=feature_names)


def is_available() -> bool:
    """Return True when the compiled native module loaded successfully."""

    return AVAILABLE and stockai_cpp_engine is not None


def import_error() -> Optional[Exception]:
    """Return the import error captured during package initialization."""

    return _import_error


if stockai_cpp_engine is not None:
    stockai_cpp_engine.compute_features = compute_features
    stockai_cpp_engine.FEATURE_COLUMNS = list(stockai_cpp_engine.get_feature_names())


__all__ = [
    "AVAILABLE",
    "FEATURE_VERSION",
    "__version__",
    "import_error",
    "is_available",
    "compute_features",
    "stockai_cpp_engine",
]
