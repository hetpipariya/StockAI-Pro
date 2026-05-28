"""
Enterprise-grade Prometheus metrics for StockAI Pro SRE observability.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram
except ImportError:
    # Safe fallback if prometheus_client is not installed/configured
    Counter = lambda name, desc, *args, **kwargs: DummyMetric()
    Gauge = lambda name, desc, *args, **kwargs: DummyMetric()
    Histogram = lambda name, desc, *args, **kwargs: DummyMetric()


class DummyMetric:
    """Fallback class that acts as a no-op when prometheus_client is missing."""
    def __init__(self, *args, **kwargs):
        pass

    def labels(self, *args, **kwargs) -> DummyMetric:
        return self

    def inc(self, amount: float = 1) -> None:
        pass

    def dec(self, amount: float = 1) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def observe(self, value: float) -> None:
        pass


# WebSocket Subsystem Metrics
WS_CONNECTIONS = Gauge(
    "stockai_ws_connections_active",
    "Number of currently active WebSocket clients"
)
WS_ROOM_SUBSCRIBERS = Gauge(
    "stockai_ws_room_subscribers_active",
    "Number of active client subscriptions in a symbol room",
    ["symbol"]
)
WS_RECONNECT_ATTEMPTS = Counter(
    "stockai_ws_reconnect_attempts_total",
    "Total WebSocket reconnect attempts to SmartAPI broker"
)
WS_THROTTLED_CONNECTIONS = Counter(
    "stockai_ws_throttled_connections_total",
    "Total number of WebSocket connections rejected by IP rate-limiting"
)

# Redis / Caching Subsystem Metrics
REDIS_OPERATION_LATENCY = Histogram(
    "stockai_redis_operation_latency_seconds",
    "Latency of Redis operations (get, set, delete) in seconds",
    ["operation"]
)
REDIS_DEGRADED_MODE = Gauge(
    "stockai_redis_degraded_mode_status",
    "Redis connection status (0 = healthy, 1 = degraded memory fallback)"
)

# Database Subsystem Metrics
DB_QUERY_LATENCY = Histogram(
    "stockai_db_query_latency_seconds",
    "Database query execution latency in seconds",
    ["operation"]
)
DB_TRANSIENT_RETRIES = Counter(
    "stockai_db_transient_retries_total",
    "Total number of database transaction retries triggered by transient errors"
)

# ML Inference Pipeline Metrics
ML_INFERENCE_LATENCY = Histogram(
    "stockai_ml_inference_latency_seconds",
    "ML model inference end-to-end latency in seconds",
    ["symbol"]
)
ML_ACTIVE_WORKERS = Gauge(
    "stockai_ml_active_workers_count",
    "Number of running ML CPU offloading worker processes"
)
ML_WORKER_HEARTBEAT = Gauge(
    "stockai_ml_worker_heartbeat_status",
    "ML worker execution pool health state (1 = healthy, 0 = crashed/broken)"
)
ML_FALLBACK_SIGNALS = Counter(
    "stockai_ml_fallback_signals_total",
    "Total number of fallback HOLD signals generated due to inference errors"
)
