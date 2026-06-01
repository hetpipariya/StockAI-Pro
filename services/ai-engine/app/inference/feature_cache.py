"""
Redis Cache Layer for Production Scaling (Asynchronous Version)
==============================================================

Implements production-grade asynchronous caching for:
1. Feature computation results (per symbol)
2. Signal results (per symbol)
3. NIFTY context data
4. Pub/Sub broadcast architecture
5. Stale-cache fallback
6. Cache warming

Designed for:
- 1000+ concurrent users
- No per-user computation duplication
- Sub-100ms cache hits
- Graceful degradation
- Async-safety under load

Version: v2.0
Updated: 2026-05-25
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

try:
    import orjson
except ImportError:
    orjson = None

import json

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ────────────────────────────────────────────────────────────────────────────

CACHE_VERSION = "v1.0"

# Cache TTL (Time-To-Live) in seconds
FEATURE_CACHE_TTL = 8  # Features valid for 8 seconds
SIGNAL_CACHE_TTL = 5  # Signals valid for 5 seconds
NIFTY_CACHE_TTL = 30  # NIFTY context cached for 30s
SNAPSHOT_CACHE_TTL = 10  # Price snapshot cached for 10s

# Stale cache fallback (if fresh cache unavailable)
STALE_FEATURE_CACHE_TTL = 60  # Fallback to stale feature data up to 60s
STALE_SIGNAL_CACHE_TTL = 30  # Fallback to stale signal data up to 30s

# Cache key prefixes
KEY_FEATURES = "features"  # features:{symbol}:{interval}
KEY_SIGNAL = "signal"  # signal:{symbol}:{interval}
KEY_NIFTY = "nifty"  # nifty:{date}
KEY_SNAPSHOT = "snapshot"  # snapshot:{symbol}
KEY_TIMESTAMP = "ts"  # ts:{symbol}:{type} (last update time)


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    if orjson is not None:
        try:
            return orjson.dumps(value).decode("utf-8")
        except Exception:
            pass
    return json.dumps(value, default=str)


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


# ────────────────────────────────────────────────────────────────────────────
# CACHE MANAGER
# ────────────────────────────────────────────────────────────────────────────


class RedisFeatureCache:
    """Redis-backed asynchronous cache for features and signals."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50,
        socket_connect_timeout: int = 5,
        socket_timeout: int = 5,
    ):
        """
        Initialize asynchronous Redis cache.
        """
        if aioredis is None:
            logger.error("[CACHE] redis.asyncio is not available. RedisFeatureCache degraded.")
            self.redis = None
            self.available = False
            return

        try:
            pool = aioredis.ConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                socket_connect_timeout=socket_connect_timeout,
                socket_timeout=socket_timeout,
                decode_responses=True,
            )
            self.redis = aioredis.Redis(connection_pool=pool)
            self.available = True
            logger.info(f"[CACHE] Async Redis client initialized for {host}:{port}")
        except Exception as exc:
            logger.error(f"[CACHE] Async Redis pool creation failed: {exc}")
            self.redis = None
            self.available = False

    def _make_key(self, key_type: str, symbol: str, interval: str = "5m") -> str:
        """Build cache key."""
        return f"{key_type}:{symbol.upper()}:{interval}"

    def _make_ts_key(self, key_type: str, symbol: str, interval: str = "5m") -> str:
        """Build timestamp tracking key."""
        return f"{KEY_TIMESTAMP}:{key_type}:{symbol.upper()}:{interval}"

    # ────────────────────────────────────────────────────────────────
    # FEATURE CACHING
    # ────────────────────────────────────────────────────────────────

    async def get_features(self, symbol: str, interval: str = "5m") -> Optional[dict]:
        """
        Get cached features for symbol asynchronously.
        """
        if not self.available or self.redis is None:
            return None

        try:
            key = self._make_key(KEY_FEATURES, symbol, interval)
            data = await self.redis.get(key)
            if data:
                return _deserialize(data)
        except Exception as exc:
            logger.debug(f"[CACHE] Async feature read failed for {symbol}: {exc}")

        return None

    async def set_features(self, symbol: str, features: dict, interval: str = "5m", ttl: int = FEATURE_CACHE_TTL):
        """
        Cache computed features asynchronously.
        """
        if not self.available or self.redis is None:
            return False

        try:
            key = self._make_key(KEY_FEATURES, symbol, interval)
            ts_key = self._make_ts_key(KEY_FEATURES, symbol, interval)

            # Serialize features
            data = _serialize(features)

            # Set with TTL
            await self.redis.setex(key, ttl, data)
            await self.redis.setex(ts_key, ttl * 2, datetime.now().isoformat())

            return True
        except Exception as exc:
            logger.debug(f"[CACHE] Async feature write failed for {symbol}: {exc}")
            return False

    async def get_features_stale(self, symbol: str, interval: str = "5m") -> Optional[dict]:
        """
        Get stale cached features asynchronously (fallback when fresh unavailable).
        """
        if not self.available or self.redis is None:
            return None

        try:
            key = self._make_key(KEY_FEATURES, symbol, interval)
            data = await self.redis.get(key)
            if data:
                await self.redis.expire(key, STALE_FEATURE_CACHE_TTL)
                return _deserialize(data)
        except Exception as exc:
            logger.debug(f"[CACHE] Async stale feature read failed: {exc}")

        return None

    # ────────────────────────────────────────────────────────────────
    # SIGNAL CACHING
    # ────────────────────────────────────────────────────────────────

    async def get_signal(self, symbol: str, interval: str = "5m") -> Optional[dict]:
        """
        Get cached signal for symbol asynchronously.
        """
        if not self.available or self.redis is None:
            return None

        try:
            key = self._make_key(KEY_SIGNAL, symbol, interval)
            data = await self.redis.get(key)
            if data:
                return _deserialize(data)
        except Exception as exc:
            logger.debug(f"[CACHE] Async signal read failed for {symbol}: {exc}")

        return None

    async def set_signal(self, symbol: str, signal_dict: dict, interval: str = "5m", ttl: int = SIGNAL_CACHE_TTL):
        """
        Cache computed signal asynchronously.
        """
        if not self.available or self.redis is None:
            return False

        try:
            key = self._make_key(KEY_SIGNAL, symbol, interval)
            ts_key = self._make_ts_key(KEY_SIGNAL, symbol, interval)

            data = _serialize(signal_dict)
            await self.redis.setex(key, ttl, data)
            await self.redis.setex(ts_key, ttl * 2, datetime.now().isoformat())

            return True
        except Exception as exc:
            logger.debug(f"[CACHE] Async signal write failed for {symbol}: {exc}")
            return False

    # ────────────────────────────────────────────────────────────────
    # NIFTY CONTEXT CACHING
    # ────────────────────────────────────────────────────────────────

    async def get_nifty_context(self) -> Optional[dict]:
        """
        Get cached NIFTY context asynchronously (shared across all users).
        """
        if not self.available or self.redis is None:
            return None

        try:
            key = f"{KEY_NIFTY}:{datetime.now().strftime('%Y-%m-%d')}"
            data = await self.redis.get(key)
            if data:
                return _deserialize(data)
        except Exception as exc:
            logger.debug(f"[CACHE] Async NIFTY read failed: {exc}")

        return None

    async def set_nifty_context(self, nifty_dict: dict, ttl: int = NIFTY_CACHE_TTL):
        """
        Cache NIFTY context data asynchronously.
        """
        if not self.available or self.redis is None:
            return False

        try:
            key = f"{KEY_NIFTY}:{datetime.now().strftime('%Y-%m-%d')}"
            data = _serialize(nifty_dict)
            await self.redis.setex(key, ttl, data)
            return True
        except Exception as exc:
            logger.debug(f"[CACHE] Async NIFTY write failed: {exc}")
            return False

    # ────────────────────────────────────────────────────────────────
    # PUB/SUB FOR WEBSOCKET BROADCAST
    # ────────────────────────────────────────────────────────────────

    async def publish_signal(self, symbol: str, signal_dict: dict, interval: str = "5m"):
        """
        Publish signal to pub/sub channel asynchronously for WebSocket broadcast.
        """
        if not self.available or self.redis is None:
            return False

        try:
            channel = f"signal:{symbol.upper()}:{interval}"
            data = _serialize(signal_dict)
            await self.redis.publish(channel, data)
            return True
        except Exception as exc:
            logger.debug(f"[CACHE] Async publish failed for {symbol}: {exc}")
            return False

    async def subscribe_signals(self, symbols: list[str], interval: str = "5m"):
        """
        Subscribe to signal channels asynchronously.
        """
        if not self.available or self.redis is None:
            return None

        try:
            pubsub = self.redis.pubsub()
            for symbol in symbols:
                channel = f"signal:{symbol.upper()}:{interval}"
                await pubsub.subscribe(channel)
            return pubsub
        except Exception as exc:
            logger.debug(f"[CACHE] Async subscribe failed: {exc}")
            return None

    # ────────────────────────────────────────────────────────────────
    # STATISTICS & MONITORING
    # ────────────────────────────────────────────────────────────────

    async def get_cache_stats(self) -> dict:
        """Get cache statistics asynchronously."""
        if not self.available or self.redis is None:
            return {"available": False}

        try:
            info = await self.redis.info()
            return {
                "available": True,
                "memory_used": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands": info.get("total_commands_processed", 0),
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
            }
        except Exception as exc:
            logger.debug(f"[CACHE] Async stats failed: {exc}")
            return {"available": False, "error": str(exc)}

    async def clear_cache(self, pattern: Optional[str] = None):
        """
        Clear cache entries asynchronously.
        """
        if not self.available or self.redis is None:
            return False

        try:
            if pattern:
                keys = await self.redis.keys(pattern)
                if keys:
                    await self.redis.delete(*keys)
                    logger.info(f"[CACHE] Async cleared {len(keys)} keys matching {pattern}")
            else:
                await self.redis.flushdb()
                logger.info("[CACHE] Async cleared all cache")
            return True
        except Exception as exc:
            logger.error(f"[CACHE] Async clear failed: {exc}")
            return False

    async def health_check(self) -> bool:
        """Check Redis connectivity asynchronously."""
        if not self.available or self.redis is None:
            return False

        try:
            await self.redis.ping()
            return True
        except Exception as exc:
            logger.debug(f"[CACHE] Async health check failed: {exc}")
            return False


# ────────────────────────────────────────────────────────────────────────────
# IN-MEMORY FALLBACK CACHE
# ────────────────────────────────────────────────────────────────────────────


class InMemoryFeatureCache:
    """
    Simple in-memory fallback cache when Redis unavailable.
    Provides async compatibility interfaces.
    """

    def __init__(self):
        self.features_cache = {}
        self.signal_cache = {}
        self.nifty_cache = None
        self.nifty_cache_time = None
        self.ttl_map = {}  # Track expiry times

    async def get_features(self, symbol: str, interval: str = "5m") -> Optional[dict]:
        """Get cached features (in-memory)."""
        key = f"{KEY_FEATURES}:{symbol}:{interval}"
        if key in self.features_cache:
            expiry = self.ttl_map.get(key)
            if expiry and datetime.now() < expiry:
                return self.features_cache[key]
            else:
                del self.features_cache[key]
        return None

    async def set_features(self, symbol: str, features: dict, interval: str = "5m", ttl: int = FEATURE_CACHE_TTL):
        """Set features in memory."""
        key = f"{KEY_FEATURES}:{symbol}:{interval}"
        self.features_cache[key] = features
        self.ttl_map[key] = datetime.now() + timedelta(seconds=ttl)

    async def get_signal(self, symbol: str, interval: str = "5m") -> Optional[dict]:
        """Get cached signal (in-memory)."""
        key = f"{KEY_SIGNAL}:{symbol}:{interval}"
        if key in self.signal_cache:
            expiry = self.ttl_map.get(key)
            if expiry and datetime.now() < expiry:
                return self.signal_cache[key]
            else:
                del self.signal_cache[key]
        return None

    async def set_signal(self, symbol: str, signal_dict: dict, interval: str = "5m", ttl: int = SIGNAL_CACHE_TTL):
        """Set signal in memory."""
        key = f"{KEY_SIGNAL}:{symbol}:{interval}"
        self.signal_cache[key] = signal_dict
        self.ttl_map[key] = datetime.now() + timedelta(seconds=ttl)

    async def health_check(self) -> bool:
        """In-memory cache always available."""
        return True
