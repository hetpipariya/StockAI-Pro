"""
Real prediction engine — Machine Learning Ensemble + Technical Scoring

Uses feature_engineering.py as the single source of truth for features.
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import joblib
import numpy as np
import pandas as pd

from app import config
from app.inference.feature_engineering import (FEATURE_COLUMNS,
                                               FEATURE_VERSION,
                                               apply_feature_compatibility,
                                               compute_features,
                                               get_feature_summary,
                                               validate_features)
from app.inference.liquidity_order_flow import compute_liquidity_order_flow
from app.inference.multi_timeframe_alignment import compute_multi_timeframe_alignment
from app.inference.risk_position_context import compute_risk_position_context
from app.inference.time_intelligence import compute_time_intelligence
from app.inference.volume_intelligence import build_feature_vector

logger = logging.getLogger(__name__)

# ── Model directory resolution ──────────────────────────────────────────────
# Priority: MODEL_PATH env var → /app/models (Docker) → relative paths
_p2 = Path(__file__).resolve().parents[2]
_p3 = Path(__file__).resolve().parents[3]

_env_model_path = os.getenv("MODEL_PATH", "").strip()
MODEL_DIR = None

if _env_model_path and Path(_env_model_path).exists():
    MODEL_DIR = Path(_env_model_path)
else:
    for candidate in [
        Path("/app/models"),
        _p2 / "models",
        _p3 / "models",
    ]:
        if (candidate / "model.pkl").exists():
            MODEL_DIR = candidate
            break

if MODEL_DIR is None:
    MODEL_DIR = _p2 / "models"

MODEL_DIR.mkdir(parents=True, exist_ok=True)
logger.info(
    "[MODELS] Using model directory: %s (exists=%s, has_model=%s)",
    MODEL_DIR,
    MODEL_DIR.exists(),
    (MODEL_DIR / "model.pkl").exists(),
)

_ensemble_model = None
_scaler = None
_features_list = None
_model_version = None
REQUIRED_MODEL_FILES = ("model.pkl", "scaler.pkl", "features.pkl")


def _missing_model_files() -> list[str]:
    return [name for name in REQUIRED_MODEL_FILES if not (MODEL_DIR / name).exists()]


def _ensure_model_feature_columns(
    feature_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    required_features: list[str],
) -> pd.DataFrame:
    """Augment canonical features with legacy columns expected by older artifacts."""
    if feature_df is None or feature_df.empty:
        return feature_df

    out = feature_df.copy()
    if not required_features:
        return out

    raw = ohlcv_df.copy()
    raw.columns = [str(col).lower() for col in raw.columns]

    def _raw_series(name: str) -> pd.Series:
        if name not in raw.columns:
            return pd.Series(np.zeros(len(out), dtype=float), index=out.index)
        series = pd.to_numeric(raw[name], errors="coerce")
        if not series.index.equals(out.index):
            series = series.reindex(out.index)
        return series.bfill().ffill().fillna(0.0)

    close_series = _raw_series("close")
    open_series = _raw_series("open")
    high_series = _raw_series("high")
    low_series = _raw_series("low")
    volume_series = _raw_series("volume")

    ema9 = close_series.ewm(span=9, adjust=False).mean()
    ema12 = close_series.ewm(span=12, adjust=False).mean()
    ema20 = close_series.ewm(span=20, adjust=False).mean()
    ema21 = close_series.ewm(span=21, adjust=False).mean()
    ema26 = close_series.ewm(span=26, adjust=False).mean()
    ema50 = close_series.ewm(span=50, adjust=False).mean()
    macd_series = ema12 - ema26
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
    vwap = (typical_price * volume_series).cumsum() / (volume_series.cumsum() + 1e-9)

    pct_change_1d = close_series.pct_change(1)
    vol_ma20 = volume_series.rolling(20, min_periods=1).mean()
    vol_std20 = volume_series.rolling(20, min_periods=3).std()
    volume_ratio_series = volume_series / (vol_ma20 + 1e-9)
    volume_zscore_series = (volume_series - vol_ma20) / (vol_std20 + 1e-9)
    volume_spike_strength_series = np.maximum(
        volume_ratio_series / 2.0,
        volume_zscore_series / 2.0,
    )
    vwap_dev_series = (close_series - vwap) / (vwap + 1e-9)

    obv_direction = np.sign(close_series.diff().fillna(0.0))
    obv_series = (obv_direction * volume_series).cumsum()
    obv_ema = obv_series.ewm(span=20, adjust=False).mean()
    obv_slope = obv_ema.diff()
    obv_slope_norm = np.tanh(obv_slope / (vol_ma20 + 1e-9))
    obv_divergence = (
        ((close_series.diff(10) > 0) & (obv_series.diff(10) < 0))
        | ((close_series.diff(10) < 0) & (obv_series.diff(10) > 0))
    ).astype(int)

    volume_fast = volume_series.ewm(span=10, adjust=False).mean()
    volume_slow = volume_series.ewm(span=20, adjust=False).mean()
    volume_trend_slope = (volume_fast - volume_slow) / (volume_slow + 1e-9)
    volume_trend_direction_score = np.where(
        volume_trend_slope > 0.03,
        1.0,
        np.where(volume_trend_slope < -0.03, -1.0, 0.0),
    )

    legacy_builders: dict[str, Any] = {
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
        "macd": lambda: (
            pd.to_numeric(out["macd"], errors="coerce")
            if "macd" in out.columns
            else macd_series
        ),
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
        "trend_strength": lambda: (close_series - ema20) / (ema20 + 1e-9),
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
    }

    for feature_name in required_features:
        if feature_name in out.columns:
            continue
        builder = legacy_builders.get(feature_name)
        if builder is not None:
            out[feature_name] = builder()
        else:
            out[feature_name] = 0.0

    for feature_name in required_features:
        out[feature_name] = pd.to_numeric(out[feature_name], errors="coerce").fillna(
            0.0
        )

    out.replace([np.inf, -np.inf], 0.0, inplace=True)
    return out


def ensure_models_loaded(max_retries: int = 3) -> bool:
    """Best-effort model load with bounded retries."""
    if _ensemble_model is not None:
        return True

    for attempt in range(1, max_retries + 1):
        try:
            load_models()
            if _ensemble_model is not None:
                return True
        except Exception as exc:
            logger.warning(
                "[MODELS] Load attempt %d/%d failed: %s", attempt, max_retries, exc
            )
        if attempt < max_retries:
            time.sleep(min(0.25 * attempt, 1.0))
    return _ensemble_model is not None


def load_models():
    """Load trained ML models from disk if available.

    Validates model feature version and specific columns to prevent silent drift.
    """
    global _ensemble_model, _scaler, _features_list, _model_version

    model_path = MODEL_DIR / "model.pkl"
    missing_files = _missing_model_files()
    if missing_files:
        logger.warning(
            "[MODELS] Missing model artifacts in %s: %s. Prediction endpoints will "
            "use HOLD-safe fallback until artifacts are restored.",
            MODEL_DIR,
            ", ".join(missing_files),
        )

    if not model_path.exists():
        logger.error(
            "[MODELS] model.pkl missing in %s — falling back to safe hold.", MODEL_DIR
        )
        _ensemble_model = None
        _scaler = None
        _features_list = None
        _model_version = None
        return

    try:
        payload = joblib.load(model_path)
    except Exception as e:
        logger.warning("[MODELS] Failed to load model.pkl (corrupted?): %s", e)
        _ensemble_model = None
        _scaler = None
        _features_list = None
        _model_version = None
        return

    if not isinstance(payload, dict) or "version" not in payload:
        logger.info(
            "[MODELS] Legacy model payload detected. Wrapping into modern dictionary format."
        )
        if isinstance(payload, dict):
            # Old dictionary format missing version
            model_obj = payload.get("model", payload)
            scaler_obj = payload.get("scaler", None)
            feat_list = payload.get("features") or payload.get("feature_columns")
        else:
            # Raw model object
            model_obj = payload
            scaler_obj = None
            feat_list = None

        # Backward compatibility: load sidecar artifacts if legacy model.pkl is raw.
        if scaler_obj is None:
            scaler_path = MODEL_DIR / "scaler.pkl"
            if scaler_path.exists():
                try:
                    scaler_obj = joblib.load(scaler_path)
                    logger.info(
                        "[MODELS] Loaded sidecar scaler artifact: %s", scaler_path
                    )
                except Exception as exc:
                    logger.warning(
                        "[MODELS] Failed loading sidecar scaler %s: %s",
                        scaler_path,
                        exc,
                    )

        if feat_list is None:
            features_path = MODEL_DIR / "features.pkl"
            if features_path.exists():
                try:
                    loaded_features = joblib.load(features_path)
                    if isinstance(loaded_features, (list, tuple)):
                        feat_list = list(loaded_features)
                        logger.info(
                            "[MODELS] Loaded sidecar features artifact: %s",
                            features_path,
                        )
                except Exception as exc:
                    logger.warning(
                        "[MODELS] Failed loading sidecar features %s: %s",
                        features_path,
                        exc,
                    )

        if feat_list is None:
            feat_list = FEATURE_COLUMNS

        payload = {
            "model": model_obj,
            "scaler": scaler_obj,
            "features": feat_list,
            "version": FEATURE_VERSION,
        }

    loaded_version = payload.get("version")
    if loaded_version != FEATURE_VERSION:
        logger.warning(
            "[MODELS] Feature version mismatch (model=%s runtime=%s). "
            "Running in compatibility mode.",
            loaded_version,
            FEATURE_VERSION,
        )

    _ensemble_model = payload.get("model")
    _scaler = payload.get("scaler")
    _features_list = payload.get("features")
    _model_version = loaded_version

    # Strict validation for canonical artifacts; legacy artifacts run in compatibility mode.
    try:
        validate_features(
            _features_list,
            FEATURE_COLUMNS,
            context="load_models() vs FEATURE_COLUMNS",
        )
    except Exception as exc:
        logger.warning(
            "[MODELS] Feature contract mismatch; enabling legacy compatibility mode: %s",
            exc,
        )

    logger.info(
        "[MODELS] ✓ Loaded ML Ensemble Pipeline — %d features validated.",
        len(_features_list),
    )


# ─── Multi-Engine Helpers ──────────────────────────────────────────────────


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _clip_signed(value: float) -> float:
    return float(np.clip(value, -1.0, 1.0))


def _score_from_signed(signed_value: float) -> float:
    return _clip01(0.5 + (0.5 * _clip_signed(signed_value)))


FINAL_FUSION_WEIGHTS: dict[str, float] = {
    "trend_score": 0.15,
    "momentum_score": 0.10,
    "volatility_score": 0.10,
    "volume_score": 0.10,
    "price_action_score": 0.10,
    "structure_score": 0.10,
    "mtf_score": 0.10,
    "regime_score": 0.08,
    "liquidity_score": 0.05,
    "time_score": 0.05,
    "risk_score": 0.04,
    "ai_score": 0.03,
}


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame is None or column not in frame.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(frame[column], errors="coerce")
    series = series.replace([np.inf, -np.inf], np.nan)
    return series.dropna().reset_index(drop=True)


def _extract_directional_probabilities(model: Any, scaled_row: np.ndarray) -> tuple[float, float]:
    """Return (prob_up, prob_down) for both binary and multiclass classifiers."""
    if not hasattr(model, "predict_proba"):
        return 0.5, 0.5

    probabilities = np.asarray(model.predict_proba(scaled_row))[0]
    classes = getattr(model, "classes_", np.arange(len(probabilities)))

    class_to_index: dict[int, int] = {}
    for idx, class_label in enumerate(classes):
        try:
            class_to_index[int(class_label)] = idx
        except Exception:
            continue

    if 1 in class_to_index:
        prob_up = float(probabilities[class_to_index[1]])
    elif len(probabilities) >= 2:
        prob_up = float(probabilities[-1])
    else:
        prob_up = float(probabilities[0])

    if -1 in class_to_index:
        prob_down = float(probabilities[class_to_index[-1]])
    elif len(probabilities) == 2 and 1 in class_to_index:
        prob_down = 1.0 - prob_up
    elif len(probabilities) >= 2:
        prob_down = float(probabilities[0])
    else:
        prob_down = 1.0 - prob_up

    if not np.isfinite(prob_up):
        prob_up = 0.5
    if not np.isfinite(prob_down):
        prob_down = 0.5

    prob_up = float(np.clip(prob_up, 0.0, 1.0))
    prob_down = float(np.clip(prob_down, 0.0, 1.0))

    return prob_up, prob_down


def _resample_close(close: pd.Series, step: int) -> pd.Series:
    if close.empty:
        return close
    if step <= 1:
        return close.reset_index(drop=True)
    buckets = np.arange(len(close)) // step
    return close.groupby(buckets).last().reset_index(drop=True)


def _compute_regime_engine(
    range_or_trend: str,
    volatility_state: str,
    mtf_alignment: str,
    trend_score: float,
    structure_score: float,
) -> Dict[str, Any]:
    range_state = str(range_or_trend or "RANGE").upper()
    vol_state = str(volatility_state or "MISSING").upper()
    mtf_state = str(mtf_alignment or "MISSING").upper()

    if range_state == "RANGE" or mtf_state in {"CONFLICTING", "NEUTRAL", "MISSING"}:
        regime_state = "SIDEWAYS"
        regime_score = _clip01(0.20 + (0.20 * _clip01(structure_score)))
        public_regime = "Ranging"
    elif vol_state in {"HIGH_VOLATILITY", "BREAKOUT"}:
        regime_state = "VOLATILE"
        regime_score = _clip01(
            0.45 + (0.35 * ((_clip01(trend_score) + _clip01(structure_score)) / 2.0))
        )
        public_regime = "Volatile"
    else:
        regime_state = "TRENDING"
        regime_score = _clip01(
            0.65 + (0.30 * ((_clip01(trend_score) + _clip01(structure_score)) / 2.0))
        )
        public_regime = "Trending"

    return {
        "regime_state": regime_state,
        "regime": public_regime,
        "regime_score": round(float(regime_score), 4),
    }


def _compute_ai_engine(
    feature_df: pd.DataFrame,
    ml_prob_up: Optional[float],
    momentum_score: float,
    trend_score: float,
    indicator_fusion_score: float,
) -> Dict[str, Any]:
    if feature_df is None or feature_df.empty:
        return {
            "ai_score": 0.5,
            "ai_label": "NEUTRAL",
            "components": {},
        }

    latest = feature_df.iloc[-1]

    norm_cols = [
        "ema_rsi_norm",
        "macd_volume_norm",
        "volume_ratio_norm",
        "rolling_std_20_norm",
    ]
    norm_values: list[float] = []
    for col in norm_cols:
        if col in latest:
            norm_values.append(_clip01(float(latest.get(col, 0.5) or 0.5)))
    derived_norm_score = float(np.mean(norm_values)) if norm_values else 0.5

    z_cols = [
        "ema_rsi_z",
        "macd_volume_z",
        "momentum_z",
        "volume_change_z",
        "rolling_std_20_z",
    ]
    z_values: list[float] = []
    for col in z_cols:
        if col in latest:
            value = float(latest.get(col, 0.0) or 0.0)
            z_values.append(min(abs(value), 4.0) / 4.0)
    stability_score = 1.0 - float(np.mean(z_values)) if z_values else 0.5
    stability_score = _clip01(stability_score)

    prob_up = float(ml_prob_up) if ml_prob_up is not None else 0.5
    ml_certainty = _clip01(abs(prob_up - 0.5) * 2.0)
    alignment_score = _clip01(1.0 - abs(_clip01(momentum_score) - _clip01(trend_score)))

    fusion_norm = _clip01((float(indicator_fusion_score) + 1.0) / 2.0)
    coherence_score = _clip01(1.0 - abs(fusion_norm - _clip01(trend_score)))

    ai_score = _clip01(
        (0.30 * derived_norm_score)
        + (0.20 * stability_score)
        + (0.30 * ml_certainty)
        + (0.10 * alignment_score)
        + (0.10 * coherence_score)
    )

    if ai_score >= 0.70:
        ai_label = "HIGH"
    elif ai_score <= 0.35:
        ai_label = "LOW"
    else:
        ai_label = "NEUTRAL"

    return {
        "ai_score": round(float(ai_score), 4),
        "ai_label": ai_label,
        "components": {
            "derived_norm": round(float(derived_norm_score), 4),
            "stability": round(float(stability_score), 4),
            "ml_certainty": round(float(ml_certainty), 4),
            "alignment": round(float(alignment_score), 4),
            "coherence": round(float(coherence_score), 4),
        },
    }


def _compute_risk_score(rr_value: float, position_size_factor: float, volatility_score: float) -> float:
    rr_component = _clip01((float(rr_value) - 1.0) / 1.5)
    size_component = _clip01(float(position_size_factor))
    vol_component = _clip01(1.0 - max(float(volatility_score) - 0.60, 0.0))
    return _clip01((0.60 * rr_component) + (0.25 * size_component) + (0.15 * vol_component))


def _compute_weighted_fusion_score(engine_scores: Dict[str, float]) -> float:
    total = 0.0
    for score_name, weight in FINAL_FUSION_WEIGHTS.items():
        total += float(weight) * _clip01(float(engine_scores.get(score_name, 0.5)))
    return _clip01(total)


def _is_mtf_aligned(mtf_alignment: str, mtf_conflict: bool) -> bool:
    return str(mtf_alignment or "MISSING").upper() in {"STRONG", "WEAK"} and (not bool(mtf_conflict))


def _estimate_directional_bias(trend_score: float, momentum_score: float) -> str:
    trend = _clip01(trend_score)
    momentum = _clip01(momentum_score)

    if trend >= 0.55 and momentum >= 0.55:
        return "BUY"
    if trend <= 0.45 and momentum <= 0.45:
        return "SELL"
    if trend >= 0.62:
        return "BUY"
    if trend <= 0.38:
        return "SELL"
    return "HOLD"


def _derive_target_price(
    side: str,
    entry_price: float,
    atr_proxy: float,
    structure_info: Dict[str, Any],
) -> float:
    entry = float(max(entry_price, 0.0))
    atr = float(max(atr_proxy, entry * 0.005))
    breakout = bool(structure_info.get("breakout", False))
    breakout_type = str(structure_info.get("breakout_type", "NONE")).upper()
    nearest_support = structure_info.get("nearest_support")
    nearest_resistance = structure_info.get("nearest_resistance")

    if side == "BUY":
        if breakout and breakout_type == "BULLISH" and nearest_resistance:
            return float(nearest_resistance) + (0.50 * atr)
        if nearest_resistance and float(nearest_resistance) > entry:
            return float(nearest_resistance)
        return entry + max(atr * 1.2, entry * 0.008)

    if side == "SELL":
        if breakout and breakout_type == "BEARISH" and nearest_support:
            return float(nearest_support) - (0.50 * atr)
        if nearest_support and float(nearest_support) < entry:
            return float(nearest_support)
        return entry - max(atr * 1.2, entry * 0.008)

    return entry


def _compute_momentum_engine(
    feature_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    ml_prob_up: Optional[float],
) -> Dict[str, Any]:
    latest = feature_df.iloc[-1].to_dict()
    close = _numeric_series(ohlcv_df, "close")
    volume = _numeric_series(ohlcv_df, "volume")

    if close.empty:
        return {
            "momentum_score": 0.5,
            "momentum_label": "NEUTRAL",
            "signed": 0.0,
            "components": {},
            "ml_prob_up": ml_prob_up,
        }

    current_price = float(close.iloc[-1])
    ret1 = float(close.pct_change(1).fillna(0.0).iloc[-1])
    ret5 = float(close.pct_change(5).fillna(0.0).iloc[-1])
    ret10 = float(close.pct_change(10).fillna(0.0).iloc[-1])
    ret20 = float(close.pct_change(20).fillna(0.0).iloc[-1])
    returns_signed = float(np.tanh((ret1 * 0.35 + ret5 * 0.30 + ret10 * 0.20 + ret20 * 0.15) * 12.0))

    rsi = float(latest.get("rsi", 50.0) or 50.0)
    rsi_signed = _clip_signed((rsi - 50.0) / 25.0)

    macd = float(latest.get("macd", 0.0) or 0.0)
    macd_signal = float(latest.get("macd_signal", macd * 0.9) or 0.0)
    macd_signed = float(np.tanh((macd - macd_signal) / max(current_price, 1e-9) * 400.0))

    bb_upper = float(latest.get("bollinger_upper", current_price) or current_price)
    bb_lower = float(latest.get("bollinger_lower", current_price) or current_price)
    if bb_upper > bb_lower:
        bb_position = ((current_price - bb_lower) / (bb_upper - bb_lower)) * 2.0 - 1.0
        bollinger_signed = _clip_signed(bb_position)
    else:
        bollinger_signed = 0.0

    volume_change = float(latest.get("volume_change", 0.0) or 0.0)
    volume_signed = float(np.tanh(volume_change * 1.5))

    if volume.empty:
        obv_signed = 0.0
    else:
        direction = np.sign(close.diff().fillna(0.0))
        volume_aligned = volume.reindex(close.index).fillna(0.0)
        obv = (direction * volume_aligned).cumsum()
        obv_fast = float(obv.rolling(5, min_periods=1).mean().iloc[-1])
        obv_slow = float(obv.rolling(20, min_periods=1).mean().iloc[-1])
        denom = float(volume_aligned.tail(20).mean() * 20.0 + 1e-9)
        obv_signed = float(np.tanh(((obv_fast - obv_slow) / denom) * 5.0))

    momentum_raw = float(latest.get("momentum", 0.0) or 0.0)
    momentum_signed = float(np.tanh((momentum_raw / max(current_price, 1e-9)) * 20.0))

    heuristic_signed = _clip_signed(
        (0.25 * returns_signed)
        + (0.20 * rsi_signed)
        + (0.20 * macd_signed)
        + (0.10 * bollinger_signed)
        + (0.10 * volume_signed)
        + (0.10 * obv_signed)
        + (0.05 * momentum_signed)
    )

    if ml_prob_up is not None:
        ml_signed = _clip_signed((float(ml_prob_up) - 0.5) / 0.5)
        final_signed = _clip_signed((0.60 * ml_signed) + (0.40 * heuristic_signed))
    else:
        final_signed = heuristic_signed

    momentum_score = _score_from_signed(final_signed)
    if momentum_score > 0.65:
        momentum_label = "BULLISH"
    elif momentum_score < 0.35:
        momentum_label = "BEARISH"
    else:
        momentum_label = "NEUTRAL"

    return {
        "momentum_score": round(momentum_score, 4),
        "momentum_label": momentum_label,
        "signed": round(final_signed, 4),
        "ml_prob_up": round(float(ml_prob_up), 4) if ml_prob_up is not None else None,
        "components": {
            "returns": round(returns_signed, 4),
            "rsi": round(rsi_signed, 4),
            "macd": round(macd_signed, 4),
            "bollinger": round(bollinger_signed, 4),
            "volume": round(volume_signed, 4),
            "obv": round(obv_signed, 4),
            "momentum": round(momentum_signed, 4),
            "heuristic": round(heuristic_signed, 4),
        },
    }


def _compute_trend_engine(ohlcv_df: pd.DataFrame) -> Dict[str, Any]:
    close = _numeric_series(ohlcv_df, "close")
    if close.empty:
        return {
            "trend_score": 0.5,
            "ema_structure": "NEUTRAL",
            "mtf_alignment": "MISSING",
            "mtf_direction": "NEUTRAL",
            "signed": 0.0,
            "component_signed": {},
            "timeframes": {},
        }

    price = float(close.iloc[-1])
    spans = [5, 9, 21, 50, 100, 200]
    ema_series = {span: close.ewm(span=span, adjust=False).mean() for span in spans}
    ema_current = {span: float(ema_series[span].iloc[-1]) for span in spans}
    ema_previous = {
        span: float(ema_series[span].iloc[-2]) if len(ema_series[span]) > 1 else float(ema_series[span].iloc[-1])
        for span in spans
    }

    ema_distance = {
        span: (price - ema_current[span]) / max(abs(ema_current[span]), 1e-9)
        for span in spans
    }
    ema_slope = {span: ema_current[span] - ema_previous[span] for span in spans}

    stack_pairs = [(5, 9), (9, 21), (21, 50), (50, 100), (100, 200)]
    bullish_pairs = sum(1 for left, right in stack_pairs if ema_current[left] > ema_current[right])
    bearish_pairs = sum(1 for left, right in stack_pairs if ema_current[left] < ema_current[right])

    if bullish_pairs == len(stack_pairs):
        ema_structure = "BULLISH STACK"
        stacking_signed = 1.0
    elif bearish_pairs == len(stack_pairs):
        ema_structure = "BEARISH STACK"
        stacking_signed = -1.0
    else:
        ema_structure = "MIXED STACK"
        stacking_signed = _clip_signed((bullish_pairs - bearish_pairs) / len(stack_pairs))

    slope_weights = {5: 0.25, 9: 0.20, 21: 0.20, 50: 0.15, 100: 0.10, 200: 0.10}
    slope_signed = _clip_signed(
        sum(
            slope_weights[span]
            * np.tanh((ema_slope[span] / max(price, 1e-9)) * 500.0)
            for span in spans
        )
    )
    distance_signed = _clip_signed(
        sum(
            slope_weights[span]
            * np.tanh(ema_distance[span] * 8.0)
            for span in spans
        )
    )

    timeframe_steps = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "1h": 60,
    }
    timeframe_direction: dict[str, str] = {}
    bull_count = 0
    bear_count = 0

    for timeframe, step in timeframe_steps.items():
        tf_close = _resample_close(close, step)
        if tf_close.empty:
            timeframe_direction[timeframe] = "MISSING"
            continue

        tf_ema21 = float(tf_close.ewm(span=21, adjust=False).mean().iloc[-1])
        tf_ema50 = float(tf_close.ewm(span=50, adjust=False).mean().iloc[-1])

        if tf_ema21 > tf_ema50:
            timeframe_direction[timeframe] = "BULLISH"
            bull_count += 1
        elif tf_ema21 < tf_ema50:
            timeframe_direction[timeframe] = "BEARISH"
            bear_count += 1
        else:
            timeframe_direction[timeframe] = "NEUTRAL"

    conflicting = bull_count > 0 and bear_count > 0
    if bull_count >= 3 and not conflicting:
        mtf_alignment = "STRONG"
        mtf_direction = "BULLISH"
        mtf_signed = 1.0
    elif bear_count >= 3 and not conflicting:
        mtf_alignment = "STRONG"
        mtf_direction = "BEARISH"
        mtf_signed = -1.0
    elif conflicting:
        mtf_alignment = "CONFLICTING"
        mtf_direction = "MIXED"
        mtf_signed = 0.0
    elif bull_count > bear_count:
        mtf_alignment = "WEAK"
        mtf_direction = "BULLISH"
        mtf_signed = 0.35
    elif bear_count > bull_count:
        mtf_alignment = "WEAK"
        mtf_direction = "BEARISH"
        mtf_signed = -0.35
    else:
        mtf_alignment = "NEUTRAL"
        mtf_direction = "NEUTRAL"
        mtf_signed = 0.0

    trend_signed = _clip_signed(
        (0.40 * stacking_signed)
        + (0.20 * slope_signed)
        + (0.20 * distance_signed)
        + (0.20 * mtf_signed)
    )
    trend_score = _score_from_signed(trend_signed)

    return {
        "trend_score": round(trend_score, 4),
        "ema_structure": ema_structure,
        "mtf_alignment": mtf_alignment,
        "mtf_direction": mtf_direction,
        "signed": round(trend_signed, 4),
        "component_signed": {
            "stacking": round(stacking_signed, 4),
            "slope": round(slope_signed, 4),
            "distance": round(distance_signed, 4),
            "mtf": round(mtf_signed, 4),
        },
        "timeframes": timeframe_direction,
    }


def _compute_volatility_engine(
    ohlcv_df: pd.DataFrame,
    feature_df: pd.DataFrame,
) -> Dict[str, Any]:
    close = _numeric_series(ohlcv_df, "close")
    high = _numeric_series(ohlcv_df, "high")
    low = _numeric_series(ohlcv_df, "low")

    if len(close) < 30 or len(high) < 30 or len(low) < 30:
        return {
            "volatility_score": 0.5,
            "volatility_state": "MISSING",
            "breakout_detected": False,
            "atr_ratio": 0.0,
            "bb_width": 0.0,
            "historical_volatility": 0.0,
            "range_pct": 0.0,
            "component_scores": {},
            "component_metrics": {},
        }

    price = float(close.iloc[-1])

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr7_series = tr.rolling(7, min_periods=3).mean()
    atr14_series = tr.rolling(14, min_periods=5).mean()
    atr21_series = tr.rolling(21, min_periods=8).mean()

    atr7 = float(atr7_series.iloc[-1]) if len(atr7_series) else 0.0
    atr14 = float(atr14_series.iloc[-1]) if len(atr14_series) else 0.0
    atr21 = float(atr21_series.iloc[-1]) if len(atr21_series) else 0.0
    atr_ratio = atr14 / max(price, 1e-9)

    atr14_avg = float(atr14_series.rolling(50, min_periods=5).mean().iloc[-1])
    atr_expansion_ratio = atr14 / max(atr14_avg, 1e-9)
    atr_expansion_score = _clip01((atr_expansion_ratio - 0.8) / 0.8)

    bb_mid = close.rolling(20, min_periods=5).mean()
    bb_std = close.rolling(20, min_periods=5).std()
    bb_upper = bb_mid + (2.0 * bb_std)
    bb_lower = bb_mid - (2.0 * bb_std)
    bb_width_series = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
    bb_width_series = bb_width_series.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    bb_width = float(bb_width_series.iloc[-1]) if len(bb_width_series) else 0.0
    bb_width_avg = float(bb_width_series.rolling(50, min_periods=5).mean().iloc[-1])
    bb_width_ratio = bb_width / max(bb_width_avg, 1e-9)
    bb_width_score = _clip01((bb_width_ratio - 0.8) / 0.8)

    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    hv_series = returns.rolling(20, min_periods=5).std().fillna(0.0)
    hv20 = float(hv_series.iloc[-1]) if len(hv_series) else 0.0
    hv_annualized = hv20 * np.sqrt(252)
    hv_avg = float(hv_series.rolling(50, min_periods=5).mean().iloc[-1])
    hv_ratio = hv20 / max(hv_avg, 1e-9)
    hv_score = _clip01((hv_ratio - 0.8) / 0.8)

    range_pct_series = (high - low) / close.replace(0, np.nan)
    range_pct_series = range_pct_series.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    range_pct = float(range_pct_series.iloc[-1]) if len(range_pct_series) else 0.0
    range_pct_avg = float(range_pct_series.rolling(20, min_periods=5).mean().iloc[-1])
    range_ratio = range_pct / max(range_pct_avg, 1e-9)
    range_score = _clip01((range_ratio - 0.8) / 1.0)

    breakout_detected = bool(
        atr_expansion_ratio > 1.5 or bb_width_ratio > 1.5 or hv_ratio > 1.5
    )
    breakout_score = 1.0 if breakout_detected else 0.0

    volatility_score = _clip01(
        (0.25 * atr_expansion_score)
        + (0.20 * bb_width_score)
        + (0.20 * hv_score)
        + (0.25 * breakout_score)
        + (0.10 * range_score)
    )

    if breakout_detected and volatility_score > 0.55:
        volatility_state = "BREAKOUT"
    elif volatility_score < 0.35 or (atr_ratio < 0.004 and bb_width < 0.03):
        volatility_state = "LOW_VOLATILITY"
    elif volatility_score > 0.80:
        volatility_state = "HIGH_VOLATILITY"
    else:
        volatility_state = "NORMAL_VOLATILITY"

    return {
        "volatility_score": round(volatility_score, 4),
        "volatility_state": volatility_state,
        "breakout_detected": breakout_detected,
        "atr_ratio": round(float(atr_ratio), 6),
        "bb_width": round(float(bb_width), 6),
        "historical_volatility": round(float(hv_annualized), 6),
        "range_pct": round(float(range_pct), 6),
        "component_scores": {
            "atr_expansion": round(float(atr_expansion_score), 4),
            "bb_width": round(float(bb_width_score), 4),
            "historical_volatility": round(float(hv_score), 4),
            "breakout": round(float(breakout_score), 4),
            "candle_range": round(float(range_score), 4),
        },
        "component_metrics": {
            "atr_7": round(float(atr7), 6),
            "atr_14": round(float(atr14), 6),
            "atr_21": round(float(atr21), 6),
            "atr_expansion_ratio": round(float(atr_expansion_ratio), 4),
            "bb_width_ratio": round(float(bb_width_ratio), 4),
            "hv_ratio": round(float(hv_ratio), 4),
            "range_ratio": round(float(range_ratio), 4),
        },
    }


def _compute_volume_engine(
    ohlcv_df: pd.DataFrame,
    feature_df: pd.DataFrame,
) -> Dict[str, Any]:
    close = _numeric_series(ohlcv_df, "close")
    volume = _numeric_series(ohlcv_df, "volume")

    if len(close) < 20 or len(volume) < 20 or feature_df.empty:
        return {
            "volume_score": 0.5,
            "volume_ratio": 1.0,
            "volume_ratio_flag": "NORMAL",
            "volume_spike": False,
            "volume_spike_strength": 0.0,
            "vwap_deviation": 0.0,
            "vwap_bias": "NEUTRAL",
            "obv_slope": 0.0,
            "obv_divergence": False,
            "volume_trend_slope": 0.0,
            "volume_trend_direction": "FLAT",
            "position_size_factor": 0.75,
            "inconsistent_volume": True,
            "components": {},
        }

    latest = feature_df.iloc[-1]
    volume_ratio = float(latest.get("volume_ratio", 1.0) or 1.0)
    volume_spike = bool(float(latest.get("volume_spike", 0.0) or 0.0) >= 0.5)
    volume_spike_strength = float(latest.get("volume_spike_strength", 0.0) or 0.0)
    vwap_deviation = float(latest.get("vwap_deviation", 0.0) or 0.0)
    obv_slope = float(latest.get("obv_slope_norm", 0.0) or 0.0)
    obv_divergence = bool(float(latest.get("obv_divergence", 0.0) or 0.0) >= 0.5)
    volume_trend_slope = float(latest.get("volume_trend_slope", 0.0) or 0.0)

    if volume_ratio > 1.5:
        volume_ratio_flag = "HIGH"
    elif volume_ratio < 0.7:
        volume_ratio_flag = "LOW"
    else:
        volume_ratio_flag = "NORMAL"

    if vwap_deviation > 0.0025:
        vwap_bias = "ABOVE"
    elif vwap_deviation < -0.0025:
        vwap_bias = "BELOW"
    else:
        vwap_bias = "NEUTRAL"

    if volume_trend_slope > 0.03:
        volume_trend_direction = "UP"
    elif volume_trend_slope < -0.03:
        volume_trend_direction = "DOWN"
    else:
        volume_trend_direction = "FLAT"

    ratio_score = _clip01((volume_ratio - 0.7) / 1.3)
    spike_score = _clip01(volume_spike_strength / 2.0)
    slope_score = _clip01((np.tanh(volume_trend_slope * 8.0) + 1.0) / 2.0)
    vwap_score = _clip01(abs(vwap_deviation) * 30.0)
    obv_score = _clip01((obv_slope + 1.0) / 2.0)

    if obv_divergence:
        obv_score *= 0.5

    volume_score = _clip01(
        (0.30 * ratio_score)
        + (0.25 * spike_score)
        + (0.20 * slope_score)
        + (0.15 * vwap_score)
        + (0.10 * obv_score)
    )

    rolling_cv = float(volume.tail(20).std() / (volume.tail(20).mean() + 1e-9))
    inconsistent_volume = bool(rolling_cv > 1.2 or volume_ratio < 0.9)

    if volume_ratio < 0.7:
        position_size_factor = 0.50
    elif inconsistent_volume or obv_divergence:
        position_size_factor = 0.75
    else:
        position_size_factor = 1.00

    return {
        "volume_score": round(volume_score, 4),
        "volume_ratio": round(volume_ratio, 4),
        "volume_ratio_flag": volume_ratio_flag,
        "volume_spike": volume_spike,
        "volume_spike_strength": round(volume_spike_strength, 4),
        "vwap_deviation": round(vwap_deviation, 6),
        "vwap_bias": vwap_bias,
        "obv_slope": round(obv_slope, 4),
        "obv_divergence": obv_divergence,
        "volume_trend_slope": round(volume_trend_slope, 4),
        "volume_trend_direction": volume_trend_direction,
        "position_size_factor": position_size_factor,
        "inconsistent_volume": inconsistent_volume,
        "components": {
            "ratio": round(ratio_score, 4),
            "spike": round(spike_score, 4),
            "slope": round(slope_score, 4),
            "vwap": round(vwap_score, 4),
            "obv": round(obv_score, 4),
        },
    }


def _compute_price_action_engine(
    ohlcv_df: pd.DataFrame,
    streak_window: int = 5,
) -> Dict[str, Any]:
    required_columns = {"open", "high", "low", "close"}
    if ohlcv_df is None or not required_columns.issubset(set(ohlcv_df.columns)):
        return {
            "price_action_score": 0.5,
            "body_strength_score": 0.5,
            "upper_wick_pct": 0.0,
            "lower_wick_pct": 0.0,
            "bullish_engulfing": 0,
            "bearish_engulfing": 0,
            "engulfing": "NONE",
            "doji": False,
            "candle_strength": "MODERATE",
            "candle_type": "NEUTRAL",
            "strong_green_candle": False,
            "strong_red_candle": False,
            "consecutive_green": 0,
            "consecutive_red": 0,
            "streak_strength_score": 0.0,
            "long_upper_wick": False,
            "long_lower_wick": False,
            "weak_body_candle": False,
            "conflicting_patterns": False,
            "components": {},
        }

    candles = (
        ohlcv_df[["open", "high", "low", "close"]]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .reset_index(drop=True)
    )

    if len(candles) < 2:
        return {
            "price_action_score": 0.5,
            "body_strength_score": 0.5,
            "upper_wick_pct": 0.0,
            "lower_wick_pct": 0.0,
            "bullish_engulfing": 0,
            "bearish_engulfing": 0,
            "engulfing": "NONE",
            "doji": False,
            "candle_strength": "MODERATE",
            "candle_type": "NEUTRAL",
            "strong_green_candle": False,
            "strong_red_candle": False,
            "consecutive_green": 0,
            "consecutive_red": 0,
            "streak_strength_score": 0.0,
            "long_upper_wick": False,
            "long_lower_wick": False,
            "weak_body_candle": False,
            "conflicting_patterns": False,
            "components": {},
        }

    epsilon = 1e-9
    current = candles.iloc[-1]
    previous = candles.iloc[-2]

    current_open = float(current["open"])
    current_high = float(current["high"])
    current_low = float(current["low"])
    current_close = float(current["close"])

    previous_open = float(previous["open"])
    previous_close = float(previous["close"])

    current_range = max(current_high - current_low, 0.0)
    current_body = abs(current_close - current_open)
    previous_body = abs(previous_close - previous_open)

    body_pct = current_body / (current_range + epsilon)
    upper_wick_pct = (
        max(current_high - max(current_open, current_close), 0.0)
        / (current_range + epsilon)
    )
    lower_wick_pct = (
        max(min(current_open, current_close) - current_low, 0.0)
        / (current_range + epsilon)
    )

    bullish_engulfing = int(
        current_body > previous_body
        and current_close > previous_open
        and current_open < previous_close
    )
    bearish_engulfing = int(
        current_body > previous_body
        and current_close < previous_open
        and current_open > previous_close
    )

    doji_flag = int(current_body < (current_range * 0.10))

    if body_pct > 0.70:
        candle_strength = "STRONG"
    elif body_pct < 0.30:
        candle_strength = "WEAK"
    else:
        candle_strength = "MODERATE"

    strong_green_candle = bool(current_close > current_open and body_pct > 0.70)
    strong_red_candle = bool(current_close < current_open and body_pct > 0.70)

    if doji_flag:
        candle_type = "DOJI"
    elif strong_green_candle:
        candle_type = "STRONG_BULLISH"
    elif strong_red_candle:
        candle_type = "STRONG_BEARISH"
    elif current_close > current_open:
        candle_type = "BULLISH"
    elif current_close < current_open:
        candle_type = "BEARISH"
    else:
        candle_type = "NEUTRAL"

    engulfing = "NONE"
    if bullish_engulfing:
        engulfing = "BULLISH"
    elif bearish_engulfing:
        engulfing = "BEARISH"

    recent = candles.tail(max(int(streak_window), 1)).copy()
    green_flags = (recent["close"] > recent["open"]).tolist()
    red_flags = (recent["close"] < recent["open"]).tolist()

    def _count_tail_true(flags: list[bool]) -> int:
        count = 0
        for value in reversed(flags):
            if value:
                count += 1
            else:
                break
        return count

    consecutive_green = _count_tail_true(green_flags)
    consecutive_red = _count_tail_true(red_flags)
    streak_strength_score = _clip01(
        max(consecutive_green, consecutive_red) / float(max(streak_window, 1))
    )

    body_strength_score = _clip01(body_pct)

    if current_close > current_open:
        wick_signed = lower_wick_pct - upper_wick_pct
    elif current_close < current_open:
        wick_signed = upper_wick_pct - lower_wick_pct
    else:
        wick_signed = -abs(upper_wick_pct - lower_wick_pct) * 0.50
    wick_analysis_score = _clip01(0.50 + wick_signed)

    engulfing_score = 1.0 if (bullish_engulfing or bearish_engulfing) else 0.30
    doji_signal_score = 0.0 if doji_flag else 1.0

    price_action_score = _clip01(
        (0.25 * body_strength_score)
        + (0.20 * wick_analysis_score)
        + (0.20 * engulfing_score)
        + (0.10 * doji_signal_score)
        + (0.25 * streak_strength_score)
    )

    conflicting_patterns = bool(
        (bullish_engulfing and bearish_engulfing)
        or (doji_flag and (bullish_engulfing or bearish_engulfing))
    )
    long_upper_wick = bool(upper_wick_pct > 0.55)
    long_lower_wick = bool(lower_wick_pct > 0.55)
    weak_body_candle = bool(body_strength_score < 0.30)

    return {
        "price_action_score": round(price_action_score, 4),
        "body_strength_score": round(body_strength_score, 4),
        "upper_wick_pct": round(float(_clip01(upper_wick_pct)), 4),
        "lower_wick_pct": round(float(_clip01(lower_wick_pct)), 4),
        "bullish_engulfing": int(bullish_engulfing),
        "bearish_engulfing": int(bearish_engulfing),
        "engulfing": engulfing,
        "doji": bool(doji_flag),
        "candle_strength": candle_strength,
        "candle_type": candle_type,
        "strong_green_candle": strong_green_candle,
        "strong_red_candle": strong_red_candle,
        "consecutive_green": int(consecutive_green),
        "consecutive_red": int(consecutive_red),
        "streak_strength_score": round(streak_strength_score, 4),
        "long_upper_wick": long_upper_wick,
        "long_lower_wick": long_lower_wick,
        "weak_body_candle": weak_body_candle,
        "conflicting_patterns": conflicting_patterns,
        "components": {
            "body_strength": round(body_strength_score, 4),
            "wick_analysis": round(wick_analysis_score, 4),
            "engulfing": round(engulfing_score, 4),
            "doji_signal": round(doji_signal_score, 4),
            "streak": round(streak_strength_score, 4),
        },
    }


def _compute_market_structure_engine(
    ohlcv_df: pd.DataFrame,
    swing_window: int = 3,
    cluster_pct: float = 0.0035,
) -> Dict[str, Any]:
    required_columns = {"open", "high", "low", "close", "volume"}

    def _fallback(reason: str) -> Dict[str, Any]:
        return {
            "structure": "NEUTRAL",
            "last_pattern": "NONE",
            "swing_highs": [],
            "swing_lows": [],
            "support_levels": [],
            "resistance_levels": [],
            "nearest_support": None,
            "nearest_resistance": None,
            "support_distance": 1.0,
            "resistance_distance": 1.0,
            "near_support": False,
            "near_resistance": False,
            "middle_zone": False,
            "breakout": False,
            "breakout_type": "NONE",
            "breakout_distance": 0.0,
            "breakout_level": None,
            "range_or_trend": "RANGE",
            "structure_score": 0.5,
            "higher_high": False,
            "higher_low": False,
            "lower_high": False,
            "lower_low": False,
            "components": {
                "trend_clarity": 0.5,
                "sr_proximity": 0.5,
                "breakout_strength": 0.0,
                "classification": 0.5,
            },
            "reason": reason,
        }

    if ohlcv_df is None or not required_columns.issubset(set(ohlcv_df.columns)):
        return _fallback("missing_columns")

    candles = (
        ohlcv_df[["open", "high", "low", "close", "volume"]]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .reset_index(drop=True)
    )

    min_rows = max((swing_window * 2) + 5, 30)
    if len(candles) < min_rows:
        return _fallback("insufficient_candles")

    close = candles["close"]
    high = candles["high"]
    low = candles["low"]
    open_price = candles["open"]
    volume = candles["volume"]
    current_price = float(close.iloc[-1])
    epsilon = 1e-9

    window = int(max(2, min(5, swing_window)))

    def _find_swings(series: pd.Series, mode: str) -> list[dict[str, float]]:
        values = pd.to_numeric(series, errors="coerce").fillna(0.0).tolist()
        swings: list[dict[str, float]] = []
        for idx in range(window, len(values) - window):
            current = float(values[idx])
            left = values[idx - window : idx]
            right = values[idx + 1 : idx + 1 + window]
            if mode == "high":
                if current > max(left) and current > max(right):
                    swings.append({"index": idx, "price": current})
            else:
                if current < min(left) and current < min(right):
                    swings.append({"index": idx, "price": current})
        return swings

    def _cluster_levels(levels: list[float]) -> list[dict[str, float]]:
        if not levels:
            return []
        sorted_levels = sorted(float(level) for level in levels)
        clusters: list[list[float]] = [[sorted_levels[0]]]
        for level in sorted_levels[1:]:
            anchor = float(np.mean(clusters[-1]))
            if abs(level - anchor) / max(abs(anchor), epsilon) <= cluster_pct:
                clusters[-1].append(level)
            else:
                clusters.append([level])

        out: list[dict[str, float]] = []
        for cluster in clusters:
            if len(cluster) >= 2:
                out.append({
                    "level": float(np.mean(cluster)),
                    "touches": float(len(cluster)),
                })
        return out

    swing_highs = _find_swings(high, mode="high")
    swing_lows = _find_swings(low, mode="low")

    higher_high = bool(
        len(swing_highs) >= 2
        and swing_highs[-1]["price"] > swing_highs[-2]["price"]
    )
    lower_high = bool(
        len(swing_highs) >= 2
        and swing_highs[-1]["price"] < swing_highs[-2]["price"]
    )
    higher_low = bool(
        len(swing_lows) >= 2
        and swing_lows[-1]["price"] > swing_lows[-2]["price"]
    )
    lower_low = bool(
        len(swing_lows) >= 2
        and swing_lows[-1]["price"] < swing_lows[-2]["price"]
    )

    high_change_ratio = 0.0
    low_change_ratio = 0.0
    if len(swing_highs) >= 2:
        prev_high = float(swing_highs[-2]["price"])
        curr_high = float(swing_highs[-1]["price"])
        high_change_ratio = abs(curr_high - prev_high) / max(abs(prev_high), epsilon)
    if len(swing_lows) >= 2:
        prev_low = float(swing_lows[-2]["price"])
        curr_low = float(swing_lows[-1]["price"])
        low_change_ratio = abs(curr_low - prev_low) / max(abs(prev_low), epsilon)

    meaningful_swing_shift = bool(high_change_ratio > 0.0025 and low_change_ratio > 0.0025)

    if higher_high and higher_low and meaningful_swing_shift:
        structure = "UPTREND"
    elif lower_high and lower_low and meaningful_swing_shift:
        structure = "DOWNTREND"
    else:
        structure = "NEUTRAL"

    last_pattern = "NONE"
    last_high_idx = int(swing_highs[-1]["index"]) if swing_highs else -1
    last_low_idx = int(swing_lows[-1]["index"]) if swing_lows else -1
    if last_high_idx >= 0 or last_low_idx >= 0:
        if last_high_idx >= last_low_idx:
            if higher_high:
                last_pattern = "HIGHER_HIGH"
            elif lower_high:
                last_pattern = "LOWER_HIGH"
            else:
                last_pattern = "SWING_HIGH"
        else:
            if higher_low:
                last_pattern = "HIGHER_LOW"
            elif lower_low:
                last_pattern = "LOWER_LOW"
            else:
                last_pattern = "SWING_LOW"

    support_clusters = _cluster_levels([item["price"] for item in swing_lows])
    resistance_clusters = _cluster_levels([item["price"] for item in swing_highs])

    if support_clusters:
        support_levels = [float(item["level"]) for item in support_clusters]
        support_touches = int(max(item["touches"] for item in support_clusters))
    else:
        support_levels = [float(item["price"]) for item in swing_lows[-3:]]
        support_touches = 1 if support_levels else 0

    if resistance_clusters:
        resistance_levels = [float(item["level"]) for item in resistance_clusters]
        resistance_touches = int(max(item["touches"] for item in resistance_clusters))
    else:
        resistance_levels = [float(item["price"]) for item in swing_highs[-3:]]
        resistance_touches = 1 if resistance_levels else 0

    def _nearest_below(levels: list[float], price: float) -> Optional[float]:
        below = [level for level in levels if level <= price]
        if below:
            return max(below)
        if levels:
            return min(levels, key=lambda level: abs(level - price))
        return None

    def _nearest_above(levels: list[float], price: float) -> Optional[float]:
        above = [level for level in levels if level >= price]
        if above:
            return min(above)
        if levels:
            return min(levels, key=lambda level: abs(level - price))
        return None

    nearest_support = _nearest_below(support_levels, current_price)
    nearest_resistance = _nearest_above(resistance_levels, current_price)

    if nearest_support is None:
        support_distance = 1.0
    else:
        support_distance = (current_price - nearest_support) / max(current_price, epsilon)

    if nearest_resistance is None:
        resistance_distance = 1.0
    else:
        resistance_distance = (nearest_resistance - current_price) / max(current_price, epsilon)

    near_support = bool(
        nearest_support is not None
        and support_distance >= -0.01
        and abs(support_distance) <= 0.015
    )
    near_resistance = bool(
        nearest_resistance is not None
        and resistance_distance >= -0.01
        and abs(resistance_distance) <= 0.015
    )

    current_open = float(open_price.iloc[-1])
    current_high = float(high.iloc[-1])
    current_low = float(low.iloc[-1])
    current_close = float(close.iloc[-1])
    current_volume = float(volume.iloc[-1])

    current_range = max(current_high - current_low, 0.0)
    body_pct = abs(current_close - current_open) / (current_range + epsilon)
    strong_candle = bool(body_pct >= 0.60)

    volume_ma20 = float(volume.rolling(20, min_periods=5).mean().iloc[-1])
    volume_ratio = current_volume / (volume_ma20 + epsilon)
    volume_spike_confirm = bool(volume_ratio > 1.40)

    avg_range20 = float((high - low).rolling(20, min_periods=5).mean().iloc[-1])
    range_ratio = current_range / (avg_range20 + epsilon)
    volatility_expansion = bool(range_ratio > 1.25)

    bullish_breakout = bool(
        nearest_resistance is not None
        and current_close > (nearest_resistance * 1.001)
        and strong_candle
        and volume_spike_confirm
        and volatility_expansion
    )
    bearish_breakout = bool(
        nearest_support is not None
        and current_close < (nearest_support * 0.999)
        and strong_candle
        and volume_spike_confirm
        and volatility_expansion
    )

    breakout = bool(bullish_breakout or bearish_breakout)
    if bullish_breakout:
        breakout_type = "BULLISH"
        breakout_level = nearest_resistance
    elif bearish_breakout:
        breakout_type = "BEARISH"
        breakout_level = nearest_support
    else:
        breakout_type = "NONE"
        breakout_level = None

    breakout_distance = (
        abs((current_price - breakout_level) / max(abs(breakout_level), epsilon))
        if breakout_level is not None
        else 0.0
    )

    trend_detected = structure in {"UPTREND", "DOWNTREND"}
    range_bound = bool(
        support_touches >= 2
        and resistance_touches >= 2
        and not breakout
        and not trend_detected
    )
    range_or_trend = "TREND" if (trend_detected or breakout) else "RANGE"

    middle_zone = False
    if (
        nearest_support is not None
        and nearest_resistance is not None
        and nearest_resistance > nearest_support
    ):
        band = nearest_resistance - nearest_support
        zone_position = (current_price - nearest_support) / max(band, epsilon)
        middle_zone = bool(0.40 <= zone_position <= 0.60)

    if trend_detected and len(swing_highs) >= 2 and len(swing_lows) >= 2:
        high_delta = abs(swing_highs[-1]["price"] - swing_highs[-2]["price"]) / max(current_price, epsilon)
        low_delta = abs(swing_lows[-1]["price"] - swing_lows[-2]["price"]) / max(current_price, epsilon)
        progression = _clip01((high_delta + low_delta) / 0.02)
        trend_clarity = _clip01(0.65 + (0.35 * progression))
    elif higher_high or higher_low or lower_high or lower_low:
        trend_clarity = 0.35
    else:
        trend_clarity = 0.20

    support_proximity = (
        _clip01(1.0 - (abs(support_distance) / 0.03)) if nearest_support is not None else 0.0
    )
    resistance_proximity = (
        _clip01(1.0 - (abs(resistance_distance) / 0.03))
        if nearest_resistance is not None
        else 0.0
    )

    if structure == "UPTREND":
        proximity_score = _clip01(
            (0.75 * support_proximity)
            + (0.25 * (1.0 if bullish_breakout else (resistance_proximity * 0.5)))
        )
    elif structure == "DOWNTREND":
        proximity_score = _clip01(
            (0.75 * resistance_proximity)
            + (0.25 * (1.0 if bearish_breakout else (support_proximity * 0.5)))
        )
    else:
        proximity_score = _clip01(max(support_proximity, resistance_proximity) * 0.70)

    body_strength = _clip01(body_pct / 0.80)
    volume_strength = _clip01((volume_ratio - 1.0) / 1.0)
    expansion_strength = _clip01((range_ratio - 1.0) / 1.0)

    if breakout:
        breakout_strength = _clip01(
            (0.40 * body_strength)
            + (0.30 * volume_strength)
            + (0.30 * expansion_strength)
        )
    else:
        breakout_strength = _clip01(
            (0.15 * body_strength)
            + (0.15 * volume_strength)
            + (0.10 * expansion_strength)
        )

    if range_or_trend == "TREND":
        classification_score = _clip01(0.65 + (0.35 * trend_clarity))
    else:
        touch_score = _clip01(min(support_touches, resistance_touches) / 3.0)
        classification_score = _clip01(0.45 + (0.55 * touch_score))

    structure_score = _clip01(
        (0.30 * trend_clarity)
        + (0.20 * proximity_score)
        + (0.30 * breakout_strength)
        + (0.20 * classification_score)
    )

    if middle_zone and range_bound and not breakout:
        structure_score = _clip01(structure_score * 0.85)

    return {
        "structure": structure,
        "last_pattern": last_pattern,
        "swing_highs": [round(float(item["price"]), 4) for item in swing_highs[-12:]],
        "swing_lows": [round(float(item["price"]), 4) for item in swing_lows[-12:]],
        "support_levels": [round(float(level), 4) for level in support_levels],
        "resistance_levels": [round(float(level), 4) for level in resistance_levels],
        "nearest_support": round(float(nearest_support), 4) if nearest_support is not None else None,
        "nearest_resistance": round(float(nearest_resistance), 4)
        if nearest_resistance is not None
        else None,
        "support_distance": round(float(support_distance), 4),
        "resistance_distance": round(float(resistance_distance), 4),
        "near_support": near_support,
        "near_resistance": near_resistance,
        "middle_zone": middle_zone,
        "breakout": breakout,
        "breakout_type": breakout_type,
        "breakout_distance": round(float(breakout_distance), 4),
        "breakout_level": round(float(breakout_level), 4) if breakout_level is not None else None,
        "range_or_trend": range_or_trend,
        "structure_score": round(float(structure_score), 4),
        "higher_high": higher_high,
        "higher_low": higher_low,
        "lower_high": lower_high,
        "lower_low": lower_low,
        "components": {
            "trend_clarity": round(float(trend_clarity), 4),
            "sr_proximity": round(float(proximity_score), 4),
            "breakout_strength": round(float(breakout_strength), 4),
            "classification": round(float(classification_score), 4),
            "strong_candle": bool(strong_candle),
            "body_pct": round(float(body_pct), 4),
            "volume_ratio": round(float(volume_ratio), 4),
            "range_ratio": round(float(range_ratio), 4),
            "volume_spike_confirm": volume_spike_confirm,
            "volatility_expansion": volatility_expansion,
            "support_touches": int(support_touches),
            "resistance_touches": int(resistance_touches),
        },
    }


def _compute_indicator_fusion_engine(
    feature_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    swing_window: int = 3,
    histogram_window: int = 5,
) -> Dict[str, Any]:
    min_candles = 50
    epsilon = 1e-9

    def _fallback(reason: str) -> Dict[str, Any]:
        return {
            "rsi_macd_signal": 0,
            "rsi_macd_strength": 0.0,
            "ema_crossover_signal": 0,
            "ema_crossover_strength": 0.0,
            "rsi_divergence": 0,
            "divergence_strength": 0.0,
            "macd_histogram_trend": 0,
            "macd_momentum_strength": 0.0,
            "fusion_score": 0.0,
            "components": {},
            "reason": reason,
        }

    if ohlcv_df is None or "close" not in ohlcv_df.columns:
        return _fallback("missing_columns")
    if feature_df is None or feature_df.empty:
        return _fallback("missing_features")

    close = _numeric_series(ohlcv_df, "close")
    if len(close) < min_candles:
        return _fallback("insufficient_candles")

    aligned_len = min(len(close), len(feature_df))
    if aligned_len < min_candles:
        return _fallback("insufficient_alignment")

    close = close.tail(aligned_len).reset_index(drop=True)
    indicators = feature_df.tail(aligned_len).copy().reset_index(drop=True)

    def _series_or_default(name: str, default: pd.Series) -> pd.Series:
        if name in indicators.columns:
            series = pd.to_numeric(indicators[name], errors="coerce")
            series = series.replace([np.inf, -np.inf], np.nan)
            return series
        return default

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_default = ema12 - ema26
    macd_signal_default = macd_default.ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(14, min_periods=14).mean()
    loss = (-delta.clip(upper=0.0)).rolling(14, min_periods=14).mean()
    rs = gain / (loss + epsilon)
    rsi_default = 100.0 - (100.0 / (1.0 + rs))

    rsi_series = _series_or_default("rsi_14", pd.Series(np.nan, index=indicators.index))
    if rsi_series.isna().all():
        rsi_series = _series_or_default("rsi", pd.Series(np.nan, index=indicators.index))
    if rsi_series.isna().all():
        rsi_series = rsi_default
    rsi_series = rsi_series.bfill().ffill().fillna(50.0).clip(lower=0.0, upper=100.0)

    macd_line = _series_or_default("macd", macd_default)
    macd_line = macd_line.bfill().ffill().fillna(0.0)

    macd_signal = _series_or_default("macd_signal", macd_signal_default)
    macd_signal = macd_signal.bfill().ffill().fillna(0.0)

    macd_hist = _series_or_default("macd_hist", macd_line - macd_signal)
    macd_hist = macd_hist.bfill().ffill().fillna(0.0)

    ema_fast = _series_or_default("ema_9", close.ewm(span=9, adjust=False).mean())
    ema_fast = ema_fast.bfill().ffill().fillna(close)

    ema_slow = _series_or_default("ema_21", close.ewm(span=21, adjust=False).mean())
    ema_slow = ema_slow.bfill().ffill().fillna(close)

    rsi_now = float(rsi_series.iloc[-1])
    macd_line_now = float(macd_line.iloc[-1])
    macd_signal_now = float(macd_signal.iloc[-1])
    macd_hist_now = float(macd_hist.iloc[-1])
    price_now = max(float(close.iloc[-1]), epsilon)

    if rsi_now > 55.0 and macd_line_now > macd_signal_now and macd_hist_now > 0.0:
        rsi_macd_signal = 1
    elif rsi_now < 45.0 and macd_line_now < macd_signal_now and macd_hist_now < 0.0:
        rsi_macd_signal = -1
    else:
        rsi_macd_signal = 0

    rsi_macd_strength_raw = abs(rsi_now - 50.0) * abs(macd_hist_now)
    macd_hist_scale = max(float(macd_hist.abs().tail(20).mean()), epsilon)
    rsi_macd_strength = _clip01(
        np.tanh(rsi_macd_strength_raw / ((20.0 * macd_hist_scale) + epsilon))
    )

    ema_fast_now = float(ema_fast.iloc[-1])
    ema_slow_now = float(ema_slow.iloc[-1])
    ema_crossover_signal = 1 if ema_fast_now >= ema_slow_now else -1
    ema_crossover_strength = _clip01(abs(ema_fast_now - ema_slow_now) / price_now)

    window = int(max(2, min(5, swing_window)))

    def _find_swings(series: pd.Series, mode: str) -> list[int]:
        values = series.tolist()
        swings: list[int] = []
        for idx in range(window, len(values) - window):
            current = float(values[idx])
            left = values[idx - window : idx]
            right = values[idx + 1 : idx + 1 + window]
            if mode == "high":
                if current > max(left) and current > max(right):
                    swings.append(idx)
            else:
                if current < min(left) and current < min(right):
                    swings.append(idx)
        return swings

    swing_highs = _find_swings(close, mode="high")
    swing_lows = _find_swings(close, mode="low")

    bullish_divergence: Optional[dict[str, float]] = None
    bearish_divergence: Optional[dict[str, float]] = None

    if len(swing_lows) >= 2:
        prev_idx = swing_lows[-2]
        curr_idx = swing_lows[-1]
        price_prev = float(close.iloc[prev_idx])
        price_curr = float(close.iloc[curr_idx])
        rsi_prev = float(rsi_series.iloc[prev_idx])
        rsi_curr = float(rsi_series.iloc[curr_idx])
        if price_curr < price_prev and rsi_curr > rsi_prev:
            bullish_divergence = {
                "index": float(curr_idx),
                "strength": float(max(rsi_curr - rsi_prev, 0.0)),
            }

    if len(swing_highs) >= 2:
        prev_idx = swing_highs[-2]
        curr_idx = swing_highs[-1]
        price_prev = float(close.iloc[prev_idx])
        price_curr = float(close.iloc[curr_idx])
        rsi_prev = float(rsi_series.iloc[prev_idx])
        rsi_curr = float(rsi_series.iloc[curr_idx])
        if price_curr > price_prev and rsi_curr < rsi_prev:
            bearish_divergence = {
                "index": float(curr_idx),
                "strength": float(max(rsi_prev - rsi_curr, 0.0)),
            }

    if bullish_divergence and bearish_divergence:
        if bullish_divergence["index"] >= bearish_divergence["index"]:
            rsi_divergence = 1
            divergence_strength = _clip01(float(bullish_divergence["strength"]) / 20.0)
        else:
            rsi_divergence = -1
            divergence_strength = _clip01(float(bearish_divergence["strength"]) / 20.0)
    elif bullish_divergence:
        rsi_divergence = 1
        divergence_strength = _clip01(float(bullish_divergence["strength"]) / 20.0)
    elif bearish_divergence:
        rsi_divergence = -1
        divergence_strength = _clip01(float(bearish_divergence["strength"]) / 20.0)
    else:
        rsi_divergence = 0
        divergence_strength = 0.0

    hist_window = int(max(3, min(5, histogram_window)))
    hist_tail = macd_hist.tail(hist_window).reset_index(drop=True)
    if len(hist_tail) >= 3:
        x = np.arange(len(hist_tail), dtype=float)
        try:
            hist_slope = float(np.polyfit(x, hist_tail.to_numpy(dtype=float), 1)[0])
        except Exception:
            hist_slope = 0.0
    else:
        hist_slope = 0.0

    hist_scale = max(float(np.mean(np.abs(hist_tail.to_numpy(dtype=float)))), epsilon)
    slope_normalized = _clip_signed(np.tanh((hist_slope / hist_scale) * 3.0))

    if slope_normalized > 0.05:
        macd_histogram_trend = 1
    elif slope_normalized < -0.05:
        macd_histogram_trend = -1
    else:
        macd_histogram_trend = 0

    macd_momentum_strength = slope_normalized

    fusion_score = _clip_signed(
        (0.30 * float(rsi_macd_signal))
        + (0.30 * float(ema_crossover_signal))
        + (0.20 * float(rsi_divergence))
        + (0.20 * float(macd_histogram_trend))
    )

    return {
        "rsi_macd_signal": int(rsi_macd_signal),
        "rsi_macd_strength": round(float(rsi_macd_strength), 4),
        "ema_crossover_signal": int(ema_crossover_signal),
        "ema_crossover_strength": round(float(ema_crossover_strength), 4),
        "rsi_divergence": int(rsi_divergence),
        "divergence_strength": round(float(divergence_strength), 4),
        "macd_histogram_trend": int(macd_histogram_trend),
        "macd_momentum_strength": round(float(macd_momentum_strength), 4),
        "fusion_score": round(float(fusion_score), 4),
        "components": {
            "rsi": round(float(rsi_now), 4),
            "macd_line": round(float(macd_line_now), 6),
            "macd_signal": round(float(macd_signal_now), 6),
            "macd_hist": round(float(macd_hist_now), 6),
            "hist_slope": round(float(hist_slope), 6),
            "swing_highs": int(len(swing_highs)),
            "swing_lows": int(len(swing_lows)),
            "candles_used": int(aligned_len),
        },
    }


def _evaluate_hold_filters(
    feature_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    momentum_info: Dict[str, Any],
    trend_info: Dict[str, Any],
    volatility_info: Dict[str, Any],
    volume_info: Dict[str, Any],
    price_action_info: Dict[str, Any],
    structure_info: Dict[str, Any],
    fusion_info: Dict[str, Any],
    liquidity_info: Dict[str, Any],
    time_info: Dict[str, Any],
) -> list[str]:
    reasons: list[str] = []

    close = _numeric_series(ohlcv_df, "close")
    high = _numeric_series(ohlcv_df, "high")
    low = _numeric_series(ohlcv_df, "low")
    volume = _numeric_series(ohlcv_df, "volume")

    if len(close) < 50 or len(high) < 50 or len(low) < 50 or len(volume) < 50:
        reasons.append("missing_data")
        return reasons

    vol_ma20 = float(volume.rolling(20, min_periods=1).mean().iloc[-1])
    vol_now = float(volume.iloc[-1])
    low_volume = bool(vol_ma20 > 0 and vol_now < (vol_ma20 * 0.60))
    if low_volume:
        reasons.append("low_volume")

    volume_ratio = float(volume_info.get("volume_ratio", 1.0) or 1.0)
    volume_spike = bool(volume_info.get("volume_spike", False))
    volume_trend_direction = str(volume_info.get("volume_trend_direction", "FLAT"))
    vwap_deviation = float(volume_info.get("vwap_deviation", 0.0) or 0.0)
    obv_divergence = bool(volume_info.get("obv_divergence", False))
    inconsistent_volume = bool(volume_info.get("inconsistent_volume", False))

    liquidity_score = float(liquidity_info.get("liquidity_score", 0.5) or 0.5)
    jump_flag = bool(liquidity_info.get("jump_flag", False))
    strong_move = bool(liquidity_info.get("strong_move", False))
    gap_flag = str(liquidity_info.get("gap_flag", "NO_GAP"))
    gap_rejection = bool(liquidity_info.get("gap_rejection", False))
    flow_state = str(liquidity_info.get("flow_state", "NEUTRAL"))

    if volume_ratio < 0.7:
        reasons.append("volume_too_low")

    if (
        volume_ratio < 1.2
        and (not volume_spike)
        and volume_trend_direction != "UP"
    ):
        reasons.append("volume_not_confirmed")

    if abs(vwap_deviation) > 0.004 and volume_ratio < 0.9:
        reasons.append("fake_move_low_volume")

    if obv_divergence:
        reasons.append("obv_divergence")

    if inconsistent_volume:
        reasons.append("volume_inconsistent")

    if gap_rejection and gap_flag != "NO_GAP":
        reasons.append("gap_rejection_trap")

    if jump_flag and (not strong_move) and volume_ratio < 1.0:
        reasons.append("jump_without_volume_support")

    if liquidity_score < 0.20 and flow_state not in {"STRONG_MOVE", "STRONG_BREAKOUT"}:
        reasons.append("liquidity_too_thin")

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    atr14 = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14, min_periods=2).mean()
    atr_now = float(atr14.iloc[-1]) if len(atr14) else 0.0
    atr_baseline = float(atr14.rolling(50, min_periods=5).mean().iloc[-1]) if len(atr14) else 0.0
    if atr_now > 0 and atr_baseline > 0 and atr_now > (atr_baseline * 1.8):
        reasons.append("atr_volatility_spike")

    if trend_info.get("mtf_alignment") == "CONFLICTING":
        reasons.append("conflicting_timeframes")
    if trend_info.get("mtf_alignment") == "MISSING":
        reasons.append("missing_data")

    volatility_state = str(volatility_info.get("volatility_state", "MISSING"))
    volatility_score = float(volatility_info.get("volatility_score", 0.5) or 0.5)
    breakout_detected = bool(volatility_info.get("breakout_detected", False))
    momentum_score = float(momentum_info.get("momentum_score", 0.5) or 0.5)
    trend_score = float(trend_info.get("trend_score", 0.5) or 0.5)
    volume_score = float(volume_info.get("volume_score", 0.5) or 0.5)
    fusion_score = float(fusion_info.get("fusion_score", 0.0) or 0.0)

    price_action_score = float(price_action_info.get("price_action_score", 0.5) or 0.5)
    doji_present = bool(price_action_info.get("doji", False))
    body_strength_score = float(price_action_info.get("body_strength_score", 0.5) or 0.5)
    upper_wick_pct = float(price_action_info.get("upper_wick_pct", 0.0) or 0.0)
    lower_wick_pct = float(price_action_info.get("lower_wick_pct", 0.0) or 0.0)
    long_upper_wick = bool(price_action_info.get("long_upper_wick", upper_wick_pct > 0.55))
    long_lower_wick = bool(price_action_info.get("long_lower_wick", lower_wick_pct > 0.55))
    conflicting_patterns = bool(price_action_info.get("conflicting_patterns", False))
    weak_body_candle = bool(
        price_action_info.get("weak_body_candle", body_strength_score < 0.30)
    )

    structure_score = float(structure_info.get("structure_score", 0.5) or 0.5)
    structure = str(structure_info.get("structure", "NEUTRAL"))
    range_or_trend = str(structure_info.get("range_or_trend", "RANGE"))
    middle_zone = bool(structure_info.get("middle_zone", False))
    structure_breakout = bool(structure_info.get("breakout", False))
    near_support = bool(structure_info.get("near_support", False))
    near_resistance = bool(structure_info.get("near_resistance", False))

    session = str(time_info.get("session", "MID"))
    time_bucket = str(time_info.get("time_bucket", "SIDEWAYS"))
    time_bias = str(time_info.get("time_bias", "NEUTRAL"))
    time_score = float(time_info.get("time_score", 0.5) or 0.5)
    expiry_flag = bool(time_info.get("expiry_flag", False))
    confirmation_threshold = float(time_info.get("confirmation_threshold", 0.65) or 0.65)

    bullish_setup = bool(momentum_score > 0.60 and trend_score > 0.55)
    bearish_setup = bool(momentum_score < 0.40 and trend_score < 0.45)

    if volatility_state == "LOW_VOLATILITY" or volatility_score < 0.30:
        reasons.append("volatility_too_low")

    if volatility_state == "HIGH_VOLATILITY" and trend_info.get("mtf_alignment") != "STRONG":
        reasons.append("volatility_too_high_no_trend")

    if breakout_detected and low_volume:
        reasons.append("fake_breakout_low_volume")

    if breakout_detected and trend_info.get("mtf_alignment") != "STRONG" and abs(momentum_score - 0.5) < 0.12:
        reasons.append("sudden_spike_without_confirmation")

    if (not breakout_detected) and volatility_score < 0.55:
        reasons.append("no_breakout")

    if doji_present:
        reasons.append("doji_indecision")

    if bullish_setup and long_upper_wick:
        reasons.append("price_action_upper_wick_rejection")

    if bearish_setup and long_lower_wick:
        reasons.append("price_action_lower_wick_rejection")

    if conflicting_patterns:
        reasons.append("price_action_conflict")

    if weak_body_candle:
        reasons.append("weak_body_candle")

    if price_action_score < 0.35:
        reasons.append("price_action_too_weak")

    if range_or_trend == "RANGE" and not structure_breakout:
        reasons.append("structure_range_bound")

    if middle_zone:
        reasons.append("structure_middle_zone")

    if structure_score < 0.45:
        reasons.append("structure_too_weak")

    if structure == "NEUTRAL" and not structure_breakout and (not near_support) and (not near_resistance):
        reasons.append("structure_unclear")

    directional_alignment = bool(
        (momentum_score > 0.55 and trend_score > 0.55 and fusion_score > 0.10)
        or (momentum_score < 0.45 and trend_score < 0.45 and fusion_score < -0.10)
    )
    conflicting_signals = bool(
        (momentum_score > 0.55 and trend_score > 0.55 and fusion_score < -0.05)
        or (momentum_score < 0.45 and trend_score < 0.45 and fusion_score > 0.05)
        or (
            abs(momentum_score - 0.5) < 0.08
            and abs(trend_score - 0.5) < 0.08
            and abs(fusion_score) > 0.35
        )
    )

    open_confirmation = _clip01(
        (0.30 * max(momentum_score, 1.0 - momentum_score))
        + (0.25 * max(trend_score, 1.0 - trend_score))
        + (0.25 * price_action_score)
        + (0.20 * volume_score)
    )

    if session == "MID" and (
        volatility_state == "LOW_VOLATILITY"
        or (time_bias == "LOW_VOLATILITY" and volatility_score < 0.45)
    ):
        reasons.append("mid_session_low_volatility")

    if session == "MID" and range_or_trend == "RANGE" and volatility_score < 0.50:
        reasons.append("mid_session_range_chop")

    if session == "OPEN" and open_confirmation < confirmation_threshold:
        reasons.append("open_session_weak_confirmation")

    if session == "OPEN" and (not directional_alignment) and time_score < 0.65:
        reasons.append("open_session_alignment_unclear")

    if expiry_flag and conflicting_signals:
        reasons.append("expiry_conflicting_signals")

    if time_bucket == "OFF_HOURS":
        reasons.append("outside_trading_hours")

    if feature_df.isna().sum().sum() > 0:
        reasons.append("missing_data")

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(reasons))


# ─── Ensemble Predictor ────────────────────────────────────────────────────


class ModelEnsemble:
    """Production ensemble with 12-engine weighted final fusion and hard filters."""

    @staticmethod
    def predict(
        symbol: str,
        ltp: float,
        features_seq: "np.ndarray",
        features_tab: "np.ndarray",
        ohlcv_df: Optional[pd.DataFrame] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:

        def _safe_hold(reason: str) -> Dict[str, Any]:
            safe_ltp = float(ltp or 0.0)
            return {
                "prediction": round(safe_ltp, 2),
                "signal": "HOLD",
                "confidence": 0.0,
                "confidence_pct": 0,
                "momentum_score": 0.5,
                "trend_score": 0.5,
                "volatility_score": 0.5,
                "volatility_state": "MISSING",
                "volume_score": 0.5,
                "price_action_score": 0.5,
                "candle_type": "NEUTRAL",
                "engulfing": "NONE",
                "doji": False,
                "candle_strength": "MODERATE",
                "body_strength_score": 0.5,
                "upper_wick_pct": 0.0,
                "lower_wick_pct": 0.0,
                "streak_strength_score": 0.0,
                "consecutive_green": 0,
                "consecutive_red": 0,
                "rsi_macd_signal": 0,
                "rsi_macd_strength": 0.0,
                "ema_crossover_signal": 0,
                "ema_crossover_strength": 0.0,
                "rsi_divergence": 0,
                "divergence_strength": 0.0,
                "macd_histogram_trend": 0,
                "macd_momentum_strength": 0.0,
                "fusion_score": 0.0,
                "structure_score": 0.5,
                "structure": "NEUTRAL",
                "last_pattern": "NONE",
                "support_levels": [],
                "resistance_levels": [],
                "nearest_support": None,
                "nearest_resistance": None,
                "support_distance": 1.0,
                "resistance_distance": 1.0,
                "breakout": False,
                "breakout_type": "NONE",
                "range_or_trend": "RANGE",
                "volume_ratio": 1.0,
                "volume_ratio_flag": "NORMAL",
                "volume_spike": False,
                "volume_spike_strength": 0.0,
                "vwap_deviation": 0.0,
                "vwap_bias": "NEUTRAL",
                "obv_slope": 0.0,
                "obv_divergence": False,
                "volume_trend_slope": 0.0,
                "volume_trend_direction": "FLAT",
                "position_size_factor": 0.75,
                "mtf_alignment": "MISSING",
                "mtf_score": 0.0,
                "ema_structure": "NEUTRAL",
                "session": "MID",
                "time_bucket": "SIDEWAYS",
                "day_of_week": int(datetime.utcnow().weekday()),
                "day_bias_score": 0.5,
                "expiry_flag": False,
                "expiry_type": "NONE",
                "time_score": 0.5,
                "time_bias": "NEUTRAL",
                "liquidity_score": 0.5,
                "regime_score": 0.5,
                "risk_score": 0.5,
                "ai_score": 0.5,
                "regime_state": "UNKNOWN",
                "price_impact": 0.0,
                "jump_flag": False,
                "gap_flag": "NO_GAP",
                "liquidity_sweep": False,
                "sweep_type": "NONE",
                "flow_state": "NEUTRAL",
                "stop": round(safe_ltp * 0.996, 2),
                "stop_loss": round(safe_ltp * 0.996, 2),
                "target": round(safe_ltp * 1.004, 2),
                "RR": 0.0,
                "position_size": 0,
                "models": {},
                "regime": "Unknown",
                "engines": {
                    "momentum": 0.5,
                    "trend": 0.5,
                    "volatility": 0.5,
                    "volume": 0.5,
                    "price_action": 0.5,
                    "structure": 0.5,
                    "regime": 0.5,
                    "time": 0.5,
                    "liquidity": 0.5,
                    "risk": 0.5,
                    "mtf": 0.5,
                    "ai": 0.5,
                },
                "factors": [reason],
                "explanation": f"Signal quality low: {reason}",
                "reason": reason,
            }

        if ohlcv_df is None or len(ohlcv_df) < 50:
            return _safe_hold("Insufficient data (< 50 candles)")

        if not _ensemble_model or _scaler is None or not _features_list:
            logger.warning("[PREDICT] Model artifacts unavailable. Returning safe fallback.")
            return _safe_hold("Model unavailable")

        feature_df = compute_features(ohlcv_df, include_legacy=True)
        if feature_df.empty:
            return _safe_hold("Feature computation returned empty")

        try:
            feature_df = build_feature_vector(ohlcv_df, base_features=feature_df)
        except Exception as exc:
            logger.warning("[PREDICT] Volume feature build failed; using base features: %s", exc)

        required_model_features = list(_features_list or FEATURE_COLUMNS)
        feature_df = apply_feature_compatibility(
            feature_df,
            ohlcv_df,
            required_model_features,
        )

        missing_model_features = [
            name for name in required_model_features if name not in feature_df.columns
        ]
        if missing_model_features:
            return _safe_hold(f"Missing model features: {missing_model_features[:5]}")

        latest = feature_df.iloc[-1].to_dict()
        debug_info: dict[str, Any] = {}
        if debug:
            debug_info["features"] = get_feature_summary(feature_df)
            debug_info["feature_count"] = len(FEATURE_COLUMNS)
            debug_info["rows_used"] = len(feature_df)

        try:
            input_data = [float(latest.get(name, 0.0)) for name in required_model_features]
            input_arr = pd.DataFrame([input_data], columns=required_model_features)
            input_scaled = _scaler.transform(input_arr)
            input_scaled = np.nan_to_num(input_scaled, nan=0.0, posinf=0.0, neginf=0.0)
            ml_prob_up, ml_prob_down = _extract_directional_probabilities(
                _ensemble_model,
                input_scaled,
            )
        except Exception as exc:
            logger.error("[ML Predict] Error running inference: %s", exc)
            if debug:
                debug_info["ml_error"] = str(exc)
            return _safe_hold("Prediction pipeline failed")

        ml_signal = "HOLD"
        if ml_prob_up >= 0.60:
            ml_signal = "BUY"
        elif ml_prob_down >= 0.60:
            ml_signal = "SELL"

        momentum_info = _compute_momentum_engine(feature_df, ohlcv_df, ml_prob_up=ml_prob_up)
        trend_info = _compute_trend_engine(ohlcv_df)
        volatility_info = _compute_volatility_engine(ohlcv_df, feature_df)
        volume_info = _compute_volume_engine(ohlcv_df, feature_df)
        price_action_info = _compute_price_action_engine(ohlcv_df)
        structure_info = _compute_market_structure_engine(ohlcv_df)
        fusion_info = _compute_indicator_fusion_engine(feature_df, ohlcv_df)
        liquidity_info = compute_liquidity_order_flow(ohlcv_df)
        time_info = compute_time_intelligence(ohlcv_df)

        mtf_info = compute_multi_timeframe_alignment(ohlcv_df)

        legacy_timeframes = trend_info.get("timeframes", {})
        if isinstance(legacy_timeframes, dict) and legacy_timeframes:
            merged_timeframes = dict(mtf_info.get("timeframes", {}))
            for tf_key, tf_value in legacy_timeframes.items():
                if tf_key not in {"1m", "5m", "15m", "1h"}:
                    continue
                legacy_tf = str(tf_value).upper()
                current_tf = str(merged_timeframes.get(tf_key, "MISSING")).upper()
                if current_tf in {"MISSING", "NEUTRAL", ""} and legacy_tf in {
                    "BULLISH",
                    "BEARISH",
                    "NEUTRAL",
                }:
                    merged_timeframes[tf_key] = legacy_tf
            mtf_info["timeframes"] = merged_timeframes

        computed_alignment = str(mtf_info.get("mtf_alignment", "MISSING") or "MISSING").upper()
        legacy_alignment = str(trend_info.get("mtf_alignment", "MISSING") or "MISSING").upper()
        if computed_alignment in {"MISSING", "NEUTRAL"} and legacy_alignment in {
            "STRONG",
            "WEAK",
            "CONFLICTING",
        }:
            mtf_info["mtf_alignment"] = legacy_alignment
        elif legacy_alignment == "CONFLICTING":
            # Preserve conservative hold behavior if either engine detects a timeframe conflict.
            mtf_info["mtf_alignment"] = "CONFLICTING"

        computed_direction = str(mtf_info.get("direction", "NEUTRAL") or "NEUTRAL").upper()
        legacy_direction = str(trend_info.get("mtf_direction", "NEUTRAL") or "NEUTRAL").upper()
        if computed_direction not in {"BULLISH", "BEARISH", "MIXED"} and legacy_direction in {
            "BULLISH",
            "BEARISH",
            "MIXED",
        }:
            mtf_info["direction"] = legacy_direction

        timeframe_trend = dict(mtf_info.get("timeframes", {}))
        bullish_tf_count = sum(
            1 for value in timeframe_trend.values() if str(value).upper() == "BULLISH"
        )
        bearish_tf_count = sum(
            1 for value in timeframe_trend.values() if str(value).upper() == "BEARISH"
        )

        mtf_direction = str(mtf_info.get("direction", "NEUTRAL") or "NEUTRAL").upper()
        if mtf_direction not in {"BULLISH", "BEARISH"}:
            if bullish_tf_count > bearish_tf_count:
                mtf_direction = "BULLISH"
            elif bearish_tf_count > bullish_tf_count:
                mtf_direction = "BEARISH"
            else:
                mtf_direction = "NEUTRAL"

        htf_confirmed = bool(
            mtf_direction in {"BULLISH", "BEARISH"}
            and timeframe_trend.get("1h", "MISSING") == mtf_direction
        )
        ltf_entry_confirmed = bool(
            mtf_direction in {"BULLISH", "BEARISH"}
            and timeframe_trend.get("1m", "MISSING") == mtf_direction
            and timeframe_trend.get("5m", "MISSING") == mtf_direction
        )

        mtf_alignment = str(mtf_info.get("mtf_alignment", "NEUTRAL") or "NEUTRAL").upper()
        mtf_conflict = bool(
            bool(mtf_info.get("conflict", False))
            or (bullish_tf_count > 0 and bearish_tf_count > 0)
            or mtf_alignment == "CONFLICTING"
        )
        if mtf_conflict and mtf_direction == "NEUTRAL":
            mtf_direction = "MIXED"

        mtf_score = float(np.clip(float(mtf_info.get("mtf_score", 0.5) or 0.5), 0.0, 1.0))
        if mtf_alignment == "STRONG":
            mtf_score = max(mtf_score, 0.85)
        elif mtf_alignment == "WEAK":
            mtf_score = max(mtf_score, 0.60)
        elif mtf_alignment == "CONFLICTING":
            mtf_score = min(mtf_score, 0.35)

        trend_info["mtf_alignment"] = mtf_alignment
        trend_info["mtf_direction"] = mtf_direction
        trend_info["mtf_score"] = round(mtf_score, 4)
        trend_info["htf_confirmed"] = htf_confirmed
        trend_info["ltf_entry_confirmed"] = ltf_entry_confirmed
        trend_info["mtf_conflict"] = mtf_conflict
        trend_info["timeframes"] = timeframe_trend

        hold_filters = _evaluate_hold_filters(
            feature_df,
            ohlcv_df,
            momentum_info,
            trend_info,
            volatility_info,
            volume_info,
            price_action_info,
            structure_info,
            fusion_info,
            liquidity_info,
            time_info,
        )

        momentum_score = float(momentum_info["momentum_score"])
        trend_score = float(trend_info["trend_score"])
        volatility_score = float(volatility_info["volatility_score"])
        volatility_state = str(volatility_info.get("volatility_state", "MISSING"))
        breakout_detected = bool(volatility_info.get("breakout_detected", False))
        volume_score = float(volume_info.get("volume_score", 0.5))
        volume_ratio = float(volume_info.get("volume_ratio", 1.0))
        volume_spike = bool(volume_info.get("volume_spike", False))
        volume_trend_direction = str(volume_info.get("volume_trend_direction", "FLAT"))
        vwap_bias = str(volume_info.get("vwap_bias", "NEUTRAL"))
        price_action_score = float(price_action_info.get("price_action_score", 0.5))
        bullish_engulfing = bool(price_action_info.get("bullish_engulfing", 0))
        bearish_engulfing = bool(price_action_info.get("bearish_engulfing", 0))
        strong_green_candle = bool(price_action_info.get("strong_green_candle", False))
        strong_red_candle = bool(price_action_info.get("strong_red_candle", False))
        candle_type = str(price_action_info.get("candle_type", "NEUTRAL"))
        candle_strength = str(price_action_info.get("candle_strength", "MODERATE"))
        engulfing = str(price_action_info.get("engulfing", "NONE"))
        doji = bool(price_action_info.get("doji", False))
        body_strength_score = float(price_action_info.get("body_strength_score", 0.5))
        upper_wick_pct = float(price_action_info.get("upper_wick_pct", 0.0))
        lower_wick_pct = float(price_action_info.get("lower_wick_pct", 0.0))
        streak_strength_score = float(price_action_info.get("streak_strength_score", 0.0))
        consecutive_green = int(price_action_info.get("consecutive_green", 0) or 0)
        consecutive_red = int(price_action_info.get("consecutive_red", 0) or 0)

        rsi_macd_signal = int(fusion_info.get("rsi_macd_signal", 0) or 0)
        rsi_macd_strength = float(fusion_info.get("rsi_macd_strength", 0.0) or 0.0)
        ema_crossover_signal = int(fusion_info.get("ema_crossover_signal", 0) or 0)
        ema_crossover_strength = float(
            fusion_info.get("ema_crossover_strength", 0.0) or 0.0
        )
        rsi_divergence = int(fusion_info.get("rsi_divergence", 0) or 0)
        divergence_strength = float(fusion_info.get("divergence_strength", 0.0) or 0.0)
        macd_histogram_trend = int(fusion_info.get("macd_histogram_trend", 0) or 0)
        macd_momentum_strength = float(
            fusion_info.get("macd_momentum_strength", 0.0) or 0.0
        )
        indicator_fusion_score = float(fusion_info.get("fusion_score", 0.0) or 0.0)

        liquidity_score = float(liquidity_info.get("liquidity_score", 0.5) or 0.5)
        price_impact = float(liquidity_info.get("price_impact", 0.0) or 0.0)
        jump_flag = bool(liquidity_info.get("jump_flag", False))
        gap_flag = str(liquidity_info.get("gap_flag", "NO_GAP"))
        gap_continuation = bool(liquidity_info.get("gap_continuation", False))
        gap_rejection = bool(liquidity_info.get("gap_rejection", False))
        liquidity_sweep = bool(liquidity_info.get("liquidity_sweep", False))
        sweep_type = str(liquidity_info.get("sweep_type", "NONE"))
        flow_state = str(liquidity_info.get("flow_state", "NEUTRAL"))

        session = str(time_info.get("session", "MID"))
        time_bucket = str(time_info.get("time_bucket", "SIDEWAYS"))
        raw_day_of_week = time_info.get("day_of_week")
        if raw_day_of_week is None:
            raw_day_of_week = datetime.utcnow().weekday()
        day_of_week = int(raw_day_of_week)
        day_bias_score = float(time_info.get("day_bias_score", 0.5) or 0.5)
        expiry_flag = bool(time_info.get("expiry_flag", False))
        expiry_type = str(time_info.get("expiry_type", "NONE"))
        time_score = float(time_info.get("time_score", 0.5) or 0.5)
        time_bias = str(time_info.get("time_bias", "NEUTRAL"))
        confirmation_threshold = float(time_info.get("confirmation_threshold", 0.65) or 0.65)
        time_position_size_factor = float(time_info.get("position_size_factor", 1.0) or 1.0)

        structure_score = float(structure_info.get("structure_score", 0.5) or 0.5)
        structure = str(structure_info.get("structure", "NEUTRAL"))
        last_pattern = str(structure_info.get("last_pattern", "NONE"))
        support_levels = list(structure_info.get("support_levels", []))
        resistance_levels = list(structure_info.get("resistance_levels", []))
        nearest_support = structure_info.get("nearest_support")
        nearest_resistance = structure_info.get("nearest_resistance")
        support_distance = float(structure_info.get("support_distance", 1.0) or 1.0)
        resistance_distance = float(structure_info.get("resistance_distance", 1.0) or 1.0)
        structure_breakout = bool(structure_info.get("breakout", False))
        breakout_type = str(structure_info.get("breakout_type", "NONE"))
        range_or_trend = str(structure_info.get("range_or_trend", "RANGE"))
        near_support = bool(structure_info.get("near_support", False))
        near_resistance = bool(structure_info.get("near_resistance", False))
        higher_high = bool(structure_info.get("higher_high", False))
        lower_low = bool(structure_info.get("lower_low", False))

        raw_close = _numeric_series(ohlcv_df, "close")
        raw_high = _numeric_series(ohlcv_df, "high")
        raw_low = _numeric_series(ohlcv_df, "low")
        current_price = float(raw_close.iloc[-1]) if not raw_close.empty else float(ltp or 0.0)
        effective_ltp = float(ltp or 0.0) if float(ltp or 0.0) > 0 else current_price

        if not raw_high.empty and not raw_low.empty:
            atr_proxy = float((raw_high.tail(14) - raw_low.tail(14)).mean())
        else:
            atr_proxy = 0.0
        if atr_proxy <= 0:
            atr_proxy = max(current_price, 1.0) * 0.015

        directional_bias = _estimate_directional_bias(trend_score, momentum_score)
        probe_target = _derive_target_price(
            directional_bias,
            effective_ltp,
            atr_proxy,
            structure_info,
        )
        risk_probe = compute_risk_position_context(
            ohlcv_df=ohlcv_df,
            signal=directional_bias,
            entry_price=effective_ltp,
            target_price=probe_target,
            capital=float(config.STARTING_CAPITAL),
            risk_per_trade=float(config.MAX_RISK_PER_TRADE_PCT),
            atr_multiplier=1.5,
            rr_min=1.5,
            volatility_state=volatility_state,
        )
        rr_probe = float(risk_probe.get("RR", 0.0) or 0.0)
        risk_probe_size_factor = float(risk_probe.get("position_size_factor", 0.0) or 0.0)
        risk_score = _compute_risk_score(rr_probe, risk_probe_size_factor, volatility_score)

        regime_info = _compute_regime_engine(
            range_or_trend=range_or_trend,
            volatility_state=volatility_state,
            mtf_alignment=mtf_alignment,
            trend_score=trend_score,
            structure_score=structure_score,
        )
        regime = str(regime_info.get("regime", "Ranging"))
        regime_state = str(regime_info.get("regime_state", "SIDEWAYS"))
        regime_score = float(regime_info.get("regime_score", 0.5) or 0.5)

        ai_info = _compute_ai_engine(
            feature_df=feature_df,
            ml_prob_up=ml_prob_up,
            momentum_score=momentum_score,
            trend_score=trend_score,
            indicator_fusion_score=indicator_fusion_score,
        )
        ai_score = float(ai_info.get("ai_score", 0.5) or 0.5)

        if vwap_bias == "ABOVE":
            directional_volume_score = _clip01(volume_score)
        elif vwap_bias == "BELOW":
            directional_volume_score = _clip01(1.0 - volume_score)
        else:
            directional_volume_score = _clip01(0.5 + ((volume_score - 0.5) * 0.35))

        if doji:
            directional_price_action_score = 0.5
        elif engulfing == "BULLISH" or candle_type in {"BULLISH", "STRONG_BULLISH"}:
            directional_price_action_score = _clip01(price_action_score)
        elif engulfing == "BEARISH" or candle_type in {"BEARISH", "STRONG_BEARISH"}:
            directional_price_action_score = _clip01(1.0 - price_action_score)
        else:
            directional_price_action_score = _clip01(0.5 + ((price_action_score - 0.5) * 0.35))

        if structure == "UPTREND" or str(breakout_type).upper() == "BULLISH":
            directional_structure_score = _clip01(structure_score)
        elif structure == "DOWNTREND" or str(breakout_type).upper() == "BEARISH":
            directional_structure_score = _clip01(1.0 - structure_score)
        else:
            directional_structure_score = _clip01(0.5 + ((structure_score - 0.5) * 0.30))

        if mtf_direction == "BULLISH":
            directional_mtf_score = _clip01(mtf_score)
        elif mtf_direction == "BEARISH":
            directional_mtf_score = _clip01(1.0 - mtf_score)
        else:
            directional_mtf_score = 0.5

        if vwap_bias == "ABOVE":
            directional_liquidity_score = _clip01(liquidity_score)
        elif vwap_bias == "BELOW":
            directional_liquidity_score = _clip01(1.0 - liquidity_score)
        else:
            directional_liquidity_score = _clip01(0.5 + ((liquidity_score - 0.5) * 0.25))

        directional_ai_score = _clip01((0.80 * ml_prob_up) + (0.20 * ai_score))

        volatility_component = _clip01(0.5 + ((volatility_score - 0.5) * 0.50))
        regime_component = _clip01(0.5 + ((regime_score - 0.5) * 0.30))
        time_component = _clip01(0.5 + ((time_score - 0.5) * 0.30))
        risk_component = _clip01(0.5 + ((risk_score - 0.5) * 0.30))

        engine_scores = {
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volatility_score": volatility_component,
            "volume_score": directional_volume_score,
            "price_action_score": directional_price_action_score,
            "structure_score": directional_structure_score,
            "mtf_score": directional_mtf_score,
            "regime_score": regime_component,
            "liquidity_score": directional_liquidity_score,
            "time_score": time_component,
            "risk_score": risk_component,
            "ai_score": directional_ai_score,
        }
        fusion_score = _compute_weighted_fusion_score(engine_scores)

        mtf_aligned = _is_mtf_aligned(mtf_alignment, mtf_conflict)
        buy_mtf_aligned = bool(mtf_aligned and mtf_direction == "BULLISH")
        sell_mtf_aligned = bool(mtf_aligned and mtf_direction == "BEARISH")

        breakout_confirmed = bool(
            (structure_breakout and str(breakout_type).upper() == "BULLISH")
            or (breakout_detected and trend_score > 0.62 and mtf_direction == "BULLISH")
        )
        support_bounce = bool(
            near_support
            and (not doji)
            and (
                engulfing == "BULLISH"
                or strong_green_candle
                or (
                    lower_wick_pct > upper_wick_pct
                    and candle_type in {"BULLISH", "STRONG_BULLISH"}
                )
            )
        )

        final_hard_filters: list[str] = []
        if regime_state == "SIDEWAYS":
            final_hard_filters.append("regime_sideways")
        if volatility_score < 0.40:
            final_hard_filters.append("volatility_too_low")
        if volume_score < 0.40:
            final_hard_filters.append("volume_too_low")
        if not mtf_aligned:
            final_hard_filters.append("mtf_misalignment")
            final_hard_filters.append("conflicting_timeframes")
        if directional_bias in {"BUY", "SELL"} and rr_probe < 1.5:
            final_hard_filters.append("rr_below_threshold")
        if doji or price_action_score < 0.45 or body_strength_score < 0.30:
            final_hard_filters.append("price_action_weak_or_doji")

        hold_filters = list(dict.fromkeys(list(hold_filters) + final_hard_filters))

        if hold_filters:
            final_signal = "HOLD"
            decision_reason = f"HOLD filter triggered: {', '.join(hold_filters)}"
        elif (
            fusion_score > 0.70
            and trend_score > 0.60
            and buy_mtf_aligned
            and (breakout_confirmed or support_bounce)
        ):
            final_signal = "BUY"
            if breakout_confirmed:
                decision_reason = "Strong multi-engine alignment with breakout confirmation"
            else:
                decision_reason = "Strong multi-engine alignment with support-bounce confirmation"
        elif fusion_score < 0.30 and trend_score < 0.40 and sell_mtf_aligned:
            final_signal = "SELL"
            decision_reason = "Bearish multi-engine alignment with MTF confirmation"
        else:
            final_signal = "HOLD"
            decision_reason = "Final fusion thresholds not met"

        if final_signal == "BUY":
            confidence_score = _clip01(fusion_score)
        elif final_signal == "SELL":
            confidence_score = _clip01(1.0 - fusion_score)
        else:
            confidence_score = _clip01(0.35 + (0.30 * (1.0 - abs(fusion_score - 0.5) * 2.0)))
            confidence_score = min(confidence_score, 0.59)

        if volatility_state in {"HIGH_VOLATILITY", "BREAKOUT"} or volatility_score > 0.80:
            confidence_score = _clip01(confidence_score * 0.94)
        if volume_score > 0.72 and volume_spike and (structure_breakout or breakout_detected):
            confidence_score = _clip01(confidence_score + 0.04)

        if final_signal != "HOLD" and expiry_flag:
            confidence_score = _clip01(confidence_score * 0.90)
            decision_reason = f"{decision_reason} | expiry risk-adjusted"

        confidence_pct = int(round(confidence_score * 100.0))

        confidence_boost = 0.6 + (confidence_score * 1.4)
        move_ratio = float(
            np.clip((atr_proxy / max(current_price, 1e-9)) * confidence_boost, 0.003, 0.04)
        )

        if final_signal == "BUY":
            predicted = round(effective_ltp * (1 + move_ratio * 0.8), 2)
            target = round(effective_ltp * (1 + move_ratio), 2)
            stop = round(effective_ltp * (1 - move_ratio * 0.75), 2)
        elif final_signal == "SELL":
            predicted = round(effective_ltp * (1 - move_ratio * 0.8), 2)
            target = round(effective_ltp * (1 - move_ratio), 2)
            stop = round(effective_ltp * (1 + move_ratio * 0.75), 2)
        else:
            predicted = round(effective_ltp, 2)
            target = round(effective_ltp * (1 + move_ratio * 0.4), 2)
            stop = round(effective_ltp * (1 - move_ratio * 0.4), 2)

        risk_info = compute_risk_position_context(
            ohlcv_df=ohlcv_df,
            signal=final_signal,
            entry_price=effective_ltp,
            target_price=target,
            capital=float(config.STARTING_CAPITAL),
            risk_per_trade=float(config.MAX_RISK_PER_TRADE_PCT),
            atr_multiplier=1.5,
            rr_min=1.5,
            volatility_state=volatility_state,
        )

        stop = float(risk_info.get("stop_loss", stop) or stop)
        target = float(risk_info.get("target", target) or target)
        rr_value = float(risk_info.get("RR", 0.0) or 0.0)
        position_size = int(risk_info.get("position_size", 0) or 0)
        risk_position_size_factor = float(risk_info.get("position_size_factor", 0.0) or 0.0)

        if final_signal in {"BUY", "SELL"} and (
            rr_value < 1.5 or bool(risk_info.get("risk_filter_fail", False))
        ):
            if "rr_below_threshold" not in hold_filters:
                hold_filters.append("rr_below_threshold")
            final_signal = "HOLD"
            decision_reason = f"HOLD filter triggered: rr_below_threshold (RR={rr_value:.2f})"

        risk_score = _compute_risk_score(rr_value, risk_position_size_factor, volatility_score)
        engine_scores["risk_score"] = _clip01(0.5 + ((risk_score - 0.5) * 0.30))

        alignment_strength = 0.0
        if final_signal == "BUY":
            alignment_strength = fusion_score
        elif final_signal == "SELL":
            alignment_strength = 1.0 - fusion_score

        volatility_size_factor = _clip01(1.0 - (0.45 * volatility_score))
        if volatility_state in {"HIGH_VOLATILITY", "BREAKOUT"}:
            volatility_size_factor *= 0.85

        alignment_boost = 1.0
        if final_signal in {"BUY", "SELL"} and mtf_aligned:
            alignment_boost += 0.25 * _clip01((alignment_strength - 0.70) / 0.30)

        base_size_factor = _clip01((0.55 * risk_score) + (0.45 * risk_position_size_factor))
        position_size_factor = _clip01(
            base_size_factor
            * volatility_size_factor
            * alignment_boost
            * float(volume_info.get("position_size_factor", 1.0) or 1.0)
            * time_position_size_factor
        )

        if final_signal in {"BUY", "SELL"}:
            scaled_position = int(np.floor(position_size * position_size_factor))
            position_size = max(1, scaled_position) if position_size > 0 else 0
        else:
            position_size = 0
            position_size_factor = min(position_size_factor, 0.75)

        if "volatility" in feature_df.columns:
            vol_pct = float(feature_df["volatility"].tail(20).mean() * 100)
        else:
            vol_pct = 0.0

        factors = [
            f"Momentum score={momentum_score:.2f} ({momentum_info.get('momentum_label', 'NEUTRAL')})",
            (
                f"Trend score={trend_score:.2f} ({mtf_alignment}, mtf_score={mtf_score:.2f}, "
                f"htf={htf_confirmed}, ltf={ltf_entry_confirmed}, "
                f"{trend_info.get('ema_structure', 'MIXED STACK')})"
            ),
            f"Volatility score={volatility_score:.2f} ({volatility_state})",
            f"Volume ratio={volume_ratio:.2f} spike={volume_spike} vwap_bias={vwap_bias}",
            (
                f"Liquidity score={liquidity_score:.2f} impact={price_impact:.6f} "
                f"jump={jump_flag} gap={gap_flag} sweep={liquidity_sweep} state={flow_state}"
            ),
            (
                f"Risk context stop={stop:.2f} target={target:.2f} RR={rr_value:.2f} "
                f"position_size={position_size}"
            ),
            (
                f"Time score={time_score:.2f} session={session} bucket={time_bucket} "
                f"day={day_of_week} expiry={expiry_flag} bias={time_bias}"
            ),
            (
                f"PriceAction score={price_action_score:.2f} candle={candle_type} "
                f"engulfing={engulfing} doji={doji}"
            ),
            (
                f"Structure score={structure_score:.2f} structure={structure} pattern={last_pattern} "
                f"zone={range_or_trend} breakout={structure_breakout}"
            ),
            (
                f"Fusion score={fusion_score:.2f} indicator_fusion={indicator_fusion_score:.2f} rsi_macd={rsi_macd_signal} "
                f"ema_cross={ema_crossover_signal} divergence={rsi_divergence} "
                f"macd_trend={macd_histogram_trend}"
            ),
            f"Regime score={regime_score:.2f} state={regime_state}",
            f"Risk score={risk_score:.2f} (RR={rr_value:.2f})",
            f"AI score={ai_score:.2f} ({ai_info.get('ai_label', 'NEUTRAL')})",
            f"ML probability up={ml_prob_up:.2f}",
        ]
        if hold_filters:
            factors.append(f"Filters={', '.join(hold_filters)}")

        result = {
            "prediction": predicted,
            "signal": final_signal,
            "confidence": round(confidence_score, 4),
            "confidence_pct": confidence_pct,
            "momentum_score": round(momentum_score, 4),
            "trend_score": round(trend_score, 4),
            "volatility_score": round(volatility_score, 4),
            "volatility_state": volatility_state,
            "volume_score": round(volume_score, 4),
            "price_action_score": round(price_action_score, 4),
            "candle_type": candle_type,
            "engulfing": engulfing,
            "doji": doji,
            "candle_strength": candle_strength,
            "body_strength_score": round(body_strength_score, 4),
            "upper_wick_pct": round(upper_wick_pct, 4),
            "lower_wick_pct": round(lower_wick_pct, 4),
            "streak_strength_score": round(streak_strength_score, 4),
            "consecutive_green": consecutive_green,
            "consecutive_red": consecutive_red,
            "rsi_macd_signal": int(rsi_macd_signal),
            "rsi_macd_strength": round(rsi_macd_strength, 4),
            "ema_crossover_signal": int(ema_crossover_signal),
            "ema_crossover_strength": round(ema_crossover_strength, 4),
            "rsi_divergence": int(rsi_divergence),
            "divergence_strength": round(divergence_strength, 4),
            "macd_histogram_trend": int(macd_histogram_trend),
            "macd_momentum_strength": round(macd_momentum_strength, 4),
            "fusion_score": round(fusion_score, 4),
            "structure_score": round(structure_score, 4),
            "structure": structure,
            "last_pattern": last_pattern,
            "support_levels": support_levels,
            "resistance_levels": resistance_levels,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "support_distance": round(support_distance, 4),
            "resistance_distance": round(resistance_distance, 4),
            "breakout": structure_breakout,
            "breakout_type": breakout_type,
            "range_or_trend": range_or_trend,
            "volume_ratio": round(volume_ratio, 4),
            "volume_ratio_flag": str(volume_info.get("volume_ratio_flag", "NORMAL")),
            "volume_spike": volume_spike,
            "volume_spike_strength": float(volume_info.get("volume_spike_strength", 0.0)),
            "vwap_deviation": float(volume_info.get("vwap_deviation", 0.0)),
            "vwap_bias": vwap_bias,
            "obv_slope": float(volume_info.get("obv_slope", 0.0)),
            "obv_divergence": bool(volume_info.get("obv_divergence", False)),
            "volume_trend_slope": float(volume_info.get("volume_trend_slope", 0.0)),
            "volume_trend_direction": str(volume_info.get("volume_trend_direction", "FLAT")),
            "position_size_factor": round(position_size_factor, 4),
            "mtf_alignment": mtf_alignment,
            "mtf_score": round(mtf_score, 4),
            "ema_structure": trend_info.get("ema_structure", "MIXED STACK"),
            "session": session,
            "time_bucket": time_bucket,
            "day_of_week": day_of_week,
            "day_bias_score": round(day_bias_score, 4),
            "expiry_flag": expiry_flag,
            "expiry_type": expiry_type,
            "time_score": round(time_score, 4),
            "time_bias": time_bias,
            "liquidity_score": round(liquidity_score, 4),
            "regime_score": round(regime_score, 4),
            "risk_score": round(risk_score, 4),
            "ai_score": round(ai_score, 4),
            "regime_state": regime_state,
            "price_impact": round(price_impact, 8),
            "jump_flag": jump_flag,
            "gap_flag": gap_flag,
            "liquidity_sweep": liquidity_sweep,
            "sweep_type": sweep_type,
            "flow_state": flow_state,
            "engines": {
                "momentum": round(momentum_score, 4),
                "trend": round(trend_score, 4),
                "volatility": round(volatility_score, 4),
                "volume": round(volume_score, 4),
                "price_action": round(price_action_score, 4),
                "structure": round(structure_score, 4),
                "regime": round(regime_score, 4),
                "time": round(time_score, 4),
                "liquidity": round(liquidity_score, 4),
                "risk": round(risk_score, 4),
                "mtf": round(mtf_score, 4),
                "ai": round(ai_score, 4),
            },
            "stop": stop,
            "stop_loss": stop,
            "target": target,
            "RR": round(rr_value, 4),
            "position_size": position_size,
            "models": {
                "ml_prob_up": round(ml_prob_up, 4),
                "ml_prob_down": round(ml_prob_down, 4),
                "ml_signal": ml_signal,
                "momentum_components": momentum_info.get("components", {}),
                "trend_components": trend_info.get("component_signed", {}),
                "volatility_components": volatility_info.get("component_scores", {}),
                "volatility_metrics": volatility_info.get("component_metrics", {}),
                "volume_components": volume_info.get("components", {}),
                "price_action_components": price_action_info.get("components", {}),
                "structure_components": structure_info.get("components", {}),
                "fusion_components": fusion_info.get("components", {}),
                "liquidity_components": liquidity_info.get("components", {}),
                "time_components": time_info.get("components", {}),
                "mtf_components": mtf_info.get("components", {}),
                "price_action_meta": {
                    "candle_type": candle_type,
                    "engulfing": engulfing,
                    "doji": doji,
                    "candle_strength": candle_strength,
                    "strong_green_candle": strong_green_candle,
                    "strong_red_candle": strong_red_candle,
                },
                "structure_meta": {
                    "structure": structure,
                    "last_pattern": last_pattern,
                    "range_or_trend": range_or_trend,
                    "breakout": structure_breakout,
                    "breakout_type": breakout_type,
                    "near_support": near_support,
                    "near_resistance": near_resistance,
                },
                "fusion_meta": {
                    "rsi_macd_signal": rsi_macd_signal,
                    "ema_crossover_signal": ema_crossover_signal,
                    "rsi_divergence": rsi_divergence,
                    "macd_histogram_trend": macd_histogram_trend,
                    "indicator_fusion_score": round(indicator_fusion_score, 4),
                    "fusion_score": round(fusion_score, 4),
                    "weights": FINAL_FUSION_WEIGHTS,
                },
                "regime_meta": {
                    "regime": regime,
                    "regime_state": regime_state,
                    "regime_score": round(regime_score, 4),
                },
                "ai_meta": {
                    "ai_score": round(ai_score, 4),
                    "ai_label": ai_info.get("ai_label", "NEUTRAL"),
                    "components": ai_info.get("components", {}),
                },
                "time_meta": {
                    "session": session,
                    "time_bucket": time_bucket,
                    "day_of_week": day_of_week,
                    "day_bias_score": round(day_bias_score, 4),
                    "expiry_flag": expiry_flag,
                    "expiry_type": expiry_type,
                    "time_score": round(time_score, 4),
                    "time_bias": time_bias,
                },
                "liquidity_meta": {
                    "liquidity_score": round(liquidity_score, 4),
                    "price_impact": round(price_impact, 8),
                    "jump_flag": jump_flag,
                    "gap_flag": gap_flag,
                    "gap_continuation": gap_continuation,
                    "gap_rejection": gap_rejection,
                    "liquidity_sweep": liquidity_sweep,
                    "sweep_type": sweep_type,
                    "flow_state": flow_state,
                },
                "risk_meta": {
                    "stop_loss": round(stop, 2),
                    "target": round(target, 2),
                    "RR": round(rr_value, 4),
                    "position_size": int(position_size),
                    "atr": float(risk_info.get("atr", 0.0) or 0.0),
                    "atr_ratio": float(risk_info.get("atr_ratio", 0.0) or 0.0),
                    "volatility_mode": str(risk_info.get("volatility_mode", "NORMAL")),
                    "risk_score": round(risk_score, 4),
                },
                "mtf_meta": {
                    "alignment": mtf_alignment,
                    "score": round(mtf_score, 4),
                    "direction": mtf_direction,
                    "conflict": mtf_conflict,
                    "htf_confirmed": htf_confirmed,
                    "ltf_entry_confirmed": ltf_entry_confirmed,
                    "timeframe_strength": mtf_info.get("timeframe_strength", {}),
                },
                "position_size_factor": round(position_size_factor, 4),
                "timeframe_trend": trend_info.get("timeframes", {}),
                "filters": hold_filters,
                "final_hard_filters": final_hard_filters,
                "engine_scores": {
                    key: round(float(value), 4) for key, value in engine_scores.items()
                },
                "regime_volatility": round(vol_pct, 2),
            },
            "regime": regime,
            "factors": factors[:10],
            "reason": decision_reason,
            "explanation": decision_reason,
        }

        if debug:
            debug_info["prob_up"] = round(ml_prob_up, 4)
            debug_info["prob_down"] = round(ml_prob_down, 4)
            debug_info["model_type"] = type(_ensemble_model).__name__
            debug_info["scaler_type"] = type(_scaler).__name__
            debug_info["signal_reasoning"] = (
                f"ml_signal={ml_signal} momentum={momentum_score:.3f} "
                f"trend={trend_score:.3f} volatility={volatility_score:.3f} "
                f"volume={volume_score:.3f} ratio={volume_ratio:.3f} "
                f"price_action={price_action_score:.3f} structure={structure_score:.3f} "
                f"fusion={fusion_score:.3f} indicator_fusion={indicator_fusion_score:.3f} "
                f"time={time_score:.3f} regime={regime_state}/{regime_score:.3f} "
                f"risk={risk_score:.3f} ai={ai_score:.3f} "
                f"mtf={mtf_alignment}/{mtf_score:.3f} htf={htf_confirmed} ltf={ltf_entry_confirmed} "
                f"mtf_conflict={mtf_conflict} "
                f"liquidity={liquidity_score:.3f} jump={jump_flag} gap={gap_flag} "
                f"session={session} bucket={time_bucket} expiry={expiry_flag} "
                f"state={volatility_state} filters={hold_filters}"
            )
            debug_info["momentum_engine"] = momentum_info
            debug_info["trend_engine"] = trend_info
            debug_info["volatility_engine"] = volatility_info
            debug_info["volume_engine"] = volume_info
            debug_info["price_action_engine"] = price_action_info
            debug_info["market_structure_engine"] = structure_info
            debug_info["indicator_fusion_engine"] = fusion_info
            debug_info["ai_engine"] = ai_info
            debug_info["regime_engine"] = regime_info
            debug_info["liquidity_order_flow_engine"] = liquidity_info
            debug_info["risk_position_context_engine"] = risk_info
            debug_info["time_intelligence_engine"] = time_info
            debug_info["hold_filters"] = hold_filters
            result["debug_info"] = debug_info

        allowed = {"BUY", "SELL", "HOLD"}
        if result["signal"] not in allowed:
            result["signal"] = "HOLD"
            result["confidence"] = 0.0
            result["confidence_pct"] = 0

        if result["signal"] != "HOLD" and result["confidence"] < 0.60:
            result["signal"] = "HOLD"
            result["reason"] = "Confidence below execution threshold"
            result["explanation"] = result["reason"]

        if result["signal"] == "BUY" and (result["target"] <= effective_ltp or result["stop"] >= effective_ltp):
            result["signal"] = "HOLD"
            result["reason"] = "Invalid BUY risk envelope"
            result["explanation"] = result["reason"]
        elif result["signal"] == "SELL" and (result["target"] >= effective_ltp or result["stop"] <= effective_ltp):
            result["signal"] = "HOLD"
            result["reason"] = "Invalid SELL risk envelope"
            result["explanation"] = result["reason"]

        if result["signal"] == "HOLD":
            result["stop"] = round(effective_ltp * 0.996, 2)
            result["target"] = round(effective_ltp * 1.004, 2)
            result["position_size"] = 0
            result["confidence"] = round(min(float(result["confidence"]), 0.59), 4)
            result["confidence_pct"] = int(round(float(result["confidence"]) * 100.0))

        result["stop_loss"] = result["stop"]
        result["RR"] = round(float(result.get("RR", 0.0) or 0.0), 4)
        result["position_size"] = int(max(0, result.get("position_size", 0) or 0))

        log_payload = {
            "event": "prediction",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "signal": result["signal"],
            "confidence": result["confidence"],
            "confidence_pct": result["confidence_pct"],
            "momentum_score": result["momentum_score"],
            "trend_score": result["trend_score"],
            "volatility_score": result["volatility_score"],
            "volatility_state": result["volatility_state"],
            "volume_score": result["volume_score"],
            "price_action_score": result["price_action_score"],
            "structure_score": result["structure_score"],
            "structure": result["structure"],
            "range_or_trend": result["range_or_trend"],
            "fusion_score": result["fusion_score"],
            "rsi_macd_signal": result["rsi_macd_signal"],
            "volume_ratio": result["volume_ratio"],
            "mtf_alignment": result["mtf_alignment"],
            "mtf_score": result["mtf_score"],
            "session": result["session"],
            "time_bucket": result["time_bucket"],
            "time_score": result["time_score"],
            "liquidity_score": result["liquidity_score"],
            "regime_score": result.get("regime_score", 0.5),
            "risk_score": result.get("risk_score", 0.5),
            "ai_score": result.get("ai_score", 0.5),
            "regime_state": result.get("regime_state", "UNKNOWN"),
            "RR": result["RR"],
            "position_size": result["position_size"],
            "jump_flag": result["jump_flag"],
            "gap_flag": result["gap_flag"],
            "expiry_flag": result["expiry_flag"],
            "feature_version": FEATURE_VERSION,
            "model_version": _model_version or "unknown",
        }
        logger.info(json.dumps(log_payload))

        logger.debug(
            "[PREDICT] Signal computed: %s %s conf=%s momentum=%s trend=%s volatility=%s volume=%s price_action=%s structure=%s fusion=%s liquidity=%s time=%s session=%s",
            symbol,
            result["signal"],
            result["confidence"],
            result["momentum_score"],
            result["trend_score"],
            result["volatility_score"],
            result["volume_score"],
            result["price_action_score"],
            result["structure_score"],
            result["fusion_score"],
            result["liquidity_score"],
            result["time_score"],
            result["session"],
        )

        return result
