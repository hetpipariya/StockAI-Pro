import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Query

from app import config
from app.inference.runner import predict_symbol
from app.services.redis_client import get_cache, set_cache
from app.services.db import async_session, PredictionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["predict"])


def _path_hold_fallback(symbol: str, reason: str) -> dict:
    return {
        "symbol": symbol,
        "signal": "HOLD",
        "confidence": 0,
        "prediction": 0.0,
        "currentPrice": 0.0,
        "target_price": 0.0,
        "stop_loss": 0.0,
        "target": 0.0,
        "stopLoss": 0.0,
        "regime": "Unknown",
        "explanation": reason,
        "timestamp": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


@router.get("/predict/{symbol}")
async def get_predict_by_path(symbol: str):
    """Path alias for prediction endpoint; delegates to the main runner pipeline."""
    normalized_symbol = symbol.strip().upper()
    try:
        response = await get_predict(symbol=normalized_symbol, horizon="15m", debug=False)
        if isinstance(response, dict) and isinstance(response.get("data"), dict):
            return response["data"]
        return response
    except Exception as exc:
        logger.error("Path prediction failed for %s: %s", normalized_symbol, exc)
        return _path_hold_fallback(normalized_symbol, reason=f"HOLD fallback: {exc}")


def _normalize_signal_payload(payload: dict, ltp: float) -> dict:
    """Clamp output shape/ranges and enforce safe HOLD fallback policy."""
    signal = str(payload.get("signal", "HOLD")).upper()
    if signal not in {"BUY", "SELL", "HOLD"}:
        signal = "HOLD"

    try:
        confidence = int(payload.get("confidence", 0))
    except Exception:
        confidence = 0
    confidence = max(0, min(100, confidence))

    # Enforce conservative threshold: below 60% is always HOLD.
    if confidence < 60:
        signal = "HOLD"

    try:
        target = float(payload.get("target_price", 0.0) or 0.0)
    except Exception:
        target = 0.0
    try:
        stop = float(payload.get("stop_loss", 0.0) or 0.0)
    except Exception:
        stop = 0.0

    if signal == "BUY" and (target <= ltp or stop >= ltp):
        signal = "HOLD"
    elif signal == "SELL" and (target >= ltp or stop <= ltp):
        signal = "HOLD"

    if signal == "HOLD":
        stop = round(ltp * 0.996, 2)
        target = round(ltp * 1.004, 2)

    payload["signal"] = signal
    payload["confidence"] = confidence
    payload["target_price"] = round(target, 2)
    payload["stop_loss"] = round(stop, 2)
    return payload


@router.get("/predict")
async def get_predict(
    symbol: str = Query(...),
    horizon: str = Query("15m", description="15m prediction horizon"),
    debug: bool = Query(False, description="Include debug info (feature values, probabilities)"),
):
    """Get AI prediction for symbol using real technical analysis."""
    symbol = symbol.strip().upper()

    try:
        # 1. Fetch real OHLCV candles for indicator analysis
        from app.routes.market import get_history, _fetch_snapshot
        
        hist = await get_history(symbol=symbol, interval="1m", limit=200)
        hist_payload = hist.get("data", {}) if isinstance(hist, dict) else {}
        candles = hist_payload.get("data", []) if isinstance(hist_payload, dict) else []

        # 4. HANDLE SMARTAPI TOKEN FAIL (Token refresh + retry)
        # If API returns an error or empty data due to a stale token
        if not candles or (isinstance(hist, dict) and str(hist.get("message", "")).lower() == "invalid token"):
            logger.warning(f"[PREDICT] Data missing or invalid token for {symbol}. Attempting to refresh token.")
            from app.services.instrument_master import regen_token
            regen_token()  # synchronous refresh
            # Retry once
            hist = await get_history(symbol=symbol, interval="1m", limit=200)
            hist_payload = hist.get("data", {}) if isinstance(hist, dict) else {}
            candles = hist_payload.get("data", []) if isinstance(hist_payload, dict) else []

        # 1. SAFE CANDLE HANDLING
        if not candles or not isinstance(candles, list):
            logger.error(f"[PREDICT] Invalid candles for {symbol}: {type(candles)}")
            return {
                "status": "error",
                "data": {
                    "signal": "HOLD",
                    "confidence": 0,
                    "factors": ["No market data available"]
                },
                "message": "Prediction failed"
            }

        last_candle = candles[-1] if len(candles) > 0 else {}
        last_candle_time = str(last_candle.get("time", "na"))

        # 2. VALIDATE DATA BEFORE MODEL
        length = len(candles)
        logger.info(f"[PREDICT] Input stats: symbol={symbol}, candles={length}, last_time={last_candle_time}")
        if length < 50:
            logger.warning(f"[PREDICT] Insufficient data ({length} < 50) for {symbol}")
            return {
                "status": "success",
                "data": {
                    "signal": "HOLD",
                    "confidence": 0,
                    "factors": ["Insufficient data"],
                    "indicators": {}
                },
                "message": "Prediction fallback"
            }

        # Cache key includes latest candle marker to avoid stale predictions
        key = f"pred:v2:{symbol}:{horizon}:{last_candle_time}"

        # Skip cache when debug is on so we always return fresh debug info
        if not debug:
            cached = await get_cache(key)
            if cached:
                # Cached value might be flat (old format) or wrapped (new format)
                if isinstance(cached, dict) and "status" in cached:
                    return cached  # Already wrapped
                return {"status": "success", "data": cached, "message": "Prediction from cache"}

        # 2.b Get current LTP
        ltp = 0.0
        try:
            snap = await _fetch_snapshot(symbol)
            # The snapshot returned could also be the standard wrapped dict depending on _fetch_snapshot implementation
            # It's an internal function so usually returns the raw dict
            ltp = float(snap.get("ltp", 0) or 0)
        except Exception as e:
            logger.warning(f"[PREDICT] LTP fetch failed for {symbol}: {e}")
            if candles:
                ltp = float(candles[-1].get("close", 0))

        # 3. Run prediction using the real ModelEnsemble pipeline
        try:
            pred = predict_symbol(
                symbol=symbol,
                timeframe=horizon,
                latest_ltp=ltp,
                ohlcv=candles,
            )
        except Exception as e:
            logger.error(f"[PREDICT] Model crash for {symbol}: {e}")
            return {
                "status": "error",
                "data": {
                    "signal": "HOLD",
                    "confidence": 0,
                    "factors": [f"Pipeline failed: {str(e)}"]
                },
                "message": "Prediction error"
            }

        logger.info(
            "[PREDICT] %s signal=%s conf=%d%% regime=%s",
            symbol, pred.signal, pred.confidence, pred.regime,
        )

        # Build response
        target_val = float(pred.target) if pred.target is not None else 0.0
        stop_val = float(pred.stop) if pred.stop is not None else 0.0

        result = {
            "symbol": pred.symbol,
            "prediction": pred.price,
            "signal": pred.signal,
            "confidence": pred.confidence,
            "stop_loss": stop_val,
            "target_price": target_val,
            "indicators": getattr(pred, 'indicators', {}),
            "models": pred.models or {},
            "regime": pred.regime or "Unknown",
            "factors": pred.factors or [],
            "explanation": pred.explanation or "Technical analysis",
        }
        result = _normalize_signal_payload(result, ltp)

        # Save to DB
        if async_session:
            try:
                async with async_session() as session:
                    pred_record = PredictionModel(
                        symbol=pred.symbol,
                        horizon=horizon,
                        predicted_price=pred.price,
                        signal=pred.signal,
                        confidence=pred.confidence,
                        stop_loss=pred.stop,
                        target=pred.target,
                        explanation=pred.explanation,
                    )
                    session.add(pred_record)
                    await session.commit()
            except Exception as e:
                logger.warning("Failed to save prediction to DB: %s", e)

        wrapped = {
            "status": "success",
            "data": result,
            "message": "Prediction generated successfully"
        }
        if not debug:
            await set_cache(key, wrapped, ttl=config.CACHE_TTL_PREDICTION_SECONDS)
        return wrapped
    except Exception as e:
        logger.error("Prediction failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "data": {
                "symbol": symbol,
                "prediction": 0,
                "signal": "HOLD",
                "confidence": 0,
                "error": str(e),
            }
        }
