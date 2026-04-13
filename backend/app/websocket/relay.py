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
                logger.debug(
                    f"[WS] Sent tick to client={client_id} symbol={symbol_upper}"
                )
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
    is_mock = bool(tick.get("is_mock", False))

    # DEDUPLICATE: Only broadcast if price or volume actually changed
    if not is_mock:
        last_tick = _last_tick.get(symbol)
        if last_tick:
            if last_tick.get("ltp") == tick.get("ltp") and last_tick.get(
                "volume"
            ) == tick.get("volume"):
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
        "unavailable": bool(tick.get("unavailable", False)),
        "is_mock": is_mock,
        "mock_reason": tick.get("mock_reason", ""),
    }

    await socket_manager.broadcast_tick(symbol, msg)


async def broadcast_candle(symbol: str, candle: dict):
    """Broadcast a completed candle to subscribed clients."""
    msg = {
        "type": "candle_update",
        "symbol": symbol,
        "timeframe": candle.get("timeframe", "1m"),
        "timestamp": candle.get("time"),
        "open": candle.get("open"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "close": candle.get("close"),
        "volume": candle.get("volume", 0),
        "data_source": candle.get("data_source", "NSE_API"),
    }
    await socket_manager.broadcast_tick(symbol, msg)


async def broadcast_signal(symbol: str, signal_payload: dict):
    """Broadcast latest signal update for a symbol to subscribed clients."""
    confidence = signal_payload.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.0

    if confidence > 1.0:
        confidence = confidence / 100.0
    confidence = max(0.0, min(1.0, confidence))

    msg = {
        "type": "signal_update",
        "symbol": symbol,
        "signal": str(signal_payload.get("signal", "HOLD")).upper(),
        "confidence": round(confidence, 4),
        "confidence_pct": int(round(confidence * 100.0)),
        "momentum_score": signal_payload.get("momentum_score", 0.5),
        "trend_score": signal_payload.get("trend_score", 0.5),
        "volatility_score": signal_payload.get("volatility_score", 0.5),
        "volatility_state": signal_payload.get("volatility_state", "MISSING"),
        "volume_score": signal_payload.get("volume_score", 0.5),
        "price_action_score": signal_payload.get("price_action_score", 0.5),
        "candle_type": signal_payload.get("candle_type", "NEUTRAL"),
        "engulfing": signal_payload.get("engulfing", "NONE"),
        "doji": signal_payload.get("doji", False),
        "candle_strength": signal_payload.get("candle_strength", "MODERATE"),
        "body_strength_score": signal_payload.get("body_strength_score", 0.5),
        "upper_wick_pct": signal_payload.get("upper_wick_pct", 0.0),
        "lower_wick_pct": signal_payload.get("lower_wick_pct", 0.0),
        "streak_strength_score": signal_payload.get("streak_strength_score", 0.0),
        "consecutive_green": signal_payload.get("consecutive_green", 0),
        "consecutive_red": signal_payload.get("consecutive_red", 0),
        "rsi_macd_signal": signal_payload.get("rsi_macd_signal", 0),
        "rsi_macd_strength": signal_payload.get("rsi_macd_strength", 0.0),
        "ema_crossover_signal": signal_payload.get("ema_crossover_signal", 0),
        "ema_crossover_strength": signal_payload.get("ema_crossover_strength", 0.0),
        "rsi_divergence": signal_payload.get("rsi_divergence", 0),
        "divergence_strength": signal_payload.get("divergence_strength", 0.0),
        "macd_histogram_trend": signal_payload.get("macd_histogram_trend", 0),
        "macd_momentum_strength": signal_payload.get("macd_momentum_strength", 0.0),
        "fusion_score": signal_payload.get("fusion_score", 0.0),
        "structure_score": signal_payload.get("structure_score", 0.5),
        "structure": signal_payload.get("structure", "NEUTRAL"),
        "last_pattern": signal_payload.get("last_pattern", "NONE"),
        "support_levels": signal_payload.get("support_levels", []),
        "resistance_levels": signal_payload.get("resistance_levels", []),
        "nearest_support": signal_payload.get("nearest_support", 0.0),
        "nearest_resistance": signal_payload.get("nearest_resistance", 0.0),
        "support_distance": signal_payload.get("support_distance", 1.0),
        "resistance_distance": signal_payload.get("resistance_distance", 1.0),
        "breakout": signal_payload.get("breakout", False),
        "breakout_type": signal_payload.get("breakout_type", "NONE"),
        "range_or_trend": signal_payload.get("range_or_trend", "RANGE"),
        "volume_ratio": signal_payload.get("volume_ratio", 1.0),
        "volume_ratio_flag": signal_payload.get("volume_ratio_flag", "NORMAL"),
        "volume_spike": signal_payload.get("volume_spike", False),
        "volume_spike_strength": signal_payload.get("volume_spike_strength", 0.0),
        "vwap_deviation": signal_payload.get("vwap_deviation", 0.0),
        "vwap_bias": signal_payload.get("vwap_bias", "NEUTRAL"),
        "obv_slope": signal_payload.get("obv_slope", 0.0),
        "obv_divergence": signal_payload.get("obv_divergence", False),
        "volume_trend_slope": signal_payload.get("volume_trend_slope", 0.0),
        "volume_trend_direction": signal_payload.get("volume_trend_direction", "FLAT"),
        "position_size_factor": signal_payload.get("position_size_factor", 0.75),
        "mtf_alignment": signal_payload.get("mtf_alignment", "NEUTRAL"),
        "mtf_score": signal_payload.get("mtf_score", 0.0),
        "ema_structure": signal_payload.get("ema_structure", "MIXED STACK"),
        "session": signal_payload.get("session", "MID"),
        "time_bucket": signal_payload.get("time_bucket", "SIDEWAYS"),
        "day_of_week": signal_payload.get("day_of_week", 0),
        "day_bias_score": signal_payload.get("day_bias_score", 0.5),
        "expiry_flag": signal_payload.get("expiry_flag", False),
        "expiry_type": signal_payload.get("expiry_type", "NONE"),
        "time_score": signal_payload.get("time_score", 0.5),
        "time_bias": signal_payload.get("time_bias", "NEUTRAL"),
        "liquidity_score": signal_payload.get("liquidity_score", 0.5),
        "regime_score": signal_payload.get("regime_score", 0.5),
        "risk_score": signal_payload.get("risk_score", 0.5),
        "ai_score": signal_payload.get("ai_score", 0.5),
        "regime_state": signal_payload.get("regime_state", "UNKNOWN"),
        "price_impact": signal_payload.get("price_impact", 0.0),
        "jump_flag": signal_payload.get("jump_flag", False),
        "gap_flag": signal_payload.get("gap_flag", "NO_GAP"),
        "liquidity_sweep": signal_payload.get("liquidity_sweep", False),
        "sweep_type": signal_payload.get("sweep_type", "NONE"),
        "flow_state": signal_payload.get("flow_state", "NEUTRAL"),
        "engines": signal_payload.get("engines", {}),
        "prediction": signal_payload.get("prediction", 0.0),
        "target_price": signal_payload.get("target_price", signal_payload.get("target", 0.0)),
        "stop_loss": signal_payload.get("stop_loss", 0.0),
        "RR": signal_payload.get("RR", 0.0),
        "position_size": signal_payload.get("position_size", 0),
        "regime": signal_payload.get("regime", "Unknown"),
        "reason": signal_payload.get("reason", signal_payload.get("explanation", "")),
        "explanation": signal_payload.get("explanation", ""),
        "data_source": signal_payload.get("data_source", "NSE_API"),
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
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
