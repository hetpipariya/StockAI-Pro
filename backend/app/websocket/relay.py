"""
WebSocket relay — manages all client connections with per-user isolation.
Per-client symbol subscriptions.
Rate-limited (100ms throttle) per symbol with safe parallel room-based broadcast.
Thread-safe broadcast via SocketManager singleton.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime
from contextlib import suppress
from typing import Any

from fastapi import WebSocket

from app.services.redis_client import get_cache, get_redis, set_cache

try:
    import orjson
except ImportError:
    orjson = None

import json

logger = logging.getLogger(__name__)

THROTTLE_MS = 100
RECONNECT_GRACE_SECONDS = 10
LATEST_TICK_CACHE_TTL_SECONDS = max(6, int(os.getenv("WS_LATEST_TICK_TTL_SECONDS", "10")))
LATEST_CANDLE_CACHE_TTL_SECONDS = max(15, int(os.getenv("WS_LATEST_CANDLE_TTL_SECONDS", "20")))
LATEST_SIGNAL_CACHE_TTL_SECONDS = max(15, int(os.getenv("WS_LATEST_SIGNAL_TTL_SECONDS", "20")))
LATEST_STATUS_CACHE_TTL_SECONDS = max(10, int(os.getenv("WS_LATEST_STATUS_TTL_SECONDS", "15")))
RELAY_RETRY_SECONDS = max(1.0, float(os.getenv("WS_RELAY_RETRY_SECONDS", "2.0")))
_RELAY_INSTANCE_ID = uuid.uuid4().hex[:12]
_RELAY_CHANNEL_PATTERN = "stockai:realtime:*"
_relay_listener_task: asyncio.Task | None = None
_relay_stop_event: asyncio.Event | None = None
_last_push: dict[str, float] = {}
_last_tick: dict[str, dict] = {}


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    if orjson is not None:
        try:
            return orjson.dumps(value).decode("utf-8")
        except Exception:
            pass
    return json.dumps(value)


def _deserialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if not isinstance(value, str):
        return value
    if orjson is not None:
        try:
            return orjson.loads(value)
        except Exception:
            pass
    try:
        return json.loads(value)
    except Exception:
        return value


def _realtime_channel(kind: str) -> str:
    return f"stockai:realtime:{kind}"


def _latest_cache_key(kind: str, symbol: str | None = None) -> str:
    normalized_symbol = str(symbol or "global").strip().upper() or "GLOBAL"
    return f"stockai:latest:{kind}:{normalized_symbol}"


def _latest_cache_ttl(kind: str) -> int:
    if kind == "tick":
        return LATEST_TICK_CACHE_TTL_SECONDS
    if kind == "candle":
        return LATEST_CANDLE_CACHE_TTL_SECONDS
    if kind == "signal":
        return LATEST_SIGNAL_CACHE_TTL_SECONDS
    return LATEST_STATUS_CACHE_TTL_SECONDS


async def _store_latest_event(kind: str, payload: dict[str, Any]) -> None:
    symbol = str(payload.get("symbol") or "global").strip().upper() or "GLOBAL"
    try:
        await set_cache(_latest_cache_key(kind, symbol), payload, ttl=_latest_cache_ttl(kind))
    except Exception as exc:
        logger.debug("[WS] Latest cache store failed for %s/%s: %s", kind, symbol, exc)


async def _load_latest_event(kind: str, symbol: str) -> dict[str, Any] | None:
    try:
        cached = await get_cache(_latest_cache_key(kind, symbol))
    except Exception as exc:
        logger.debug("[WS] Latest cache load failed for %s/%s: %s", kind, symbol, exc)
        return None
    return cached if isinstance(cached, dict) else None


async def _publish_realtime_event(kind: str, payload: dict[str, Any]) -> None:
    redis_client = await get_redis()
    if redis_client is None:
        return

    envelope = {
        "origin": _RELAY_INSTANCE_ID,
        "payload": payload,
    }

    try:
        await redis_client.publish(_realtime_channel(kind), _serialize(envelope))
    except Exception as exc:
        logger.debug("[WS] Redis publish failed for %s: %s", kind, exc)


async def _relay_realtime_message(kind: str, payload: dict[str, Any]) -> None:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if kind == "status":
        await socket_manager.broadcast_to_all(payload)
        await _store_latest_event(kind, payload)
        return

    if not symbol:
        return

    await socket_manager.broadcast_tick(symbol, payload)
    await _store_latest_event(kind, payload)


async def _redis_relay_listener() -> None:
    stop_event = _relay_stop_event
    if stop_event is None:
        return

    backoff = RELAY_RETRY_SECONDS
    while not stop_event.is_set():
        redis_client = await get_redis()
        if redis_client is None:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 10.0)
            continue

        pubsub = None
        try:
            pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
            await pubsub.psubscribe(_RELAY_CHANNEL_PATTERN)
            logger.info("[WS] Redis relay listener attached to %s", _RELAY_CHANNEL_PATTERN)
            backoff = RELAY_RETRY_SECONDS

            async for message in pubsub.listen():
                if stop_event.is_set():
                    break

                if not isinstance(message, dict):
                    continue

                message_type = str(message.get("type") or "").lower()
                if message_type not in {"message", "pmessage"}:
                    continue

                raw_data = message.get("data")
                if raw_data is None:
                    continue

                if isinstance(raw_data, bytes):
                    raw_text = raw_data.decode("utf-8", errors="ignore")
                else:
                    raw_text = str(raw_data)

                try:
                    envelope = _deserialize(raw_text)
                except Exception:
                    continue

                if not isinstance(envelope, dict):
                    continue

                if str(envelope.get("origin") or "") == _RELAY_INSTANCE_ID:
                    continue

                payload = envelope.get("payload")
                if not isinstance(payload, dict):
                    continue

                channel = str(message.get("channel") or message.get("pattern") or "")
                kind = channel.rsplit(":", 1)[-1].lower() if ":" in channel else "tick"
                await _relay_realtime_message(kind, payload)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[WS] Redis relay listener error: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 10.0)
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.close()


async def start_realtime_relay_listener() -> str:
    global _relay_listener_task, _relay_stop_event

    if _relay_listener_task is not None and not _relay_listener_task.done():
        return "Redis relay already running"

    _relay_stop_event = asyncio.Event()
    _relay_listener_task = asyncio.create_task(_redis_relay_listener(), name="redis-realtime-relay")
    return "Redis relay started"


async def stop_realtime_relay_listener() -> None:
    global _relay_listener_task, _relay_stop_event

    if _relay_stop_event is not None:
        _relay_stop_event.set()

    task = _relay_listener_task
    _relay_listener_task = None
    _relay_stop_event = None

    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


class SocketManager:
    """
    Manages all connected WebSocket clients with per-user isolation.
    Room-based symbol subscriptions — clients only receive ticks for symbols they subscribed to.
    Parallel asynchronous fanning with slow client protection and partitioned locks.
    """

    def __init__(self):
        # client_id → WebSocket
        self._connections: dict[str, WebSocket] = {}
        # client_id → user_id
        self._user_map: dict[str, int] = {}
        # user_id → active client_ids
        self._user_clients: dict[int, set[str]] = defaultdict(set)
        # client_id → set of subscribed symbols
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        # symbol → set of client_ids (Room-based model)
        self._rooms: dict[str, set[str]] = defaultdict(set)
        # client_id → restored symbols from reconnect cache
        self._restored_symbols: dict[str, list[str]] = {}
        # user_id → reconnect payload (symbols + expiration)
        self._recent_disconnects: dict[int, dict[str, Any]] = {}
        
        # Partitioned locks for ultra-low latency
        self._conn_lock = asyncio.Lock()  # Lock for connections, user maps
        self._sub_lock = asyncio.Lock()   # Lock for rooms and subscriptions
        self._recent_lock = asyncio.Lock() # Lock for reconnect cache

    @staticmethod
    def _now_monotonic() -> float:
        return asyncio.get_running_loop().time()

    async def _prune_recent_disconnects(self, now: float) -> None:
        async with self._recent_lock:
            expired = [
                uid
                for uid, payload in self._recent_disconnects.items()
                if float(payload.get("expires_at", 0.0)) <= now
            ]
            for uid in expired:
                self._recent_disconnects.pop(uid, None)

    async def connect(self, websocket: WebSocket, user_id: int) -> str:
        client_id = str(uuid.uuid4())[:8]
        restored_symbols: list[str] = []
        now = self._now_monotonic()

        await self._prune_recent_disconnects(now)

        async with self._conn_lock:
            self._connections[client_id] = websocket
            self._user_map[client_id] = user_id
            self._user_clients[user_id].add(client_id)

        async with self._recent_lock:
            cached = self._recent_disconnects.pop(user_id, None)
        
        if cached:
            restored_symbols = [
                str(symbol).upper()
                for symbol in cached.get("symbols", [])
                if str(symbol).strip()
            ]
            if restored_symbols:
                async with self._sub_lock:
                    self._subscriptions[client_id].update(restored_symbols)
                    for symbol in restored_symbols:
                        self._rooms[symbol].add(client_id)

        self._restored_symbols[client_id] = restored_symbols

        logger.info(
            f"[SocketManager] Connected: client={client_id} user={user_id} "
            f"total={len(self._connections)}"
        )
        return client_id

    def pop_restored_symbols(self, client_id: str) -> list[str]:
        return list(self._restored_symbols.pop(client_id, []))

    async def disconnect(self, client_id: str) -> list[str]:
        """
        Disconnect client and return symbols that now have 0 active subscribers.
        This enables caller to trigger Broker unsubscription.
        """
        now = self._now_monotonic()
        unsubscribed_tokens = []

        async with self._conn_lock:
            user_id = self._user_map.pop(client_id, None)
            self._connections.pop(client_id, None)
            self._restored_symbols.pop(client_id, None)

            if user_id is not None:
                client_set = self._user_clients.get(user_id, set())
                client_set.discard(client_id)
                if not client_set:
                    self._user_clients.pop(user_id, None)

        async with self._sub_lock:
            symbols = sorted(self._subscriptions.pop(client_id, set()))
            for symbol in symbols:
                room = self._rooms[symbol]
                room.discard(client_id)
                if not room:
                    self._rooms.pop(symbol, None)
                    unsubscribed_tokens.append(symbol)

        if user_id is not None:
            async with self._recent_lock:
                self._recent_disconnects[user_id] = {
                    "symbols": symbols,
                    "expires_at": now + RECONNECT_GRACE_SECONDS,
                }

        await self._prune_recent_disconnects(now)

        logger.info(
            f"[SocketManager] Disconnected: client={client_id} "
            f"total={len(self._connections)}"
        )
        return unsubscribed_tokens

    async def subscribe(self, client_id: str, symbols: list[str]):
        normalized = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        if not normalized:
            return

        async with self._sub_lock:
            self._subscriptions[client_id].update(normalized)
            for symbol in normalized:
                self._rooms[symbol].add(client_id)

        async with self._conn_lock:
            websocket = self._connections.get(client_id)
            
        logger.debug(f"[SocketManager] client={client_id} subscribed={symbols}")

        if websocket is None:
            return

        # Deliver latest state immediately from cache
        for symbol in normalized:
            for kind in ("tick", "candle", "signal"):
                cached = await _load_latest_event(kind, symbol)
                if cached is None:
                    continue
                try:
                    await asyncio.wait_for(websocket.send_text(_serialize(cached)), timeout=0.2)
                except Exception:
                    # Connection is unresponsive, let cleanup handle it
                    return

    async def unsubscribe(self, client_id: str, symbols: list[str]) -> list[str]:
        """
        Unsubscribe client from symbols and return tokens that now have 0 active subscribers.
        """
        normalized = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        unsubscribed_tokens = []
        
        async with self._sub_lock:
            for symbol in normalized:
                self._subscriptions[client_id].discard(symbol)
                room = self._rooms[symbol]
                room.discard(client_id)
                if not room:
                    self._rooms.pop(symbol, None)
                    unsubscribed_tokens.append(symbol)
                    
        return unsubscribed_tokens

    async def _send_safe(self, client_id: str, ws: WebSocket, raw: str) -> str | None:
        """Helper to send message asynchronously with strict 200ms timeout guardrail."""
        try:
            await asyncio.wait_for(ws.send_text(raw), timeout=0.2)
            return None
        except Exception:
            # Client timed out or dropped connection, return client_id for cleanup
            return client_id

    async def send_to_user(self, user_id: int, payload: dict):
        """Send payload only to sockets owned by the given user_id."""
        async with self._conn_lock:
            target_ids = list(self._user_clients.get(int(user_id), set()))
            targets = [(cid, self._connections.get(cid)) for cid in target_ids]

        if not targets:
            return

        raw = _serialize(payload)
        tasks = [self._send_safe(cid, ws, raw) for cid, ws in targets if ws is not None]
        
        if tasks:
            results = await asyncio.gather(*tasks)
            dead_clients = [cid for cid in results if cid is not None]
            for cid in dead_clients:
                await self.disconnect(cid)

    async def broadcast_tick(self, symbol: str, payload: dict):
        """
        Send tick only to clients subscribed to this symbol (Room-based).
        Silently cleans up unresponsive slow clients concurrently.
        """
        symbol_upper = symbol.upper()

        async with self._sub_lock:
            client_ids = list(self._rooms.get(symbol_upper, set()))

        if not client_ids:
            return

        async with self._conn_lock:
            targets = [(cid, self._connections.get(cid)) for cid in client_ids]

        raw = _serialize(payload)
        tasks = [self._send_safe(cid, ws, raw) for cid, ws in targets if ws is not None]
        
        if tasks:
            results = await asyncio.gather(*tasks)
            dead_clients = [cid for cid in results if cid is not None]
            for cid in dead_clients:
                await self.disconnect(cid)

    async def broadcast_to_all(self, payload: dict):
        """Broadcast to ALL connected clients (market status, heartbeats, etc.)."""
        async with self._conn_lock:
            targets = list(self._connections.items())

        if not targets:
            return

        raw = _serialize(payload)
        tasks = [self._send_safe(cid, ws, raw) for cid, ws in targets]
        
        if tasks:
            results = await asyncio.gather(*tasks)
            dead_clients = [cid for cid in results if cid is not None]
            for cid in dead_clients:
                await self.disconnect(cid)

    def get_client_count(self) -> int:
        return len(self._connections)

    def get_stats(self) -> dict:
        return {
            "total_connections": len(self._connections),
            "active_users": len(self._user_clients),
            "total_subscriptions": sum(len(subs) for subs in self._subscriptions.values()),
            "active_rooms": len(self._rooms),
            "reconnect_cache_users": len(self._recent_disconnects),
        }

    def get_subscribed_symbols(self) -> set[str]:
        """Get the set of all active symbols subscribed by at least one client."""
        return set(self._rooms.keys())


# Module-level singleton
socket_manager = SocketManager()


# ─── Backward-compatible functions used by server.py ──────────────────

def register_client(ws: WebSocket):
    pass  # Now handled by socket_manager.connect() in the WS handler


def unregister_client(ws: WebSocket):
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
    await _publish_realtime_event("tick", msg)
    await _store_latest_event("tick", msg)


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
    await _publish_realtime_event("candle", msg)
    await _store_latest_event("candle", msg)


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
    await _publish_realtime_event("signal", msg)
    await _store_latest_event("signal", msg)


async def broadcast_status(connected: bool, detail: str = ""):
    """Broadcast connection status to all clients."""
    msg = {
        "type": "status",
        "connected": connected,
        "detail": detail,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    await socket_manager.broadcast_to_all(msg)
    await _publish_realtime_event("status", msg)
    await _store_latest_event("status", {**msg, "symbol": "GLOBAL"})
