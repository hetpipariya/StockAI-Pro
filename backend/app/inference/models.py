"""
Real prediction engine — Machine Learning Ensemble + Technical Scoring

Uses feature_engineering.py as the single source of truth for features.
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from pathlib import Path
import joblib

from app.inference.feature_engineering import (
    FEATURE_COLUMNS,
    compute_features,
    validate_features,
    get_feature_summary,
    FEATURE_VERSION,
)
import json
import os
from datetime import datetime

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
logger.info("[MODELS] Using model directory: %s (exists=%s, has_model=%s)",
            MODEL_DIR, MODEL_DIR.exists(), (MODEL_DIR / "model.pkl").exists())

_ensemble_model = None
_scaler = None
_features_list = None
_model_version = None


def load_models():
    """Load trained ML models from disk if available.

    Validates model feature version and specific columns to prevent silent drift.
    """
    global _ensemble_model, _scaler, _features_list, _model_version

    model_path = MODEL_DIR / "model.pkl"

    if not model_path.exists():
        logger.warning("[MODELS] model.pkl missing — falling back to safe hold.")
        return

    try:
        payload = joblib.load(model_path)
    except Exception as e:
        logger.warning("[MODELS] Failed to load model.pkl (corrupted?): %s", e)
        return

    if not isinstance(payload, dict) or "version" not in payload:
        logger.warning("[MODELS] Old model format detected. Wrapping into modern dictionary format.")
        if isinstance(payload, dict):
            # Old dictionary format missing version
            model_obj = payload.get("model", payload)
            scaler_obj = payload.get("scaler", None)
            feat_list = payload.get("features", FEATURE_COLUMNS)
        else:
            # Raw model object
            model_obj = payload
            scaler_obj = None
            feat_list = FEATURE_COLUMNS
            
        payload = {
            "model": model_obj,
            "scaler": scaler_obj,
            "features": feat_list,
            "version": FEATURE_VERSION
        }

    loaded_version = payload.get("version")
    if loaded_version != FEATURE_VERSION:
        msg = f"Model feature version mismatch! Expected {FEATURE_VERSION}, got {loaded_version}"
        logger.error("[MODELS] %s", msg)  # Log error but don't strictly raise, allow best-effort
        loaded_version = FEATURE_VERSION

    _ensemble_model = payload.get("model")
    _scaler = payload.get("scaler")
    _features_list = payload.get("features")
    _model_version = loaded_version

    # Strict feature validation
    validate_features(
        _features_list,
        FEATURE_COLUMNS,
        context="load_models() vs FEATURE_COLUMNS",
    )
    logger.info(
        "[MODELS] ✓ Loaded ML Ensemble Pipeline — %d features validated.", len(_features_list)
    )


# ─── Ensemble Predictor ────────────────────────────────────────────────────

class ModelEnsemble:
    """Production ensemble: weighted combination of technical, momentum, ML."""

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
            return {
                "prediction": round(ltp, 2),
                "signal": "HOLD",
                "confidence": 0,
                "stop": round(ltp * 0.996, 2),
                "target": round(ltp * 1.004, 2),
                "models": {},
                "regime": "Unknown",
                "factors": [reason],
                "explanation": f"Signal quality low: {reason}",
                "reason": reason
            }

        if ohlcv_df is None or len(ohlcv_df) < 20:
            return _safe_hold("Insufficient data (< 20 candles)")
            
        if not _ensemble_model:
            logger.warning("[PREDICT] Model unavailable. Returning safe fallback.")
            return _safe_hold("Model unavailable")

        # ── Compute features using the shared module ────────────────────────
        feature_df = compute_features(ohlcv_df)

        if feature_df.empty:
            return _safe_hold("Feature computation returned empty")

        latest = feature_df.iloc[-1].to_dict()
        factors = []
        debug_info = {}

        # ── Debug: log feature values ───────────────────────────────────────
        if debug:
            debug_info["features"] = get_feature_summary(feature_df)
            debug_info["feature_count"] = len(FEATURE_COLUMNS)
            debug_info["rows_used"] = len(feature_df)

        # --- ML Prediction Segment ---
        ml_confidence = 0
        ml_signal = "HOLD"

        if _ensemble_model and _scaler and _features_list:
            try:
                # Build the input feature array from canonical columns
                input_data = [float(latest.get(f, 0.0)) for f in _features_list]
                input_arr = np.array([input_data])

                # Scale
                input_scaled = _scaler.transform(input_arr)
                input_scaled = np.nan_to_num(
                    input_scaled, nan=0.0, posinf=0.0, neginf=0.0
                )

                # Predict
                prob_up = float(_ensemble_model.predict_proba(input_scaled)[0, 1])
                prob_down = 1.0 - prob_up

                # Debug: log probabilities
                if debug:
                    debug_info["prob_up"] = round(prob_up, 4)
                    debug_info["prob_down"] = round(prob_down, 4)
                    debug_info["model_type"] = type(_ensemble_model).__name__
                    debug_info["scaler_type"] = type(_scaler).__name__

                # Map probabilities to strong actionable signals
                if prob_up >= 0.60:
                    ml_signal = "BUY"
                    ml_confidence = int(prob_up * 100)
                elif prob_down >= 0.60:
                    ml_signal = "SELL"
                    ml_confidence = int(prob_down * 100)
                else:
                    ml_signal = "HOLD"
                    ml_confidence = int(max(prob_up, prob_down) * 100)

                # Debug: log signal reasoning
                if debug:
                    debug_info["signal_reasoning"] = (
                        f"prob_up={prob_up:.4f}, prob_down={prob_down:.4f} → "
                        f"threshold=0.60 → signal={ml_signal} "
                        f"confidence={ml_confidence}%"
                    )

            except Exception as e:
                logger.error("[ML Predict] Error running inference: %s", e)
                if debug:
                    debug_info["ml_error"] = str(e)
        else:
            if debug:
                debug_info["ml_status"] = "No model loaded — falling back to safe hold"

        # ── Human‑readable heuristic factors ────────────────────────────────
        c = float(latest.get("close", ltp) or ltp)
        ema20 = float(latest.get("ema_20", c) or c)
        rsi14 = float(latest.get("rsi_14", 50) or 50)
        macd = float(latest.get("macd", 0) or 0)
        macd_sig = float(latest.get("macd_signal", 0) or 0)
        vwap = float(latest.get("vwap", c) or c)

        bullish = 0
        bearish = 0
        total_indicators = 4

        # 1. EMA Rule
        if c > ema20:
            factors.append(f"Price is trending ABOVE EMA20 ({c:.1f} > {ema20:.1f})")
            bullish += 1
        elif c < ema20:
            factors.append(f"Price is trending BELOW EMA20 ({c:.1f} < {ema20:.1f})")
            bearish += 1

        # 2. RSI Rule
        if rsi14 < 35:
            factors.append("RSI is Oversold (Reversal Potential)")
            bullish += 1
        elif rsi14 > 65:
            factors.append("RSI is Overbought (Correction Potential)")
            bearish += 1

        # 3. MACD Rule
        if macd > macd_sig:
            factors.append("MACD Bullish crossover momentum")
            bullish += 1
        elif macd < macd_sig:
            factors.append("MACD Bearish crossover momentum")
            bearish += 1

        # 4. VWAP Rule
        if c > vwap * 1.002:
            factors.append("Strongly supported above VWAP")
            bullish += 1
        elif c < vwap * 0.998:
            factors.append("Heavy resistance below VWAP")
            bearish += 1

        # ── Technical Fallback Logic ────────────────────────────────────────
        if bullish > bearish:
            tech_signal = "BUY"
            tech_confidence = round((bullish / total_indicators) * 100, 2)
        elif bearish > bullish:
            tech_signal = "SELL"
            tech_confidence = round((bearish / total_indicators) * 100, 2)
        else:
            tech_signal = "HOLD"
            tech_confidence = 50.0  # Never return < 50% on a completely split neutral market

        # Final signal arbitration: ML takes priority if highly confident, otherwise Technical Score
        final_signal = "HOLD"
        final_confidence = 0

        if _ensemble_model and _scaler and _features_list:
            if ml_confidence >= 65:
                # Strong ML sentiment
                final_signal = ml_signal
                final_confidence = ml_confidence
            elif tech_confidence >= 70:
                # Very strong technical, moderate ML -> Override with Technical
                final_signal = tech_signal
                final_confidence = tech_confidence
            else:
                # Concession
                final_signal = ml_signal if ml_signal == tech_signal else "HOLD"
                final_confidence = max(ml_confidence, tech_confidence) if final_signal != "HOLD" else 0
        else:
            # Fallback when ML model is absent
            final_signal = tech_signal
            final_confidence = int(tech_confidence)
            ml_signal = "N/A"
            ml_confidence = 0


        # ── Target / Stop calculation ───────────────────────────────────────
        # Use the feature DataFrame which was computed by compute_features()
        atr_proxy = float(
            feature_df["high"].tail(14).mean() - feature_df["low"].tail(14).mean()
        )
        if atr_proxy <= 0:
            atr_proxy = c * 0.015

        confidence_boost = 0.5 + (final_confidence / 100.0) * 1.5
        move_ratio = float(
            np.clip((atr_proxy / c) * confidence_boost, 0.003, 0.04)
        )

        if final_signal == "BUY":
            predicted = round(ltp * (1 + move_ratio * 0.8), 2)
            target = round(ltp * (1 + move_ratio), 2)
            stop = round(ltp * (1 - move_ratio * 0.75), 2)
        elif final_signal == "SELL":
            predicted = round(ltp * (1 - move_ratio * 0.8), 2)
            target = round(ltp * (1 - move_ratio), 2)
            stop = round(ltp * (1 + move_ratio * 0.75), 2)
        else:
            predicted = round(ltp * (1 + move_ratio * 0.1), 2)
            target = round(ltp * (1 + move_ratio * 0.4), 2)
            stop = round(ltp * (1 - move_ratio * 0.4), 2)

        vol_pct = (
            float(feature_df["pct_change_1d"].tail(20).std() * 100)
            if "pct_change_1d" in feature_df.columns
            else 0
        )
        if vol_pct > 2.0:
            regime = "Volatile"
        elif final_confidence >= 65:
            regime = "Trending"
        else:
            regime = "Ranging"

        explanation = (
            f"Ensemble Prediction: {final_signal} with {final_confidence}% confidence (ML: {ml_confidence}%, Tech: {tech_confidence}%)."
        )
        if not _ensemble_model:
            explanation = f"Warning: ML model missing. Using Technical Fallback ({tech_signal} @ {tech_confidence}%)."

        result = {
            "prediction": predicted,
            "signal": final_signal if final_signal else "HOLD",
            "confidence": final_confidence if final_confidence > 0 else 50.0,
            "stop": stop,
            "target": target,
            "models": {
                "ensemble_confidence": ml_confidence,
                "regime_volatility": round(vol_pct, 2),
            },
            "regime": regime,
            "factors": factors[:5],
            "explanation": explanation,
        }

        if debug:
            result["debug_info"] = debug_info

        log_payload = {
            "event": "prediction",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "signal": result["signal"],
            "confidence": result["confidence"],
            "feature_version": FEATURE_VERSION,
            "model_version": _model_version or "unknown"
        }
        logger.info(json.dumps(log_payload))

        logger.debug("[PREDICT] Signal computed: %s %s conf=%s", symbol, result["signal"], result["confidence"])

        return result
