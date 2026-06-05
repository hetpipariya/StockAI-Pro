import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.websockets import WebSocketDisconnect

from app.websocket.relay import SocketManager
from app.websocket.handler import _resolve_websocket_user_id, _normalize_watchlist_price
from app.services.redis_client import is_degraded_mode

class MockWebSocket:
    """Mock WebSocket matching FastAPI/Starlette specification."""
    def __init__(self, host: str = "127.0.0.1", query_params=None):
        self.host = host
        self.query_params = query_params or {}
        self.messages = []
        self.closed_code = None
        self.closed_reason = None
        self.accepted = False
        
        class Client:
            def __init__(self, h: str):
                self.host = h
        self.client = Client(host)

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        self.messages.append(data)

    async def send_text(self, raw: str):
        import json
        self.messages.append(json.loads(raw))

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_code = code
        self.closed_reason = reason

@pytest.mark.anyio
async def test_ws_connection_auth_handshake_success(monkeypatch):
    """Success: Valid JWT token in connection handshake is accepted."""
    monkeypatch.setattr("app.utils.auth_utils.decode_access_token", lambda token: {"sub": "1", "email": "trader@desk.com"})
    monkeypatch.setattr("app.services.redis_client.get_cache", AsyncMock(return_value=1)) # return cached user id
    
    user_id = await _resolve_websocket_user_id("valid_token")
    assert user_id == 1

@pytest.mark.anyio
async def test_ws_room_subscription_bounds(monkeypatch):
    """Limit: Subscribing to more than 50 symbols triggers immediate warning and bounds block."""
    from app.websocket.handler import _process_ws_message
    
    manager = SocketManager()
    ws = MockWebSocket()
    
    client_id = await manager.connect(ws, user_id=1)
    
    # Verify manager.subscribe returns None as designed
    res = await manager.subscribe(client_id, ["SBIN"])
    assert res is None
    
    # Try to subscribe to 60 symbols via _process_ws_message
    symbols = [f"SYM_{i}" for i in range(60)]
    await _process_ws_message({"action": "subscribe", "symbols": symbols}, client_id, 1, ws)
    
    # Verify subscription is capped/fails or triggers warnings
    assert len(ws.messages) == 1
    assert "limit" in ws.messages[0]["message"].lower()

@pytest.mark.anyio
async def test_ws_reconnect_subscription_restore():
    """Grace: Reconnecting within the grace window successfully restores active symbol monitors."""
    manager = SocketManager()
    ws1 = MockWebSocket()
    ws2 = MockWebSocket()
    
    client_id1 = await manager.connect(ws1, user_id=77)
    await manager.subscribe(client_id1, ["sbin", "reliance"])
    await manager.disconnect(client_id1)
    
    # Connect a second socket to trigger the restore
    client_id2 = await manager.connect(ws2, user_id=77)
    
    # Verify symbol is stored in reconnect register cache
    restored = manager.pop_restored_symbols(client_id2)
    assert set(restored) == {"SBIN", "RELIANCE"}

@pytest.mark.anyio
async def test_pubsub_broadcast_normalises_ticks():
    """Broadcast: Interservice relays normalise paise values (e.g. multiplying Indian Equity tick fractions)."""
    # Verify normalisation: 134810.0 paise -> 1348.10 Rs
    ltp = _normalize_watchlist_price("RELIANCE", 134810.0, 0.0)
    assert ltp == 1348.1
