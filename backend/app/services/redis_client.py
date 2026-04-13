from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

try:
    import redis
except Exception:
    redis = None

try:
    import redis.asyncio as redis_asyncio
except Exception:
    redis_asyncio = None

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

SESSION_KEY = "smartapi_session"
SESSION_TTL_SECONDS = 24 * 60 * 60
_REDIS_RETRY_INTERVAL_SECONDS = 30

# Async redis client state
_async_redis: Optional[Any] = None
_async_failed = False
_async_last_attempt: float = 0.0
asyncio_lock = None

# Sync redis client state
_sync_redis: Optional[Any] = None
_sync_failed = False
_sync_last_attempt: float = 0.0
_sync_lock = threading.Lock()

# In-memory fallback shared by async/sync paths
_fallback_cache: dict[str, tuple[str, float]] = {}
_fallback_lock = threading.Lock()


# Lazily create asyncio lock only when needed (requires running event loop context)
def _get_async_lock():
    global asyncio_lock
    if asyncio_lock is None:
        import asyncio

        asyncio_lock = asyncio.Lock()
    return asyncio_lock


def _serialize(value: Any) -> str:
    return json.dumps(value) if not isinstance(value, str) else value


def _deserialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _parse_epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            return 0.0
    return 0.0


def _normalize_session_payload(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, dict):
        return None

    jwt_token = str(value.get("jwtToken") or value.get("authToken") or "").strip()
    refresh_token = str(value.get("refreshToken") or "").strip()
    feed_raw = value.get("feedToken")
    feed_token = str(feed_raw).strip() if feed_raw not in (None, "") else None
    expiry = _parse_epoch(
        value.get("expiry") or value.get("expiresEpoch") or value.get("expiresAt")
    )
    if expiry <= 0:
        expiry = time.time() + SESSION_TTL_SECONDS

    if not jwt_token or not refresh_token:
        return None

    return {
        "jwtToken": jwt_token,
        "refreshToken": refresh_token,
        "feedToken": feed_token,
        "expiry": int(expiry),
    }


def _fallback_set(key: str, value: Any, ttl: int) -> None:
    expires_at = time.monotonic() + max(1, int(ttl))
    serialized = _serialize(value)
    with _fallback_lock:
        _fallback_cache[key] = (serialized, expires_at)


def _fallback_get(key: str) -> Any:
    now = time.monotonic()
    with _fallback_lock:
        entry = _fallback_cache.get(key)
        if not entry:
            return None
        value, expires_at = entry
        if now > expires_at:
            _fallback_cache.pop(key, None)
            return None
    return _deserialize(value)


def _fallback_delete(key: str) -> None:
    with _fallback_lock:
        _fallback_cache.pop(key, None)


async def get_redis() -> Optional[Any]:
    global _async_redis, _async_failed, _async_last_attempt

    if _async_redis is not None:
        return _async_redis

    if redis_asyncio is None:
        if not _async_failed:
            logger.warning("[REDIS] async client unavailable, using fallback cache")
        _async_failed = True
        return None

    lock = _get_async_lock()
    async with lock:
        if _async_redis is not None:
            return _async_redis

        now = time.monotonic()
        if _async_failed and (now - _async_last_attempt) < _REDIS_RETRY_INTERVAL_SECONDS:
            return None

        _async_last_attempt = now

        try:
            client = redis_asyncio.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            await client.ping()
            _async_redis = client
            _async_failed = False
            logger.info("[REDIS] async connected")
        except Exception as exc:
            _async_redis = None
            _async_failed = True
            logger.warning("[REDIS] async connection failed, fallback mode: %s", type(exc).__name__)

    return _async_redis


def get_redis_sync() -> Optional[Any]:
    global _sync_redis, _sync_failed, _sync_last_attempt

    if _sync_redis is not None:
        return _sync_redis

    if redis is None:
        if not _sync_failed:
            logger.warning("[REDIS] sync client unavailable, using fallback cache")
        _sync_failed = True
        return None

    with _sync_lock:
        if _sync_redis is not None:
            return _sync_redis

        now = time.monotonic()
        if _sync_failed and (now - _sync_last_attempt) < _REDIS_RETRY_INTERVAL_SECONDS:
            return None

        _sync_last_attempt = now

        try:
            client = redis.Redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            client.ping()
            _sync_redis = client
            _sync_failed = False
            logger.info("[REDIS] sync connected")
        except Exception as exc:
            _sync_redis = None
            _sync_failed = True
            logger.warning("[REDIS] sync connection failed, fallback mode: %s", type(exc).__name__)

    return _sync_redis


async def set_cache(key: str, value: Any, ttl: int = 60) -> None:
    redis_client = await get_redis()
    if redis_client:
        try:
            await redis_client.setex(key, max(1, int(ttl)), _serialize(value))
            logger.debug("[CACHE] set key=%s ttl=%ss backend=redis", key, int(ttl))
            return
        except Exception as exc:
            logger.warning("[CACHE] redis set failed key=%s: %s", key, type(exc).__name__)

    _fallback_set(key, value, ttl)
    logger.debug("[CACHE] set key=%s ttl=%ss backend=fallback", key, int(ttl))


async def get_cache(key: str) -> Optional[Any]:
    redis_client = await get_redis()
    if redis_client:
        try:
            value = await redis_client.get(key)
            if value is not None:
                logger.debug("[CACHE] hit key=%s backend=redis", key)
                return _deserialize(value)
            logger.debug("[CACHE] miss key=%s backend=redis", key)
        except Exception as exc:
            logger.warning("[CACHE] redis get failed key=%s: %s", key, type(exc).__name__)

    value = _fallback_get(key)
    if value is not None:
        logger.debug("[CACHE] hit key=%s backend=fallback", key)
    else:
        logger.debug("[CACHE] miss key=%s backend=fallback", key)
    return value


async def delete_cache(key: str) -> None:
    redis_client = await get_redis()
    if redis_client:
        try:
            await redis_client.delete(key)
            logger.debug("[CACHE] delete key=%s backend=redis", key)
            _fallback_delete(key)
            return
        except Exception as exc:
            logger.warning("[CACHE] redis delete failed key=%s: %s", key, type(exc).__name__)

    _fallback_delete(key)
    logger.debug("[CACHE] delete key=%s backend=fallback", key)


def set_cache_sync(key: str, value: Any, ttl: int = 60) -> None:
    redis_client = get_redis_sync()
    if redis_client:
        try:
            redis_client.setex(key, max(1, int(ttl)), _serialize(value))
            logger.debug("[CACHE] set key=%s ttl=%ss backend=redis-sync", key, int(ttl))
            return
        except Exception as exc:
            logger.warning("[CACHE] redis-sync set failed key=%s: %s", key, type(exc).__name__)

    _fallback_set(key, value, ttl)
    logger.debug("[CACHE] set key=%s ttl=%ss backend=fallback", key, int(ttl))


def get_cache_sync(key: str) -> Optional[Any]:
    redis_client = get_redis_sync()
    if redis_client:
        try:
            value = redis_client.get(key)
            if value is not None:
                logger.debug("[CACHE] hit key=%s backend=redis-sync", key)
                return _deserialize(value)
            logger.debug("[CACHE] miss key=%s backend=redis-sync", key)
        except Exception as exc:
            logger.warning("[CACHE] redis-sync get failed key=%s: %s", key, type(exc).__name__)

    value = _fallback_get(key)
    if value is not None:
        logger.debug("[CACHE] hit key=%s backend=fallback", key)
    else:
        logger.debug("[CACHE] miss key=%s backend=fallback", key)
    return value


def delete_cache_sync(key: str) -> None:
    redis_client = get_redis_sync()
    if redis_client:
        try:
            redis_client.delete(key)
            logger.debug("[CACHE] delete key=%s backend=redis-sync", key)
            _fallback_delete(key)
            return
        except Exception as exc:
            logger.warning("[CACHE] redis-sync delete failed key=%s: %s", key, type(exc).__name__)

    _fallback_delete(key)
    logger.debug("[CACHE] delete key=%s backend=fallback", key)


async def store_session_token(token_data: dict) -> None:
    normalized = _normalize_session_payload(token_data)
    if not normalized:
        logger.warning("[TOKEN] Refusing to persist malformed session payload")
        return
    await set_cache(SESSION_KEY, normalized, ttl=SESSION_TTL_SECONDS)


async def get_session_token() -> Optional[dict]:
    value = await get_cache(SESSION_KEY)
    normalized = _normalize_session_payload(value)
    if not normalized:
        return None

    if isinstance(value, dict) and value != normalized:
        await set_cache(SESSION_KEY, normalized, ttl=SESSION_TTL_SECONDS)
    return normalized


async def clear_session() -> None:
    await delete_cache(SESSION_KEY)


def store_session_token_sync(token_data: dict) -> None:
    normalized = _normalize_session_payload(token_data)
    if not normalized:
        logger.warning("[TOKEN] Refusing to persist malformed session payload")
        return
    set_cache_sync(SESSION_KEY, normalized, ttl=SESSION_TTL_SECONDS)


def get_session_token_sync() -> Optional[dict]:
    value = get_cache_sync(SESSION_KEY)
    normalized = _normalize_session_payload(value)
    if not normalized:
        return None

    if isinstance(value, dict) and value != normalized:
        set_cache_sync(SESSION_KEY, normalized, ttl=SESSION_TTL_SECONDS)
    return normalized


def clear_session_sync() -> None:
    delete_cache_sync(SESSION_KEY)
