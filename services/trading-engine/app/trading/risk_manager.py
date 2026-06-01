"""
Risk Manager — enforces position sizing, daily loss limits, and trade frequency caps.
Mirrors the exact backtest math: 1% equity risk per trade, ATR-based stops.
Persists daily state to DB for crash recovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from stockai_shared.config import config

logger = logging.getLogger(__name__)


@dataclass
class TradeRisk:
    """Calculated risk parameters for a single trade."""

    symbol: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    stop_price: float
    target_price: float
    position_size: int  # Number of shares
    risk_amount: float  # Capital at risk (₹)
    reward_amount: float  # Potential reward (₹)
    atr: float


class RiskManager:
    """
    Controls risk for the live trading engine.
    - 1% equity risk per trade
    - ATR-based stop loss (1.5x ATR)
    - ATR-based target (1.5x ATR * R:R ratio)
    - Daily loss limit (-3% of starting equity)
    - Max concurrent positions
    - Max trades per day
    - Minimum account balance floor
    - DB-persisted daily state for crash recovery
    """

    def __init__(
        self,
        starting_capital: float = None,
        risk_per_trade_pct: float = None,
        reward_risk_ratio: float = 1.5,
        atr_stop_multiplier: float = 1.5,
        daily_loss_limit_pct: float = None,
        max_concurrent_positions: int = None,
        max_trades_per_day: int = None,
        min_account_balance: float = None,
    ):
        # Pull from config if not explicitly passed
        self.starting_capital = (
            starting_capital
            if starting_capital is not None
            else config.STARTING_CAPITAL
        )
        self.capital = self.starting_capital
        self.risk_per_trade = (
            risk_per_trade_pct
            if risk_per_trade_pct is not None
            else config.MAX_RISK_PER_TRADE_PCT
        )
        self.rr_ratio = reward_risk_ratio
        self.atr_mult = atr_stop_multiplier
        self.daily_loss_limit = (
            daily_loss_limit_pct
            if daily_loss_limit_pct is not None
            else config.DAILY_LOSS_LIMIT_PCT
        )
        self.max_positions = (
            max_concurrent_positions
            if max_concurrent_positions is not None
            else config.MAX_CONCURRENT_POSITIONS
        )
        self.max_daily_trades = (
            max_trades_per_day
            if max_trades_per_day is not None
            else config.MAX_TRADES_PER_DAY
        )
        self.min_balance = (
            min_account_balance
            if min_account_balance is not None
            else config.MIN_ACCOUNT_BALANCE
        )

        # Daily tracking
        self._today: Optional[date] = None
        self._daily_start_capital: float = self.starting_capital
        self._trades_today: int = 0
        self._open_positions: int = 0
        self._halted: bool = False

        self._check_new_day()

    def _check_new_day(self):
        """Reset daily counters if the date has changed."""
        today = date.today()
        if self._today != today:
            self._today = today
            self._daily_start_capital = self.capital
            self._trades_today = 0
            self._halted = False
            logger.info(f"[RISK] New trading day: capital=₹{self.capital:,.2f}")

    @property
    def is_halted(self) -> bool:
        self._check_new_day()
        return self._halted

    def daily_pnl_pct(self) -> float:
        if self._daily_start_capital <= 0:
            return 0.0
        return (self.capital - self._daily_start_capital) / self._daily_start_capital

    def can_trade(self) -> tuple[bool, str]:
        """Check if we are allowed to take a new trade."""
        self._check_new_day()

        if self._halted:
            return False, "HALTED: Daily loss limit exceeded"

        # Kill-switch check
        if not config.TRADING_ENABLED:
            return False, "BLOCKED: Kill-switch active (TRADING_ENABLED=false)"

        if self._trades_today >= self.max_daily_trades:
            return False, f"Max trades ({self.max_daily_trades}) reached for today"

        if self._open_positions >= self.max_positions:
            return False, f"Max concurrent positions ({self.max_positions}) reached"

        # Minimum account balance floor
        if self.capital <= self.min_balance:
            self._halted = True
            logger.warning(
                f"[RISK] HALTED — Capital ₹{self.capital:,.2f} below minimum ₹{self.min_balance:,.2f}"
            )
            return (
                False,
                f"HALTED: Capital below minimum balance (₹{self.min_balance:,.0f})",
            )

        # Check daily loss limit
        daily_pnl = self.daily_pnl_pct()
        if daily_pnl <= -self.daily_loss_limit:
            self._halted = True
            logger.warning(
                f"[RISK] HALTED — Daily loss {daily_pnl * 100:.2f}% exceeds limit "
                f"of -{self.daily_loss_limit * 100:.1f}%"
            )
            return False, f"HALTED: Daily loss {daily_pnl * 100:.2f}% exceeds limit"

        return True, "OK"

    def calculate_trade(
        self, symbol: str, direction: str, entry_price: float, atr: float
    ) -> Optional[TradeRisk]:
        """
        Calculate position size and risk parameters for a trade.
        Returns None if the trade violates risk rules.
        """
        can, reason = self.can_trade()
        if not can:
            logger.info(f"[RISK] Trade rejected for {symbol}: {reason}")
            return None

        if atr <= 0 or entry_price <= 0:
            logger.warning(
                f"[RISK] Invalid ATR ({atr}) or entry ({entry_price}) for {symbol}"
            )
            return None

        stop_dist = self.atr_mult * atr
        target_dist = stop_dist * self.rr_ratio

        if direction == "BUY":
            stop_price = round(entry_price - stop_dist, 2)
            target_price = round(entry_price + target_dist, 2)
        else:
            stop_price = round(entry_price + stop_dist, 2)
            target_price = round(entry_price - target_dist, 2)

        # Position sizing: risk exactly risk_per_trade% of capital
        risk_amount = self.capital * self.risk_per_trade
        shares = int(risk_amount / stop_dist)

        if shares <= 0:
            logger.info(
                f"[RISK] Position size too small for {symbol} (ATR={atr:.2f}, stop_dist={stop_dist:.2f})"
            )
            return None

        # Ensure we don't exceed capital
        cost = shares * entry_price
        if cost > self.capital:
            shares = int(self.capital / entry_price)
            if shares <= 0:
                return None

        reward_amount = shares * target_dist

        return TradeRisk(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry_price, 2),
            stop_price=stop_price,
            target_price=target_price,
            position_size=shares,
            risk_amount=round(risk_amount, 2),
            reward_amount=round(reward_amount, 2),
            atr=round(atr, 4),
        )

    def calculate_trade_percent(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> Optional[TradeRisk]:
        """
        Calculate position sizing with fixed percentage stop-loss/take-profit.
        Useful for systems that were optimized with percent-based exits.
        """
        can, reason = self.can_trade()
        if not can:
            logger.info(f"[RISK] Trade rejected for {symbol}: {reason}")
            return None

        if entry_price <= 0:
            logger.warning(f"[RISK] Invalid entry ({entry_price}) for {symbol}")
            return None

        if stop_loss_pct <= 0 or take_profit_pct <= 0:
            logger.warning(
                "[RISK] Invalid stop/target pct for %s: stop=%s target=%s",
                symbol,
                stop_loss_pct,
                take_profit_pct,
            )
            return None

        stop_dist = entry_price * stop_loss_pct
        target_dist = entry_price * take_profit_pct
        if stop_dist <= 0 or target_dist <= 0:
            return None

        direction = str(direction).upper()
        if direction == "BUY":
            stop_price = round(entry_price - stop_dist, 2)
            target_price = round(entry_price + target_dist, 2)
        else:
            stop_price = round(entry_price + stop_dist, 2)
            target_price = round(entry_price - target_dist, 2)

        risk_amount = self.capital * self.risk_per_trade
        shares = int(risk_amount / stop_dist)

        if shares <= 0:
            logger.info(
                "[RISK] Position size too small for %s (stop_dist=%.4f)",
                symbol,
                stop_dist,
            )
            return None

        cost = shares * entry_price
        if cost > self.capital:
            shares = int(self.capital / entry_price)
            if shares <= 0:
                return None

        reward_amount = shares * target_dist

        return TradeRisk(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry_price, 2),
            stop_price=stop_price,
            target_price=target_price,
            position_size=shares,
            risk_amount=round(risk_amount, 2),
            reward_amount=round(reward_amount, 2),
            atr=0.0,
        )

    def on_trade_opened(self):
        """Called when a trade is actually placed."""
        self._trades_today += 1
        self._open_positions += 1
        logger.info(
            f"[RISK] Trade opened — {self._trades_today} today, {self._open_positions} open"
        )
        self._persist_state()

    def on_trade_closed(self, pnl: float):
        """Called when a trade is exited. pnl = realized profit/loss in ₹."""
        self._open_positions = max(0, self._open_positions - 1)
        self.capital += pnl
        logger.info(
            "[RISK] Trade closed - PnL=Rs%.2f, Capital=Rs%.2f, Daily=%.2f%%",
            pnl,
            self.capital,
            self.daily_pnl_pct() * 100,
        )

        # Check daily limit after close
        if self.daily_pnl_pct() <= -self.daily_loss_limit:
            self._halted = True
            logger.warning(
                "[RISK] HALTED after trade close — daily loss limit breached"
            )

        self._persist_state()

    async def _persist_state_async(self):
        """Write current risk state to DailyRiskState table asynchronously."""
        try:
            from stockai_shared.db.db import DailyRiskState, AsyncSessionLocal
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                today_str = date.today().isoformat()
                stmt = select(DailyRiskState).where(DailyRiskState.date == today_str).limit(1)
                result = await session.execute(stmt)
                row = result.scalars().first()
                if row:
                    row.current_capital = self.capital
                    row.trades_today = self._trades_today
                    row.halted = self._halted
                else:
                    row = DailyRiskState(
                        date=today_str,
                        starting_capital=self._daily_start_capital,
                        current_capital=self.capital,
                        trades_today=self._trades_today,
                        halted=self._halted,
                    )
                    session.add(row)
                await session.commit()
        except Exception as e:
            logger.error(f"[RISK] Failed to persist state asynchronously: {e}")

    def _persist_state_sync_fallback(self):
        """Sync fallback worker to write risk state in a background thread."""
        try:
            from stockai_shared.db.db import DailyRiskState, get_sync_db_session
            db_gen = get_sync_db_session()
            session = next(db_gen)
            if session is None:
                return
            try:
                today_str = date.today().isoformat()
                row = session.query(DailyRiskState).filter_by(date=today_str).first()
                if row:
                    row.current_capital = self.capital
                    row.trades_today = self._trades_today
                    row.halted = self._halted
                else:
                    row = DailyRiskState(
                        date=today_str,
                        starting_capital=self._daily_start_capital,
                        current_capital=self.capital,
                        trades_today=self._trades_today,
                        halted=self._halted,
                    )
                    session.add(row)
                session.commit()
            finally:
                session.close()
        except Exception as exc:
            logger.error(f"[RISK] Sync fallback persist state failed: {exc}")

    def _persist_state(self):
        """Write current risk state. Uses async non-blocking task if loop is active."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_state_async())
        except RuntimeError:
            import threading
            threading.Thread(target=self._persist_state_sync_fallback, daemon=True).start()

    async def load_from_db_async(self):
        """Restore risk state from DB asynchronously."""
        try:
            from stockai_shared.db.db import DailyRiskState, PositionModel, AsyncSessionLocal
            from sqlalchemy import select, func

            async with AsyncSessionLocal() as session:
                today_str = date.today().isoformat()

                # 1. Restore daily risk state
                stmt = select(DailyRiskState).where(DailyRiskState.date == today_str).limit(1)
                result = await session.execute(stmt)
                risk_state = result.scalars().first()
                if risk_state:
                    self._daily_start_capital = risk_state.starting_capital
                    self.capital = risk_state.current_capital
                    self._trades_today = risk_state.trades_today
                    self._halted = risk_state.halted
                    logger.info(
                        f"[RISK] Restored from DB (async): capital=₹{self.capital:,.2f}, "
                        f"trades={self._trades_today}, halted={self._halted}"
                    )

                # 2. Count open positions from DB
                count_stmt = select(func.count(PositionModel.id))
                count_result = await session.execute(count_stmt)
                open_count = count_result.scalar() or 0
                self._open_positions = open_count
                logger.info(f"[RISK] Restored {open_count} open positions from DB (async)")
        except Exception as e:
            logger.error(f"[RISK] Failed to load state from DB asynchronously: {e}")

    def _load_from_db_sync_fallback(self):
        """Sync fallback load state from DB."""
        try:
            from stockai_shared.db.db import (DailyRiskState, PositionModel,
                                         get_sync_db_session)
            db_gen = get_sync_db_session()
            session = next(db_gen)
            if session is None:
                return
            try:
                today_str = date.today().isoformat()
                risk_state = session.query(DailyRiskState).filter_by(date=today_str).first()
                if risk_state:
                    self._daily_start_capital = risk_state.starting_capital
                    self.capital = risk_state.current_capital
                    self._trades_today = risk_state.trades_today
                    self._halted = risk_state.halted
                open_count = session.query(PositionModel).count()
                self._open_positions = open_count
            finally:
                session.close()
        except Exception as exc:
            logger.error(f"[RISK] Sync fallback load from DB failed: {exc}")

    def load_from_db(self):
        """Restore risk state from DailyRiskState + open positions in DB."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # Loop is running, we can schedule the coroutine or execute sync in fallback
                # To guarantee synchronization on startup, let's run the sync fallback to load instantly
                self._load_from_db_sync_fallback()
            else:
                asyncio.run(self.load_from_db_async())
        except RuntimeError:
            self._load_from_db_sync_fallback()


    def get_status(self) -> dict:
        self._check_new_day()
        return {
            "capital": round(self.capital, 2),
            "daily_pnl_pct": round(self.daily_pnl_pct() * 100, 2),
            "trades_today": self._trades_today,
            "open_positions": self._open_positions,
            "halted": self._halted,
            "max_trades_per_day": self.max_daily_trades,
            "max_positions": self.max_positions,
            "min_account_balance": self.min_balance,
            "trading_enabled": config.TRADING_ENABLED,
            "trading_mode": config.TRADING_MODE,
        }
