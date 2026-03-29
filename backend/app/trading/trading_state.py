"""
Trading State Loader — restores system state from DB on startup.

Ensures the trading engine doesn't lose state across restarts:
  1. Initializes the LiveExecutor singleton
  2. Restores RiskManager state from DailyRiskState table
  3. Logs restored state summary
"""
from __future__ import annotations

import logging

from app import config

logger = logging.getLogger(__name__)


def load_trading_state():
    """
    Synchronous startup function. Called from server lifespan after init_db().
    Initializes the executor and restores risk state from the database.
    """
    from app.trading.live_executor import get_executor

    mode = config.TRADING_MODE
    capital = config.STARTING_CAPITAL

    logger.info(f"[STATE] Loading trading state: mode={mode}, starting_capital=₹{capital:,.2f}")

    # Initialize executor singleton (creates RiskManager + OrderRouter)
    executor = get_executor(mode=mode, capital=capital)

    # Restore risk state from DB
    executor.risk.load_from_db()

    # Safety summary
    status = executor.risk.get_status()
    logger.info(
        f"[STATE] ✓ Trading state loaded | "
        f"Mode={mode} | Capital=₹{status['capital']:,.2f} | "
        f"Trades today={status['trades_today']} | "
        f"Open positions={status['open_positions']} | "
        f"Halted={status['halted']} | "
        f"Kill-switch={'OFF' if config.TRADING_ENABLED else 'ON'}"
    )

    if mode == "LIVE":
        if not config.TRADING_ENABLED:
            logger.warning("[STATE] ⚠ LIVE mode requested but TRADING_ENABLED=false — orders will be blocked")
        if not config.LIVE_CONFIRMED:
            logger.warning("[STATE] ⚠ LIVE mode requested but LIVE_CONFIRMED=false — live orders require confirmation")
