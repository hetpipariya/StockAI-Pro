from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from stockai_shared.config.config import SLOW_REQUEST_LOG_MS
from stockai_shared.services.instrument_service import normalize_symbol_input
from app.services.bundle_service import get_bundle as get_bundle_data

logger = logging.getLogger(__name__)

_SLOW_BUNDLE_MS = max(50, SLOW_REQUEST_LOG_MS)

router = APIRouter(tags=["bundle"])


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


def _degraded_response(symbol: str, code: str, message: str, data: dict | None = None) -> dict:
    payload = _normalize_bundle_data(symbol, data)
    payload["partial"] = True
    payload["warnings"] = list(
        dict.fromkeys(
            [
                *(
                    payload.get("warnings")
                    if isinstance(payload.get("warnings"), list)
                    else []
                ),
                f"{code}: {message}",
            ]
        )
    )
    return _success_response(payload)


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
    normalized["symbol"] = symbol

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
    normalized["snapshot"]["symbol"] = symbol
    normalized["prediction"] = {
        **defaults["prediction"],
        **prediction,
    }
    normalized["prediction"]["symbol"] = symbol
    normalized["indicators"] = {
        **defaults["indicators"],
        **indicators,
    }
    normalized["indicators"]["symbol"] = symbol

    candles = normalized["history"].get("candles")
    if not isinstance(candles, list):
        normalized["history"]["candles"] = []

    return normalized


@router.get("/api/v1/bundle/{symbol}")
@router.get("/api/bundle/{symbol}", include_in_schema=False)
async def get_bundle(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(200, ge=50, le=300),
    horizon: str = Query("15m"),
):
    """Single optimized market bundle endpoint."""
    raw_symbol = symbol.strip()
    normalized_symbol = normalize_symbol_input(raw_symbol)
    started_at = time.perf_counter()
    fallback_payload = _default_bundle_data(normalized_symbol)

    try:
        payload = await asyncio.wait_for(
            get_bundle_data(
                raw_symbol,
                interval=interval,
                limit=limit,
                horizon=horizon,
            ),
            timeout=8.0,
        )
        normalized_payload = _normalize_bundle_data(normalized_symbol, payload)
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        if latency_ms >= _SLOW_BUNDLE_MS:
            logger.warning(
                "[SLOW_BUNDLE] symbol=%s interval=%s horizon=%s status=200 duration_ms=%.1f",
                normalized_symbol,
                interval,
                horizon,
                latency_ms,
            )
        return _success_response(normalized_payload)
    except KeyError as exc:
        message = str(exc.args[0]) if exc.args else str(exc)
        logger.warning(
            "[BUNDLE] Unknown symbol=%s interval=%s horizon=%s error=%s",
            normalized_symbol,
            interval,
            horizon,
            message,
        )
        return JSONResponse(
            status_code=200,
            content=_degraded_response(
                normalized_symbol,
                code="SYMBOL_NOT_FOUND",
                message=message,
                data=fallback_payload,
            ),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[BUNDLE] Timeout symbol=%s interval=%s horizon=%s",
            normalized_symbol,
            interval,
            horizon,
        )
        return JSONResponse(
            status_code=200,
            content=_degraded_response(
                normalized_symbol,
                code="BUNDLE_TIMEOUT",
                message="Bundle request timed out",
                data=fallback_payload,
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
            status_code=200,
            content=_degraded_response(
                normalized_symbol,
                code="BUNDLE_ERROR",
                message="Failed to build market bundle",
                data=fallback_payload,
            ),
        )
