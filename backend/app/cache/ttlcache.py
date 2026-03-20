"""In-memory LRU TTL cache for market snapshots and features."""
from __future__ import annotations

import time
from typing import Any, Optional
from threading import Lock

_default_ttl = 60  # seconds
_default_maxsize = 1000


class TTLCache:
    def __init__(self, maxsize: int = _default_maxsize, ttl: int = _default_ttl):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._order: list[str] = []
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            val, ts = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                if key in self._order:
                    self._order.remove(key)
                return None
            return val

    def set(self, key: str, value: Any):
        with self._lock:
            if key in self._order:
                self._order.remove(key)
            elif len(self._order) >= self._maxsize:
                oldest = self._order.pop(0)
                self._cache.pop(oldest, None)
            self._cache[key] = (value, time.time())
            self._order.append(key)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
            if key in self._order:
                self._order.remove(key)
