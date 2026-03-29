from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.config import FRONTEND_URL as _FRONTEND_URL, API_RATE_LIMIT
from app.utils.auth_utils import decode_access_token

logger = logging.getLogger(__name__)

_login_attempts: dict[str, deque] = {}
_api_requests: dict[str, deque] = {}

_LOGIN_RATE_LIMIT = 5
_LOGIN_RATE_WINDOW = 300.0
_RATE_WINDOW = 60.0
_RATE_LIMIT = API_RATE_LIMIT
_CLEANUP_EVERY = 300.0
_last_cleanup = time.monotonic()


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _extract_rate_key(request: Request, client_ip: str) -> str:
    """Prefer authenticated user key, fallback to IP key."""
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            try:
                payload = decode_access_token(token)
                user_id = str(payload.get("sub", "")).strip()
                if user_id:
                    return f"user:{user_id}"
            except Exception:
                pass
    return f"ip:{client_ip}"


def _normalize_payload(payload: Any, status_code: int) -> dict[str, Any]:
    success = 200 <= status_code < 400
    timestamp = _utc_now_iso()

    if isinstance(payload, dict):
        if "success" in payload:
            success = bool(payload.get("success"))
        elif "status" in payload:
            success = str(payload.get("status", "")).lower() in {"ok", "success", "true"}

        if payload.get("error"):
            success = False

        data = payload.get("data") if "data" in payload else (payload if success else None)
        error = None if success else (
            payload.get("error")
            or payload.get("detail")
            or payload.get("message")
            or "Request failed"
        )

        normalized: dict[str, Any] = {
            "success": success,
            "data": data,
            "error": error,
            "timestamp": timestamp,
        }
        for key, value in payload.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    return {
        "success": success,
        "data": payload if success else None,
        "error": None if success else "Request failed",
        "timestamp": timestamp,
    }


async def _normalize_json_response(request: Request, response: Response) -> Response:
    path = request.url.path
    if path.startswith("/docs") or path.startswith("/openapi") or path.startswith("/redoc"):
        return response

    body = b""
    if getattr(response, "body", None) is not None:
        body = bytes(response.body)
    else:
        async for chunk in response.body_iterator:
            body += chunk

    content_encoding = response.headers.get("content-encoding", "").lower()
    body_for_json = body
    if "gzip" in content_encoding and body:
        try:
            body_for_json = gzip.decompress(body)
        except Exception:
            body_for_json = body

    try:
        payload = json.loads(body_for_json.decode("utf-8")) if body_for_json else {}
    except Exception:
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
            background=response.background,
        )

    normalized = _normalize_payload(payload, response.status_code)

    headers = dict(response.headers)
    headers.pop("content-length", None)

    if "gzip" in content_encoding:
        serialized = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
        compressed = gzip.compress(serialized)
        headers["content-encoding"] = "gzip"
        return Response(
            content=compressed,
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
            background=response.background,
        )

    return JSONResponse(
        status_code=response.status_code,
        content=normalized,
        headers=headers,
        background=response.background,
    )


def configure_cors(app: FastAPI) -> list[str]:
    """Attach CORS middleware and return effective origins list."""
    default_origins = [
        "https://stockai-pro.in",
        "https://www.stockai-pro.in",
        "https://stockai-pro.pages.dev",
        "*",  # DEBUG: Allow all origins for Cloudflare/mobile troubleshooting
        _FRONTEND_URL,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    extra_origins = [
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    allowed_origins = sorted({origin.rstrip("/") for origin in [*default_origins, *extra_origins] if origin})

    logger.info("[CORS] Allowed origins (%d): %s", len(allowed_origins), ", ".join(allowed_origins))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    return allowed_origins


def _check_rate_limit(key: str, limit: int = _RATE_LIMIT, window: float = _RATE_WINDOW) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    global _last_cleanup
    now = time.monotonic()

    if now - _last_cleanup > _CLEANUP_EVERY:
        stale_ips = [
            seen_key
            for seen_key, times in list(_api_requests.items())
            if not times or (now - times[-1]) > window * 2
        ]
        for stale_key in stale_ips:
            del _api_requests[stale_key]
        _last_cleanup = now

    if key not in _api_requests:
        _api_requests[key] = deque()

    times = _api_requests[key]
    cutoff = now - window
    while times and times[0] < cutoff:
        times.popleft()

    if len(times) >= limit:
        return False

    times.append(now)
    return True


def add_production_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def production_middleware(request: Request, call_next):
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"
        rate_key = _extract_rate_key(request, client_ip)
        now = time.monotonic()

        if request.method == "POST" and path in ("/api/v1/auth/login", "/api/v1/auth/token"):
            if rate_key not in _login_attempts:
                _login_attempts[rate_key] = deque()
            attempts = _login_attempts[rate_key]
            cutoff = now - _LOGIN_RATE_WINDOW
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            if len(attempts) >= _LOGIN_RATE_LIMIT:
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "status": "error",
                        "error": "Too many login attempts. Wait 5 minutes.",
                        "message": "Too many login attempts. Wait 5 minutes.",
                        "data": None,
                        "timestamp": _utc_now_iso(),
                    },
                )
            attempts.append(now)

        if path.startswith("/api/") and not _check_rate_limit(rate_key):
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "status": "error",
                    "error": f"Rate limit exceeded ({_RATE_LIMIT}/min). Slow down.",
                    "message": f"Rate limit exceeded ({_RATE_LIMIT}/min). Slow down.",
                    "data": None,
                    "timestamp": _utc_now_iso(),
                },
            )

        start_time = time.perf_counter()
        try:
            response = await asyncio.wait_for(call_next(request), timeout=45.0)
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start_time
            logger.error("[TIMEOUT] %s %s timed out after %.1fs from %s", request.method, path, elapsed, client_ip)
            return JSONResponse(
                status_code=504,
                content={
                    "success": False,
                    "status": "error",
                    "error": "Request timed out",
                    "message": "Request timed out",
                    "data": None,
                    "timestamp": _utc_now_iso(),
                },
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            logger.error("[ERROR] %s %s failed after %.1fs: %s", request.method, path, elapsed, exc)
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "status": "error",
                    "error": "Internal server error",
                    "message": "Internal server error",
                    "data": None,
                    "timestamp": _utc_now_iso(),
                },
            )

        elapsed = time.perf_counter() - start_time
        if path.startswith("/api/") and elapsed > 0.5:
            logger.info("[API] %s %s -> %d (%.2fs) from %s", request.method, path, response.status_code, elapsed, client_ip)

        return await _normalize_json_response(request, response)


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "status": "error",
                "error": exc.detail if isinstance(exc.detail, str) else "Request failed",
                "message": exc.detail if isinstance(exc.detail, str) else "Request failed",
                "data": None,
                "code": exc.status_code,
                "timestamp": _utc_now_iso(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "status": "error",
                "error": "Request validation failed",
                "message": "Request validation failed",
                "data": {"errors": errors},
                "code": 422,
                "timestamp": _utc_now_iso(),
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "[UNHANDLED EXCEPTION] %s %s - %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
            str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "error",
                "error": "An internal server error occurred. Please try again.",
                "message": "An internal server error occurred. Please try again.",
                "data": None,
                "code": 500,
                "timestamp": _utc_now_iso(),
            },
        )
