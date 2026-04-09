import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.services.bundle_service import get_prediction as get_prediction_service

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
        "timestamp": datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }


# Deprecated: replaced by /api/bundle
@router.get("/predict/{symbol}", deprecated=True)
async def get_predict_by_path(symbol: str):
    """Path alias for prediction endpoint; delegates to the main runner pipeline."""
    normalized_symbol = symbol.strip().upper()
    try:
        response = await get_predict(
            symbol=normalized_symbol, horizon="15m", debug=False
        )
        if isinstance(response, dict) and isinstance(response.get("data"), dict):
            return response["data"]
        return response
    except Exception as exc:
        logger.error("Path prediction failed for %s: %s", normalized_symbol, exc)
        return _path_hold_fallback(normalized_symbol, reason=f"HOLD fallback: {exc}")


# Deprecated: replaced by /api/bundle
@router.get("/predict", deprecated=True)
async def get_predict(
    symbol: str = Query(...),
    horizon: str = Query("15m", description="15m prediction horizon"),
    debug: bool = Query(
        False, description="Include debug info (feature values, probabilities)"
    ),
):
    """Get AI prediction for symbol using shared bundle data services."""
    normalized_symbol = symbol.strip().upper()

    try:
        result = await get_prediction_service(
            symbol=normalized_symbol,
            horizon=horizon,
        )
        return {
            "status": "success",
            "data": result,
            "message": "Prediction generated successfully",
        }
    except Exception as exc:
        logger.error("Prediction failed for %s: %s", normalized_symbol, exc, exc_info=True)
        return {
            "status": "error",
            "data": _path_hold_fallback(
                normalized_symbol,
                reason=f"HOLD fallback: {exc}",
            ),
            "message": "Prediction failed",
        }


@router.get("/predict/signal/{symbol}")
async def get_signal(symbol: str):
    """Get AI trading signal for a specific symbol (path-based)."""
    normalized_symbol = symbol.strip().upper()
    
    try:
        result = await get_prediction_service(
            symbol=normalized_symbol,
            horizon="15m",
        )
        
        # Extract just the signal data in the format the frontend expects
        signal_data = {
            "symbol": normalized_symbol,
            "signal": result.get("signal", "HOLD"),
            "confidence": result.get("confidence", 0),
            "prediction": result.get("prediction", 0.0),
            "currentPrice": result.get("currentPrice", 0.0),
            "target_price": result.get("target_price", 0.0),
            "stop_loss": result.get("stop_loss", 0.0),
            "target": result.get("target", 0.0),
            "stopLoss": result.get("stopLoss", 0.0),
            "regime": result.get("regime", "Unknown"),
            "explanation": result.get("explanation", ""),
            "timestamp": result.get("timestamp", 
                datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        }
        
        return {
            "status": "success",
            "data": signal_data,
            "message": "Signal retrieved successfully",
        }
    except Exception as exc:
        logger.error("Signal fetch failed for %s: %s", normalized_symbol, exc, exc_info=True)
        return {
            "status": "error",
            "data": _path_hold_fallback(
                normalized_symbol,
                reason=f"HOLD fallback: {exc}",
            ),
            "message": "Signal fetch failed",
        }
