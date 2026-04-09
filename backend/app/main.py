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

from app.server import app  # noqa: F401 — re-export the FastAPI instance

logger = logging.getLogger(__name__)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    logger.info("[BOOT] Starting FastAPI on %s:%s", "0.0.0.0", 8000)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
