"""Compatibility ASGI entrypoint.

Allows running the backend from the `backend/` directory with:

    python -m uvicorn main:app --reload --port 8000

while keeping `app.main:app` as the canonical path.
"""

from app.main import app

__all__ = ["app"]
