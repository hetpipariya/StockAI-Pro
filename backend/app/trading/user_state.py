"""
Per-user trading state management.
Replaces global singleton pattern with user-isolated instances.

Each user gets their own:
  - Capital tracking
  - Open positions
  - Risk limits (daily loss, trade count)
  - Kill-switch
  - Mode (PAPER / LIVE)

Thread-safe via asyncio.Lock per user state instance.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from app import config

logger = logging.getLogger(__name__)


@dataclass
class UserPosition:
    """A single open position for a specific user."""

    user_id: int
    symbol: str
    direction: str  # "BUY" or "SELL"
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    confidence: int
    mode: str  # "paper" or "live"
    reason: str = ""
    opened_at: datetime = field(default_factory=datetime.utcnow)
    order_id: str = ""


@dataclass
class UserRiskState:
    """
    Daily risk state per user.
    Tracks capital, drawdown, and trading limits.
    """

    user_id: int
    starting_capital: float
    current_capital: float
    daily_pnl: float = 0.0
    trades_today: int = 0
    open_position_count: int = 0
    halted: bool = False
    last_reset_date: date = field(default_factory=date.today)

    # Configurable limits (pulled from config defaults)
    max_risk_per_trade: float = field(
        default_factory=lambda: config.MAX_RISK_PER_TRADE_PCT
    )
    max_trades_per_day: int = field(default_factory=lambda: config.MAX_TRADES_PER_DAY)
    max_concurrent_positions: int = field(
        default_factory=lambda: config.MAX_CONCURRENT_POSITIONS
    )
    daily_loss_limit_pct: float = field(
        default_factory=lambda: config.DAILY_LOSS_LIMIT_PCT
    )
    min_account_balance: float = field(
        default_factory=lambda: config.MIN_ACCOUNT_BALANCE
    )

    @property
    def daily_pnl_pct(self) -> float:
        if self.starting_capital <= 0:
            return 0.0
        return (self.daily_pnl / self.starting_capital) * 100

    @property
    def max_daily_loss_reached(self) -> bool:
        """Stop trading if daily loss exceeds configured limit of capital."""
        return self.daily_pnl_pct <= -(self.daily_loss_limit_pct * 100)

    def reset_if_new_day(self):
        today = date.today()
        if self.last_reset_date != today:
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.halted = False
            self.last_reset_date = today
            logger.info(f"[User {self.user_id}] Daily risk state reset for {today}")


class UserTradingState:
    """
    Complete isolated trading context for one user.
    Each user gets their own capital, positions, and risk limits.
    """

    def __init__(
        self, user_id: int, starting_capital: float = 100_000.0, mode: str = "PAPER"
    ):
        self.user_id = user_id
        self.mode = mode.upper()
        self.positions: dict[str, UserPosition] = {}
        self.trade_journal: list[dict] = []
        self.risk = UserRiskState(
            user_id=user_id,
            starting_capital=starting_capital,
            current_capital=starting_capital,
        )
        self._lock = asyncio.Lock()
        logger.info(
            f"[TradingState] Created state for user_id={user_id} "
            f"capital=₹{starting_capital:,.0f} mode={mode}"
        )

    def can_trade(self) -> tuple[bool, str]:
        """Check if user is allowed to take a new trade."""
        self.risk.reset_if_new_day()

        if self.risk.halted:
            return False, "HALTED: Kill-switch active for your account"

        if not config.TRADING_ENABLED:
            return (
                False,
                "BLOCKED: System-wide kill-switch active (TRADING_ENABLED=false)",
            )

        if self.risk.max_daily_loss_reached:
            return (
                False,
                f"HALTED: Daily loss {self.risk.daily_pnl_pct:.1f}% exceeds limit",
            )

        if self.risk.trades_today >= self.risk.max_trades_per_day:
            return (
                False,
                f"Max trades ({self.risk.max_trades_per_day}) reached for today",
            )

        if len(self.positions) >= self.risk.max_concurrent_positions:
            return (
                False,
                f"Max concurrent positions ({self.risk.max_concurrent_positions}) reached",
            )

        if self.risk.current_capital <= self.risk.min_account_balance:
            self.risk.halted = True
            return (
                False,
                f"HALTED: Capital {self.risk.current_capital:,.0f} below minimum {self.risk.min_account_balance:,.0f}",
            )

        return True, "OK"

    async def open_position(self, pos: UserPosition) -> tuple[bool, str]:
        """
        Open a new position for this user.
        Returns (success, message).
        """
        async with self._lock:
            can, reason = self.can_trade()
            if not can:
                logger.warning(f"[User {self.user_id}] Trade blocked: {reason}")
                return False, reason

            if pos.symbol in self.positions:
                msg = f"Position already open for {pos.symbol}"
                logger.warning(f"[User {self.user_id}] {msg}")
                return False, msg

            self.positions[pos.symbol] = pos
            self.risk.open_position_count = len(self.positions)

            # Log to journal
            self.trade_journal.append(
                {
                    "event": "OPEN",
                    "user_id": self.user_id,
                    "symbol": pos.symbol,
                    "direction": pos.direction,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "target": pos.target,
                    "confidence": pos.confidence,
                    "mode": pos.mode,
                    "reason": pos.reason,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
            )

            logger.info(
                f"[User {self.user_id}] Opened {pos.direction} "
                f"{pos.symbol} @ ₹{pos.entry_price:.2f} qty={pos.quantity} "
                f"SL=₹{pos.stop_loss:.2f} TP=₹{pos.target:.2f}"
            )
            return True, "Position opened"

    async def close_position(
        self, symbol: str, exit_price: float, reason: str = ""
    ) -> Optional[float]:
        """
        Close a position and calculate PnL.
        Returns realized PnL or None if no position existed.
        """
        async with self._lock:
            pos = self.positions.pop(symbol, None)
            if not pos:
                return None

            if pos.direction == "BUY":
                pnl = (exit_price - pos.entry_price) * pos.quantity
            else:
                pnl = (pos.entry_price - exit_price) * pos.quantity

            self.risk.daily_pnl += pnl
            self.risk.trades_today += 1
            self.risk.current_capital += pnl
            self.risk.open_position_count = len(self.positions)

            # Log to journal
            self.trade_journal.append(
                {
                    "event": "CLOSE",
                    "user_id": self.user_id,
                    "symbol": symbol,
                    "direction": pos.direction,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "exit_price": exit_price,
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "mode": pos.mode,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
            )

            logger.info(
                f"[User {self.user_id}] Closed {pos.direction} {symbol} "
                f"@ ₹{exit_price:.2f} pnl=₹{pnl:+,.2f} reason={reason}"
            )
            return pnl

    def get_position(self, symbol: str) -> Optional[UserPosition]:
        return self.positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_all_positions(self) -> list[dict]:
        return [
            {
                "symbol": p.symbol,
                "direction": p.direction,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "stop_loss": p.stop_loss,
                "target": p.target,
                "confidence": p.confidence,
                "mode": p.mode,
                "reason": p.reason,
                "opened_at": p.opened_at.isoformat() + "Z",
                "order_id": p.order_id,
            }
            for p in self.positions.values()
        ]

    def toggle_kill_switch(self, halt: bool):
        self.risk.halted = halt
        logger.warning(
            f"[User {self.user_id}] Kill-switch {'ACTIVATED' if halt else 'DEACTIVATED'}"
        )

    def get_journal(self, limit: int = 50) -> list[dict]:
        """Return most recent trade journal entries."""
        return self.trade_journal[-limit:][::-1]  # Newest first

    def get_summary(self) -> dict:
        self.risk.reset_if_new_day()
        can, reason = self.can_trade()
        return {
            "user_id": self.user_id,
            "mode": self.mode,
            "capital": round(self.risk.current_capital, 2),
            "starting_capital": round(self.risk.starting_capital, 2),
            "daily_pnl": round(self.risk.daily_pnl, 2),
            "daily_pnl_pct": round(self.risk.daily_pnl_pct, 2),
            "trades_today": self.risk.trades_today,
            "max_trades_per_day": self.risk.max_trades_per_day,
            "open_positions": len(self.positions),
            "max_positions": self.risk.max_concurrent_positions,
            "is_halted": self.risk.halted,
            "max_loss_reached": self.risk.max_daily_loss_reached,
            "can_trade": can,
            "can_trade_reason": reason,
            "trading_enabled": config.TRADING_ENABLED,
            "live_confirmed": config.LIVE_CONFIRMED,
        }


class TradingManager:
    """
    Central registry that maps user_id → UserTradingState.
    Thread-safe. Provides user isolation for the entire trading subsystem.

    Usage:
        state = await trading_manager.get_state(user_id=42)
        await state.open_position(pos)
    """

    _instance: Optional["TradingManager"] = None

    def __init__(self):
        self._states: dict[int, UserTradingState] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "TradingManager":
        if cls._instance is None:
            cls._instance = TradingManager()
        return cls._instance

    async def get_state(
        self, user_id: int, starting_capital: float = 100_000.0, mode: str = "PAPER"
    ) -> UserTradingState:
        """
        Get or create isolated trading state for a user.
        The state persists for the server lifetime.
        """
        async with self._lock:
            if user_id not in self._states:
                # Use config mode as default if not explicitly set
                actual_mode = getattr(config, "TRADING_MODE", mode)
                self._states[user_id] = UserTradingState(
                    user_id=user_id,
                    starting_capital=starting_capital,
                    mode=actual_mode,
                )
            return self._states[user_id]

    async def remove_state(self, user_id: int):
        """Remove state when user logs out / session ends."""
        async with self._lock:
            state = self._states.pop(user_id, None)
            if state:
                logger.info(
                    f"[TradingManager] Removed state for user_id={user_id} "
                    f"(had {len(state.positions)} open positions)"
                )

    def get_active_user_count(self) -> int:
        return len(self._states)

    def get_all_summaries(self) -> list[dict]:
        return [state.get_summary() for state in self._states.values()]


# ── Module-level singleton accessor ──
trading_manager = TradingManager.get_instance()
