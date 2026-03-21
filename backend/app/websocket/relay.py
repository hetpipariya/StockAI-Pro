"""
WebSocket relay — broadcasts real-time ticks and candle updates to connected clients.
Rate-limited (100ms throttle) per symbol with safe parallel broadcast.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Set
from datetime import datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)

THROTTLE_MS = 100
_clients: Set[WebSocket] = set()
_last_push: dict[str, float] = {}


async def broadcast_tick(symbol: str, tick: dict):
    """Broadcast a raw tick to all connected clients (throttled)."""
    now = datetime.utcnow().timestamp()
    key = f"tick:{symbol}"
    if key in _last_push and (now - _last_push[key]) * 1000 < THROTTLE_MS:
        return
    _last_push[key] = now

    # Periodic cleanup: remove stale throttle entries (older than 5 minutes)
    if len(_last_push) > 50:
        stale = [k for k, v in _last_push.items() if (now - v) > 300]
        for k in stale:
            _last_push.pop(k, None)

    msg = {
        "type": "tick",
        "symbol": symbol,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ltp": tick.get("ltp"),
        "bid": tick.get("bid", tick.get("ltp")),
        "ask": tick.get("ask", tick.get("ltp")),
        "volume": tick.get("volume", 0),
        "signal": tick.get("signal", "HOLD"),
    }

    await _broadcast(msg)


async def broadcast_candle(symbol: str, candle: dict):
    """Broadcast a completed 1m candle to all clients."""
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
    await _broadcast(msg)


async def broadcast_status(connected: bool, detail: str = ""):
    """Broadcast connection status to all clients."""
    msg = {
        "type": "status",
        "connected": connected,
        "detail": detail,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    await _broadcast(msg)


async def _send_safe(ws: WebSocket, payload: str) -> bool:
    """Send text to a single client. Returns False if the client is dead."""
    try:
        await asyncio.wait_for(ws.send_text(payload), timeout=2.0)
        return True
    except Exception:
        return False


async def _broadcast(msg: dict):
    """Internal: send JSON to all connected clients in parallel, remove dead ones."""
    if not _clients:
        return
    payload = json.dumps(msg)

    # Send to all clients concurrently
    clients_list = list(_clients)
    if clients_list:
        logger.debug(f"[WS-SEND] Sending payload to {len(clients_list)} clients: {payload[:60]}...")
    results = await asyncio.gather(
        *[_send_safe(ws, payload) for ws in clients_list],
        return_exceptions=True,
    )

    # Remove dead clients
    dead = set()
    for ws, ok in zip(clients_list, results):
        if ok is not True:
            dead.add(ws)

    for ws in dead:
        _clients.discard(ws)
    if dead:
        logger.info(f"[WS] Removed {len(dead)} dead client(s), {len(_clients)} remaining")


def register_client(ws: WebSocket):
    _clients.add(ws)
    logger.info(f"[WS] Client connected — {len(_clients)} total")


def unregister_client(ws: WebSocket):
    _clients.discard(ws)
    logger.info(f"[WS] Client disconnected — {len(_clients)} remaining")


def get_client_count() -> int:
    return len(_clients)
