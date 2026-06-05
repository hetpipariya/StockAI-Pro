"""
Enterprise-grade Prometheus metrics for StockAI Pro SRE observability.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram, REGISTRY
except ImportError:
    # Safe fallback if prometheus_client is not installed/configured
    Counter = lambda name, desc, *args, **kwargs: DummyMetric()
    Gauge = lambda name, desc, *args, **kwargs: DummyMetric()
    Histogram = lambda name, desc, *args, **kwargs: DummyMetric()
    REGISTRY = None


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


def safe_gauge(name: str, desc: str, *args, **kwargs) -> Any:
    if REGISTRY is not None and hasattr(REGISTRY, "_names_to_collectors"):
        if name in REGISTRY._names_to_collectors:
            return REGISTRY._names_to_collectors[name]
    return Gauge(name, desc, *args, **kwargs)


def safe_counter(name: str, desc: str, *args, **kwargs) -> Any:
    if REGISTRY is not None and hasattr(REGISTRY, "_names_to_collectors"):
        if name in REGISTRY._names_to_collectors:
            return REGISTRY._names_to_collectors[name]
    return Counter(name, desc, *args, **kwargs)


def safe_histogram(name: str, desc: str, *args, **kwargs) -> Any:
    if REGISTRY is not None and hasattr(REGISTRY, "_names_to_collectors"):
        if name in REGISTRY._names_to_collectors:
            return REGISTRY._names_to_collectors[name]
    return Histogram(name, desc, *args, **kwargs)


# WebSocket Subsystem Metrics
WS_CONNECTIONS = safe_gauge(
    "stockai_ws_connections_active",
    "Number of currently active WebSocket clients"
)
WS_ROOM_SUBSCRIBERS = safe_gauge(
    "stockai_ws_room_subscribers_active",
    "Number of active client subscriptions in a symbol room",
    ["symbol"]
)
WS_RECONNECT_ATTEMPTS = safe_counter(
    "stockai_ws_reconnect_attempts_total",
    "Total WebSocket reconnect attempts to SmartAPI broker"
)
WS_THROTTLED_CONNECTIONS = safe_counter(
    "stockai_ws_throttled_connections_total",
    "Total number of WebSocket connections rejected by IP rate-limiting"
)

# Redis / Caching Subsystem Metrics
REDIS_OPERATION_LATENCY = safe_histogram(
    "stockai_redis_operation_latency_seconds",
    "Latency of Redis operations (get, set, delete) in seconds",
    ["operation"]
)
REDIS_DEGRADED_MODE = safe_gauge(
    "stockai_redis_degraded_mode_status",
    "Redis connection status (0 = healthy, 1 = degraded memory fallback)"
)

# Database Subsystem Metrics
DB_QUERY_LATENCY = safe_histogram(
    "stockai_db_query_latency_seconds",
    "Database query execution latency in seconds",
    ["operation"]
)
DB_TRANSIENT_RETRIES = safe_counter(
    "stockai_db_transient_retries_total",
    "Total number of database transaction retries triggered by transient errors"
)

# ML Inference Pipeline Metrics
ML_INFERENCE_LATENCY = safe_histogram(
    "stockai_ml_inference_latency_seconds",
    "ML model inference end-to-end latency in seconds",
    ["symbol"]
)
ML_ACTIVE_WORKERS = safe_gauge(
    "stockai_ml_active_workers_count",
    "Number of running ML CPU offloading worker processes"
)
ML_WORKER_HEARTBEAT = safe_gauge(
    "stockai_ml_worker_heartbeat_status",
    "ML worker execution pool health state (1 = healthy, 0 = crashed/broken)"
)
ML_FALLBACK_SIGNALS = safe_counter(
    "stockai_ml_fallback_signals_total",
    "Total number of fallback HOLD signals generated due to inference errors"
)

# New Preloading and ProcessPool Queue Metrics
WS_PRELOAD_DURATION = safe_gauge(
    "stockai_ws_preload_duration_seconds",
    "Time taken to pre-populate last known prices in seconds"
)
WS_PRELOAD_SUCCESS = safe_counter(
    "stockai_ws_preload_success_total",
    "Total successfully pre-populated last known prices"
)
WS_PRELOAD_FAILURES = safe_counter(
    "stockai_ws_preload_failures_total",
    "Total failed pre-populations of last known prices"
)
ML_PROCESSPOOL_QUEUE_DEPTH = safe_gauge(
    "stockai_ml_processpool_queue_depth",
    "Current number of pending tasks in the ML ProcessPoolExecutor queue"
)
