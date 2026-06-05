"""Canonical 20-feature contract shared by training and runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from app.cpp_engine import FEATURE_VERSION as CPP_FEATURE_VERSION
from app.cpp_engine import stockai_cpp_engine

EXPECTED_FEATURE_COLUMNS: list[str] = [
    "ema_9_21_ratio",
    "close_to_ema50_pct",
    "linreg_slope_20",
    "adx_14",
    "rsi_14",
    "macd_hist_pct",
    "stoch_rsi_k",
    "cci_20_clamped",
    "volume_ratio_20",
    "mfi_14",
    "relative_volume_intraday",
    "atr_pct",
    "bb_width_pct",
    "bb_pct_b",
    "vwap_distance_pct",
    "vwap_zscore_20",
    "cpr_width_pct",
    "bos_strength_pct",
    "fvg_gap_pct",
    "candle_body_ratio",
    "nifty_direction",
    "sector_strength_pct",
    "daily_distance_ema50_pct",
    "session_progress_pct",
]

CPP_RAW_FEATURE_COLUMNS: list[str] = list(EXPECTED_FEATURE_COLUMNS)

CPP_TO_CANONICAL = {name: name for name in CPP_RAW_FEATURE_COLUMNS}

FEATURE_COLUMNS: list[str] = list(EXPECTED_FEATURE_COLUMNS)
EXPECTED_FEATURE_COUNT = len(EXPECTED_FEATURE_COLUMNS)
FEATURE_VERSION = str(CPP_FEATURE_VERSION or "v3.0_cpp")


def _native_feature_names() -> list[str]:
    if stockai_cpp_engine is None:
        return list(EXPECTED_FEATURE_COLUMNS)
    names = [str(name) for name in stockai_cpp_engine.get_feature_names()]
    if names != CPP_RAW_FEATURE_COLUMNS:
        raise RuntimeError(
            "C++ feature contract mismatch. "
            f"Expected {CPP_RAW_FEATURE_COLUMNS}, got {names}"
        )
    return [CPP_TO_CANONICAL[name] for name in names]


NATIVE_FEATURE_COLUMNS = _native_feature_names()


@dataclass(frozen=True)
class FeatureContractError(RuntimeError):
    message: str

    def __str__(self) -> str:  # pragma: no cover - inherited behavior wrapper
        return self.message


def _normalize_columns(columns: Iterable[str] | pd.DataFrame | pd.Series | None) -> list[str]:
    if columns is None:
        return []
    if isinstance(columns, pd.DataFrame):
        return [str(column) for column in columns.columns]
    if isinstance(columns, pd.Series):
        return [str(columns.name)] if columns.name else []
    return [str(column) for column in columns]


def _canonical_expected(expected: Sequence[str] | None) -> list[str]:
    expected_list = list(EXPECTED_FEATURE_COLUMNS if expected is None else [str(col) for col in expected])
    if set(expected_list) == set(EXPECTED_FEATURE_COLUMNS):
        return list(EXPECTED_FEATURE_COLUMNS)
    return expected_list


def validate_features(
    actual: Iterable[str] | pd.DataFrame | None,
    expected: Sequence[str] | None = None,
    context: str = "feature_contract",
) -> list[str]:
    actual_list = _normalize_columns(actual)
    expected_list = _canonical_expected(expected)

    missing = [column for column in expected_list if column not in actual_list]
    extra = [column for column in actual_list if column not in expected_list]
    if missing:
        raise FeatureContractError(f"[{context}] Missing feature columns: {missing}")
    if extra:
        raise FeatureContractError(f"[{context}] Extra feature columns: {extra}")
    if actual_list != expected_list:
        raise FeatureContractError(
            f"[{context}] Order mismatch. Expected {expected_list}, got {actual_list}"
        )
    return expected_list


def validate_feature_contract(
    frame_or_columns: pd.DataFrame | Iterable[str] | None,
    expected: Sequence[str] | None = None,
    context: str = "feature_contract",
) -> list[str]:
    expected_list = _canonical_expected(expected)
    if isinstance(frame_or_columns, pd.DataFrame):
        validate_features(frame_or_columns.columns, expected_list, context=context)
        matrix = frame_or_columns[expected_list].apply(pd.to_numeric, errors="coerce")
        nan_rows = int(matrix.isna().any(axis=1).sum())
        inf_rows = int(np.isinf(matrix.to_numpy(dtype=float)).any(axis=1).sum()) if len(matrix) else 0
        if nan_rows:
            raise FeatureContractError(f"[{context}] Feature frame contains NaN rows: {nan_rows}")
        if inf_rows:
            raise FeatureContractError(f"[{context}] Feature frame contains inf rows: {inf_rows}")
        return expected_list
    return validate_features(frame_or_columns, expected_list, context=context)


def align_feature_frame(
    frame: pd.DataFrame | None,
    expected: Sequence[str] | None = None,
    context: str = "feature_contract",
) -> pd.DataFrame:
    expected_list = _canonical_expected(expected)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=expected_list)

    out = frame.copy()
    missing = [column for column in expected_list if column not in out.columns]
    if missing:
        raise FeatureContractError(f"[{context}] Missing feature columns: {missing}")

    out = out.loc[:, expected_list].copy()
    out = out.apply(pd.to_numeric, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan)
    if out.isna().any().any():
        nan_rows = int(out.isna().any(axis=1).sum())
        raise FeatureContractError(f"[{context}] Feature frame contains NaN rows: {nan_rows}")
    return out


def check_inference_compatibility(
    model_features: Sequence[str] | None,
    runtime_features: Sequence[str] | None = None,
) -> None:
    validate_features(
        model_features or [],
        expected=_canonical_expected(runtime_features),
        context="inference_compatibility",
    )


def get_feature_summary(feature_df: pd.DataFrame | None) -> dict[str, float | int | str]:
    if feature_df is None or feature_df.empty:
        return {"error": "empty_feature_frame"}

    frame = align_feature_frame(feature_df, FEATURE_COLUMNS, context="feature_summary")
    latest = frame.iloc[-1]
    summary: dict[str, float | int | str] = {
        column: float(latest[column]) for column in FEATURE_COLUMNS
    }
    summary["_rows_used"] = int(len(frame))
    summary["_nan_count"] = int(frame.isna().sum().sum())
    summary["_inf_count"] = int(np.isinf(frame.to_numpy(dtype=float)).sum())
    summary["_feature_version"] = FEATURE_VERSION
    return summary


__all__ = [
    "EXPECTED_FEATURE_COLUMNS",
    "EXPECTED_FEATURE_COUNT",
    "CPP_RAW_FEATURE_COLUMNS",
    "CPP_TO_CANONICAL",
    "FEATURE_COLUMNS",
    "FEATURE_VERSION",
    "FeatureContractError",
    "align_feature_frame",
    "check_inference_compatibility",
    "get_feature_summary",
    "validate_feature_contract",
    "validate_features",
]
