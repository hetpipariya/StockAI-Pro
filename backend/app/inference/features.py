"""Legacy feature helpers for the inference runner.

This module preserves the older `app.inference.features` import surface
while delegating feature construction to the canonical feature-engineering
implementation.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from app.inference.feature_engineering import BASE_5M_FEATURE_COLUMNS, FEATURE_COLUMNS, compute_features


def _to_dataframe(ohlcv: pd.DataFrame | Sequence[dict] | None) -> pd.DataFrame:
    if ohlcv is None:
        return pd.DataFrame()
    if isinstance(ohlcv, pd.DataFrame):
        return ohlcv.copy()
    return pd.DataFrame(list(ohlcv))


def extract_features(ohlcv: pd.DataFrame | Sequence[dict]) -> pd.DataFrame:
    """Build the legacy inference feature frame from raw OHLCV input."""

    frame = _to_dataframe(ohlcv)
    if frame.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    for column in ["open", "high", "low", "close", "volume"]:
        if column not in frame.columns:
            frame[column] = 0.0

    return compute_features(frame)


def get_latest_sequence(feature_df: pd.DataFrame, window: int = 20) -> np.ndarray:
    """Return a simple rolling feature sequence for legacy ensemble inputs."""

    frame = feature_df.copy() if isinstance(feature_df, pd.DataFrame) else pd.DataFrame(feature_df)
    if frame.empty:
        return np.zeros((window, len(FEATURE_COLUMNS)), dtype=float)

    columns = [name for name in FEATURE_COLUMNS if name in frame.columns]
    if not columns:
        columns = list(frame.columns[: min(len(frame.columns), len(FEATURE_COLUMNS))])

    trimmed = frame[columns].tail(window).astype(float).to_numpy(copy=True)
    if len(trimmed) < window:
        pad = np.zeros((window - len(trimmed), trimmed.shape[1] if trimmed.ndim == 2 else len(columns)), dtype=float)
        trimmed = np.vstack([pad, trimmed]) if trimmed.size else pad

    if trimmed.ndim == 1:
        trimmed = trimmed.reshape(-1, 1)

    return np.nan_to_num(trimmed, nan=0.0, posinf=0.0, neginf=0.0)


def get_latest_tabular(feature_df: pd.DataFrame) -> np.ndarray:
    """Return the latest feature row as a 2D tabular input."""

    frame = feature_df.copy() if isinstance(feature_df, pd.DataFrame) else pd.DataFrame(feature_df)
    if frame.empty:
        return np.zeros((1, len(FEATURE_COLUMNS)), dtype=float)

    columns = [name for name in FEATURE_COLUMNS if name in frame.columns]
    if not columns:
        columns = list(frame.columns[: min(len(frame.columns), len(FEATURE_COLUMNS))])

    latest = frame.iloc[-1:][columns].astype(float).to_numpy(copy=True)
    return np.nan_to_num(latest, nan=0.0, posinf=0.0, neginf=0.0)


__all__ = [
    "BASE_5M_FEATURE_COLUMNS",
    "FEATURE_COLUMNS",
    "extract_features",
    "get_latest_sequence",
    "get_latest_tabular",
]
