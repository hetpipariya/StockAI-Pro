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

from app.server import app  # noqa: F401 — re-export the FastAPI instance
from app.config import BACKEND_HOST, BACKEND_PORT

import logging

logger = logging.getLogger(__name__)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    logger.info("[BOOT] Starting FastAPI on %s:%s", BACKEND_HOST, BACKEND_PORT)
    uvicorn.run("app.main:app", host=BACKEND_HOST, port=BACKEND_PORT, proxy_headers=True, forwarded_allow_ips="*")
