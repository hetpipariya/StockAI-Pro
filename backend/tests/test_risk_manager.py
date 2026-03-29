"""
Tests for the RiskManager — position sizing, daily limits, trade caps.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.trading.risk_manager import RiskManager, TradeRisk


class TestRiskManagerBasics:
    """Test basic risk calculations."""

    def test_initial_capital(self):
        rm = RiskManager(starting_capital=100_000)
        assert rm.capital == 100_000

    def test_can_trade_initially(self):
        rm = RiskManager()
        can, reason = rm.can_trade()
        assert can is True
        assert reason == "OK"

    def test_position_size_1pct_risk(self):
        """1% of 100k = 1000 risk. With ATR=10 and mult=1.5, stop_dist=15.
        Shares = 1000 / 15 = 66."""
        rm = RiskManager(starting_capital=100_000, risk_per_trade_pct=0.01,
                         atr_stop_multiplier=1.5)
        trade = rm.calculate_trade("RELIANCE", "BUY", 1000.0, atr=10.0)
        assert trade is not None
        assert trade.position_size == 66  # 1000 / 15 = 66.67 -> 66
        assert trade.risk_amount == 1000.0

    def test_stop_loss_for_buy(self):
        rm = RiskManager(atr_stop_multiplier=1.5)
        trade = rm.calculate_trade("TEST", "BUY", 100.0, atr=2.0)
        assert trade is not None
        assert trade.stop_price == 97.0  # 100 - 1.5*2 = 97
        assert trade.target_price == 104.5  # 100 + 1.5*2*1.5 = 104.5

    def test_stop_loss_for_sell(self):
        rm = RiskManager(atr_stop_multiplier=1.5)
        trade = rm.calculate_trade("TEST", "SELL", 100.0, atr=2.0)
        assert trade is not None
        assert trade.stop_price == 103.0  # 100 + 1.5*2 = 103
        assert trade.target_price == 95.5  # 100 - 1.5*2*1.5 = 95.5

    def test_zero_atr_returns_none(self):
        rm = RiskManager()
        trade = rm.calculate_trade("TEST", "BUY", 100.0, atr=0)
        assert trade is None

    def test_zero_price_returns_none(self):
        rm = RiskManager()
        trade = rm.calculate_trade("TEST", "BUY", 0, atr=1.0)
        assert trade is None


class TestRiskManagerDailyLimits:
    """Test daily loss limits and trade caps."""

    def test_max_trades_per_day(self):
        rm = RiskManager(max_trades_per_day=3)
        for _ in range(3):
            rm.on_trade_opened()
        can, reason = rm.can_trade()
        assert can is False
        assert "Max trades" in reason

    def test_max_concurrent_positions(self):
        rm = RiskManager(max_concurrent_positions=2)
        rm.on_trade_opened()
        rm.on_trade_opened()
        can, reason = rm.can_trade()
        assert can is False
        assert "Max concurrent" in reason

    def test_closing_position_frees_slot(self):
        rm = RiskManager(max_concurrent_positions=2)
        rm.on_trade_opened()
        rm.on_trade_opened()
        can, _ = rm.can_trade()
        assert can is False

        rm.on_trade_closed(pnl=100.0)
        can, _ = rm.can_trade()
        assert can is True

    def test_daily_loss_halt(self):
        rm = RiskManager(
            starting_capital=100_000,
            daily_loss_limit_pct=0.03,
            max_concurrent_positions=10,
        )
        # Simulate losing 3100 (> 3% of 100k)
        rm.on_trade_opened()
        rm.on_trade_closed(pnl=-3100.0)
        assert rm.is_halted is True
        can, reason = rm.can_trade()
        assert can is False
        assert "HALTED" in reason

    def test_capital_tracks_pnl(self):
        rm = RiskManager(starting_capital=100_000)
        rm.on_trade_opened()
        rm.on_trade_closed(pnl=500.0)
        assert rm.capital == 100_500.0

        rm.on_trade_opened()
        rm.on_trade_closed(pnl=-200.0)
        assert rm.capital == 100_300.0


class TestRiskManagerEdgeCases:
    """Test edge cases and safety checks."""

    def test_position_size_exceeds_capital(self):
        """If shares * price > capital, cap shares."""
        rm = RiskManager(starting_capital=1000, risk_per_trade_pct=0.10, min_account_balance=0)
        trade = rm.calculate_trade("TEST", "BUY", 500.0, atr=1.0)
        assert trade is not None
        # Risk = 100, stop_dist = 1.5, shares = 100/1.5 = 66
        # Cost = 66 * 500 = 33000 > 1000 → shares = 1000/500 = 2
        assert trade.position_size == 2

    def test_very_high_atr_small_position(self):
        """High ATR means large stop_dist → fewer shares."""
        rm = RiskManager(starting_capital=100_000)
        trade = rm.calculate_trade("TEST", "BUY", 100.0, atr=50.0)
        assert trade is not None
        # stop_dist = 1.5 * 50 = 75, risk = 1000, shares = 1000/75 = 13
        assert trade.position_size == 13

    def test_negative_atr_returns_none(self):
        rm = RiskManager()
        trade = rm.calculate_trade("TEST", "BUY", 100.0, atr=-5.0)
        assert trade is None

    def test_trade_risk_dataclass_fields(self):
        rm = RiskManager()
        trade = rm.calculate_trade("RELIANCE", "BUY", 2500.0, atr=10.0)
        assert trade is not None
        assert trade.symbol == "RELIANCE"
        assert trade.direction == "BUY"
        assert isinstance(trade.entry_price, float)
        assert isinstance(trade.stop_price, float)
        assert isinstance(trade.target_price, float)
        assert isinstance(trade.position_size, int)
        assert isinstance(trade.risk_amount, float)
        assert isinstance(trade.reward_amount, float)
        assert isinstance(trade.atr, float)

    def test_get_status_returns_dict(self):
        rm = RiskManager(starting_capital=50_000)
        status = rm.get_status()
        assert status["capital"] == 50_000
        assert status["trades_today"] == 0
        assert status["open_positions"] == 0
        assert status["halted"] is False
