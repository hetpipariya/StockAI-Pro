"""
Live Trading Executor — evaluates 15m candles against the XGBoost model.
Mirrors the exact backtest parameters: EMA9/21/50, RSI, Volume Spike, ATR.
Operates in PAPER or LIVE mode with multi-layer safety checks.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from app import config
from app.connectors.order_router import OrderRouter
from app.inference.feature_engineering import compute_features
from app.trading.candle_builder import candle_builder_15m
from app.trading.risk_manager import RiskManager
from app.trading.trade_logger import log_trade

logger = logging.getLogger(__name__)


class LiveExecutor:
    """
    Core trading engine. Flow:
    1. Receives completed 15m candle from CandleBuilder
    2. Builds feature DataFrame from candle history
    3. Runs XGBoost prediction + technical filters
    4. If signal fires → RiskManager sizes the trade → OrderRouter executes
    5. Monitors open positions for stop/target hits
    """

    def __init__(self, mode: str = "PAPER", starting_capital: float = 100_000.0):
        self.risk = RiskManager(starting_capital=starting_capital)
        self.router = OrderRouter(mode=mode)
        self._model = None
        self._scaler = None
        self._features_list = None
        self._running = False
        self._load_model()

    def _load_model(self):
        """Load the trained XGBoost ensemble from disk."""
        try:
            from app.inference.models import _ensemble_model, load_models

            if not _ensemble_model:
                load_models()
            from app.inference.models import _ensemble_model as m
            from app.inference.models import _features_list as f
            from app.inference.models import _scaler as s

            self._model = m
            self._scaler = s
            self._features_list = f
            if self._model:
                logger.info("[EXECUTOR] ML model loaded successfully")
            else:
                logger.warning(
                    "[EXECUTOR] No ML model available — signals will be technical-only"
                )
        except Exception as e:
            logger.warning(f"[EXECUTOR] Failed to load ML model: {e}")

    def _get_ml_prediction_and_proba(self, df: pd.DataFrame) -> tuple[int, int]:
        """Run the XGBoost model on the latest row. Returns (pred_class, confidence_pct)."""
        if not self._model or not self._scaler or not self._features_list:
            return -1, 0

        try:
            latest = df.iloc[-1]
            input_data = [latest.get(f, 0.0) for f in self._features_list]
            input_arr = np.array([input_data])
            input_scaled = self._scaler.transform(input_arr)
            input_scaled = np.nan_to_num(input_scaled, nan=0.0, posinf=0.0, neginf=0.0)

            pred = int(self._model.predict(input_scaled)[0])
            if hasattr(self._model, "predict_proba"):
                proba_arr = self._model.predict_proba(input_scaled)[0]
                confidence = int((proba_arr[1] if pred == 1 else proba_arr[0]) * 100)
            else:
                confidence = 0
            return pred, confidence
        except Exception as e:
            logger.error(f"[EXECUTOR] ML prediction error: {e}")
            return -1, 0

    def evaluate_signal(
        self, symbol: str, user_id: Optional[int] = None
    ) -> Optional[dict]:
        """
        Evaluate the current 15m candle history for a trade signal.
        Returns signal dict or None if no trade.
        """
        # Safety gate: check kill-switch before evaluation
        if not config.TRADING_ENABLED:
            logger.info(
                f"[EXECUTOR] Kill-switch active — skipping signal eval for {symbol}"
            )
            return None

        candles = candle_builder_15m.get_history(symbol, limit=200)
        current = candle_builder_15m.get_current_candle(symbol)

        if current:
            candles = candles + [current]

        candles_df = pd.DataFrame(candles)
        if candles_df.empty:
            return None

        for col in ["open", "high", "low", "close", "volume"]:
            if col in candles_df.columns:
                candles_df[col] = pd.to_numeric(candles_df[col], errors="coerce")

        candles_df.ffill(inplace=True)
        candles_df.fillna(0, inplace=True)

        feature_df = compute_features(candles_df.tail(200))
        if feature_df.empty:
            return None

        latest_features = feature_df.iloc[-1]
        latest_price_row = candles_df.iloc[-1]

        close = float(latest_price_row.get("close", 0.0))
        ema_9 = float(latest_features.get("ema_9", 0.0))
        ema_21 = float(latest_features.get("ema_21", 0.0))
        ema_50 = float(latest_features.get("ema_50", 0.0))
        rsi = float(latest_features.get("rsi_14", 0.0))
        vol_spike = int(float(latest_features.get("volume_ratio_20", 1.0)) >= 1.5)
        atr = float(latest_features.get("atr_14", 0.0))

        ml_pred, confidence = self._get_ml_prediction_and_proba(feature_df)

        # --- EXACT BACKTEST ENTRY RULES ---
        signal = None
        reason = ""

        # BUY: ML=1 + Close > EMA50 + Volume Spike + RSI 55-75 + ATR > 0.3% price
        if (
            ml_pred == 1
            and close > ema_50
            and ema_9 > ema_21
            and vol_spike == 1
            and 55 < rsi < 75
            and atr > close * 0.003
        ):
            signal = "BUY"
            reason = f"ML=UP ({confidence}%) EMA9>21 RSI={rsi:.1f} VolSpike"

        # SELL: ML=0 + Close < EMA50 + Volume Spike + RSI 25-45 + ATR > 0.3% price
        elif (
            ml_pred == 0
            and close < ema_50
            and ema_9 < ema_21
            and vol_spike == 1
            and 25 < rsi < 45
            and atr > close * 0.003
        ):
            signal = "SELL"
            reason = f"ML=DN ({confidence}%) EMA9<21 RSI={rsi:.1f} VolSpike"

        if not signal:
            return None

        # Check risk and calculate position
        trade_risk = self.risk.calculate_trade(symbol, signal, close, atr)
        if not trade_risk:
            return None

        # Log the signal to trade audit trail
        signal_data = {
            "symbol": symbol,
            "signal": signal,
            "entry": trade_risk.entry_price,
            "stop_loss": trade_risk.stop_price,
            "target": trade_risk.target_price,
            "quantity": trade_risk.position_size,
            "risk_amount": trade_risk.risk_amount,
            "atr": trade_risk.atr,
            "rsi": round(rsi, 2),
            "ml_prediction": ml_pred,
            "confidence": confidence,
            "reason": reason,
        }

        log_trade(
            "SIGNAL",
            order_id="PRE-ORDER",
            symbol=symbol,
            direction=signal,
            quantity=trade_risk.position_size,
            price=trade_risk.entry_price,
            stop_loss=trade_risk.stop_price,
            target=trade_risk.target_price,
            confidence=confidence,
            reason=reason,
            mode=self.router.mode,
            atr=trade_risk.atr,
            rsi=round(rsi, 2),
            ml_prediction=ml_pred,
            user_id=user_id,
        )

        return signal_data

    def execute_signal(self, signal_data: dict, user_id: Optional[int] = None) -> dict:
        """Execute a validated signal through the order router."""
        if user_id is None:
            logger.warning(
                "[EXECUTOR] Missing user_id — blocking execution for %s",
                signal_data["symbol"],
            )
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": self.router.mode,
                "error": "Missing user_id",
            }

        # Final safety gate before execution
        if not config.TRADING_ENABLED:
            logger.warning(
                f"[EXECUTOR] Kill-switch active — blocking execution for {signal_data['symbol']}"
            )
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": self.router.mode,
                "error": "Kill-switch active",
            }

        # LIVE mode requires explicit confirmation to prevent accidental real-money trades
        if self.router.mode == "LIVE" and not config.LIVE_CONFIRMED:
            logger.warning(
                "[EXECUTOR] LIVE mode not confirmed — blocking execution for %s. "
                "Set LIVE_CONFIRMED=true in .env to enable.",
                signal_data["symbol"],
            )
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": "LIVE",
                "error": "LIVE trading not confirmed. Set LIVE_CONFIRMED=true in .env",
            }

        result = self.router.place_order(
            symbol=signal_data["symbol"],
            direction=signal_data["signal"],
            quantity=signal_data["quantity"],
            price=signal_data["entry"],
            stop_loss=signal_data["stop_loss"],
            target=signal_data["target"],
            user_id=user_id,
            reason=signal_data["reason"],
            confidence=signal_data["confidence"],
        )

        # Auto-confirm paper orders for seamless paper trading
        if result.status == "PENDING_CONFIRMATION" and self.router.mode == "PAPER":
            confirmed = self.router.confirm_and_execute(
                result.order_id, user_id=user_id
            )
            if confirmed:
                self.risk.on_trade_opened()
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

    def check_exits(
        self, symbol: str, current_price: float, user_id: Optional[int] = None
    ) -> Optional[dict]:
        """Check if an open position should be exited (hit SL or TP)."""
        pos = self.router.get_position(symbol, user_id=user_id)
        if not pos:
            return None

        exit_reason = None
        if pos.direction == "BUY":
            if current_price >= pos.target:
                exit_reason = "TARGET_HIT"
            elif current_price <= pos.stop_loss:
                exit_reason = "STOP_LOSS_HIT"
        elif pos.direction == "SELL":
            if current_price <= pos.target:
                exit_reason = "TARGET_HIT"
            elif current_price >= pos.stop_loss:
                exit_reason = "STOP_LOSS_HIT"

        if exit_reason:
            pnl = self.router.close_position(symbol, current_price, user_id=user_id)
            if pnl is not None:
                self.risk.on_trade_closed(pnl)
            return {
                "symbol": symbol,
                "reason": exit_reason,
                "exit_price": current_price,
                "pnl": round(pnl or 0, 2),
            }

        return None

    def on_candle_complete(self, symbol: str, user_id: Optional[int] = None):
        """
        Called when a 15m candle completes. This is the main strategy trigger.
        Checks for exits first, then evaluates new signals.
        """
        # Step 1: Check exits on open positions
        current_candle = candle_builder_15m.get_current_candle(symbol)
        if current_candle and self.router.has_position(symbol, user_id=user_id):
            exit_result = self.check_exits(
                symbol, current_candle["close"], user_id=user_id
            )
            if exit_result:
                logger.info(
                    "[EXECUTOR] EXIT %s: %s @ Rs%.2f PnL=Rs%.2f",
                    symbol,
                    exit_result["reason"],
                    float(exit_result["exit_price"]),
                    float(exit_result["pnl"]),
                )
                return {"action": "EXIT", **exit_result}

        # Step 2: If no position, evaluate new signal
        if not self.router.has_position(symbol, user_id=user_id):
            signal = self.evaluate_signal(symbol, user_id=user_id)
            if signal:
                exec_result = self.execute_signal(signal, user_id=user_id)
                logger.info(
                    "[EXECUTOR] ENTRY %s %s @ Rs%.2f Qty=%s -> %s",
                    signal["signal"],
                    symbol,
                    float(signal["entry"]),
                    signal["quantity"],
                    exec_result["status"],
                )
                return {"action": "ENTRY", **signal, **exec_result}

        return None

    def get_status(self, user_id: Optional[int] = None) -> dict:
        """Full system status for the /trading/status API."""
        return {
            "mode": self.router.mode,
            "risk": self.risk.get_status(),
            "open_positions": self.router.get_open_positions(user_id=user_id),
            "trade_journal": self.router.get_journal(user_id=user_id)[-20:],  # Last 20
            "model_loaded": self._model is not None,
            "trading_enabled": config.TRADING_ENABLED,
            "live_confirmed": config.LIVE_CONFIRMED,
        }


# User-scoped executors to avoid cross-user risk state leakage.
_system_executor: Optional[LiveExecutor] = None
_user_executors: dict[int, LiveExecutor] = {}


def get_executor(
    user_id: Optional[int] = None,
    mode: str = "PAPER",
    capital: float = 100_000.0,
) -> LiveExecutor:
    actual_mode = config.TRADING_MODE if hasattr(config, "TRADING_MODE") else mode

    if user_id is None:
        global _system_executor
        if _system_executor is None:
            _system_executor = LiveExecutor(mode=actual_mode, starting_capital=capital)
        elif _system_executor.router.mode != actual_mode:
            logger.info(
                "[EXECUTOR][SYSTEM] Mode changed: %s → %s",
                _system_executor.router.mode,
                actual_mode,
            )
            _system_executor.router.mode = actual_mode
        return _system_executor

    key = int(user_id)
    executor = _user_executors.get(key)
    if executor is None:
        executor = LiveExecutor(mode=actual_mode, starting_capital=capital)
        _user_executors[key] = executor
        logger.info("[EXECUTOR] Created user-scoped executor for user_id=%d", key)
    elif executor.router.mode != actual_mode:
        logger.info(
            "[EXECUTOR][user=%d] Mode changed: %s → %s",
            key,
            executor.router.mode,
            actual_mode,
        )
        executor.router.mode = actual_mode

    return executor
