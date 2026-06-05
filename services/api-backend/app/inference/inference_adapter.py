"""
inference_adapter.py — Backend Integration Adapter
====================================================
Drop this file into backend/app/inference/.

HOW TO USE:
    from app.inference.inference_adapter import StockAIPredictor

    predictor = StockAIPredictor.load(
        entry_model_dir="backend/models/entry_5m",
        trend_model_dir="backend/models/trend_1h",
    )
    result = predictor.predict(candles_5m, candles_1h)

This adapter:
  - Loads model + calibrator + scaler + feature_list from disk
  - Validates feature contract HARD (no zero-fill)
  - Returns calibrated probability, not a rule-based score
  - Applies 1h trend gate before issuing BUY/SELL
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

# Add project root to sys.path so feature_engineering is importable
ROOT = Path(__file__).resolve().parents[3]   # backend/app/inference → project root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.inference.feature_engineering import (
    BASE_5M_FEATURE_COLUMNS,
    CONTEXT_1H_FEATURE_COLUMNS,
    TREND_FEATURE_COLUMNS,
    DataConfig,
    build_1h_context,
    check_inference_compatibility,
    compute_base_features,
    merge_5m_with_1h_context,
    validate_feature_contract,
)


class StockAIPredictor:
    """
    Production inference wrapper.
    Loads artifacts, validates contracts, returns calibrated signals.
    """

    def __init__(
        self,
        entry_model,
        entry_calibrator,
        entry_scaler,
        entry_features: list[str],
        trend_model,
        trend_calibrator,
        trend_scaler,
        trend_features: list[str],
        entry_buy_threshold: float = 0.40,
        entry_sell_threshold: float = 0.40,
        trend_bull_threshold: float = 0.55,
    ):
        self.entry_model = entry_model
        self.entry_calibrator = entry_calibrator
        self.entry_scaler = entry_scaler
        self.entry_features = entry_features

        self.trend_model = trend_model
        self.trend_calibrator = trend_calibrator
        self.trend_scaler = trend_scaler
        self.trend_features = trend_features

        self.buy_threshold  = entry_buy_threshold
        self.sell_threshold = entry_sell_threshold
        self.bull_threshold = trend_bull_threshold

        # Validate that runtime can produce all model-required features
        check_inference_compatibility(self.trend_features, TREND_FEATURE_COLUMNS)
        check_inference_compatibility(self.entry_features, BASE_5M_FEATURE_COLUMNS)

    @classmethod
    def load(
        cls,
        entry_model_dir: str | Path,
        trend_model_dir: str | Path,
        entry_buy_threshold: float = 0.40,
        entry_sell_threshold: float = 0.40,
        trend_bull_threshold: float = 0.55,
    ) -> "StockAIPredictor":
        """Load all artifacts. Hard-fails if any file is missing."""
        def _load_dir(d: Path) -> tuple:
            d = Path(d)
            model      = joblib.load(d / "model.pkl")
            calibrator = joblib.load(d / "calibrator.pkl")
            scaler     = joblib.load(d / "scaler.pkl")
            features   = json.loads((d / "feature_list.json").read_text())
            return model, calibrator, scaler, features

        em, ec, es, ef = _load_dir(entry_model_dir)
        tm, tc, ts, tf = _load_dir(trend_model_dir)

        return cls(
            entry_model=em, entry_calibrator=ec,
            entry_scaler=es, entry_features=ef,
            trend_model=tm, trend_calibrator=tc,
            trend_scaler=ts, trend_features=tf,
            entry_buy_threshold=entry_buy_threshold,
            entry_sell_threshold=entry_sell_threshold,
            trend_bull_threshold=trend_bull_threshold,
        )

    def _build_feature_row(
        self,
        candles_5m: list[dict[str, Any]],
        candles_1h: list[dict[str, Any]],
        symbol: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Convert raw OHLCV candle lists into feature DataFrames.
        Returns (feat_5m_row, feat_1h_row) for the latest bar.
        """
        def to_df(candles: list[dict], tf: str) -> pd.DataFrame:
            df = pd.DataFrame(candles)
            # Normalise column names
            df.columns = [c.strip().lower() for c in df.columns]
            for alias in ("datetime", "date", "time"):
                if alias in df.columns:
                    df = df.rename(columns={alias: "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["symbol"] = symbol
            df["timeframe"] = tf
            df["source_file"] = "live"
            df["is_gap_filled"] = 0
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.dropna(subset=["open", "high", "low", "close", "volume"])

        df5 = to_df(candles_5m, "5m")
        df1 = to_df(candles_1h, "1h")

        feat5 = compute_base_features(df5)
        feat1 = compute_base_features(df1)

        ctx1  = build_1h_context(feat1)
        fused = merge_5m_with_1h_context(feat5, ctx1)

        return fused, feat1

    def predict(
        self,
        candles_5m: list[dict[str, Any]],
        candles_1h: list[dict[str, Any]],
        symbol: str = "UNKNOWN",
    ) -> dict[str, Any]:
        """
        Full prediction pipeline:
        1. Build features from live candles
        2. Validate feature contract (hard error — no zero-fill)
        3. Get 1h trend probability
        4. Get 5m entry probability
        5. Apply trend gate: only issue BUY when 1h=BULL, SELL when 1h=BEAR
        6. Return calibrated probabilities + signal

        Returns dict with keys:
            signal          : "BUY" | "SELL" | "HOLD"
            buy_probability : calibrated P(BUY) from 5m model
            sell_probability: calibrated P(SELL) from 5m model
            trend           : "BULL" | "BEAR" | "NEUTRAL"
            trend_probability: calibrated P(BULL) from 1h model
            confidence      : signal class probability (the one chosen)
            features_used   : number of features passed to model
            zero_filled     : always False (contract enforced)
        """
        if len(candles_5m) < 60:
            return {"signal": "HOLD", "reason": "insufficient_5m_data", "zero_filled": False}
        if len(candles_1h) < 30:
            return {"signal": "HOLD", "reason": "insufficient_1h_data", "zero_filled": False}

        fused, feat1 = self._build_feature_row(candles_5m, candles_1h, symbol)

        if fused.empty:
            return {"signal": "HOLD", "reason": "feature_build_failed", "zero_filled": False}

        # Hard validate — raises RuntimeError if any feature is missing or NaN
        validate_feature_contract(fused, self.entry_features, context=f"inference:{symbol}")
        validate_feature_contract(feat1, self.trend_features, context=f"inference_1h:{symbol}")

        # Latest bar only
        entry_row = fused.iloc[[-1]][self.entry_features].values
        trend_row = feat1.iloc[[-1]][self.trend_features].values

        # ── 1h Trend ──────────────────────────
        trend_row_s  = self.trend_scaler.transform(trend_row)
        trend_proba  = self.trend_calibrator.predict_proba(trend_row_s)[0, 1]  # P(BULL)
        if trend_proba >= self.bull_threshold:
            trend = "BULL"
        elif trend_proba <= (1 - self.bull_threshold):
            trend = "BEAR"
        else:
            trend = "NEUTRAL"

        # ── 5m Entry ──────────────────────────
        entry_row_s  = self.entry_scaler.transform(entry_row)
        entry_proba  = self.entry_calibrator.predict_proba(entry_row_s)[0]  # [SELL, HOLD, BUY]
        sell_p, hold_p, buy_p = float(entry_proba[0]), float(entry_proba[1]), float(entry_proba[2])

        # ── Trend Gate ────────────────────────
        # Only take directional trades aligned with 1h trend
        # This is the #1 filter that improves live precision
        raw_signal = "HOLD"
        confidence = hold_p

        if buy_p >= self.buy_threshold and trend == "BULL":
            raw_signal = "BUY"
            confidence = buy_p
        elif sell_p >= self.sell_threshold and trend == "BEAR":
            raw_signal = "SELL"
            confidence = sell_p
        elif buy_p >= self.buy_threshold and trend == "NEUTRAL":
            raw_signal = "HOLD"   # Trend uncertain — wait
        elif sell_p >= self.sell_threshold and trend == "NEUTRAL":
            raw_signal = "HOLD"

        return {
            "signal": raw_signal,
            "confidence": round(confidence, 4),
            "buy_probability": round(buy_p, 4),
            "sell_probability": round(sell_p, 4),
            "hold_probability": round(hold_p, 4),
            "trend": trend,
            "trend_probability": round(float(trend_proba), 4),
            "features_used": len(self.entry_features),
            "zero_filled": False,   # ALWAYS False — contract enforced
            "symbol": symbol,
        }
