"""
Inference runner — loads ensemble models and produces predictions
using real OHLCV data and technical indicators.
"""

import sys
from pathlib import Path

# Add the service root directory to sys.path to allow 'app.*' imports when run directly
service_root = Path(__file__).resolve().parents[2]
if str(service_root) not in sys.path:
    sys.path.insert(0, str(service_root))

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.inference.feature_engineering import compute_features
from app.inference.features import get_latest_sequence, get_latest_tabular
from app.inference.models import (ModelEnsemble, ensure_models_loaded,
                                  load_models)

logger = logging.getLogger(__name__)

# Initialize models once at import
try:
    load_models()
except Exception as exc:
    logger.warning(
        "[MODELS] Initial model load failed at import; continuing with HOLD fallback: %s",
        exc,
    )


@dataclass
class PredictionResult:
    symbol: str
    price: float
    signal: str  # BUY | SELL | HOLD
    confidence: float  # 0.0-1.0
    momentum_score: float = 0.5
    trend_score: float = 0.5
    volatility_score: float = 0.5
    volatility_state: str = "MISSING"
    volume_score: float = 0.5
    price_action_score: float = 0.5
    candle_type: str = "NEUTRAL"
    engulfing: str = "NONE"
    doji: bool = False
    candle_strength: str = "MODERATE"
    body_strength_score: float = 0.5
    upper_wick_pct: float = 0.0
    lower_wick_pct: float = 0.0
    streak_strength_score: float = 0.0
    consecutive_green: int = 0
    consecutive_red: int = 0
    rsi_macd_signal: int = 0
    rsi_macd_strength: float = 0.0
    ema_crossover_signal: int = 0
    ema_crossover_strength: float = 0.0
    rsi_divergence: int = 0
    divergence_strength: float = 0.0
    macd_histogram_trend: int = 0
    macd_momentum_strength: float = 0.0
    fusion_score: float = 0.0
    structure_score: float = 0.5
    structure: str = "NEUTRAL"
    last_pattern: str = "NONE"
    support_levels: Optional[List[float]] = None
    resistance_levels: Optional[List[float]] = None
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    support_distance: float = 1.0
    resistance_distance: float = 1.0
    breakout: bool = False
    breakout_type: str = "NONE"
    range_or_trend: str = "RANGE"
    volume_ratio: float = 1.0
    volume_ratio_flag: str = "NORMAL"
    volume_spike: bool = False
    volume_spike_strength: float = 0.0
    vwap_deviation: float = 0.0
    vwap_bias: str = "NEUTRAL"
    obv_slope: float = 0.0
    obv_divergence: bool = False
    volume_trend_slope: float = 0.0
    volume_trend_direction: str = "FLAT"
    position_size_factor: float = 0.75
    mtf_alignment: str = "NEUTRAL"
    mtf_score: float = 0.0
    ema_structure: str = "MIXED STACK"
    session: str = "MID"
    time_bucket: str = "SIDEWAYS"
    day_of_week: int = 0
    day_bias_score: float = 0.5
    expiry_flag: bool = False
    expiry_type: str = "NONE"
    time_score: float = 0.5
    time_bias: str = "NEUTRAL"
    liquidity_score: float = 0.5
    regime_score: float = 0.5
    risk_score: float = 0.5
    ai_score: float = 0.5
    regime_state: str = "UNKNOWN"
    price_impact: float = 0.0
    jump_flag: bool = False
    gap_flag: str = "NO_GAP"
    liquidity_sweep: bool = False
    sweep_type: str = "NONE"
    flow_state: str = "NEUTRAL"
    engines: Optional[dict[str, float]] = None
    stop_loss: Optional[float] = None
    RR: float = 0.0
    position_size: int = 0
    reason: Optional[str] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    models: Optional[dict] = None
    regime: Optional[str] = None
    factors: Optional[list[str]] = None
    explanation: Optional[str] = None


import time
_last_predictions: dict[str, tuple[float, PredictionResult]] = {}
PREDICTION_THROTTLE_SECONDS = 2.0


def predict_symbol(
    symbol: str,
    timeframe: str = "15m",
    latest_ltp: Optional[float] = None,
    features_df: Optional[pd.DataFrame] = None,
    ohlcv: Optional[List[Dict[str, Any]]] = None,
) -> PredictionResult:
    """
    Produce prediction for symbol using real ensemble models.
    ohlcv: raw candle list [{time, open, high, low, close, volume}, ...]
    """
    now_time = time.time()
    cache_key = f"{symbol}:{timeframe}"
    if cache_key in _last_predictions:
        ts, cached_res = _last_predictions[cache_key]
        if now_time - ts < PREDICTION_THROTTLE_SECONDS:
            logger.debug("[RUNNER] Serving throttled prediction cache for %s:%s", symbol, timeframe)
            return cached_res

    base = latest_ltp or 1000.0

    # Build OHLCV DataFrame from raw candles
    ohlcv_df = None
    if ohlcv and len(ohlcv) > 0:
        ohlcv_df = pd.DataFrame(ohlcv)
        for col in ("open", "high", "low", "close", "volume"):
            if col in ohlcv_df.columns:
                ohlcv_df[col] = pd.to_numeric(ohlcv_df[col], errors="coerce")

        # If no LTP provided, take last close
        if base <= 0 or latest_ltp is None:
            last_close = ohlcv_df["close"].iloc[-1]
            if not pd.isna(last_close) and last_close > 0:
                base = float(last_close)

    if not ohlcv or len(ohlcv) < 50:
        return PredictionResult(
            symbol=symbol,
            price=round(base, 2),
            signal="HOLD",
            confidence=0.0,
            momentum_score=0.5,
            trend_score=0.5,
            volatility_score=0.5,
            volatility_state="MISSING",
            volume_score=0.5,
            price_action_score=0.5,
            candle_type="NEUTRAL",
            engulfing="NONE",
            doji=False,
            candle_strength="MODERATE",
            body_strength_score=0.5,
            upper_wick_pct=0.0,
            lower_wick_pct=0.0,
            streak_strength_score=0.0,
            consecutive_green=0,
            consecutive_red=0,
            rsi_macd_signal=0,
            rsi_macd_strength=0.0,
            ema_crossover_signal=0,
            ema_crossover_strength=0.0,
            rsi_divergence=0,
            divergence_strength=0.0,
            macd_histogram_trend=0,
            macd_momentum_strength=0.0,
            fusion_score=0.0,
            structure_score=0.5,
            structure="NEUTRAL",
            last_pattern="NONE",
            support_levels=[],
            resistance_levels=[],
            nearest_support=None,
            nearest_resistance=None,
            support_distance=1.0,
            resistance_distance=1.0,
            breakout=False,
            breakout_type="NONE",
            range_or_trend="RANGE",
            volume_ratio=1.0,
            volume_ratio_flag="NORMAL",
            volume_spike=False,
            volume_spike_strength=0.0,
            vwap_deviation=0.0,
            vwap_bias="NEUTRAL",
            obv_slope=0.0,
            obv_divergence=False,
            volume_trend_slope=0.0,
            volume_trend_direction="FLAT",
            position_size_factor=0.75,
            mtf_alignment="MISSING",
            mtf_score=0.0,
            ema_structure="NEUTRAL",
            session="MID",
            time_bucket="SIDEWAYS",
            day_of_week=0,
            day_bias_score=0.5,
            expiry_flag=False,
            expiry_type="NONE",
            time_score=0.5,
            time_bias="NEUTRAL",
            regime_score=0.5,
            risk_score=0.5,
            ai_score=0.5,
            regime_state="UNKNOWN",
            reason="Insufficient data (< 50 candles)",
            stop=round(base * 0.996, 2),
            target=round(base * 1.004, 2),
            models={},
            regime="Unknown",
            factors=["Insufficient data (< 50 candles)"],
            explanation="Signal quality low: insufficient candle history",
        )

    ensure_models_loaded(max_retries=3)

    # Extract ML features from OHLCV if not provided
    if features_df is None and ohlcv and len(ohlcv) >= 50:
        try:
            features_df = compute_features(pd.DataFrame(ohlcv))
        except Exception as exc:
            logger.warning("[RUNNER] C++ feature computation failed for %s: %s", symbol, exc)
            features_df = None

    # Prepare feature arrays for ML models
    if features_df is not None and len(features_df) > 0:
        seq = get_latest_sequence(features_df)
        tab = get_latest_tabular(features_df)
    else:
        seq = np.zeros((20, 10))
        tab = np.zeros((1, 10))

    res = ModelEnsemble.predict(symbol, base, seq, tab, feature_df=features_df, ohlcv_df=ohlcv_df)

    final_res = PredictionResult(
        symbol=symbol,
        price=res["prediction"],
        signal=res["signal"],
        confidence=res["confidence"],
        momentum_score=float(res.get("momentum_score", 0.5)),
        trend_score=float(res.get("trend_score", 0.5)),
        volatility_score=float(res.get("volatility_score", 0.5)),
        volatility_state=str(res.get("volatility_state", "MISSING")),
        volume_score=float(res.get("volume_score", 0.5)),
        price_action_score=float(res.get("price_action_score", 0.5)),
        candle_type=str(res.get("candle_type", "NEUTRAL")),
        engulfing=str(res.get("engulfing", "NONE")),
        doji=bool(res.get("doji", False)),
        candle_strength=str(res.get("candle_strength", "MODERATE")),
        body_strength_score=float(res.get("body_strength_score", 0.5)),
        upper_wick_pct=float(res.get("upper_wick_pct", 0.0)),
        lower_wick_pct=float(res.get("lower_wick_pct", 0.0)),
        streak_strength_score=float(res.get("streak_strength_score", 0.0)),
        consecutive_green=int(res.get("consecutive_green", 0) or 0),
        consecutive_red=int(res.get("consecutive_red", 0) or 0),
        rsi_macd_signal=int(res.get("rsi_macd_signal", 0) or 0),
        rsi_macd_strength=float(res.get("rsi_macd_strength", 0.0)),
        ema_crossover_signal=int(res.get("ema_crossover_signal", 0) or 0),
        ema_crossover_strength=float(res.get("ema_crossover_strength", 0.0)),
        rsi_divergence=int(res.get("rsi_divergence", 0) or 0),
        divergence_strength=float(res.get("divergence_strength", 0.0)),
        macd_histogram_trend=int(res.get("macd_histogram_trend", 0) or 0),
        macd_momentum_strength=float(res.get("macd_momentum_strength", 0.0)),
        fusion_score=float(res.get("fusion_score", 0.0)),
        structure_score=float(res.get("structure_score", 0.5)),
        structure=str(res.get("structure", "NEUTRAL")),
        last_pattern=str(res.get("last_pattern", "NONE")),
        support_levels=list(res.get("support_levels", []) or []),
        resistance_levels=list(res.get("resistance_levels", []) or []),
        nearest_support=res.get("nearest_support"),
        nearest_resistance=res.get("nearest_resistance"),
        support_distance=float(res.get("support_distance", 1.0)),
        resistance_distance=float(res.get("resistance_distance", 1.0)),
        breakout=bool(res.get("breakout", False)),
        breakout_type=str(res.get("breakout_type", "NONE")),
        range_or_trend=str(res.get("range_or_trend", "RANGE")),
        volume_ratio=float(res.get("volume_ratio", 1.0)),
        volume_ratio_flag=str(res.get("volume_ratio_flag", "NORMAL")),
        volume_spike=bool(res.get("volume_spike", False)),
        volume_spike_strength=float(res.get("volume_spike_strength", 0.0)),
        vwap_deviation=float(res.get("vwap_deviation", 0.0)),
        vwap_bias=str(res.get("vwap_bias", "NEUTRAL")),
        obv_slope=float(res.get("obv_slope", 0.0)),
        obv_divergence=bool(res.get("obv_divergence", False)),
        volume_trend_slope=float(res.get("volume_trend_slope", 0.0)),
        volume_trend_direction=str(res.get("volume_trend_direction", "FLAT")),
        position_size_factor=float(res.get("position_size_factor", 0.75)),
        mtf_alignment=str(res.get("mtf_alignment", "NEUTRAL")),
        mtf_score=float(res.get("mtf_score", 0.0)),
        ema_structure=str(res.get("ema_structure", "MIXED STACK")),
        session=str(res.get("session", "MID")),
        time_bucket=str(res.get("time_bucket", "SIDEWAYS")),
        day_of_week=int(res.get("day_of_week", 0) or 0),
        day_bias_score=float(res.get("day_bias_score", 0.5)),
        expiry_flag=bool(res.get("expiry_flag", False)),
        expiry_type=str(res.get("expiry_type", "NONE")),
        time_score=float(res.get("time_score", 0.5)),
        time_bias=str(res.get("time_bias", "NEUTRAL")),
        liquidity_score=float(res.get("liquidity_score", 0.5)),
        regime_score=float(res.get("regime_score", 0.5)),
        risk_score=float(res.get("risk_score", 0.5)),
        ai_score=float(res.get("ai_score", 0.5)),
        regime_state=str(res.get("regime_state", "UNKNOWN")),
        price_impact=float(res.get("price_impact", 0.0)),
        jump_flag=bool(res.get("jump_flag", False)),
        gap_flag=str(res.get("gap_flag", "NO_GAP")),
        liquidity_sweep=bool(res.get("liquidity_sweep", False)),
        sweep_type=str(res.get("sweep_type", "NONE")),
        flow_state=str(res.get("flow_state", "NEUTRAL")),
        engines=dict(res.get("engines", {}) or {}),
        stop_loss=res.get("stop_loss", res.get("stop")),
        RR=float(res.get("RR", 0.0) or 0.0),
        position_size=int(res.get("position_size", 0) or 0),
        reason=res.get("reason") or res.get("explanation"),
        stop=res["stop"],
        target=res["target"],
        models=res["models"],
        regime=res["regime"],
        factors=res["factors"],
        explanation=res["explanation"],
    )
    # Memory stabilization: Keep prediction cache under 2,000 items and discard items older than 10 minutes
    if len(_last_predictions) > 2000:
        stale_keys = [k for k, (ts, _) in _last_predictions.items() if now_time - ts > 600.0]
        for k in stale_keys:
            _last_predictions.pop(k, None)
        if len(_last_predictions) > 2000:
            sorted_items = sorted(_last_predictions.items(), key=lambda x: x[1][0])
            to_pop = len(_last_predictions) // 10
            for k, _ in sorted_items[:to_pop]:
                _last_predictions.pop(k, None)

    _last_predictions[cache_key] = (now_time, final_res)
    return final_res

