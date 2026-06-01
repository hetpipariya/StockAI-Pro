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

# --- SRE Observability Hardening Metrics ---

# Database Pool Metrics
DB_POOL_CHECKED_OUT = Gauge(
    "stockai_db_pool_checked_out",
    "Number of database connections currently checked out"
)
DB_POOL_IDLE = Gauge(
    "stockai_db_pool_idle",
    "Number of database connections currently idle in pool"
)
DB_POOL_OVERFLOW = Gauge(
    "stockai_db_pool_overflow",
    "Number of database overflow connections currently open"
)
DB_POOL_WAITING = Gauge(
    "stockai_db_pool_waiting",
    "Number of threads/tasks currently waiting for a database connection"
)

# Redis Capacity Metrics
REDIS_MEMORY_USED_BYTES = Gauge(
    "stockai_redis_memory_used_bytes",
    "Total bytes of memory used by Redis"
)
REDIS_CONNECTED_CLIENTS = Gauge(
    "stockai_redis_connected_clients",
    "Number of active clients connected to Redis"
)
REDIS_PUBSUB_CHANNELS = Gauge(
    "stockai_redis_pubsub_channels",
    "Number of active Pub/Sub channels in Redis"
)
REDIS_PUBSUB_SUBSCRIBERS = Gauge(
    "stockai_redis_pubsub_subscribers",
    "Number of active Pub/Sub subscribers/patterns in Redis"
)
REDIS_KEY_COUNT = Gauge(
    "stockai_redis_key_count",
    "Total number of keys stored in Redis databases"
)
REDIS_CACHE_HIT_RATIO = Gauge(
    "stockai_redis_cache_hit_ratio",
    "Cache hit ratio calculated from keyspace hits and misses"
)
REDIS_REPLICA_STATUS = Gauge(
    "stockai_redis_replica_status",
    "Redis replication state (1 = master or link ok, 0 = link down)"
)
REDIS_SENTINEL_STATUS = Gauge(
    "stockai_redis_sentinel_status",
    "Redis Sentinel master discovery status (1 = ok, 0 = failed/degraded)"
)

# AI Feature Drift Metrics
AI_FEATURE_DRIFT_SCORE = Gauge(
    "stockai_ai_feature_drift_score",
    "Kolmogorov-Smirnov statistics drift score for the feature",
    ["symbol", "feature"]
)
AI_FEATURE_DRIFT_PVALUE = Gauge(
    "stockai_ai_feature_drift_pvalue",
    "P-value of the feature drift Kolmogorov-Smirnov test",
    ["symbol", "feature"]
)
AI_FEATURE_DRIFT_ALERTS = Counter(
    "stockai_ai_feature_drift_alerts_total",
    "Total number of feature distribution drift alerts triggered (p-value < 0.05)",
    ["symbol", "feature"]
)

# AI Inference Metrics
AI_PREDICTIONS_TOTAL = Counter(
    "stockai_ml_prediction_count_total",
    "Total number of ML predictions executed"
)
AI_BUY_SIGNALS_TOTAL = Counter(
    "stockai_ml_buy_signals_total",
    "Total number of BUY signals generated"
)
AI_SELL_SIGNALS_TOTAL = Counter(
    "stockai_ml_sell_signals_total",
    "Total number of SELL signals generated"
)
AI_HOLD_SIGNALS_TOTAL = Counter(
    "stockai_ml_hold_signals_total",
    "Total number of HOLD signals generated"
)
AI_CONFIDENCE_DISTRIBUTION = Histogram(
    "stockai_ml_confidence_distribution",
    "Distribution of prediction confidence scores",
    ["symbol"]
)
AI_PREDICTION_QUEUE_DEPTH = Gauge(
    "stockai_ml_prediction_queue_depth",
    "Number of candles currently queued for predictions"
)
AI_PROCESS_POOL_UTILIZATION = Gauge(
    "stockai_ml_process_pool_utilization",
    "Fraction of active ProcessPoolExecutor workers currently executing predictions"
)

# Paper Trading Subsystem Metrics
PAPER_POSITIONS_OPEN = Gauge(
    "stockai_paper_positions_open",
    "Number of currently open paper trading positions"
)
PAPER_POSITIONS_CLOSED = Counter(
    "stockai_paper_positions_closed",
    "Total number of closed paper trading positions"
)
PAPER_TRADES_TOTAL = Counter(
    "stockai_paper_trades_total",
    "Total number of paper trading orders placed (open + close)"
)
PAPER_TRADE_WIN_RATE = Gauge(
    "stockai_paper_trade_win_rate",
    "Win rate calculated from realized profits of closed trades"
)
PAPER_REALIZED_PNL = Gauge(
    "stockai_paper_realized_pnl",
    "Total realized profit/loss in Rs."
)
PAPER_UNREALIZED_PNL = Gauge(
    "stockai_paper_unrealized_pnl",
    "Total unrealized profit/loss in Rs."
)
RISK_HALTS_TOTAL = Counter(
    "stockai_risk_halts_total",
    "Total number of daily risk halt lockouts triggered"
)
DAILY_DRAWDOWN_PERCENT = Gauge(
    "stockai_daily_drawdown_percent",
    "Current daily drawdown of account capital in percent"
)

# Slow Query Metrics
DB_SLOW_QUERIES_TOTAL = Counter(
    "stockai_db_slow_queries_total",
    "Total number of queries taking longer than DB_SLOW_QUERY_MS"
)
DB_SLOWEST_QUERY_MS = Gauge(
    "stockai_db_slowest_query_ms",
    "Execution duration of the slowest query in milliseconds"
)

# Slow API Metrics
API_SLOW_REQUESTS_TOTAL = Counter(
    "stockai_api_slow_requests_total",
    "Total number of API requests taking longer than SLOW_REQUEST_LOG_MS",
    ["endpoint"]
)
API_WORST_LATENCY_MS = Gauge(
    "stockai_api_worst_latency_ms",
    "Execution latency of the slowest API request in milliseconds",
    ["endpoint"]
)

# Logging Queue Metrics
DROPPED_LOG_ENTRIES_TOTAL = Counter(
    "stockai_dropped_log_entries_total",
    "Total number of log messages dropped due to queue saturation"
)
LOG_QUEUE_SIZE = Gauge(
    "stockai_log_queue_size",
    "Current number of elements in the logging memory queue"
)
LOG_QUEUE_UTILIZATION = Gauge(
    "stockai_log_queue_utilization",
    "Fraction of logging queue capacity currently utilized"
)

# --- Caching Optimization Metrics ---
AI_PROCESSED_CANDLE_CACHE_SIZE = Gauge(
    "ai_processed_candle_cache_size",
    "Current size of processed candle cache set"
)
FEATURE_CACHE_SIZE = Gauge(
    "feature_cache_size",
    "Current size of the in-memory feature cache"
)
FEATURE_CACHE_HITS = Counter(
    "feature_cache_hits",
    "Total hits to the feature cache"
)
FEATURE_CACHE_MISSES = Counter(
    "feature_cache_misses",
    "Total misses to the feature cache"
)
CACHE_HITS_TOTAL = Counter(
    "cache_hits_total",
    "Total cache hits (Redis & Memory)"
)
CACHE_MISSES_TOTAL = Counter(
    "cache_misses_total",
    "Total cache misses (Redis & Memory)"
)
CACHE_HIT_RATIO = Gauge(
    "cache_hit_ratio",
    "Overall cache hit ratio"
)
INDICATOR_CACHE_HITS = Counter(
    "indicator_cache_hits",
    "Total hits to the indicator cache"
)
INDICATOR_CACHE_MISSES = Counter(
    "indicator_cache_misses",
    "Total misses to the indicator cache"
)
PREDICTION_CACHE_HITS = Counter(
    "prediction_cache_hits",
    "Total hits to the prediction cache"
)
PREDICTION_CACHE_MISSES = Counter(
    "prediction_cache_misses",
    "Total misses to the prediction cache"
)
REDIS_CACHE_MEMORY_BYTES = Gauge(
    "redis_cache_memory_bytes",
    "Memory used by Redis for cache storage"
)
