from __future__ import annotations

import asyncio
import logging
import time
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


def _default_bundle_data(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "history": {
            "candles": [],
            "count": 0,
            "source": "UNAVAILABLE",
            "data_source": "UNAVAILABLE",
        },
        "snapshot": {
            "symbol": symbol,
            "price": 0.0,
            "ltp": 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 0.0,
            "change": 0.0,
            "volume": 0,
            "source": "UNAVAILABLE",
            "data_source": "UNAVAILABLE",
            "market_status": "CLOSED",
        },
        "prediction": {
            "symbol": symbol,
            "signal": "HOLD",
            "confidence": 0.0,
            "confidence_pct": 0,
            "prediction": 0.0,
            "target": 0.0,
            "stop_loss": 0.0,
            "reasoning": "Prediction unavailable",
        },
        "indicators": {
            "symbol": symbol,
            "ema_20": 0.0,
            "ema_50": 0.0,
            "rsi": 0.0,
            "macd": {
                "value": 0.0,
                "signal": 0.0,
                "histogram": 0.0,
            },
            "bollinger": {
                "upper": 0.0,
                "middle": 0.0,
                "lower": 0.0,
            },
        },
    }


def _normalize_bundle_data(symbol: str, payload: dict | None) -> dict:
    defaults = _default_bundle_data(symbol)
    if not isinstance(payload, dict):
        return defaults

    normalized = {
        **defaults,
        **payload,
    }

    history = payload.get("history") if isinstance(payload.get("history"), dict) else {}
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    indicators = payload.get("indicators") if isinstance(payload.get("indicators"), dict) else {}

    normalized["history"] = {
        **defaults["history"],
        **history,
    }
    normalized["snapshot"] = {
        **defaults["snapshot"],
        **snapshot,
    }
    normalized["prediction"] = {
        **defaults["prediction"],
        **prediction,
    }
    normalized["indicators"] = {
        **defaults["indicators"],
        **indicators,
    }

    candles = normalized["history"].get("candles")
    if not isinstance(candles, list):
        normalized["history"]["candles"] = []

    return normalized


@router.get("/bundle/{symbol}")
async def get_bundle(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(100, ge=50, le=300),
    horizon: str = Query("15m"),
):
    """Single optimized market bundle endpoint."""
    normalized_symbol = symbol.strip().upper()
    started_at = time.perf_counter()
    logger.debug(
        "[BUNDLE] request symbol=%s interval=%s limit=%s horizon=%s",
        normalized_symbol,
        interval,
        limit,
        horizon,
    )

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
        normalized_payload = _normalize_bundle_data(normalized_symbol, payload)
        logger.info(
            "[BUNDLE] success symbol=%s interval=%s horizon=%s latency_ms=%.2f",
            normalized_symbol,
            interval,
            horizon,
            (time.perf_counter() - started_at) * 1000.0,
        )
        return _success_response(normalized_payload)
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
