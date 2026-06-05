"""Thin FastAPI assembly layer for StockAI Pro backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import DATABASE_URL
from app.core.database import healthcheck as db_healthcheck
from app.logging_setup import configure_logging
from app.middleware import (add_exception_handlers, add_production_middleware,
                            configure_cors)
from app.routes import (auth, auth_signup, backtest, bundle, indicators, instruments, market, news,
                        order_proxy, portfolio, predict, sentiment, signals, symbols,
                        trade_api, trade_decision,
                        trades, trading)
from app.services.redis_client import get_cache, set_cache
from app.websocket.handler import (get_last_tick_age_seconds, get_ws_state,
                                   is_ws_streaming, setup_websocket_routes)
from app.websocket.relay import get_client_count

_bootstrap_logger = logging.getLogger(__name__)

try:
    from app.lifespan import lifespan
except ModuleNotFoundError:
    try:
        from .lifespan import lifespan  # type: ignore[no-redef]
    except Exception as exc:
        lifespan_import_error = str(exc)

        @asynccontextmanager
        async def lifespan(app: FastAPI):  # type: ignore[no-redef]
            _bootstrap_logger.warning(
                "[STARTUP] Lifespan module unavailable (%s). Running minimal lifecycle fallback.",
                lifespan_import_error,
            )
            yield
            _bootstrap_logger.info("[SHUTDOWN] Minimal lifecycle fallback complete")

configure_logging()
logger = logging.getLogger(__name__)

_HEALTH_CACHE_TTL_SECONDS = 3
_HEALTH_CACHE_KEY = "health:detailed:v1"
_DB_PING_CACHE_TTL_SECONDS = 2
_DB_PING_CACHE_KEY = "health:db-ping:v1"

_DB_BACKEND = "SQLite" if DATABASE_URL.startswith("sqlite") else "PostgreSQL"
try:
    _parsed = urlparse(DATABASE_URL)
    if _parsed.hostname:
        clean_path = _parsed.path or ""
        for sep in ("\n", "\r", "`n", "`r"):
            clean_path = clean_path.split(sep)[0]
        for marker in ("JWT_SECRET=", "APP_ENV=", "ENV=", "REDIS_URL="):
            clean_path = clean_path.split(marker)[0]
        clean_path = clean_path.strip()
        _DB_LOCATION = f"{_parsed.hostname}:{_parsed.port}{clean_path}"
    else:
        _DB_LOCATION = "configured"
except Exception:
    _DB_LOCATION = "configured"

app = FastAPI(title="StockAI Pro API", version="2.0", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=500)
add_production_middleware(app)
configure_cors(app)
add_exception_handlers(app)
Instrumentator().instrument(app).expose(app)

app.include_router(auth.router)
app.include_router(auth_signup.router)
app.include_router(news.router)
app.include_router(sentiment.router)
app.include_router(backtest.router)
app.include_router(market.router)
app.include_router(predict.router)
app.include_router(bundle.router)
app.include_router(indicators.router)
app.include_router(symbols.router)
app.include_router(instruments.router)
app.include_router(instruments.legacy_router)
app.include_router(trading.router)
app.include_router(trade_api.router)
app.include_router(trades.router)
app.include_router(portfolio.router)
app.include_router(order_proxy.router)
app.include_router(signals.router)
app.include_router(trade_decision.router)
setup_websocket_routes(app)


def _list_api_routes() -> list[str]:
    paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api")
    }
    return sorted(paths)


@app.get("/api/v1")
async def api_index():
    endpoints = _list_api_routes()
    return {
        "status": "ok",
        "service": "stockai-pro",
        "base": "/api/v1",
        "count": len(endpoints),
        "endpoints": endpoints,
        "docs": "/docs",
    }


@app.get("/api/v1/system/db-ping")
async def api_db_ping():
    cached = await get_cache(_DB_PING_CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    db_ok = await db_healthcheck(retries=1, delay=0.0)
    payload = {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "database_backend": _DB_BACKEND,
        "database_location": _DB_LOCATION,
    }
    await set_cache(_DB_PING_CACHE_KEY, payload, ttl=_DB_PING_CACHE_TTL_SECONDS)
    return payload


@app.get("/api/v1/health")
async def health():
    return {
        "success": True,
        "status": "ok",
        "service": "stockai-pro-backend",
    }


@app.get("/ping")
async def ping():
    """Ultra-lightweight health check for Cloudflare and load balancers.

    This endpoint returns immediately with minimal overhead.
    Use this for keep-alive and timeout detection.
    """
    return {"status": "pong"}


@app.get("/health/live")
async def health_live():
    """Lightweight live health check confirming that ASGI is processing loop frames."""
    return {"status": "ok", "uptime": "nominal"}


@app.get("/health/ready")
async def health_ready():
    """Deep readiness check asserting database connection, Redis, and ML pipeline health."""
    from app.services.db import check_db_connection
    from app.services.redis_client import get_redis, is_degraded_mode
    from app.websocket.handler import get_ws_state
    from app.inference.production_pipeline import _process_executor
    from fastapi.responses import JSONResponse

    db_ok = await check_db_connection(retries=1, delay=0.0)

    redis_ok = False
    redis_client = await get_redis()
    if redis_client:
        try:
            await redis_client.ping()
            redis_ok = True
        except Exception:
            pass

    ml_ok = _process_executor is not None
    ws_state = get_ws_state()

    # Database is critical; Redis is nominal if active OR running degraded local mode
    is_ready = db_ok and (redis_ok or is_degraded_mode())
    status_code = 200 if is_ready else 503

    payload = {
        "status": "ready" if is_ready else "not_ready",
        "subsystems": {
            "database": "nominal" if db_ok else "unreachable",
            "redis": "nominal" if redis_ok else ("degraded_fallback" if is_degraded_mode() else "unreachable"),
            "ml_workers": "active" if ml_ok else "idle",
            "websocket_stream": ws_state,
        }
    }
    return JSONResponse(content=payload, status_code=status_code)



@app.get("/api/v1/health/detailed")
async def detailed_health():
    """Detailed health check with component status."""
    cached = await get_cache(_HEALTH_CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    db_ok = await db_healthcheck(retries=1, delay=0.0)
    ws_state = get_ws_state()
    ws_streaming = is_ws_streaming()
    last_tick_age = get_last_tick_age_seconds()

    # Check broker token status
    broker_status = "unknown"
    broker_session_age_minutes = None
    try:
        from app.connectors import get_market_data_connector

        connector = get_market_data_connector()
        state = connector.active_snapshot()
        broker_status = state.get("active_broker", "unknown")
        broker_session_age_minutes = None
    except Exception as e:
        broker_status = f"error: {str(e)[:50]}"

    payload = {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "broker": {
            "status": broker_status,
            "session_age_minutes": broker_session_age_minutes,
        },
        "websocket": {
            "state": ws_state,
            "streaming": ws_streaming,
            "last_tick_age_seconds": (
                last_tick_age if last_tick_age != float("inf") else None
            ),
        },
        "clients": get_client_count(),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    await set_cache(_HEALTH_CACHE_KEY, payload, ttl=_HEALTH_CACHE_TTL_SECONDS)
    return payload

@app.get("/")
async def root_status():
    return {
        "status": "ok",
        "service": "stockai-pro",
        "docs": "/docs",
        "health": "/api/v1/health",
        "ws": "/ws",
        "ws_legacy": "/live",
        "api": "/api/v1",
    }
