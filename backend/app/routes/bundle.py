from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.bundle_service import get_bundle as get_bundle_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["bundle"])


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _success_response(data: dict) -> dict:
    return {
        "success": True,
        "data": data,
        "error": None,
        "timestamp": _utc_now_iso(),
    }


def _error_response(code: str, message: str) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
        "timestamp": _utc_now_iso(),
    }


@router.get("/bundle/{symbol}")
async def get_bundle(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(100, ge=50, le=300),
    horizon: str = Query("15m"),
):
    """Single optimized market bundle endpoint."""
    normalized_symbol = symbol.strip().upper()

    try:
        payload = await asyncio.wait_for(
            get_bundle_data(
                normalized_symbol,
                interval=interval,
                limit=limit,
                horizon=horizon,
            ),
            timeout=8.0,
        )
        return _success_response(payload)
    except asyncio.TimeoutError:
        logger.warning(
            "[BUNDLE] Timeout symbol=%s interval=%s horizon=%s",
            normalized_symbol,
            interval,
            horizon,
        )
        return JSONResponse(
            status_code=504,
            content=_error_response(
                code="BUNDLE_TIMEOUT",
                message="Bundle request timed out",
            ),
        )
    except Exception as exc:
        logger.error(
            "[BUNDLE] Failed symbol=%s interval=%s horizon=%s error=%s",
            normalized_symbol,
            interval,
            horizon,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content=_error_response(
                code="BUNDLE_ERROR",
                message="Failed to build market bundle",
            ),
        )
