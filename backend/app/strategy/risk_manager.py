"""
backend/app/strategy/risk_manager.py
=====================================
Production Risk Manager for StockAI Pro.

Enforces:
  - Daily trade count cap
  - Daily P&L loss limit (stops new entries today)
  - Peak-to-trough drawdown kill switch (stops system entirely)
  - Per-trade exposure validation

Thread-safe for FastAPI async context (state is per-instance, not shared).

Usage:
    risk = RiskManager(starting_equity=1_000_000)

    # Before opening a trade
    ok, reason = risk.pre_trade_check(signal)
    if not ok:
        logger.warning("Trade blocked: %s", reason)
        return

    # After trade closes
    risk.record_trade_result(pnl_amount=+1200.0, symbol="RELIANCE")

    # At start of new day
    risk.reset_daily()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

from app.strategy.config import StrategyConfig

if TYPE_CHECKING:
    from app.strategy.signal_engine import TradeSignal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# TRADE RECORD
# ─────────────────────────────────────────────
@dataclass
class TradeRecord:
    symbol:    str
    direction: str
    entry:     float
    exit:      float | None
    qty:       float
    pnl:       float | None
    opened_at: datetime
    closed_at: datetime | None = None
    outcome:   str = "OPEN"  # OPEN | WIN | LOSS | TIMEOUT


# ─────────────────────────────────────────────
# RISK MANAGER
# ─────────────────────────────────────────────
class RiskManager:
    """
    Tracks equity, daily P&L, open trades, and enforces all circuit-breakers.

    State lifecycle:
        Session start → __init__
        Each new day  → reset_daily()
        Trade open    → pre_trade_check() → record_trade_open()
        Trade close   → record_trade_result()
        Kill switch   → is_system_halted() → True

    All monetary values in Rs (or whatever base currency).
    """

    def __init__(self, starting_equity: float = StrategyConfig.CAPITAL_INITIAL):
        self.equity         = starting_equity
        self.peak_equity    = starting_equity
        self._system_halted = False
        self._halt_reason   = ""

        # Daily state — reset by reset_daily()
        self._daily_trades  = 0
        self._daily_pnl     = 0.0
        self._trading_date  = date.today()
        self._day_halted    = False
        self._day_halt_reason = ""

        # Full trade log (append-only)
        self._trade_log: list[TradeRecord] = []
        self._open_symbols: set[str] = set()

        logger.info(
            "RiskManager initialized | equity=%.0f | daily_cap=%d | "
            "daily_loss_limit=%.1f%% | dd_kill=%.1f%%",
            starting_equity,
            StrategyConfig.MAX_TRADES_PER_DAY,
            StrategyConfig.DAILY_LOSS_LIMIT * 100,
            StrategyConfig.DRAWDOWN_KILL * 100,
        )

    # ─────────────────────────────────────────
    # PUBLIC STATE QUERIES
    # ─────────────────────────────────────────
    def is_system_halted(self) -> bool:
        return self._system_halted

    def is_day_halted(self) -> bool:
        return self._day_halted or self._system_halted

    def drawdown(self) -> float:
        """Current drawdown from peak equity (negative = loss)."""
        return (self.equity - self.peak_equity) / self.peak_equity

    def daily_pnl_pct(self) -> float:
        """Today's realized P&L as fraction of starting-of-day equity."""
        return self._daily_pnl / max(self.equity, 1.0)

    def open_trade_count(self) -> int:
        return len(self._open_symbols)

    def summary(self) -> dict:
        return {
            "equity":            round(self.equity, 2),
            "peak_equity":       round(self.peak_equity, 2),
            "drawdown_pct":      round(self.drawdown() * 100, 2),
            "daily_trades":      self._daily_trades,
            "daily_pnl":         round(self._daily_pnl, 2),
            "system_halted":     self._system_halted,
            "halt_reason":       self._halt_reason or self._day_halt_reason,
            "day_halted":        self._day_halted,
            "open_positions":    list(self._open_symbols),
            "total_trades_log":  len(self._trade_log),
        }

    # ─────────────────────────────────────────
    # PRE-TRADE GATE
    # ─────────────────────────────────────────
    def pre_trade_check(self, signal: "TradeSignal") -> tuple[bool, str]:
        """
        Returns (True, "") if the trade may proceed.
        Returns (False, reason) if any circuit-breaker is active.
        Call this BEFORE sending order to broker.
        """
        # System-level kill switch
        if self._system_halted:
            return False, f"SYSTEM_HALTED: {self._halt_reason}"

        # Day-level halt
        if self._day_halted:
            return False, f"DAY_HALTED: {self._day_halt_reason}"

        # Already have an open position in this symbol
        if signal.symbol in self._open_symbols:
            return False, f"ALREADY_IN_{signal.symbol}"

        # Daily trade cap
        if self._daily_trades >= StrategyConfig.MAX_TRADES_PER_DAY:
            return False, f"MAX_TRADES_REACHED ({StrategyConfig.MAX_TRADES_PER_DAY}/day)"

        # Position exposure sanity check
        exposure = signal.entry_price * signal.qty
        if exposure > self.equity * 0.20:
            # Single position > 20% of equity is too concentrated
            return False, f"EXPOSURE_TOO_LARGE: {exposure:.0f} > 20% of equity"

        return True, ""

    # ─────────────────────────────────────────
    # TRADE LIFECYCLE
    # ─────────────────────────────────────────
    def record_trade_open(self, signal: "TradeSignal") -> TradeRecord:
        """Call immediately after order confirmation from broker."""
        record = TradeRecord(
            symbol=signal.symbol,
            direction=signal.signal,
            entry=signal.entry_price,
            exit=None,
            qty=signal.qty,
            pnl=None,
            opened_at=signal.timestamp or datetime.now(),
        )
        self._trade_log.append(record)
        self._open_symbols.add(signal.symbol)
        self._daily_trades += 1
        logger.info(
            "[TRADE OPEN] %s %s qty=%.0f @ %.2f | day_count=%d",
            signal.symbol, signal.signal, signal.qty,
            signal.entry_price, self._daily_trades,
        )
        return record

    def record_trade_result(
        self,
        symbol: str,
        exit_price: float,
        outcome: str = "CLOSED",
        closed_at: datetime | None = None,
    ) -> float:
        """
        Call after position closes (TP/SL/timeout/manual).
        Returns the realized P&L in rupees.
        Applies circuit-breakers after updating equity.
        """
        record = self._find_open_record(symbol)
        if record is None:
            logger.warning("record_trade_result: no open position for %s", symbol)
            return 0.0

        direction_sign = 1 if record.direction == "BUY" else -1
        pnl_pct        = direction_sign * (exit_price / record.entry - 1)
        pnl_rs         = pnl_pct * record.entry * record.qty

        # Apply slippage on exit
        pnl_rs -= StrategyConfig.SLIPPAGE_PCT * record.entry * record.qty

        record.exit      = exit_price
        record.pnl       = pnl_rs
        record.outcome   = "WIN" if pnl_rs > 0 else "LOSS"
        record.closed_at = closed_at or datetime.now()

        self._open_symbols.discard(symbol)
        self._daily_pnl += pnl_rs
        self.equity     += pnl_rs
        self.peak_equity = max(self.peak_equity, self.equity)

        logger.info(
            "[TRADE CLOSE] %s %s @ %.2f → %.2f | PnL=%.0f Rs | equity=%.0f",
            symbol, record.direction, record.entry, exit_price,
            pnl_rs, self.equity,
        )

        # ── Circuit-breaker checks ─────────────────────────────────────────
        self._check_circuit_breakers()
        return pnl_rs

    # ─────────────────────────────────────────
    # DAILY RESET
    # ─────────────────────────────────────────
    def reset_daily(self, new_date: date | None = None) -> None:
        """Call at market open each day to reset daily counters."""
        self._daily_trades     = 0
        self._daily_pnl        = 0.0
        self._trading_date     = new_date or date.today()
        self._day_halted       = False
        self._day_halt_reason  = ""
        # System-level halt persists across days (manual reset required)
        logger.info("Daily reset | equity=%.0f | date=%s", self.equity, self._trading_date)

    def resume_system(self, reason: str = "manual") -> None:
        """Manually clear the system-level kill switch."""
        if self._system_halted:
            logger.warning("System resuming from halt. Reason: %s", reason)
            self._system_halted = False
            self._halt_reason   = ""

    # ─────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────
    def _check_circuit_breakers(self) -> None:
        # Daily loss limit
        if not self._day_halted:
            daily_pct = self._daily_pnl / max(self.equity, 1.0)
            if daily_pct <= StrategyConfig.DAILY_LOSS_LIMIT:
                self._day_halted      = True
                self._day_halt_reason = (
                    f"DAILY_LOSS_LIMIT hit: {daily_pct*100:.2f}% "
                    f"<= {StrategyConfig.DAILY_LOSS_LIMIT*100:.1f}%"
                )
                logger.warning("DAY HALTED: %s", self._day_halt_reason)

        # Drawdown kill switch
        if not self._system_halted:
            dd = self.drawdown()
            if dd <= StrategyConfig.DRAWDOWN_KILL:
                self._system_halted = True
                self._halt_reason   = (
                    f"DRAWDOWN_KILL hit: {dd*100:.2f}% "
                    f"<= {StrategyConfig.DRAWDOWN_KILL*100:.1f}%"
                )
                logger.critical("SYSTEM HALTED: %s", self._halt_reason)

    def _find_open_record(self, symbol: str) -> TradeRecord | None:
        for r in reversed(self._trade_log):
            if r.symbol == symbol and r.exit is None:
                return r
        return None

    # ─────────────────────────────────────────
    # STATISTICS
    # ─────────────────────────────────────────
    def performance_report(self) -> dict:
        """Aggregate statistics over all closed trades."""
        closed = [r for r in self._trade_log if r.pnl is not None]
        if not closed:
            return {"error": "no closed trades"}

        pnls  = [r.pnl for r in closed]
        wins  = [p for p in pnls if p > 0]
        losses= [p for p in pnls if p < 0]

        return {
            "total_trades"  : len(closed),
            "wins"          : len(wins),
            "losses"        : len(losses),
            "win_rate"      : round(len(wins) / len(closed), 4),
            "profit_factor" : round(sum(wins) / abs(sum(losses)), 4) if losses else 999.0,
            "total_pnl_rs"  : round(sum(pnls), 2),
            "avg_win_rs"    : round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss_rs"   : round(sum(losses) / len(losses), 2) if losses else 0,
            "current_equity": round(self.equity, 2),
            "peak_equity"   : round(self.peak_equity, 2),
            "max_drawdown"  : round(self.drawdown() * 100, 2),
            "return_pct"    : round((self.equity / StrategyConfig.CAPITAL_INITIAL - 1) * 100, 2),
        }
