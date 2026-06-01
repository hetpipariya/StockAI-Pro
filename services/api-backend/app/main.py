"""
StockAI Pro — FastAPI entrypoint.

This module is the canonical ASGI application entry point for the StockAI Pro
backend.  It re-exports the fully-configured FastAPI ``app`` instance from
``app.server`` so that the backend can be launched with *either*:

    uvicorn app.main:app --reload --port 8000
    uvicorn app.server:app --reload --port 8000

Both commands resolve to the exact same application object.

Why this file exists
--------------------
Many deployment tools, CI pipelines, and developers expect the ASGI app to
live at ``app.main:app``.  By providing this thin re-export we keep full
backward compatibility with ``app.server:app`` (used by Dockerfile,
docker-compose, and the README) while also supporting the conventional path.
"""

import logging

from stockai_shared.config.config import (BACKEND_HOST, BACKEND_PORT, LOG_LEVEL,
                        UVICORN_ACCESS_LOG, UVICORN_LOOP,
                        UVICORN_TIMEOUT_KEEP_ALIVE, UVICORN_WORKERS)
from .server import app  # noqa: F401 — re-export the FastAPI instance

logger = logging.getLogger(__name__)


def _validate_route_contract() -> None:
    """Boot-time guardrail to ensure critical API routes stay mounted."""
    required_routes = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/trades/active",
        "/api/v1/portfolio/balance",
        "/api/v1/signals",
    }
    mounted_routes = {
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", "")
    }
    missing = sorted(required_routes - mounted_routes)
    if missing:
        logger.warning("[STARTUP] Missing critical routes: %s", ", ".join(missing))
    else:
        logger.debug("[STARTUP] Critical API route contract validated")


_validate_route_contract()

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    logger.info("[STARTUP] Starting FastAPI on %s:%s", BACKEND_HOST, BACKEND_PORT)
    uvicorn.run(
        "app.main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        proxy_headers=True,
        forwarded_allow_ips="*",
        workers=UVICORN_WORKERS,
        timeout_keep_alive=UVICORN_TIMEOUT_KEEP_ALIVE,
        loop=UVICORN_LOOP,
        access_log=UVICORN_ACCESS_LOG,
        log_level=str(LOG_LEVEL).lower(),
    )
