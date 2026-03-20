"""
Inference runner — loads ensemble models and produces predictions
using real OHLCV data and technical indicators.
"""
import logging
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from app.inference.features import extract_features, get_latest_sequence, get_latest_tabular
from app.inference.models import ModelEnsemble, load_models

logger = logging.getLogger(__name__)

# Initialize models once at import
load_models()


@dataclass
class PredictionResult:
    symbol: str
    price: float
    signal: str  # BUY | SELL | HOLD
    confidence: int  # 0-100
    stop: Optional[float] = None
    target: Optional[float] = None
    models: Optional[dict] = None
    regime: Optional[str] = None
    factors: Optional[list[str]] = None
    explanation: Optional[str] = None


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

    # Extract ML features from OHLCV if not provided
    if features_df is None and ohlcv and len(ohlcv) > 50:
        features_df = extract_features(ohlcv)

    # Prepare feature arrays for ML models
    if features_df is not None and len(features_df) > 0:
        seq = get_latest_sequence(features_df)
        tab = get_latest_tabular(features_df)
    else:
        seq = np.zeros((20, 10))
        tab = np.zeros((1, 10))

    res = ModelEnsemble.predict(symbol, base, seq, tab, ohlcv_df=ohlcv_df)

    return PredictionResult(
        symbol=symbol,
        price=res["prediction"],
        signal=res["signal"],
        confidence=res["confidence"],
        stop=res["stop"],
        target=res["target"],
        models=res["models"],
        regime=res["regime"],
        factors=res["factors"],
        explanation=res["explanation"],
    )
