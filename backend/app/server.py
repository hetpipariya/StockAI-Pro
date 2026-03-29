"""Thin FastAPI assembly layer for StockAI Pro backend."""
from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import DATABASE_URL
from app.middleware import add_exception_handlers, add_production_middleware, configure_cors
from app.routes import auth, backtest, bundle, indicators, market, news, predict, sentiment, symbols, trading
from app.services.db import check_db_connection
from app.services.instrument_master import get_instrument_count
from app.services.market_state import is_market_open
from app.websocket.handler import (
    get_last_tick_age_seconds,
    get_ws_connector,
    get_ws_state,
    is_ws_streaming,
    setup_websocket_routes,
)
from app.websocket.relay import get_client_count

_bootstrap_logger = logging.getLogger(__name__)

try:
    from app.lifespan import lifespan
except ModuleNotFoundError:
    try:
        from .lifespan import lifespan  # type: ignore[no-redef]
    except Exception as exc:
        @asynccontextmanager
        async def lifespan(app: FastAPI):  # type: ignore[no-redef]
            _bootstrap_logger.warning(
                "[STARTUP] Lifespan module unavailable (%s). Running minimal lifecycle fallback.",
                exc,
            )
            yield
            _bootstrap_logger.info("[SHUTDOWN] Minimal lifecycle fallback complete")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_DB_BACKEND = "SQLite" if DATABASE_URL.startswith("sqlite") else "PostgreSQL"
try:
    _parsed = urlparse(DATABASE_URL)
    if _parsed.hostname:
        clean_path = (_parsed.path or "")
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

app.include_router(auth.compat_router)
app.include_router(auth.router)
app.include_router(news.router)
app.include_router(sentiment.router)
app.include_router(backtest.router)
app.include_router(market.router)
app.include_router(predict.router)
app.include_router(bundle.router)
app.include_router(indicators.router)
app.include_router(symbols.router)
app.include_router(trading.router)
setup_websocket_routes(app)


def _list_api_routes() -> list[str]:
    paths = {route.path for route in app.routes if getattr(route, "path", "").startswith("/api")}
    return sorted(paths)


@app.get("/api")
async def api_index():
    endpoints = _list_api_routes()
    return {
        "status": "ok",
        "service": "stockai-pro",
        "base": "/api",
        "count": len(endpoints),
        "endpoints": endpoints,
        "docs": "/docs",
    }


@app.get("/api/system/db-ping")
async def api_db_ping():
    db_ok = await check_db_connection(retries=1, delay=0.0)
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "database_backend": _DB_BACKEND,
        "database_location": _DB_LOCATION,
    }


@app.get("/api/health")
async def health():
    return {
        "success": True,
        "status": "ok",
        "service": "stockai-pro-backend",
    }


@app.get("/predict/{symbol}")
async def predict_alias(symbol: str):
    """Compatibility prediction endpoint: returns signal payload with fallback fields."""
    try:
        from app.inference.quant_predictor import predict_signal
    except ModuleNotFoundError:
        from .inference.quant_predictor import predict_signal

    try:
        return predict_signal(symbol.strip().upper())
    except Exception as exc:
        logger.error("/predict alias failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol.strip().upper(),
            "signal": "HOLD",
            "confidence": 0,
            "prediction": 0.0,
            "currentPrice": 0.0,
            "target_price": 0.0,
            "stop_loss": 0.0,
            "target": 0.0,
            "stopLoss": 0.0,
            "regime": "Unknown",
            "explanation": f"HOLD fallback: {exc}",
            "timestamp": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }


@app.get("/")
async def root_status():
    return {
        "status": "ok",
        "service": "stockai-pro",
        "docs": "/docs",
        "health": "/api/health",
        "ws": "/ws",
        "ws_legacy": "/live",
        "api": "/api",
    }
