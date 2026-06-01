"""Canonical strategy configuration for StockAI Pro.

This adapter keeps the live strategy modules off ``experiments_v2`` while
preserving the constants and helper methods they expect.
"""

from __future__ import annotations

import os

from stockai_shared.config import config as app_config


class StrategyConfig:
    CAPITAL_INITIAL = float(getattr(app_config, "STARTING_CAPITAL", 100_000.0))
    TREND_BULL_MIN = float(os.getenv("STRATEGY_TREND_BULL_MIN", "0.55"))
    TREND_BEAR_MAX = float(os.getenv("STRATEGY_TREND_BEAR_MAX", "0.45"))
    ENTRY_BUY_MIN = float(os.getenv("STRATEGY_ENTRY_BUY_MIN", "0.60"))
    ENTRY_SELL_MIN = float(os.getenv("STRATEGY_ENTRY_SELL_MIN", "0.60"))
    MIN_ATR_PCT = float(os.getenv("STRATEGY_MIN_ATR_PCT", "0.002"))
    MIN_VOL_RATIO = float(os.getenv("STRATEGY_MIN_VOL_RATIO", "0.5"))
    COOLDOWN_BARS = int(os.getenv("STRATEGY_COOLDOWN_BARS", "3"))
    TP_PCT = float(os.getenv("STRATEGY_TP_PCT", "0.01"))
    SL_PCT = float(os.getenv("STRATEGY_SL_PCT", "0.005"))
    MAX_TRADES_PER_DAY = int(getattr(app_config, "MAX_TRADES_PER_DAY", 10))
    DAILY_LOSS_LIMIT = float(getattr(app_config, "DAILY_LOSS_LIMIT_PCT", 0.035))
    DRAWDOWN_KILL = float(os.getenv("STRATEGY_DRAWDOWN_KILL", "0.08"))
    SLIPPAGE_PCT = float(os.getenv("STRATEGY_SLIPPAGE_PCT", "0.0005"))

    @staticmethod
    def rr_ratio() -> float:
        sl_pct = max(StrategyConfig.SL_PCT, 1e-9)
        return float(StrategyConfig.TP_PCT / sl_pct)

    @staticmethod
    def position_size(equity: float, entry_price: float) -> float:
        equity = max(float(equity), 0.0)
        entry_price = max(float(entry_price), 0.0)
        if equity <= 0.0 or entry_price <= 0.0:
            return 0.0

        risk_amount = equity * min(float(getattr(app_config, "MAX_RISK_PER_TRADE_PCT", 0.02)), 0.025)
        stop_distance = max(entry_price * StrategyConfig.SL_PCT, entry_price * 0.001)
        risk_qty = risk_amount / stop_distance
        max_notional_qty = (equity * 0.20) / entry_price
        return max(0.0, min(risk_qty, max_notional_qty))


class SimConfig:
    CAPITAL_INITIAL = StrategyConfig.CAPITAL_INITIAL
    TRADING_MODE = getattr(app_config, "TRADING_MODE", "PAPER")
    TRADING_ENABLED = bool(getattr(app_config, "TRADING_ENABLED", True))
    MARKET_OPEN = getattr(app_config, "MARKET_OPEN", "09:15")
    MARKET_CLOSE = getattr(app_config, "MARKET_CLOSE", "15:30")


__all__ = ["StrategyConfig", "SimConfig"]