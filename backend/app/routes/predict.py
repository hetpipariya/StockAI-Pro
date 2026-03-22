import logging
import numpy as np
from fastapi import APIRouter, Query

from app.inference.runner import predict_symbol
from app.services.redis_client import get_cache, set_cache
from app.services.db import async_session, PredictionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["predict"])


@router.get("/predict")
@router.get("/signal")
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
        candles = hist.get("data", []) if hist else []

        # Cache key includes latest candle marker to avoid stale predictions
        last_candle_time = "na"
        if candles:
            last_candle_time = str(candles[-1].get("time", "na"))
        key = f"pred:v2:{symbol}:{horizon}:{last_candle_time}"

        # Skip cache when debug is on so we always return fresh debug info
        if not debug:
            cached = await get_cache(key)
            if cached:
                return cached

        # 2. Get current LTP
        ltp = 0.0
        try:
            snap = await _fetch_snapshot(symbol)
            ltp = float(snap.get("ltp", 0) or 0)
        except Exception:
            if candles:
                ltp = float(candles[-1].get("close", 0))

        # 3. Run prediction using the real ModelEnsemble pipeline
        pred = predict_symbol(
            symbol=symbol,
            timeframe=horizon,
            latest_ltp=ltp,
            ohlcv=candles,
        )

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

        if not debug:
            await set_cache(key, result, ttl=30)
        return {
            "status": "success",
            "data": result,
            "message": "Prediction generated successfully"
        }
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
