from __future__ import annotations

import json
import logging
import time
from typing import Optional, Any
import redis.asyncio as redis
from app.config import REDIS_URL

logger = logging.getLogger(__name__)

# Global redis client
_redis: Optional[redis.Redis] = None

# Fallback in-memory dict if Redis fails
_fallback_cache: dict[str, tuple[str, float]] = {}  # (value, expiry_monotonic)

# Track Redis connection state to avoid repeated noisy reconnect attempts
_redis_failed = False
_redis_last_attempt: float = 0
_REDIS_RETRY_INTERVAL = 60  # seconds between re-attempts


async def get_redis() -> Optional[redis.Redis]:
    """Get Redis connection or fallback to in-memory mode.
    Only attempts to connect once; retries every 60s."""
    global _redis, _redis_failed, _redis_last_attempt

    if _redis is not None:
        return _redis

    # If we already know Redis is down, only retry periodically
    if _redis_failed:
        now = time.monotonic()
        if (now - _redis_last_attempt) < _REDIS_RETRY_INTERVAL:
            return None  # Use memory fallback silently
        # Time to retry
        logger.info("[REDIS] Retrying connection after %ds cooldown...", _REDIS_RETRY_INTERVAL)

    _redis_last_attempt = time.monotonic()

    try:
        client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)
        await client.ping()
        _redis = client
        _redis_failed = False
        logger.info("[REDIS] ✓ Connected to %s", REDIS_URL)
    except Exception as e:
        _redis_failed = True
        _redis = None
        logger.warning("[REDIS] Unavailable (%s). Using in-memory fallback.", type(e).__name__)

    return _redis


async def set_cache(key: str, value: Any, ttl: int = 60) -> None:
    """Store value in cache with TTL."""
    val_str = json.dumps(value) if not isinstance(value, str) else value
    r = await get_redis()
    if r:
        try:
            await r.setex(key, ttl, val_str)
            return
        except Exception:
            logger.debug("[REDIS] set_cache error for key=%s", key)

    # Fallback — store with expiry time
    import time as _time
    _fallback_cache[key] = (val_str, _time.monotonic() + ttl)


async def get_cache(key: str) -> Optional[Any]:
    """Retrieve value from cache."""
    r = await get_redis()
    if r:
        try:
            val = await r.get(key)
            if val is not None:
                try:
                    return json.loads(val)
                except Exception:
                    return val
        except Exception:
            logger.debug("[REDIS] get_cache error for key=%s", key)

    # Fallback — check TTL
    import time as _time
    entry = _fallback_cache.get(key)
    if entry:
        val, expiry = entry
        if _time.monotonic() > expiry:
            _fallback_cache.pop(key, None)  # expired
            return None
        try:
            return json.loads(val)
        except Exception:
            return val
    return None


async def delete_cache(key: str) -> None:
    """Delete value from cache."""
    r = await get_redis()
    if r:
        try:
            await r.delete(key)
            return
        except Exception:
            logger.debug("[REDIS] delete_cache error for key=%s", key)

    # Fallback
    _fallback_cache.pop(key, None)


async def store_session_token(token_data: dict) -> None:
    """Store SmartAPI token data with 1-day TTL."""
    # 24 hours TTL
    await set_cache("smartapi_session", token_data, ttl=86400)


async def get_session_token() -> Optional[dict]:
    """Retrieve existing SmartAPI token data."""
    return await get_cache("smartapi_session")


async def clear_session() -> None:
    """Clear session data."""
    await delete_cache("smartapi_session")
