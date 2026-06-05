from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import zlib
import base64
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
    from redis.asyncio.sentinel import Sentinel as AsyncSentinel
except ImportError:
    AsyncSentinel = None

try:
    from redis.sentinel import Sentinel as SyncSentinel
except ImportError:
    SyncSentinel = None

try:
    import orjson
except ImportError:
    orjson = None

from stockai_shared.config.config import (
    REDIS_URL,
    REDIS_MASTER_NAME,
    REDIS_SENTINELS,
    REDIS_REPLICA_URL,
    REDIS_TLS_SKIP_VERIFY,
)

logger = logging.getLogger(__name__)

SESSION_KEY = "smartapi_session"
SESSION_TTL_SECONDS = 24 * 60 * 60
_REDIS_RETRY_INTERVAL_SECONDS = 2

# Async redis client states
_async_redis: Optional[Any] = None
_async_replica: Optional[Any] = None
_async_failed = False
_async_replica_failed = False
_async_last_attempt: float = 0.0
_async_replica_last_attempt: float = 0.0
asyncio_lock = None
asyncio_replica_lock = None

# Sync redis client states
_sync_redis: Optional[Any] = None
_sync_replica: Optional[Any] = None
_sync_failed = False
_sync_replica_failed = False
_sync_last_attempt: float = 0.0
_sync_replica_last_attempt: float = 0.0
_sync_lock = threading.Lock()
_sync_replica_lock = threading.Lock()

# In-memory fallback shared by async/sync paths
_fallback_cache: dict[str, tuple[str, float]] = {}
_fallback_lock = threading.Lock()
_fallback_cleanup_task: Optional[asyncio.Task] = None


async def _fallback_cleanup_loop() -> None:
    """Background task to periodically prune expired fallback cache entries to avoid memory leak."""
    logger.info("[REDIS] Starting background fallback cache cleanup loop.")
    try:
        while True:
            await asyncio.sleep(60.0)
            now = time.monotonic()
            with _fallback_lock:
                expired_keys = [
                    key for key, (_, expires_at) in _fallback_cache.items()
                    if now > expires_at
                ]
                for key in expired_keys:
                    _fallback_cache.pop(key, None)
            if expired_keys:
                logger.debug(
                    "[REDIS] Fallback cache GC swept %d expired keys.",
                    len(expired_keys)
                )
    except asyncio.CancelledError:
        logger.info("[REDIS] Background fallback cache cleanup loop cancelled.")
    except Exception as exc:
        logger.error("[REDIS] Background fallback cache cleanup loop error: %s", exc, exc_info=True)


# Lazily create asyncio locks only when needed (requires running event loop context)
def _get_async_lock():
    global asyncio_lock
    if asyncio_lock is None:
        asyncio_lock = asyncio.Lock()
    return asyncio_lock


def _get_async_replica_lock():
    global asyncio_replica_lock
    if asyncio_replica_lock is None:
        asyncio_replica_lock = asyncio.Lock()
    return asyncio_replica_lock


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


def normalize_key(key: str) -> str:
    if key.startswith("snap:v4:"):
        rest = key[len("snap:v4:"):]
        return f"stockai:latest:tick:{rest}"
    return key


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        timestamp = value.get("timestamp")
        last_ts = value.get("last_ts")
        if timestamp and not last_ts:
            value = dict(value)
            value["last_ts"] = timestamp
        elif last_ts and not timestamp:
            value = dict(value)
            value["timestamp"] = last_ts
    return value


COMPRESSION_PREFIX = "zlib_b64:"
COMPRESSION_THRESHOLD = 50 * 1024  # 50 KB


def _serialize_and_compress(value: Any) -> str:
    normalized_val = _normalize_payload(value)
    serialized = _serialize(normalized_val)
    if len(serialized) > COMPRESSION_THRESHOLD:
        compressed = zlib.compress(serialized.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("utf-8")
        return f"{COMPRESSION_PREFIX}{encoded}"
    return serialized


def _decompress_and_deserialize(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(COMPRESSION_PREFIX):
        encoded = value[len(COMPRESSION_PREFIX):]
        compressed = base64.b64decode(encoded.encode("utf-8"))
        decompressed = zlib.decompress(compressed).decode("utf-8")
        return _deserialize(decompressed)
    return _deserialize(value)


_hits_count = 0
_misses_count = 0
_metrics_lock = threading.Lock()


def _record_cache_hit_or_miss(is_hit: bool):
    global _hits_count, _misses_count
    with _metrics_lock:
        if is_hit:
            _hits_count += 1
            try:
                from stockai_shared.metrics.metrics import CACHE_HITS_TOTAL
                CACHE_HITS_TOTAL.inc()
            except Exception:
                pass
        else:
            _misses_count += 1
            try:
                from stockai_shared.metrics.metrics import CACHE_MISSES_TOTAL
                CACHE_MISSES_TOTAL.inc()
            except Exception:
                pass
        
        total = _hits_count + _misses_count
        if total > 0:
            ratio = _hits_count / total
            try:
                from stockai_shared.metrics.metrics import CACHE_HIT_RATIO
                CACHE_HIT_RATIO.set(ratio)
            except Exception:
                pass



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


def _get_ssl_options(url: str) -> dict[str, Any]:
    ssl_opts = {}
    if url.startswith("rediss://"):
        ssl_opts["ssl"] = True
        if REDIS_TLS_SKIP_VERIFY:
            ssl_opts["ssl_cert_reqs"] = "none"
        else:
            ssl_opts["ssl_cert_reqs"] = "required"
    return ssl_opts


def _parse_sentinels() -> list[tuple[str, int]]:
    hosts = []
    if not REDIS_SENTINELS:
        return hosts
    for s in REDIS_SENTINELS.split(","):
        s = s.strip()
        if not s:
            continue
        if ":" in s:
            host, port = s.rsplit(":", 1)
            try:
                hosts.append((host, int(port)))
            except ValueError:
                hosts.append((host, 26379))
        else:
            hosts.append((s, 26379))
    return hosts


def _trigger_circuit_breaker(exc: Exception, is_sync: bool = False) -> None:
    global _async_redis, _async_replica, _async_failed, _async_replica_failed
    global _sync_redis, _sync_replica, _sync_failed, _sync_replica_failed, _degraded_mode_active
    from stockai_shared.metrics.metrics import REDIS_DEGRADED_MODE

    _degraded_mode_active = True
    try:
        REDIS_DEGRADED_MODE.set(1)
    except Exception:
        pass

    if is_sync:
        _sync_redis = None
        _sync_replica = None
        _sync_failed = True
        _sync_replica_failed = True
        logger.error(
            "[REDIS][CIRCUIT-BREAKER] Sync Redis connection dropped: %s. Switched to Degraded Fallback mode.",
            type(exc).__name__,
        )
    else:
        _async_redis = None
        _async_replica = None
        _async_failed = True
        _async_replica_failed = True
        logger.error(
            "[REDIS][CIRCUIT-BREAKER] Async Redis connection dropped: %s. Switched to Degraded Fallback mode.",
            type(exc).__name__,
        )


import contextlib

@contextlib.asynccontextmanager
async def distributed_job_lock(job_name: str, lock_ttl_seconds: int = 50):
    """Enforces that a cron job runs on only one microservice instance using a Redis distributed lock."""
    redis_client = await get_redis()
    acquired = False
    lock_key = f"stockai:scheduler:lock:{job_name}"
    
    if redis_client:
        try:
            res = await redis_client.set(lock_key, "1", nx=True, ex=lock_ttl_seconds)
            if res:
                acquired = True
        except Exception as e:
            logger.warning("[SCHEDULER-LOCK] Failed to acquire Redis lock for %s: %s", job_name, e)
            acquired = True
    else:
        acquired = True
        
    try:
        yield acquired
    finally:
        pass


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
            sentinel_hosts = _parse_sentinels()
            ssl_opts = _get_ssl_options(REDIS_URL)

            if sentinel_hosts and AsyncSentinel is not None:
                logger.info("[REDIS] Connecting to async Sentinel hosts: %s", sentinel_hosts)
                sentinel_kwargs = {
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                }
                if ssl_opts:
                    sentinel_kwargs.update(ssl_opts)

                sentinel = AsyncSentinel(sentinel_hosts, sentinel_kwargs=sentinel_kwargs)

                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(ssl_opts)
                client = sentinel.master_for(REDIS_MASTER_NAME, **connection_kwargs)
            else:
                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(ssl_opts)
                client = redis_asyncio.from_url(REDIS_URL, **connection_kwargs)

            await client.ping()
            _async_redis = client
            _async_failed = False
            _degraded_mode_active = False
            try:
                from stockai_shared.metrics.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(0)
            except Exception:
                pass
            logger.info("[REDIS] async connected & circuit breaker reset")
        except Exception as exc:
            _async_redis = None
            _async_failed = True
            _degraded_mode_active = True
            try:
                from stockai_shared.metrics.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(1)
            except Exception:
                pass
            logger.warning("[REDIS] async connection failed, fallback mode: %s", type(exc).__name__)

    return _async_redis


async def _get_replica_redis(*, force_retry: bool = False) -> Optional[Any]:
    global _async_replica, _async_replica_failed, _async_replica_last_attempt

    if _async_replica is not None:
        return _async_replica

    if redis_asyncio is None:
        return None

    lock = _get_async_replica_lock()
    async with lock:
        if _async_replica is not None:
            return _async_replica

        now = time.monotonic()
        if (
            _async_replica_failed
            and not force_retry
            and (now - _async_replica_last_attempt) < _REDIS_RETRY_INTERVAL_SECONDS
        ):
            return await get_redis()

        _async_replica_last_attempt = now

        try:
            sentinel_hosts = _parse_sentinels()
            ssl_opts = _get_ssl_options(REDIS_REPLICA_URL or REDIS_URL)

            if sentinel_hosts and AsyncSentinel is not None:
                sentinel_kwargs = {
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                }
                if _get_ssl_options(REDIS_URL):
                    sentinel_kwargs.update(_get_ssl_options(REDIS_URL))

                sentinel = AsyncSentinel(sentinel_hosts, sentinel_kwargs=sentinel_kwargs)

                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(_get_ssl_options(REDIS_URL))
                client = sentinel.slave_for(REDIS_MASTER_NAME, **connection_kwargs)
            elif REDIS_REPLICA_URL:
                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(ssl_opts)
                client = redis_asyncio.from_url(REDIS_REPLICA_URL, **connection_kwargs)
            else:
                _async_replica = await get_redis()
                return _async_replica

            await client.ping()
            _async_replica = client
            _async_replica_failed = False
            logger.info("[REDIS] async replica connected successfully")
        except Exception as exc:
            logger.warning("[REDIS] async replica connection failed: %s. Using master fallback.", exc)
            _async_replica = None
            _async_replica_failed = True
            return await get_redis()

    return _async_replica


async def initialize_redis(
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> str:
    global _fallback_cleanup_task
    try:
        if _fallback_cleanup_task is None or _fallback_cleanup_task.done():
            _fallback_cleanup_task = asyncio.create_task(_fallback_cleanup_loop())
    except Exception as e:
        logger.warning("[REDIS] Could not start fallback cache cleanup loop: %s", e)

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
            sentinel_hosts = _parse_sentinels()
            ssl_opts = _get_ssl_options(REDIS_URL)

            if sentinel_hosts and SyncSentinel is not None:
                logger.info("[REDIS] Connecting to sync Sentinel hosts: %s", sentinel_hosts)
                sentinel_kwargs = {
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                }
                if ssl_opts:
                    sentinel_kwargs.update(ssl_opts)
                sentinel = SyncSentinel(sentinel_hosts, sentinel_kwargs=sentinel_kwargs)

                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(ssl_opts)
                client = sentinel.master_for(REDIS_MASTER_NAME, **connection_kwargs)
            else:
                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(ssl_opts)
                client = redis.Redis.from_url(REDIS_URL, **connection_kwargs)

            client.ping()
            _sync_redis = client
            _sync_failed = False
            _degraded_mode_active = False
            try:
                from stockai_shared.metrics.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(0)
            except Exception:
                pass
            logger.info("[REDIS] sync connected & circuit breaker reset")
        except Exception as exc:
            _sync_redis = None
            _sync_failed = True
            _degraded_mode_active = True
            try:
                from stockai_shared.metrics.metrics import REDIS_DEGRADED_MODE
                REDIS_DEGRADED_MODE.set(1)
            except Exception:
                pass
            logger.warning("[REDIS] sync connection failed, fallback mode: %s", type(exc).__name__)

    return _sync_redis


def get_replica_redis_sync() -> Optional[Any]:
    global _sync_replica, _sync_replica_failed, _sync_replica_last_attempt

    if _sync_replica is not None:
        return _sync_replica

    if redis is None:
        return None

    with _sync_replica_lock:
        if _sync_replica is not None:
            return _sync_replica

        now = time.monotonic()
        if _sync_replica_failed and (now - _sync_replica_last_attempt) < _REDIS_RETRY_INTERVAL_SECONDS:
            return get_redis_sync()

        _sync_replica_last_attempt = now

        try:
            sentinel_hosts = _parse_sentinels()
            ssl_opts = _get_ssl_options(REDIS_REPLICA_URL or REDIS_URL)

            if sentinel_hosts and SyncSentinel is not None:
                sentinel_kwargs = {
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                }
                if _get_ssl_options(REDIS_URL):
                    sentinel_kwargs.update(_get_ssl_options(REDIS_URL))
                sentinel = SyncSentinel(sentinel_hosts, sentinel_kwargs=sentinel_kwargs)

                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(_get_ssl_options(REDIS_URL))
                client = sentinel.slave_for(REDIS_MASTER_NAME, **connection_kwargs)
            elif REDIS_REPLICA_URL:
                connection_kwargs = {
                    "decode_responses": True,
                    "socket_connect_timeout": 2,
                    "socket_timeout": 2,
                    "health_check_interval": 30,
                }
                connection_kwargs.update(ssl_opts)
                client = redis.Redis.from_url(REDIS_REPLICA_URL, **connection_kwargs)
            else:
                _sync_replica = get_redis_sync()
                return _sync_replica

            client.ping()
            _sync_replica = client
            _sync_replica_failed = False
            logger.info("[REDIS] sync replica connected successfully")
        except Exception as exc:
            logger.warning("[REDIS] sync replica connection failed: %s. Using master fallback.", exc)
            _sync_replica = None
            _sync_replica_failed = True
            return get_redis_sync()

    return _sync_replica

async def set_cache(key: str, value: Any, ttl: int = 60) -> None:
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    key = normalize_key(key)
    
    if not _degraded_mode_active:
        redis_client = await get_redis()
        
    if redis_client:
        try:
            await redis_client.setex(key, max(1, int(ttl)), _serialize_and_compress(value))
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


async def set_cache_batch(mapping: dict[str, Any], ttl: int = 60) -> None:
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    
    if not _degraded_mode_active:
        redis_client = await get_redis()
        
    if redis_client:
        try:
            async with redis_client.pipeline(transaction=False) as pipe:
                for key, value in mapping.items():
                    pipe.setex(normalize_key(key), max(1, int(ttl)), _serialize_and_compress(value))
                await pipe.execute()
            logger.debug("[CACHE] pipelined set %d keys backend=redis", len(mapping))
            try:
                REDIS_OPERATION_LATENCY.labels(operation="set_batch").observe(time.perf_counter() - start_time)
            except Exception:
                pass
            return
        except Exception as exc:
            _trigger_circuit_breaker(exc, is_sync=False)

    for key, value in mapping.items():
        _fallback_set(normalize_key(key), value, ttl)
    logger.debug("[CACHE] pipelined set %d keys backend=fallback", len(mapping))



async def get_cache(key: str) -> Optional[Any]:
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    value = None
    read_success = False
    key = normalize_key(key)
    
    if not _degraded_mode_active:
        # Try replica first
        try:
            replica_client = await _get_replica_redis()
            if replica_client:
                value = await replica_client.get(key)
                read_success = True
        except Exception as replica_exc:
            logger.warning("[REDIS] Replica read failed for key %s, trying master fallback: %s", key, replica_exc)
            
        # Fallback to master if replica failed or was not available
        if not read_success:
            try:
                master_client = await get_redis()
                if master_client:
                    value = await master_client.get(key)
                    read_success = True
            except Exception as master_exc:
                _trigger_circuit_breaker(master_exc, is_sync=False)

    if read_success:
        try:
            REDIS_OPERATION_LATENCY.labels(operation="get").observe(time.perf_counter() - start_time)
        except Exception:
            pass
        if value is not None:
            logger.debug("[CACHE] hit key=%s backend=redis", key)
            _record_cache_hit_or_miss(True)
            return _decompress_and_deserialize(value)
        logger.debug("[CACHE] miss key=%s backend=redis", key)
        _record_cache_hit_or_miss(False)
        return None

    value = _fallback_get(key)
    if value is not None:
        logger.debug("[CACHE] hit key=%s backend=fallback", key)
        _record_cache_hit_or_miss(True)
    else:
        logger.debug("[CACHE] miss key=%s backend=fallback", key)
        _record_cache_hit_or_miss(False)
    return value


async def delete_cache(key: str) -> None:
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    key = normalize_key(key)
    
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
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    key = normalize_key(key)
    
    if not _degraded_mode_active:
        redis_client = get_redis_sync()
        
    if redis_client:
        try:
            redis_client.setex(key, max(1, int(ttl)), _serialize_and_compress(value))
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
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    value = None
    read_success = False
    key = normalize_key(key)
    
    if not _degraded_mode_active:
        # Try replica first
        try:
            replica_client = get_replica_redis_sync()
            if replica_client:
                value = replica_client.get(key)
                read_success = True
        except Exception as replica_exc:
            logger.warning("[REDIS] Sync replica read failed for key %s, trying master fallback: %s", key, replica_exc)
            
        # Fallback to master if replica failed or was not available
        if not read_success:
            try:
                master_client = get_redis_sync()
                if master_client:
                    value = master_client.get(key)
                    read_success = True
            except Exception as master_exc:
                _trigger_circuit_breaker(master_exc, is_sync=True)

    if read_success:
        try:
            REDIS_OPERATION_LATENCY.labels(operation="get_sync").observe(time.perf_counter() - start_time)
        except Exception:
            pass
        if value is not None:
            logger.debug("[CACHE] hit key=%s backend=redis-sync", key)
            _record_cache_hit_or_miss(True)
            return _decompress_and_deserialize(value)
        logger.debug("[CACHE] miss key=%s backend=redis-sync", key)
        _record_cache_hit_or_miss(False)
        return None

    value = _fallback_get(key)
    if value is not None:
        logger.debug("[CACHE] hit key=%s backend=fallback", key)
        _record_cache_hit_or_miss(True)
    else:
        logger.debug("[CACHE] miss key=%s backend=fallback", key)
        _record_cache_hit_or_miss(False)
    return value


def delete_cache_sync(key: str) -> None:
    from stockai_shared.metrics.metrics import REDIS_OPERATION_LATENCY
    
    start_time = time.perf_counter()
    redis_client = None
    key = normalize_key(key)
    
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


_local_rate_limits: dict[str, list[float]] = {}
_local_rate_lock = threading.Lock()


def _fallback_rate_limit(key: str, limit: int, window: int) -> bool:
    now = time.time()
    with _local_rate_lock:
        timestamps = _local_rate_limits.setdefault(key, [])
        # Filter stale timestamps
        timestamps = [t for t in timestamps if now - t < window]
        if len(timestamps) >= limit:
            _local_rate_limits[key] = timestamps
            return False
        timestamps.append(now)
        _local_rate_limits[key] = timestamps
        return True


async def check_rate_limit(key: str, limit: int, window: int = 60) -> bool:
    """
    Check if the rate limit for a key is exceeded.
    Returns True if allowed (under limit), False if rate-limited (over limit).
    """
    redis_client = await get_redis()
    if not redis_client:
        return _fallback_rate_limit(key, limit, window)
        
    try:
        now = int(time.time())
        window_bucket = now // window
        redis_key = f"rate_limit:{key}:{window_bucket}"
        
        async with redis_client.pipeline(transaction=False) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window + 10)
            res = await pipe.execute()
            
        count = res[0]
        return count <= limit
    except Exception as e:
        logger.warning("[REDIS] Rate limiter failed, falling back to memory: %s", e)
        return _fallback_rate_limit(key, limit, window)


async def blacklist_access_token(token: str, expires_in_seconds: int) -> None:
    """Blacklist an access token upon user logout."""
    if expires_in_seconds <= 0:
        return
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    redis_key = f"jwt_blacklist:{token_hash}"
    logger.warning(f"[BLACKLIST] Revoking token: {token[:15]}... Key: {redis_key}")
    await set_cache(redis_key, "revoked", ttl=expires_in_seconds)


async def is_access_token_blacklisted(token: str) -> bool:
    """Check if an access token has been blacklisted/revoked."""
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    redis_key = f"jwt_blacklist:{token_hash}"
    val = await get_cache(redis_key)
    logger.warning(f"[BLACKLIST-CHECK] Checking token: {token[:15]}... Key: {redis_key} -> Value: {val}")
    return val == "revoked"

