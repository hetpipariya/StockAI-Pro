"""
Live 5m trading executor.

Implements the production 5m strategy with:
- confidence gating
- trend + volatility regime filtering
- fixed-percent SL/TP sizing (1% risk-per-trade by default)
- per-user execution via OrderRouter
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from stockai_shared.config import config
from stockai_shared.connectors.order_router import OrderRouter
from ..inference.feature_engineering import FEATURE_COLUMNS, compute_features, validate_feature_contract
from .candle_builder import candle_builder_5m
from .risk_manager import RiskManager
from stockai_shared.utils.trade_logger import log_trade

logger = logging.getLogger(__name__)


class LiveExecutor5m:
    def __init__(self, mode: str = "PAPER", starting_capital: float = 100_000.0):
        self.risk = RiskManager(starting_capital=starting_capital)
        self.router = OrderRouter(mode=mode)

        self.confidence_threshold = float(config.LIVE_5M_CONFIDENCE_THRESHOLD)
        self.trend_threshold = float(config.LIVE_5M_TREND_THRESHOLD)
        self.volatility_threshold = float(config.LIVE_5M_VOLATILITY_THRESHOLD)
        self.stop_loss_pct = float(config.LIVE_5M_STOP_LOSS_PCT)
        self.take_profit_pct = float(config.LIVE_5M_TAKE_PROFIT_PCT)
        self.max_holding_bars = int(config.LIVE_5M_MAX_HOLDING_BARS)
        self.history_limit = int(config.LIVE_5M_HISTORY_LIMIT)

        self._model = None
        self._scaler = None
        self._features_list: list[str] = []
        self._model_source = "uninitialized"

        # Tracks bars-held per open position to support max-holding exits.
        self._bars_held: dict[str, int] = {}

        self._load_model()

    @staticmethod
    def _position_key(symbol: str, user_id: Optional[int]) -> str:
        uid = int(user_id) if user_id is not None else -1
        return f"{uid}:{symbol.upper()}"

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            out = float(value)
            if np.isfinite(out):
                return out
        except Exception:
            pass
        return default

    def _load_model(self) -> None:
        """Load only the strict v3 C++ artifact."""
        model_path = Path(str(config.LIVE_5M_MODEL_PATH)).expanduser()

        if model_path.exists():
            try:
                payload = joblib.load(model_path)

                model = None
                scaler = None
                features: list[str] = []

                if isinstance(payload, dict):
                    model = payload.get("model")
                    scaler = payload.get("scaler")
                    features = list(
                        payload.get("feature_columns")
                        or payload.get("features")
                        or []
                    )
                elif hasattr(payload, "predict"):
                    model = payload

                if model is not None:
                    if not features and hasattr(model, "feature_names_in_"):
                        features = list(getattr(model, "feature_names_in_", []) or [])

                    self._features_list = [str(f) for f in features]
                    if self._features_list != FEATURE_COLUMNS:
                        logger.error(
                            "[EXECUTOR-5M] Rejecting non-canonical model from %s (features=%d)",
                            model_path,
                            len(self._features_list),
                        )
                        self._features_list = []
                        self._model_source = "none"
                        return
                    self._model = model
                    self._scaler = scaler
                    self._model_source = str(model_path)
                    logger.info(
                        "[EXECUTOR-5M] Loaded model from %s (features=%d)",
                        model_path,
                        len(self._features_list),
                    )
                    return

                logger.warning(
                    "[EXECUTOR-5M] Unsupported payload in %s; attempting fallback model",
                    model_path,
                )
            except Exception as exc:
                logger.warning(
                    "[EXECUTOR-5M] Failed loading %s: %s; attempting fallback model",
                    model_path,
                    exc,
                )
        else:
            logger.warning(
                "[EXECUTOR-5M] Model path missing: %s; attempting fallback model",
                model_path,
            )

        try:
            from ..inference.models import _ensemble_model, _features_list, _scaler, load_models

            if _ensemble_model is None:
                load_models()

            from ..inference.models import _ensemble_model as model
            from ..inference.models import _features_list as features
            from ..inference.models import _scaler as scaler

            self._features_list = [str(f) for f in (features or [])]
            if self._features_list != FEATURE_COLUMNS:
                logger.error("[EXECUTOR-5M] Shared model is not canonical C++ v3; executor disabled")
                self._model = None
                self._scaler = None
                self._features_list = []
                self._model_source = "none"
                return
            self._model = model
            self._scaler = scaler
            self._model_source = "app.inference.models"

            if self._model is None:
                logger.warning(
                    "[EXECUTOR-5M] No fallback model available; executor will stay signal-safe"
                )
            else:
                logger.info(
                    "[EXECUTOR-5M] Using fallback model from app.inference.models"
                )
        except Exception as exc:
            logger.error("[EXECUTOR-5M] Fallback model load failed: %s", exc)
            self._model = None
            self._scaler = None
            self._features_list = []
            self._model_source = "none"

    def _predict(self, feature_df: pd.DataFrame) -> tuple[int, float, float]:
        """Return (pred_class, prob_buy, confidence)."""
        if self._model is None or feature_df.empty:
            return -1, 0.0, 0.0

        latest = feature_df.iloc[-1]

        cols = self._features_list or list(feature_df.columns)
        row_vals = [self._safe_float(latest.get(col, 0.0), 0.0) for col in cols]
        input_arr = np.array([row_vals], dtype=np.float64)

        if self._scaler is not None:
            try:
                input_arr = self._scaler.transform(input_arr)
            except Exception as exc:
                logger.warning("[EXECUTOR-5M] Scaler transform failed: %s", exc)

        input_arr = np.nan_to_num(input_arr, nan=0.0, posinf=0.0, neginf=0.0)

        try:
            pred = int(self._model.predict(input_arr)[0])
        except Exception as exc:
            logger.error("[EXECUTOR-5M] Model predict failed: %s", exc)
            return -1, 0.0, 0.0

        prob_buy = 0.5
        if hasattr(self._model, "predict_proba"):
            try:
                proba = self._model.predict_proba(input_arr)[0]
                if len(proba) >= 2:
                    prob_buy = float(proba[1])
            except Exception as exc:
                logger.warning("[EXECUTOR-5M] predict_proba failed: %s", exc)

        prob_buy = min(max(prob_buy, 0.0), 1.0)
        confidence = max(prob_buy, 1.0 - prob_buy)
        return pred, prob_buy, confidence

    def _prepare_feature_frame(self, candles_df: pd.DataFrame) -> pd.DataFrame:
        if candles_df.empty:
            return pd.DataFrame()

        feature_df = compute_features(candles_df.tail(self.history_limit))
        if feature_df.empty:
            return feature_df

        required = self._features_list or list(feature_df.columns)
        validate_feature_contract(feature_df, required, context="LiveExecutor5m")

        for col in required:
            if col not in feature_df.columns:
                feature_df[col] = 0.0
            feature_df[col] = pd.to_numeric(feature_df[col], errors="coerce")

        feature_df.replace([np.inf, -np.inf], 0.0, inplace=True)
        feature_df.ffill(inplace=True)
        feature_df.fillna(0.0, inplace=True)
        return feature_df

    def _resolve_quality(self, latest_features: pd.Series, latest_close: float) -> tuple[float, float]:
        trend = self._safe_float(latest_features.get("linreg_slope"), default=np.nan)
        if not np.isfinite(trend):
            ema50 = self._safe_float(latest_features.get("ema50"), 0.0)
            if ema50 > 0 and latest_close > 0:
                trend = (latest_close - ema50) / max(abs(ema50), 1e-12)
            else:
                trend = 0.0

        atr14 = self._safe_float(latest_features.get("atr14"), default=np.nan)
        if np.isfinite(atr14) and latest_close > 0:
            volatility = atr14 / max(abs(latest_close), 1e-12)
        else:
            volatility = self._safe_float(latest_features.get("bb_width"), 0.0)

        return float(trend), max(float(volatility), 0.0)

    def evaluate_signal(self, symbol: str, user_id: Optional[int] = None) -> Optional[dict]:
        if not config.TRADING_ENABLED:
            logger.info("[EXECUTOR-5M] Kill-switch active; skipping %s", symbol)
            return None

        can_trade, reason = self.risk.can_trade()
        if not can_trade:
            logger.info("[EXECUTOR-5M] Risk gate blocked %s: %s", symbol, reason)
            return None

        candles = candle_builder_5m.get_history(symbol, limit=self.history_limit)
        if len(candles) < 50:
            return None

        candles_df = pd.DataFrame(candles)
        if candles_df.empty:
            return None

        for col in ["open", "high", "low", "close", "volume"]:
            if col in candles_df.columns:
                candles_df[col] = pd.to_numeric(candles_df[col], errors="coerce")

        candles_df.ffill(inplace=True)
        candles_df.fillna(0.0, inplace=True)

        feature_df = self._prepare_feature_frame(candles_df)
        if feature_df.empty:
            return None

        latest_price = self._safe_float(candles_df.iloc[-1].get("close"), 0.0)
        if latest_price <= 0:
            return None

        pred, prob_buy, confidence = self._predict(feature_df)
        if pred not in (0, 1):
            return None

        if confidence < self.confidence_threshold:
            return None

        latest_features = feature_df.iloc[-1]
        trend_strength, volatility = self._resolve_quality(latest_features, latest_price)
        # Add trend-quality filters: ADX and Bollinger Band width
        adx = float(latest_features.get("adx14") or 0.0)
        bb_width = float(latest_features.get("bb_width") or 0.0)

        regime_is_trending = (
            abs(trend_strength) >= self.trend_threshold
            and volatility >= self.volatility_threshold
            and adx >= float(config.LIVE_5M_ADX_THRESHOLD)
            and bb_width >= float(config.LIVE_5M_BBWIDTH_THRESHOLD)
        )
        if not regime_is_trending:
            return None

        signal = "BUY" if pred == 1 else "SELL"

        if signal == "BUY" and trend_strength < self.trend_threshold:
            return None
        if signal == "SELL" and trend_strength > -self.trend_threshold:
            return None

        trade_risk = self.risk.calculate_trade_percent(
            symbol=symbol,
            direction=signal,
            entry_price=latest_price,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
        )
        if not trade_risk:
            return None

        confidence_pct = int(round(confidence * 100.0))
        reason_text = (
            f"5m_model={signal} conf={confidence_pct}% "
            f"trend={trend_strength:.5f} vol={volatility:.5f} regime=TRENDING"
        )

        signal_data = {
            "symbol": symbol,
            "signal": signal,
            "entry": trade_risk.entry_price,
            "stop_loss": trade_risk.stop_price,
            "target": trade_risk.target_price,
            "quantity": trade_risk.position_size,
            "risk_amount": trade_risk.risk_amount,
            "reward_amount": trade_risk.reward_amount,
            "confidence": confidence_pct,
            "confidence_raw": round(float(confidence), 6),
            "prob_buy": round(float(prob_buy), 6),
            "trend_strength": round(float(trend_strength), 6),
            "volatility": round(float(volatility), 6),
            "reason": reason_text,
            "model_source": self._model_source,
        }

        log_trade(
            "SIGNAL",
            order_id="PRE-ORDER-5M",
            symbol=symbol,
            direction=signal,
            quantity=trade_risk.position_size,
            price=trade_risk.entry_price,
            stop_loss=trade_risk.stop_price,
            target=trade_risk.target_price,
            confidence=confidence_pct,
            reason=reason_text,
            mode=self.router.mode,
            user_id=user_id,
        )

        return signal_data

    def execute_signal(self, signal_data: dict, user_id: Optional[int] = None) -> dict:
        if user_id is None:
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": self.router.mode,
                "error": "Missing user_id",
            }

        if not config.TRADING_ENABLED:
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": self.router.mode,
                "error": "Kill-switch active",
            }

        if self.router.mode == "LIVE" and not config.LIVE_CONFIRMED:
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": "LIVE",
                "error": "LIVE trading not confirmed. Set LIVE_CONFIRMED=true",
            }

        result = self.router.place_order(
            symbol=signal_data["symbol"],
            direction=signal_data["signal"],
            quantity=signal_data["quantity"],
            price=signal_data["entry"],
            stop_loss=signal_data["stop_loss"],
            target=signal_data["target"],
            user_id=user_id,
            reason=signal_data.get("reason", ""),
            confidence=int(signal_data.get("confidence", 0)),
        )

        if result.status == "PENDING_CONFIRMATION" and self.router.mode == "PAPER":
            confirmed = self.router.confirm_and_execute(result.order_id, user_id=user_id)
            if confirmed:
                self.risk.on_trade_opened()
                self._bars_held[self._position_key(signal_data["symbol"], user_id)] = 0
                return {
                    "order_id": confirmed.order_id,
                    "status": confirmed.status,
                    "mode": confirmed.mode,
                    "error": confirmed.error,
                }

        return {
            "order_id": result.order_id,
            "status": result.status,
            "mode": result.mode,
            "error": result.error,
        }

    def check_exits(self, symbol: str, completed_candle: dict, user_id: Optional[int] = None) -> Optional[dict]:
        pos = self.router.get_position(symbol, user_id=user_id)
        if not pos:
            self._bars_held.pop(self._position_key(symbol, user_id), None)
            return None

        candle_high = self._safe_float(completed_candle.get("high"), 0.0)
        candle_low = self._safe_float(completed_candle.get("low"), 0.0)
        candle_close = self._safe_float(completed_candle.get("close"), 0.0)
        if candle_close <= 0:
            return None

        key = self._position_key(symbol, user_id)
        bars_held = self._bars_held.get(key, 0) + 1
        self._bars_held[key] = bars_held

        exit_reason = None
        exit_price = None

        if pos.direction == "BUY":
            hit_tp = candle_high >= float(pos.target)
            hit_sl = candle_low <= float(pos.stop_loss)
            if hit_tp and hit_sl:
                exit_reason = "STOP_LOSS_HIT"
                exit_price = float(pos.stop_loss)
            elif hit_sl:
                exit_reason = "STOP_LOSS_HIT"
                exit_price = float(pos.stop_loss)
            elif hit_tp:
                exit_reason = "TARGET_HIT"
                exit_price = float(pos.target)
        elif pos.direction == "SELL":
            hit_tp = candle_low <= float(pos.target)
            hit_sl = candle_high >= float(pos.stop_loss)
            if hit_tp and hit_sl:
                exit_reason = "STOP_LOSS_HIT"
                exit_price = float(pos.stop_loss)
            elif hit_sl:
                exit_reason = "STOP_LOSS_HIT"
                exit_price = float(pos.stop_loss)
            elif hit_tp:
                exit_reason = "TARGET_HIT"
                exit_price = float(pos.target)

        if exit_reason is None and bars_held >= self.max_holding_bars:
            exit_reason = "MAX_HOLD_EXIT"
            exit_price = candle_close

        if exit_reason is None or exit_price is None:
            return None

        pnl = self.router.close_position(symbol, float(exit_price), user_id=user_id)
        if pnl is not None:
            self.risk.on_trade_closed(float(pnl))

        self._bars_held.pop(key, None)
        return {
            "symbol": symbol,
            "reason": exit_reason,
            "exit_price": float(exit_price),
            "pnl": round(float(pnl or 0.0), 2),
            "bars_held": bars_held,
        }

    def on_candle_complete(self, symbol: str, completed_candle: dict, user_id: Optional[int] = None):
        if self.router.has_position(symbol, user_id=user_id):
            exit_result = self.check_exits(symbol, completed_candle, user_id=user_id)
            if exit_result:
                logger.info(
                    "[EXECUTOR-5M] EXIT %s: %s @ Rs%.2f PnL=Rs%.2f",
                    symbol,
                    exit_result["reason"],
                    float(exit_result["exit_price"]),
                    float(exit_result["pnl"]),
                )
                return {"action": "EXIT", **exit_result}

        if not self.router.has_position(symbol, user_id=user_id):
            signal = self.evaluate_signal(symbol, user_id=user_id)
            if signal:
                exec_result = self.execute_signal(signal, user_id=user_id)
                logger.info(
                    "[EXECUTOR-5M] ENTRY %s %s @ Rs%.2f Qty=%s -> %s",
                    signal["signal"],
                    symbol,
                    float(signal["entry"]),
                    signal["quantity"],
                    exec_result["status"],
                )
                return {"action": "ENTRY", **signal, **exec_result}

        return None

    def get_status(self, user_id: Optional[int] = None) -> dict:
        return {
            "mode": self.router.mode,
            "risk": self.risk.get_status(),
            "open_positions": self.router.get_open_positions(user_id=user_id),
            "model_loaded": self._model is not None,
            "model_source": self._model_source,
            "strategy": {
                "timeframe": "5m",
                "confidence_threshold": self.confidence_threshold,
                "trend_threshold": self.trend_threshold,
                "volatility_threshold": self.volatility_threshold,
                "stop_loss_pct": self.stop_loss_pct,
                "take_profit_pct": self.take_profit_pct,
                "max_holding_bars": self.max_holding_bars,
            },
            "trading_enabled": config.TRADING_ENABLED,
            "live_confirmed": config.LIVE_CONFIRMED,
        }


_system_executor_5m: Optional[LiveExecutor5m] = None
_user_executors_5m: dict[int, LiveExecutor5m] = {}


def get_executor_5m(
    user_id: Optional[int] = None,
    mode: str = "PAPER",
    capital: float = 100_000.0,
) -> LiveExecutor5m:
    actual_mode = config.TRADING_MODE if hasattr(config, "TRADING_MODE") else mode

    if user_id is None:
        global _system_executor_5m
        if _system_executor_5m is None:
            _system_executor_5m = LiveExecutor5m(mode=actual_mode, starting_capital=capital)
        elif _system_executor_5m.router.mode != actual_mode:
            _system_executor_5m.router.mode = actual_mode
        return _system_executor_5m

    key = int(user_id)
    executor = _user_executors_5m.get(key)
    if executor is None:
        executor = LiveExecutor5m(mode=actual_mode, starting_capital=capital)
        _user_executors_5m[key] = executor
        logger.info("[EXECUTOR-5M] Created user executor for user_id=%d", key)
    elif executor.router.mode != actual_mode:
        executor.router.mode = actual_mode

    return executor
