from __future__ import annotations

import asyncio
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

try:
    import orjson
except ImportError:
    orjson = None

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
        asyncio_lock = asyncio.Lock()
    return asyncio_lock


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


_degraded_mode_active = False


def is_degraded_mode() -> bool:
    global _degraded_mode_active
    return _degraded_mode_active


def _trigger_circuit_breaker(exc: Exception, is_sync: bool = False) -> None:
    global _async_redis, _async_failed, _sync_redis, _sync_failed, _degraded_mode_active
    from app.services.metrics import REDIS_DEGRADED_MODE

    _degraded_mode_active = True
    try:
        REDIS_DEGRADED_MODE.set(1)
    except Exception:
        pass

    if is_sync:
        _sync_redis = None
        _sync_failed = True
        logger.error(
            "[REDIS][CIRCUIT-BREAKER] Sync Redis connection dropped: %s. Switched to Degraded Fallback mode.",
            type(exc).__name__,
        )
    else:
        _async_redis = None
        _async_failed = True
        logger.error(
            "[REDIS][CIRCUIT-BREAKER] Async Redis connection dropped: %s. Switched to Degraded Fallback mode.",
            type(exc).__name__,
        )


async def get_redis() -> Optional[Any]:
    return await _get_redis(force_retry=False)


async def _get_redis(*, force_retry: bool) -> Optional[Any]:
    global _async_redis, _async_failed, _async_last_attempt, _degraded_mode_active

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
        if (
            _async_failed
            and not force_retry
            and (now - _async_last_attempt) < _REDIS_RETRY_INTERVAL_SECONDS
        ):
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
            _degraded_mode_active = False
            try:
                from app.services.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(0)
            except Exception:
                pass
            logger.info("[REDIS] async connected & circuit breaker reset")
        except Exception as exc:
            _async_redis = None
            _async_failed = True
            _degraded_mode_active = True
            try:
                from app.services.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(1)
            except Exception:
                pass
            logger.warning("[REDIS] async connection failed, fallback mode: %s", type(exc).__name__)

    return _async_redis


async def initialize_redis(
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> str:
    attempts = max(1, int(max_attempts))

    for attempt in range(1, attempts + 1):
        client = await _get_redis(force_retry=True)
        if client is not None:
            if attempt > 1:
                logger.info("[REDIS] startup connection recovered on attempt %d/%d", attempt, attempts)
            return "redis"

        if attempt < attempts:
            logger.warning(
                "[REDIS] startup connection failed on attempt %d/%d; retrying in %.1fs",
                attempt,
                attempts,
                retry_delay_seconds,
            )
            await asyncio.sleep(max(0.1, float(retry_delay_seconds)))

    logger.warning(
        "[REDIS] startup initialization failed after %d attempts; using in-memory fallback cache",
        attempts,
    )
    return "memory"


def get_cache_backend_name() -> str:
    if _async_redis is not None or _sync_redis is not None:
        return "redis"
    return "memory"


def get_redis_sync() -> Optional[Any]:
    global _sync_redis, _sync_failed, _sync_last_attempt, _degraded_mode_active

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
            _degraded_mode_active = False
            try:
                from app.services.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(0)
            except Exception:
                pass
            logger.info("[REDIS] sync connected & circuit breaker reset")
        except Exception as exc:
            _sync_redis = None
            _sync_failed = True
            _degraded_mode_active = True
            try:
                from app.services.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(1)
            except Exception:
                pass
            logger.warning("[REDIS] sync connection failed, fallback mode: %s", type(exc).__name__)

    return _sync_redis


async def set_cache(key: str, value: Any, ttl: int = 60) -> None:
    from app.services.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = await get_redis()
        
    if redis_client:
        try:
            await redis_client.setex(key, max(1, int(ttl)), _serialize(value))
            logger.debug("[CACHE] set key=%s ttl=%ss backend=redis", key, int(ttl))
            try:
                REDIS_OPERATION_LATENCY.labels(operation="set").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            return
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=False)

    _fallback_set(key, value, ttl)
    logger.debug("[CACHE] set key=%s ttl=%ss backend=fallback", key, int(ttl))


async def get_cache(key: str) -> Optional[Any]:
    from app.services.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = await get_redis()
        
    if redis_client:
        try:
            value = await redis_client.get(key)
            try:
                REDIS_OPERATION_LATENCY.labels(operation="get").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            if value is not None:
                logger.debug("[CACHE] hit key=%s backend=redis", key)
                return _deserialize(value)
            logger.debug("[CACHE] miss key=%s backend=redis", key)
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=False)

    value = _fallback_get(key)
    if value is not None:
        logger.debug("[CACHE] hit key=%s backend=fallback", key)
    else:
        logger.debug("[CACHE] miss key=%s backend=fallback", key)
    return value


async def delete_cache(key: str) -> None:
    from app.services.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = await get_redis()
        
    if redis_client:
        try:
            await redis_client.delete(key)
            logger.debug("[CACHE] delete key=%s backend=redis", key)
            try:
                REDIS_OPERATION_LATENCY.labels(operation="delete").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            _fallback_delete(key)
            return
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=False)

    _fallback_delete(key)
    logger.debug("[CACHE] delete key=%s backend=fallback", key)


def set_cache_sync(key: str, value: Any, ttl: int = 60) -> None:
    from app.services.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = get_redis_sync()
        
    if redis_client:
        try:
            redis_client.setex(key, max(1, int(ttl)), _serialize(value))
            logger.debug("[CACHE] set key=%s ttl=%ss backend=redis-sync", key, int(ttl))
            try:
                REDIS_OPERATION_LATENCY.labels(operation="set_sync").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            return
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=True)

    _fallback_set(key, value, ttl)
    logger.debug("[CACHE] set key=%s ttl=%ss backend=fallback", key, int(ttl))


def get_cache_sync(key: str) -> Optional[Any]:
    from app.services.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = get_redis_sync()
        
    if redis_client:
        try:
            value = redis_client.get(key)
            try:
                REDIS_OPERATION_LATENCY.labels(operation="get_sync").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            if value is not None:
                logger.debug("[CACHE] hit key=%s backend=redis-sync", key)
                return _deserialize(value)
            logger.debug("[CACHE] miss key=%s backend=redis-sync", key)
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=True)

    value = _fallback_get(key)
    if value is not None:
        logger.debug("[CACHE] hit key=%s backend=fallback", key)
    else:
        logger.debug("[CACHE] miss key=%s backend=fallback", key)
    return value


def delete_cache_sync(key: str) -> None:
    from app.services.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = get_redis_sync()
        
    if redis_client:
        try:
            redis_client.delete(key)
            logger.debug("[CACHE] delete key=%s backend=redis-sync", key)
            try:
                REDIS_OPERATION_LATENCY.labels(operation="delete_sync").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            _fallback_delete(key)
            return
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=True)

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
