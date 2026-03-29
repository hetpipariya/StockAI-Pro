from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.inference.runner import predict_symbol
from app.routes.market import get_history, get_snapshot
from app.services.indicators import IndicatorEngine
from app.services.redis_client import get_cache, set_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["bundle"])


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _bundle_hold_fallback(symbol: str, interval: str, horizon: str, reason: str) -> dict:
    return {
        "status": "success",
        "data": {
            "symbol": symbol,
            "interval": interval,
            "horizon": horizon,
            "snapshot": {"symbol": symbol, "ltp": 0.0},
            "history": {"count": 0, "source": "FALLBACK", "data_source": "FALLBACK", "candles": []},
            "indicators": {},
            "prediction": {
                "signal": "HOLD",
                "confidence": 0,
                "prediction": 0.0,
                "stop_loss": 0.0,
                "target_price": 0.0,
                "regime": "Unknown",
                "factors": [reason],
                "explanation": reason,
            },
            "latency_ms": 0.0,
        },
        "message": "Bundle fallback",
    }


@router.get("/bundle/{symbol}")
async def get_bundle(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(100, ge=50, le=300),
    horizon: str = Query("15m"),
):
    """Single-shot data bundle: snapshot + candles + indicators + prediction."""
    started_at = time.perf_counter()
    normalized_symbol = symbol.strip().upper()
    cache_key = f"bundle:v1:{normalized_symbol}:{interval}:{limit}:{horizon}"

    cached = await get_cache(cache_key)
    if cached:
        return {"status": "success", "data": cached, "message": "Bundle from cache"}

    try:
        snapshot_resp, history_resp = await asyncio.wait_for(
            asyncio.gather(
                get_snapshot(symbol=normalized_symbol),
                get_history(symbol=normalized_symbol, interval=interval, limit=limit),
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[BUNDLE] Upstream timeout symbol=%s interval=%s", normalized_symbol, interval)
        return _bundle_hold_fallback(normalized_symbol, interval, horizon, "Upstream timeout")
    except Exception as exc:
        logger.warning("[BUNDLE] Upstream error symbol=%s interval=%s err=%s", normalized_symbol, interval, exc)
        return _bundle_hold_fallback(normalized_symbol, interval, horizon, "Upstream failure")

    snapshot = snapshot_resp.get("data", {}) if isinstance(snapshot_resp, dict) else {}
    history_payload = history_resp.get("data", {}) if isinstance(history_resp, dict) else {}
    candles = history_payload.get("data", []) if isinstance(history_payload, dict) else []

    if not isinstance(candles, list) or len(candles) < 50:
        return _bundle_hold_fallback(normalized_symbol, interval, horizon, "Insufficient candles")

    ltp = _to_float(snapshot.get("ltp", 0.0), 0.0)
    if ltp <= 0:
        ltp = _to_float(candles[-1].get("close", 0.0), 0.0)
    if ltp <= 0:
        return _bundle_hold_fallback(normalized_symbol, interval, horizon, "Invalid market price")

    try:
        prediction, indicators_df = await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(
                    predict_symbol,
                    symbol=normalized_symbol,
                    timeframe=horizon,
                    latest_ltp=ltp,
                    ohlcv=candles,
                ),
                asyncio.to_thread(IndicatorEngine.compute_all, candles),
            ),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[BUNDLE] Compute timeout symbol=%s horizon=%s", normalized_symbol, horizon)
        return _bundle_hold_fallback(normalized_symbol, interval, horizon, "Compute timeout")
    except Exception as exc:
        logger.warning("[BUNDLE] Compute error symbol=%s horizon=%s err=%s", normalized_symbol, horizon, exc)
        return _bundle_hold_fallback(normalized_symbol, interval, horizon, "Compute failure")
    latest_indicators: dict[str, Any] = {}
    if not indicators_df.empty:
        latest = indicators_df.iloc[-1].to_dict()
        for key in ["ema9", "ema15", "rsi9", "macd", "macd_signal", "atr14", "vwap"]:
            latest_indicators[key] = _to_float(latest.get(key, 0.0), 0.0)

    payload = {
        "symbol": normalized_symbol,
        "interval": interval,
        "horizon": horizon,
        "snapshot": snapshot,
        "history": {
            "count": len(candles),
            "source": history_payload.get("source", "UNKNOWN") if isinstance(history_payload, dict) else "UNKNOWN",
            "data_source": history_payload.get("data_source", "UNKNOWN") if isinstance(history_payload, dict) else "UNKNOWN",
            "candles": candles,
        },
        "indicators": latest_indicators,
        "prediction": {
            "signal": prediction.signal,
            "confidence": prediction.confidence,
            "prediction": prediction.price,
            "stop_loss": prediction.stop,
            "target_price": prediction.target,
            "regime": prediction.regime,
            "factors": prediction.factors or [],
            "explanation": prediction.explanation,
        },
        "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
    }

    await set_cache(cache_key, payload, ttl=max(30, config.CACHE_TTL_BUNDLE_SECONDS))
    logger.info("[BUNDLE] symbol=%s interval=%s latency_ms=%.2f", normalized_symbol, interval, payload["latency_ms"])

    return {"status": "success", "data": payload, "message": "Bundle generated"}
