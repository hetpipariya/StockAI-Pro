"""
Tests for the hardened trading engine — state reload, safety checks,
order lifecycle, trade logging, and kill-switch.
"""
import pytest
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestRiskManagerPersistence:
    """Test that RiskManager correctly persists and restores state from DB."""

    def test_persist_state_creates_daily_risk_row(self):
        """After on_trade_opened, state should be persisted."""
        from app.trading.risk_manager import RiskManager

        rm = RiskManager(starting_capital=100_000)
        # Mock the DB session to verify persist is called
        with patch("app.services.db.get_sync_db_session") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value = iter([mock_session])
            mock_session.query.return_value.filter_by.return_value.first.return_value = None

            rm.on_trade_opened()
            # Verify session.add was called (new DailyRiskState row)
            assert mock_session.add.called
            assert mock_session.commit.called

    def test_load_from_db_restores_capital(self):
        """load_from_db should restore capital and trade counts."""
        from app.trading.risk_manager import RiskManager

        rm = RiskManager(starting_capital=100_000)

        with patch("app.services.db.get_sync_db_session") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value = iter([mock_session])

            # Mock DailyRiskState row
            mock_risk_state = MagicMock()
            mock_risk_state.starting_capital = 100_000
            mock_risk_state.current_capital = 97_500
            mock_risk_state.trades_today = 3
            mock_risk_state.halted = False

            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_risk_state
            mock_session.query.return_value.count.return_value = 2

            rm.load_from_db()

            assert rm.capital == 97_500
            assert rm._trades_today == 3
            assert rm._open_positions == 2


class TestRiskManagerSafety:
    """Test enhanced safety checks."""

    def test_min_balance_blocks_trading(self):
        """When capital drops below min_balance, trading should be halted."""
        from app.trading.risk_manager import RiskManager

        # Set capital just barely above min, with loose daily loss limit so it doesn't halt from that
        rm = RiskManager(starting_capital=11_000, min_account_balance=10_000, daily_loss_limit_pct=0.99)
        # Lose enough to drop below min_balance but not trigger daily loss limit
        rm.on_trade_opened()
        rm.on_trade_closed(pnl=-2000.0)
        # Capital = 9000, below min of 10000
        can, reason = rm.can_trade()
        assert can is False
        assert "minimum balance" in reason

    def test_kill_switch_blocks_trading(self):
        """When TRADING_ENABLED is False, can_trade should return False."""
        from app.trading.risk_manager import RiskManager

        rm = RiskManager(starting_capital=100_000)
        with patch("app.trading.risk_manager.config") as mock_config:
            mock_config.TRADING_ENABLED = False
            mock_config.MAX_RISK_PER_TRADE_PCT = 0.01
            mock_config.STARTING_CAPITAL = 100_000
            mock_config.MIN_ACCOUNT_BALANCE = 10_000
            mock_config.MAX_TRADES_PER_DAY = 10
            mock_config.MAX_CONCURRENT_POSITIONS = 3
            mock_config.DAILY_LOSS_LIMIT_PCT = 0.03
            can, reason = rm.can_trade()
            assert can is False
            assert "Kill-switch" in reason

    def test_status_includes_safety_fields(self):
        """get_status should include trading_enabled and trading_mode."""
        from app.trading.risk_manager import RiskManager

        rm = RiskManager(starting_capital=50_000)
        status = rm.get_status()
        assert "trading_enabled" in status
        assert "trading_mode" in status
        assert "min_account_balance" in status


class TestOrderRouterSafety:
    """Test order router safety gates."""

    def test_router_forces_paper_when_live_not_confirmed(self):
        """LIVE mode should downgrade to PAPER if LIVE_CONFIRMED is False."""
        with patch("app.connectors.order_router.config") as mock_config:
            mock_config.TRADING_ENABLED = True
            mock_config.TRADING_MODE = "LIVE"
            mock_config.LIVE_CONFIRMED = False

            from app.connectors.order_router import OrderRouter
            router = OrderRouter(mode="LIVE")
            assert router.mode == "PAPER"

    def test_kill_switch_blocks_order_placement(self):
        """When kill-switch is active, place_order should return REJECTED."""
        with patch("app.connectors.order_router.config") as mock_config:
            mock_config.TRADING_ENABLED = False
            mock_config.TRADING_MODE = "PAPER"
            mock_config.LIVE_CONFIRMED = False

            with patch("app.connectors.order_router.log_trade"):
                from app.connectors.order_router import OrderRouter
                router = OrderRouter(mode="PAPER")
                result = router.place_order(
                    symbol="TEST", direction="BUY", quantity=10,
                    price=100.0, stop_loss=95.0, target=110.0
                )
                assert result.status == "REJECTED"
                assert "Kill-switch" in result.error


class TestTradeLogger:
    """Test structured trade logging."""

    def test_log_trade_writes_jsonl(self):
        """log_trade should append to the JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_trades.jsonl"

            with patch("app.trading.trade_logger._TRADE_LOG_FILE", log_file):
                with patch("app.trading.trade_logger._write_db"):
                    from app.trading.trade_logger import log_trade

                    log_trade(
                        "SIGNAL", order_id="TEST-001", symbol="RELIANCE",
                        direction="BUY", quantity=10, price=2500.0,
                        confidence=75, reason="ML=UP", mode="PAPER",
                    )

                    assert log_file.exists()
                    lines = log_file.read_text().strip().split("\n")
                    assert len(lines) == 1

                    entry = json.loads(lines[0])
                    assert entry["event"] == "SIGNAL"
                    assert entry["symbol"] == "RELIANCE"
                    assert entry["direction"] == "BUY"
                    assert entry["confidence"] == 75

    def test_log_trade_includes_optional_fields(self):
        """Signal metadata (atr, rsi, ml_prediction) should be included when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test_trades2.jsonl"

            with patch("app.trading.trade_logger._TRADE_LOG_FILE", log_file):
                with patch("app.trading.trade_logger._write_db"):
                    from app.trading.trade_logger import log_trade

                    log_trade(
                        "SIGNAL", order_id="TEST-002", symbol="TCS",
                        direction="SELL", quantity=5, price=3400.0,
                        atr=15.5, rsi=32.1, ml_prediction=0,
                        mode="PAPER",
                    )

                    entry = json.loads(log_file.read_text().strip())
                    assert entry["atr"] == 15.5
                    assert entry["rsi"] == 32.1
                    assert entry["ml_prediction"] == 0


class TestConfigValues:
    """Test config loading."""

    def test_trading_safety_defaults(self):
        """Default config values should be safe."""
        from app.config import (
            TRADING_MODE, TRADING_ENABLED, LIVE_CONFIRMED,
            STARTING_CAPITAL, MIN_ACCOUNT_BALANCE, MAX_RISK_PER_TRADE_PCT,
        )
        assert TRADING_MODE == "PAPER"
        assert LIVE_CONFIRMED is False  # Default must be False for safety
        assert STARTING_CAPITAL == 100_000
        assert MIN_ACCOUNT_BALANCE == 10_000
        assert MAX_RISK_PER_TRADE_PCT == 0.01


class TestOrderLifecycle:
    """Test strict order state machine transitions."""

    def test_confirm_rejects_non_pending_order(self):
        """confirm_and_execute should reject orders not in PENDING_CONFIRMATION state."""
        with patch("app.connectors.order_router.config") as mock_config:
            mock_config.TRADING_ENABLED = True
            mock_config.TRADING_MODE = "PAPER"
            mock_config.LIVE_CONFIRMED = False

            with patch("app.connectors.order_router.get_sync_db_session") as mock_db:
                mock_session = MagicMock()
                mock_db.return_value = iter([mock_session])

                # Mock order already FILLED
                mock_order = MagicMock()
                mock_order.status = "FILLED"
                mock_order.order_id = "TEST-123"
                mock_session.query.return_value.filter_by.return_value.first.return_value = mock_order

                from app.connectors.order_router import OrderRouter
                router = OrderRouter(mode="PAPER")
                result = router.confirm_and_execute("TEST-123")
                assert result is None  # Should reject
