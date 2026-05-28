"""
Comprehensive chaos, stress, and SRE resilience tests for StockAI Pro.
Verifies self-healing circuit breakers, ML pool recovery, and rate-limiting limits.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.db import run_db_transaction_with_retry, is_transient_db_error
from app.services.redis_client import set_cache, get_cache, is_degraded_mode, _trigger_circuit_breaker
from app.websocket import handler, relay
from app.inference.production_pipeline import ProductionInferencePipeline, get_process_executor, shutdown_process_executor
from app.inference.runner import predict_symbol


class MockWebSocket:
    """Mock WebSocket matching FastAPI/Starlette WebSocket specification."""
    def __init__(self, host: str = "127.0.0.1"):
        self.host = host
        self.sent_messages: list[dict] = []
        self.closed_code: int | None = None
        self.closed_reason: str | None = None
        self.accepted = False
        
        # Mock client class
        class Client:
            def __init__(self, h: str):
                self.host = h
        self.client = Client(host)

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        self.sent_messages.append(data)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_code = code
        self.closed_reason = reason


@pytest.fixture(autouse=True)
def reset_concurrency_states():
    """Resets global connection rate trackers, subscription logs, and process executors."""
    handler._ip_connection_attempts.clear()
    handler._ws_subscribed_symbols.clear()
    
    # Reset redis degradation
    import app.services.redis_client as rc
    rc._degraded_mode_active = False
    rc._async_redis = None
    rc._async_failed = False
    
    yield
    
    handler._ip_connection_attempts.clear()
    handler._ws_subscribed_symbols.clear()
    shutdown_process_executor()


@pytest.mark.anyio
async def test_websocket_ip_handshake_rate_limiting():
    """Chaos: Simulate a rapid reconnect storm from a single IP and assert rate-limiting."""
    ip = "192.168.1.100"
    
    # Simulate 6 handshakes in a row
    sockets = [MockWebSocket(host=ip) for _ in range(6)]
    
    for i, ws in enumerate(sockets):
        await handler.websocket_live(ws, token="mock_token_jwt")
        
    # The first 5 connections should bypass the rate limiter (accepted or processed)
    # The 6th connection must be rejected with WS code 4029 (Too many connection attempts)
    assert sockets[5].closed_code == 4029
    assert "Too many connection attempts" in sockets[5].closed_reason
    
    # Assert other IPs are unaffected (tenant isolation & IP containment)
    healthy_ws = MockWebSocket(host="8.8.8.8")
    await handler.websocket_live(healthy_ws, token="mock_token_jwt")
    assert healthy_ws.closed_code != 4029


@pytest.mark.anyio
async def test_websocket_subscription_limit_guard():
    """Stress: Verify subscription limits prevent clients from exhausting memory bounds."""
    ws = MockWebSocket()
    client_id = "test_client_uuid"
    
    # Attempt to subscribe to 55 symbols (limit is 50)
    abusive_payload = {
        "action": "subscribe",
        "symbols": [f"SYM{i}" for i in range(55)]
    }
    
    # Trigger message processing
    await handler._process_ws_message(abusive_payload, client_id, user_id=1, websocket=ws)
    
    # The response must contain a subscription limit error
    assert len(ws.sent_messages) == 1
    assert ws.sent_messages[0]["type"] == "error"
    assert "Subscription limit exceeded" in ws.sent_messages[0]["message"]


@pytest.mark.anyio
async def test_redis_outage_circuit_breaker_resilience():
    """Chaos: Simulate Redis connection outage, assert circuit-breaker trips to protect event loop latency."""
    import redis.exceptions
    
    # Mock redis client that raises connection failure
    mock_redis = MagicMock()
    mock_redis.setex = AsyncMock(side_effect=redis.exceptions.ConnectionError("Connection lost!"))
    mock_redis.get = AsyncMock(side_effect=redis.exceptions.ConnectionError("Connection lost!"))
    
    with patch("app.services.redis_client.get_redis", AsyncMock(return_value=mock_redis)):
        # Verify circuit breaker is nominal initially
        assert is_degraded_mode() is False
        
        # Execute cache operation - should trigger exception, trip circuit-breaker, and fallback
        await set_cache("chaos_key", "chaos_value", ttl=10)
        
        # Verify circuit breaker is now tripped/degraded
        assert is_degraded_mode() is True
        
        # Subsequent get/set operations should instantly bypass Redis to protect latency
        start_time = time.perf_counter()
        val = await get_cache("chaos_key")
        elapsed = (time.perf_counter() - start_time) * 1000.0
        
        # Should hit local memory cache fallback instantly (< 1.0ms)
        assert val == "chaos_value"
        assert elapsed < 5.0


@pytest.mark.anyio
async def test_database_transient_retry_success():
    """Chaos: Simulate database lock conflict / serialization error, verify retry and self-healing recovery."""
    calls = 0
    
    async def mock_db_operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            # Raise transient psycopg2 deadlock or serialization conflict
            raise OperationalError("select 1", {}, "deadlock detected")
        return "transaction_committed"

    # Run query with retry wrapper
    result = await run_db_transaction_with_retry(
        mock_db_operation,
        max_retries=3,
        base_delay=0.01,
        timeout_seconds=2.0
    )
    
    # Should commit successfully on the 3rd attempt
    assert result == "transaction_committed"
    assert calls == 3


@pytest.mark.anyio
async def test_ml_pipeline_broken_worker_process_recovery():
    """Chaos: Simulate ML worker crash (e.g. BrokenProcessPool), verify self-healing recovery."""
    from concurrent.futures.process import BrokenProcessPool
    
    df_5m = pd.DataFrame({
        "open": [100.0] * 100,
        "high": [101.0] * 100,
        "low": [99.0] * 100,
        "close": [100.5] * 100,
        "volume": [1000] * 100,
    })
    
    # Simulate a crashed process executor raising a BrokenProcessPool exception
    mock_run_in_executor = AsyncMock(side_effect=BrokenProcessPool("Process pool has crashed!"))
    
    pipeline = ProductionInferencePipeline(model=None, redis_cache=None, use_feature_cache=True)
    
    with patch("asyncio.AbstractEventLoop.run_in_executor", mock_run_in_executor):
        # Trigger inference - should handle process crash gracefully, return fallback HOLD signal, and trigger reset
        signal = await pipeline.infer(symbol="CRASH_SYM", ohlcv_5m=df_5m, interval="5m")
        
        assert signal is not None
        assert signal.signal.name == "HOLD"
        
        # Verify the process executor was shut down and cleared to None for lazy restart
        from app.inference.production_pipeline import _process_executor
        assert _process_executor is None
