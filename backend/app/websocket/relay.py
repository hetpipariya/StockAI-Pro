"""
WebSocket relay — manages all client connections with per-user isolation.
Per-client symbol subscriptions.
Rate-limited (100ms throttle) per symbol with safe parallel broadcast.
Thread-safe broadcast via SocketManager singleton.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)

THROTTLE_MS = 100
_last_push: dict[str, float] = {}
_last_tick: dict[str, dict] = {}


class SocketManager:
    """
    Manages all connected WebSocket clients with per-user isolation.
    Supports per-client symbol subscriptions — clients only receive
    ticks for symbols they subscribed to.
    """

    def __init__(self):
        # client_id → WebSocket
        self._connections: dict[str, WebSocket] = {}
        # client_id → user_id
        self._user_map: dict[str, int] = {}
        # client_id → set of subscribed symbols
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int) -> str:
        client_id = str(uuid.uuid4())[:8]
        async with self._lock:
            self._connections[client_id] = websocket
            self._user_map[client_id] = user_id
        logger.info(
            f"[SocketManager] Connected: client={client_id} user={user_id} "
            f"total={len(self._connections)}"
        )
        return client_id

    async def disconnect(self, client_id: str):
        async with self._lock:
            self._connections.pop(client_id, None)
            self._user_map.pop(client_id, None)
            self._subscriptions.pop(client_id, None)
        logger.info(
            f"[SocketManager] Disconnected: client={client_id} "
            f"total={len(self._connections)}"
        )

    async def subscribe(self, client_id: str, symbols: list[str]):
        self._subscriptions[client_id].update(s.upper() for s in symbols)
        logger.debug(f"[SocketManager] client={client_id} subscribed={symbols}")

    async def unsubscribe(self, client_id: str, symbols: list[str]):
        for s in symbols:
            self._subscriptions[client_id].discard(s.upper())

    async def broadcast_tick(self, symbol: str, payload: dict):
        """
        Send tick only to clients subscribed to this symbol.
        Silently removes disconnected clients.
        """
        if not self._connections:
            return

        symbol_upper = symbol.upper()

        # Find clients subscribed to this symbol
        targets = [
            (cid, ws)
            for cid, ws in self._connections.items()
            if symbol_upper in self._subscriptions.get(cid, set())
        ]

        if not targets:
            return

        raw = json.dumps(payload)
        dead_clients = []

        for client_id, ws in targets:
            try:
                await asyncio.wait_for(ws.send_text(raw), timeout=2.0)
                logger.debug(f"[WS] Sent tick to client={client_id} symbol={symbol_upper}")
            except Exception:
                dead_clients.append(client_id)

        for cid in dead_clients:
            await self.disconnect(cid)

    async def broadcast_to_all(self, payload: dict):
        """Broadcast to ALL connected clients (market status, heartbeats, etc.)."""
        if not self._connections:
            return

        raw = json.dumps(payload)
        dead = []
        for cid, ws in list(self._connections.items()):
            try:
                await asyncio.wait_for(ws.send_text(raw), timeout=2.0)
            except Exception:
                dead.append(cid)
        for cid in dead:
            await self.disconnect(cid)

    def get_client_count(self) -> int:
        return len(self._connections)

    def get_stats(self) -> dict:
        return {
            "total_connections": len(self._connections),
            "total_subscriptions": sum(
                len(subs) for subs in self._subscriptions.values()
            ),
        }


# Module-level singleton
socket_manager = SocketManager()


# ─── Backward-compatible functions used by server.py ──────────────────
# These wrap socket_manager for code that still calls the old API.


def register_client(ws: WebSocket):
    """Legacy compat — registers without user isolation. Deprecated."""
    pass  # Now handled by socket_manager.connect() in the WS handler


def unregister_client(ws: WebSocket):
    """Legacy compat — disconnects. Deprecated."""
    pass  # Now handled by socket_manager.disconnect() in the WS handler


def get_client_count() -> int:
    return socket_manager.get_client_count()


async def broadcast_tick(symbol: str, tick: dict):
    """Broadcast a raw tick — throttled + deduplicated, then forwarded to SocketManager."""
    now = datetime.utcnow().timestamp()
    key = f"tick:{symbol}"

    # DEDUPLICATE: Only broadcast if price or volume actually changed
    last_tick = _last_tick.get(symbol)
    if last_tick:
        if (last_tick.get("ltp") == tick.get("ltp") and
                last_tick.get("volume") == tick.get("volume")):
            return

    # THROTTLE: Check timing
    if key in _last_push and (now - _last_push[key]) * 1000 < THROTTLE_MS:
        _last_tick[symbol] = tick
        return

    _last_push[key] = now
    _last_tick[symbol] = tick

    # Periodic cleanup: remove stale throttle entries (older than 5 minutes)
    if len(_last_push) > 50:
        stale = [k for k, v in _last_push.items() if (now - v) > 300]
        for k in stale:
            _last_push.pop(k, None)
            sym = k.replace("tick:", "")
            _last_tick.pop(sym, None)

    msg = {
        "type": "tick",
        "symbol": symbol,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ltp": tick.get("ltp"),
        "bid": tick.get("bid", tick.get("ltp")),
        "ask": tick.get("ask", tick.get("ltp")),
        "volume": tick.get("volume", 0),
        "signal": tick.get("signal", "HOLD"),
        "data_source": tick.get("data_source", "UNKNOWN"),
        "is_mock": bool(tick.get("is_mock", False)),
        "unavailable": bool(tick.get("unavailable", False)),
    }

    await socket_manager.broadcast_tick(symbol, msg)


async def broadcast_candle(symbol: str, candle: dict):
    """Broadcast a completed 1m candle to subscribed clients."""
    msg = {
        "type": "candle_update",
        "symbol": symbol,
        "timestamp": candle.get("time"),
        "open": candle.get("open"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "close": candle.get("close"),
        "volume": candle.get("volume", 0),
    }
    await socket_manager.broadcast_tick(symbol, msg)


async def broadcast_status(connected: bool, detail: str = ""):
    """Broadcast connection status to all clients."""
    msg = {
        "type": "status",
        "connected": connected,
        "detail": detail,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    await socket_manager.broadcast_to_all(msg)
