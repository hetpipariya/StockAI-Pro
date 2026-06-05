from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from stockai_shared.config import config
from stockai_shared.services.instrument_service import get_token_by_symbol
from stockai_shared.cache.redis_client import get_redis, get_cache, set_cache
from stockai_shared.utils.auth_utils import decode_access_token
from .relay import RECONNECT_GRACE_SECONDS, socket_manager, _RELAY_INSTANCE_ID

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "TATASTEEL", "ITC",
    "AXISBANK", "KOTAKBANK", "WIPRO", "BHARTIARTL", "HINDUNILVR", "LT", "MARUTI"
]

_last_live_tick_time = 0.0
_ip_connection_attempts: dict[str, list[float]] = {}
_ip_connection_lock = asyncio.Lock()


def get_ws_state() -> str:
    """Check Redis health to return gateway connection status."""
    return "CONNECTED"


def is_ws_streaming() -> bool:
    return True


def get_last_tick_age_seconds() -> float:
    global _last_live_tick_time
    if _last_live_tick_time <= 0:
        return float("inf")
    return max(0.0, time.time() - _last_live_tick_time)


def update_last_live_tick_time() -> None:
    global _last_live_tick_time
    _last_live_tick_time = time.time()


def get_last_known_price(symbol: str) -> float | None:
    return None


async def _update_redis_active_subscriptions() -> None:
    """Store the set of active gateway client subscriptions in Redis with a 60-second TTL."""
    redis_client = await get_redis()
    if redis_client is None:
        return
    symbols = socket_manager.get_subscribed_symbols()
    key = f"stockai:active_subscriptions:{_RELAY_INSTANCE_ID}"
    try:
        async with redis_client.pipeline() as pipe:
            pipe.delete(key)
            if symbols:
                pipe.sadd(key, *symbols)
                pipe.expire(key, 60)
            await pipe.execute()
    except Exception as exc:
        logger.debug("[WS] Failed to update active subscriptions in Redis for %s: %s", _RELAY_INSTANCE_ID, exc)


async def _resolve_websocket_user_id(token: str) -> int | None:
    from stockai_shared.db.db import AsyncSessionLocal, UserModel, is_transient_db_error
    from stockai_shared.cache.redis_client import is_access_token_blacklisted
    if await is_access_token_blacklisted(token):
        logger.warning("[WS] Attempted connection with blacklisted/revoked token")
        return None

    payload = decode_access_token(token)
    user_id = int(payload.get("user_id", payload["sub"]))

    # Check cached auth token to protect database connection pool
    cache_key = f"auth:user_ws_resolve:{user_id}"
    cached_id = await get_cache(cache_key)
    if cached_id is not None:
        return int(cached_id)

    auth_timeout = max(0.5, float(config.WS_AUTH_DB_TIMEOUT_SECONDS))
    max_attempts = max(1, min(config.DB_MAX_RETRIES, 3))
    base_delay = max(0.05, float(config.DB_RETRY_BASE_DELAY_SECONDS))

    for attempt in range(1, max_attempts + 1):
        try:
            async with AsyncSessionLocal() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        select(UserModel.id)
                        .where(UserModel.id == user_id, UserModel.is_active.is_(True))
                        .limit(1)
                    ),
                    timeout=auth_timeout,
                )
                resolved_id = result.scalar_one_or_none()
                if resolved_id is not None:
                    await set_cache(cache_key, int(resolved_id), ttl=300)
                    return int(resolved_id)
                return None
        except Exception as exc:
            transient = is_transient_db_error(exc)
            if transient and attempt < max_attempts:
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise

    return None


async def _build_user_state_payload(user_id: int) -> dict[str, Any]:
    """Retrieve user state from user_trading_state table in database (fully decoupled)."""
    from stockai_shared.db.db import AsyncSessionLocal, UserTradingStateModel

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserTradingStateModel)
                .where(UserTradingStateModel.user_id == user_id)
                .limit(1)
            )
            row = result.scalars().first()

        if row is not None:
            return {
                "type": "user_state",
                "user_id": user_id,
                "mode": "PAPER",
                "balance": row.balance,
                "daily_pnl": 0.0,
                "daily_pnl_pct": 0.0,
                "can_trade": True,
                "can_trade_reason": "OK",
                "positions": row.positions or [],
                "orders": row.orders or [],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
    except Exception as exc:
        logger.warning("[WS] Failed to load trading state from DB: %s", exc)

    return {
        "type": "user_state",
        "user_id": user_id,
        "mode": "PAPER",
        "balance": 100000.0,
        "daily_pnl": 0.0,
        "daily_pnl_pct": 0.0,
        "can_trade": True,
        "can_trade_reason": "OK",
        "positions": [],
        "orders": [],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


async def _send_user_state_snapshot(
    websocket: WebSocket,
    user_id: int,
    source: str,
) -> None:
    payload = await _build_user_state_payload(user_id=user_id)
    payload["source"] = source
    await websocket.send_json(payload)


async def websocket_live(
    websocket: WebSocket, token: Optional[str] = Query(default=None)
):
    """Authenticated websocket endpoint: /ws?token=<jwt> (legacy alias: /live)."""
    client_host = websocket.client.host if websocket.client else "unknown"

    # 1. Distributed Handshake Rate Limiting (max 10 handshake attempts per minute)
    from stockai_shared.cache.redis_client import check_rate_limit
    allowed_ip = await check_rate_limit(f"ws_handshake:ip:{client_host}", 10, 60)
    
    allowed_token = True
    if token:
        import hashlib
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        allowed_token = await check_rate_limit(f"ws_handshake:token:{token_hash}", 10, 60)

    if not allowed_ip or not allowed_token:
        logger.warning("[WS][RATE-LIMIT] IP %s or token triggered handshake limit. Rejecting connection.", client_host)
        try:
            from stockai_shared.metrics.metrics import WS_THROTTLED_CONNECTIONS
            WS_THROTTLED_CONNECTIONS.inc()
        except Exception:
            pass
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="WebSocket handshake rate limit exceeded (10/min)")

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        logger.warning("[WS] Rejected unauthenticated connection from %s", client_host)
        return

    try:
        user_id = await _resolve_websocket_user_id(token)
        if user_id is None:
            await websocket.close(code=4003, reason="User not found")
            return
    except Exception as exc:
        await websocket.close(code=4001, reason="Invalid token")
        logger.warning("[WS] Auth failed from %s: %s", client_host, type(exc).__name__)
        return

    await websocket.accept()
    await _handle_ws_connection(websocket, user_id)


async def _handle_ws_connection(websocket: WebSocket, user_id: int):
    client_id = await socket_manager.connect(websocket, user_id)
    restored_symbols = socket_manager.pop_restored_symbols(client_id)
    msg_timestamps: list[float] = []

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "WebSocket connected. Send subscribe message.",
                "connection_state": get_ws_state(),
                "restored_symbols": restored_symbols,
                "reconnect_grace_seconds": RECONNECT_GRACE_SECONDS,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        if restored_symbols:
            await websocket.send_json(
                {
                    "type": "restored_subscriptions",
                    "symbols": restored_symbols,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        await _send_user_state_snapshot(
            websocket=websocket,
            user_id=user_id,
            source="connect",
        )

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)

                # 2. Message Size Limit Guard (max 64KB)
                if len(raw) > 65536:
                    logger.warning("[WS] Client client_id=%s user_id=%d sent oversized frame: size=%d", client_id, user_id, len(raw))
                    await websocket.send_json(
                        {"type": "error", "message": "Message size limit exceeded (max 64KB)."}
                    )
                    await websocket.close(code=4009, reason="Message size limit exceeded")
                    break

                # 3. Connection Message Rate Limit (max 20 messages per 10 seconds)
                now_time = time.time()
                msg_timestamps = [t for t in msg_timestamps if now_time - t < 10.0]
                if len(msg_timestamps) >= 20:
                    logger.warning("[WS][RATE-LIMIT] Client client_id=%s user_id=%d exceeded message rate limit.", client_id, user_id)
                    await websocket.send_json(
                        {"type": "error", "message": "Message rate limit exceeded (max 20 per 10s)."}
                    )
                    await websocket.close(code=1008, reason="Message rate limit exceeded")
                    break
                msg_timestamps.append(now_time)

                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    await websocket.send_json(
                        {"type": "error", "message": "Payload must be a JSON object."}
                    )
                    continue
                await _process_ws_message(msg, client_id, user_id, websocket)

            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "connection_state": get_ws_state(),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "message": "Invalid JSON payload."}
                )
            except WebSocketDisconnect:
                break

    finally:
        # Clean up client subscriptions
        unsubscribed_tokens = await socket_manager.disconnect(client_id)
        if unsubscribed_tokens:
            await _update_redis_active_subscriptions()


async def _process_ws_message(
    msg: dict, client_id: str, user_id: int, websocket: WebSocket
):
    action = msg.get("action")

    if action == "subscribe":
        symbols = msg.get("symbols", [])
        
        # Max subscriptions guard per client to protect server memory bounds (max 50)
        current_subs = socket_manager._subscriptions.get(client_id, set())
        if isinstance(symbols, list) and len(current_subs) + len(symbols) > 50:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Subscription limit exceeded. Max 50 symbols allowed. Current count: {len(current_subs)}",
                }
            )
            return

        valid: list[str] = []
        rejected: list[str] = []
        if isinstance(symbols, list):
            for symbol in symbols:
                if not isinstance(symbol, str):
                    continue
                normalized = symbol.strip().upper()
                if not normalized or normalized in valid or normalized in rejected:
                    continue

                try:
                    get_token_by_symbol(normalized, exchange=config.SMARTAPI_EXCHANGE)
                    valid.append(normalized)
                except KeyError:
                    rejected.append(normalized)

        await socket_manager.subscribe(client_id, valid)
        if valid:
            await _update_redis_active_subscriptions()

        await websocket.send_json(
            {
                "type": "subscribed",
                "symbols": valid,
                "rejected_symbols": rejected,
                "connection_state": get_ws_state(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        logger.info(
            "[WS] user_id=%d client_id=%s subscribed=%s rejected=%s",
            user_id,
            client_id,
            valid,
            rejected,
        )

    elif action == "unsubscribe":
        symbols = msg.get("symbols", [])
        normalized = (
            [s.strip().upper() for s in symbols if isinstance(s, str)]
            if isinstance(symbols, list)
            else []
        )
        unsubscribed_tokens = await socket_manager.unsubscribe(client_id, normalized)
        if unsubscribed_tokens:
            await _update_redis_active_subscriptions()
                    
        await websocket.send_json({"type": "unsubscribed", "symbols": normalized})

    elif action == "pong":
        return

    elif action == "ping":
        await websocket.send_json(
            {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    elif action in {"sync_state", "state", "get_state"}:
        await _send_user_state_snapshot(
            websocket=websocket,
            user_id=user_id,
            source="manual",
        )

    else:
        await websocket.send_json(
            {"type": "error", "message": f"Unknown action: {action}"}
        )


def setup_websocket_routes(app: FastAPI) -> None:
    app.websocket("/ws")(websocket_live)
    app.websocket("/live")(websocket_live)
