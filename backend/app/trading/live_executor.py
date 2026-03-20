"""
Live Trading Executor — evaluates 15m candles against the XGBoost model.
Mirrors the exact backtest parameters: EMA9/21/50, RSI, Volume Spike, ATR.
Operates in PAPER or LIVE mode with multi-layer safety checks.
"""
from __future__ import annotations

import logging
import asyncio
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

from app import config
from app.trading.candle_builder import candle_builder_15m
from app.trading.risk_manager import RiskManager, TradeRisk
from app.trading.trade_logger import log_trade
from app.connectors.order_router import OrderRouter

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
            from app.inference.models import _ensemble_model, _scaler, _features_list, load_models
            if not _ensemble_model:
                load_models()
            from app.inference.models import _ensemble_model as m, _scaler as s, _features_list as f
            self._model = m
            self._scaler = s
            self._features_list = f
            if self._model:
                logger.info("[EXECUTOR] ML model loaded successfully")
            else:
                logger.warning("[EXECUTOR] No ML model available — signals will be technical-only")
        except Exception as e:
            logger.warning(f"[EXECUTOR] Failed to load ML model: {e}")

    def _build_features(self, candles: list[dict]) -> Optional[pd.DataFrame]:
        """Convert candle history into a feature DataFrame matching training format."""
        if len(candles) < 50:
            return None

        df = pd.DataFrame(candles)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df.ffill(inplace=True)
        df.fillna(0, inplace=True)

        c = df['close']
        h = df['high']
        l = df['low']

        # EMAs
        df['ema_9'] = c.ewm(span=9, adjust=False).mean()
        df['ema_20'] = c.ewm(span=20, adjust=False).mean()
        df['ema_21'] = c.ewm(span=21, adjust=False).mean()
        df['ema_50'] = c.ewm(span=50, adjust=False).mean()

        # RSI
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi_14'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = c.ewm(span=12, adjust=False).mean()
        exp2 = c.ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # VWAP
        q = df['volume']
        p = (h + l + c) / 3
        df['vwap'] = (p * q).cumsum() / (q.cumsum() + 1e-9)

        # Volume Spike (2x 20-period MA)
        vol_ma = df['volume'].rolling(20, min_periods=1).mean()
        df['volume_spike'] = (df['volume'] > (vol_ma * 2.0)).astype(int)

        # ATR
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        df['true_range'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr_14'] = df['true_range'].rolling(14).mean()

        # Advanced features
        df['price_change'] = c - df['open']
        safe_c = c.clip(lower=1e-5)
        df['volatility'] = (h - l) / safe_c
        df['momentum'] = c - c.shift(3)
        df['rolling_mean_5'] = c.rolling(5, min_periods=1).mean()
        df['rolling_std_5'] = c.rolling(5, min_periods=2).std()
        df['pct_change_1d'] = c.pct_change(1)
        df['pct_change_5d'] = c.pct_change(5)
        df['roll_std_5d'] = df['pct_change_1d'].rolling(5).std()
        df['roll_std_20d'] = df['pct_change_1d'].rolling(20).std()
        df['roll_mean_5d'] = c.rolling(5).mean()
        df['roll_mean_20d'] = c.rolling(20).mean()
        df['trend_strength'] = (c - df['ema_20']) / (df['ema_20'] + 1e-9)
        df['rsi_momentum'] = df['rsi_14'].diff()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.fillna(0, inplace=True)

        return df

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

    def evaluate_signal(self, symbol: str) -> Optional[dict]:
        """
        Evaluate the current 15m candle history for a trade signal.
        Returns signal dict or None if no trade.
        """
        # Safety gate: check kill-switch before evaluation
        if not config.TRADING_ENABLED:
            logger.info(f"[EXECUTOR] Kill-switch active — skipping signal eval for {symbol}")
            return None

        candles = candle_builder_15m.get_history(symbol, limit=200)
        current = candle_builder_15m.get_current_candle(symbol)

        if current:
            candles = candles + [current]

        df = self._build_features(candles)
        if df is None:
            return None

        latest = df.iloc[-1]
        close = float(latest['close'])
        ema_9 = float(latest['ema_9'])
        ema_21 = float(latest['ema_21'])
        ema_50 = float(latest['ema_50'])
        rsi = float(latest['rsi_14'])
        vol_spike = int(latest['volume_spike'])
        atr = float(latest['atr_14'])

        ml_pred, confidence = self._get_ml_prediction_and_proba(df)

        # --- EXACT BACKTEST ENTRY RULES ---
        signal = None
        reason = ""

        # BUY: ML=1 + Close > EMA50 + Volume Spike + RSI 55-75 + ATR > 0.3% price
        if (ml_pred == 1 and close > ema_50 and ema_9 > ema_21
            and vol_spike == 1 and 55 < rsi < 75
            and atr > close * 0.003):
            signal = "BUY"
            reason = f"ML=UP ({confidence}%) EMA9>21 RSI={rsi:.1f} VolSpike"

        # SELL: ML=0 + Close < EMA50 + Volume Spike + RSI 25-45 + ATR > 0.3% price
        elif (ml_pred == 0 and close < ema_50 and ema_9 < ema_21
              and vol_spike == 1 and 25 < rsi < 45
              and atr > close * 0.003):
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
            "SIGNAL", order_id="PRE-ORDER", symbol=symbol,
            direction=signal, quantity=trade_risk.position_size,
            price=trade_risk.entry_price, stop_loss=trade_risk.stop_price,
            target=trade_risk.target_price, confidence=confidence,
            reason=reason, mode=self.router.mode, atr=trade_risk.atr,
            rsi=round(rsi, 2), ml_prediction=ml_pred,
        )

        return signal_data

    def execute_signal(self, signal_data: dict) -> dict:
        """Execute a validated signal through the order router."""
        # Final safety gate before execution
        if not config.TRADING_ENABLED:
            logger.warning(f"[EXECUTOR] Kill-switch active — blocking execution for {signal_data['symbol']}")
            return {
                "order_id": "BLOCKED",
                "status": "REJECTED",
                "mode": self.router.mode,
                "error": "Kill-switch active",
            }

        # LIVE mode requires explicit confirmation to prevent accidental real-money trades
        if self.router.mode == "LIVE" and not config.LIVE_CONFIRMED:
            logger.warning(f"[EXECUTOR] LIVE mode not confirmed — blocking execution for {signal_data['symbol']}. Set LIVE_CONFIRMED=true in .env to enable.")
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
            reason=signal_data["reason"],
            confidence=signal_data["confidence"]
        )

        # Auto-confirm paper orders for seamless paper trading
        if result.status == "PENDING_CONFIRMATION" and self.router.mode == "PAPER":
            confirmed = self.router.confirm_and_execute(result.order_id)
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

    def check_exits(self, symbol: str, current_price: float) -> Optional[dict]:
        """Check if an open position should be exited (hit SL or TP)."""
        pos = self.router.get_position(symbol)
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
            pnl = self.router.close_position(symbol, current_price)
            if pnl is not None:
                self.risk.on_trade_closed(pnl)
            return {
                "symbol": symbol,
                "reason": exit_reason,
                "exit_price": current_price,
                "pnl": round(pnl or 0, 2),
            }

        return None

    def on_candle_complete(self, symbol: str):
        """
        Called when a 15m candle completes. This is the main strategy trigger.
        Checks for exits first, then evaluates new signals.
        """
        # Step 1: Check exits on open positions
        current_candle = candle_builder_15m.get_current_candle(symbol)
        if current_candle and self.router.has_position(symbol):
            exit_result = self.check_exits(symbol, current_candle['close'])
            if exit_result:
                logger.info(f"[EXECUTOR] EXIT {symbol}: {exit_result['reason']} @ ₹{exit_result['exit_price']:.2f} PnL=₹{exit_result['pnl']:,.2f}")
                return {"action": "EXIT", **exit_result}

        # Step 2: If no position, evaluate new signal
        if not self.router.has_position(symbol):
            signal = self.evaluate_signal(symbol)
            if signal:
                exec_result = self.execute_signal(signal)
                logger.info(f"[EXECUTOR] ENTRY {signal['signal']} {symbol} @ ₹{signal['entry']:.2f} Qty={signal['quantity']} → {exec_result['status']}")
                return {"action": "ENTRY", **signal, **exec_result}

        return None

    def get_status(self) -> dict:
        """Full system status for the /trading/status API."""
        return {
            "mode": self.router.mode,
            "risk": self.risk.get_status(),
            "open_positions": self.router.get_open_positions(),
            "trade_journal": self.router.get_journal()[-20:],  # Last 20
            "model_loaded": self._model is not None,
            "trading_enabled": config.TRADING_ENABLED,
            "live_confirmed": config.LIVE_CONFIRMED,
        }


# Singleton — initialized on first import
_executor: Optional[LiveExecutor] = None


def get_executor(mode: str = "PAPER", capital: float = 100_000.0) -> LiveExecutor:
    global _executor
    if _executor is None:
        # Use config mode if available, otherwise use parameter
        actual_mode = config.TRADING_MODE if hasattr(config, 'TRADING_MODE') else mode
        _executor = LiveExecutor(mode=actual_mode, starting_capital=capital)
    else:
        # Sync mode from config on every access to pick up runtime changes
        current_config_mode = config.TRADING_MODE if hasattr(config, 'TRADING_MODE') else mode
        if _executor.router.mode != current_config_mode:
            logger.info(f"[EXECUTOR] Mode changed: {_executor.router.mode} → {current_config_mode}")
            _executor.router.mode = current_config_mode
    return _executor
