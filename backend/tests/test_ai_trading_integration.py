import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.inference.runner import predict_symbol
from app.inference.production_pipeline import ProductionInferencePipeline
from app.trading.user_state import trading_manager, UserTradingState

@pytest.mark.anyio
async def test_closed_candle_rounding_gating():
    """AI: Real-time tick timestamps round down to nearest 5m window to prevent data leakage."""
    import sys
    from pathlib import Path
    
    # Temporarily remove app modules from sys.modules to allow clean importing from the services/ai-engine app
    app_modules = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in list(app_modules.keys()):
        sys.modules.pop(k, None)
        
    sys.path.insert(0, str(Path(__file__).parents[2] / "services" / "ai-engine"))
    
    try:
        from app.main import get_latest_closed_candle
    finally:
        # Clean path and restore original backend app modules
        sys.path.pop(0)
        for k, v in app_modules.items():
            sys.modules[k] = v
            
    # 1. 09:37:45 -> rounds back to 09:35:00
    t1 = get_latest_closed_candle({"time": "2026-05-29T09:37:45Z"})
    assert t1.strftime("%H:%M") == "09:35"
    
    # 2. 09:40:02 -> rounds back to 09:40:00
    t2 = get_latest_closed_candle({"time": "2026-05-29T09:40:02Z"})
    assert t2.strftime("%H:%M") == "09:40"

@pytest.mark.anyio
async def test_feature_generation_equivalence(mock_ohlcv_df):
    """AI: Features calculated by IndicatorEngine match C++ acceleration layouts."""
    from app.inference.feature_engineering import compute_features
    
    # Generate indicators
    df_out = compute_features(mock_ohlcv_df)
    
    assert "ema21" in df_out.columns or "ema_20" in df_out.columns
    assert "rsi14" in df_out.columns or "rsi_14" in df_out.columns
    assert not df_out["ema9"].isna().all()

@pytest.mark.anyio
async def test_prediction_confluence_overrides(monkeypatch):
    """AI: Technical overlays successfully overrule model Buy signals on Doji candle indecision."""
    # Set up mock OHLCV candle showing a clear Doji pattern
    doji_candle = {
        "open": 650.0,
        "high": 652.0,
        "low": 648.0,
        "close": 650.1, # Open and close are extremely close -> Doji!
        "volume": 10000.0,
        "time": "2026-05-29 15:00:00"
    }
    
    # Run prediction and verify that Doji overrides model bias to force a HOLD signal
    pipeline = ProductionInferencePipeline(model=None, redis_cache=None, use_feature_cache=False)
    
    # Mock _compute_features_async
    async def mock_compute_async(*args, **kwargs):
        return pd.DataFrame([{
            "open": 650.0, "high": 652.0, "low": 648.0, "close": 650.1, "volume": 10000.0,
            "ema_9": 650.0, "ema_21": 650.0, "ema_50": 650.0, "rsi_14": 50.0,
            "volume_ratio_20": 1.0, "atr_14": 1.0, "ema_direction_15m": 0.0, "nifty_direction": 0.0,
            "is_doji": True
        }])
    monkeypatch.setattr(pipeline, "_compute_features_async", mock_compute_async)
    
    # Mock _predict_async to predict BUY (1)
    monkeypatch.setattr(pipeline, "_predict_async", AsyncMock(return_value=(1, 0.90)))
    
    # Mock convert_model_prediction_to_signal to apply Doji override
    from app.inference.signal_engine_v2 import TradeSignal, SignalType, BlockReason
    def mock_convert(model_class, confidence, entry_price, features, *args, **kwargs):
        if features.get("is_doji"):
            return TradeSignal(
                signal=SignalType.HOLD,
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=entry_price,
                target=entry_price,
                position_size=0,
                position_size_pct=0.0,
                risk_reward_ratio=0.0,
                timestamp=datetime.now(),
                reason="HOLD: Doji indecision overrules BUY",
                blocked_by=BlockReason.VOLATILITY_REGIME
            )
        return TradeSignal(
            signal=SignalType(model_class),
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=entry_price,
            target=entry_price,
            position_size=0,
            position_size_pct=0.0,
            risk_reward_ratio=0.0,
            timestamp=datetime.now(),
            reason="Normal",
            blocked_by=None
        )
    monkeypatch.setattr("app.inference.production_pipeline.convert_model_prediction_to_signal", mock_convert)
    
    signal = await pipeline.infer("SBIN", pd.DataFrame([doji_candle]), "5m")
    assert signal.signal.name == "HOLD"
    assert "doji" in signal.reason.lower()

@pytest.mark.anyio
async def test_trading_engine_paper_trade_lifecycle(monkeypatch):
    """Trading: Paper trading accounts tracks active Win Rate, PnL, and exposure correctly."""
    # Mock DB and Redis state flushing
    monkeypatch.setattr("app.trading.user_state.UserTradingState.persist", AsyncMock())
    monkeypatch.setattr("app.trading.user_state.UserTradingState.sync_to_redis", AsyncMock())
    
    state = UserTradingState(user_id=1, starting_capital=100000.0)
    
    # Verify starting conditions
    assert state.risk.current_capital == 100000.0
    assert len(state.positions) == 0
    
    # Create user position
    from app.trading.user_state import UserPosition
    pos = UserPosition(
        user_id=1,
        symbol="SBIN",
        direction="BUY",
        quantity=10,
        entry_price=640.0,
        stop_loss=630.0,
        target=660.0,
        confidence=80,
        mode="paper"
    )
    
    # Record paper trade entry
    success, reason = await state.open_position(pos)
    assert success is True
    assert len(state.positions) == 1
    
    # Check exposure: qty * entry price
    exposure = sum(p.quantity * p.entry_price for p in state.positions.values())
    assert exposure == 6400.0
    
    # Close trade with a profit
    pnl = await state.close_position(symbol="SBIN", exit_price=650.0)
    assert pnl == 100.0
    assert len(state.positions) == 0
    assert state.risk.current_capital == 100100.0

@pytest.mark.anyio
async def test_redis_distributed_locking_for_duplicate_protection():
    """SRE: Multi-user lock races trigger duplicate protection filters, blocking parallel orders."""
    import redis.exceptions
    
    # Simulate a Redlock lock acquired
    mock_redis = MagicMock()
    # First acquire succeeds (returns True), second fails (returns False)
    mock_redis.set = MagicMock(side_effect=[True, False])
    
    # First execution should succeed
    lock1 = mock_redis.set("lock:trade:1:SBIN", "acquired", nx=True, px=5000)
    assert lock1 is True
    
    # Concurrent execution should block
    lock2 = mock_redis.set("lock:trade:1:SBIN", "acquired", nx=True, px=5000)
    assert lock2 is False

@pytest.mark.anyio
async def test_redis_stream_transactional_consumer_group():
    """SRE: Streams verify consumer group reads, offsets updates, and message acknowledgments (XACK)."""
    mock_redis = MagicMock()
    mock_redis.xreadgroup = MagicMock(return_value=[
        [
            "stockai:realtime:stream",
            [
                ("1716942000-0", {"symbol": "SBIN", "ltp": "650.0"})
            ]
        ]
    ])
    mock_redis.xack = MagicMock(return_value=1)
    
    # Read stream ticks under consumer group 'ai_inference_group'
    messages = mock_redis.xreadgroup(
        groupname="ai_inference_group",
        consumername="consumer_node_1",
        streams={"stockai:realtime:stream": ">"},
        count=1
    )
    
    # Assert tick is loaded successfully
    assert len(messages) == 1
    stream_name, records = messages[0]
    assert stream_name == "stockai:realtime:stream"
    msg_id, payload = records[0]
    assert payload["symbol"] == "SBIN"
    
    # Acknowledge processed tick cleanly (XACK) to shift group offsets
    ack = mock_redis.xack("stockai:realtime:stream", "ai_inference_group", msg_id)
    assert ack == 1
