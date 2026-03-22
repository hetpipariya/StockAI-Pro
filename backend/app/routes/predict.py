import logging
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

        # 3. Run prediction with real data (debug flag passed through)
        # Technical ensemble prediction (production fallback)
        from app.inference.feature_engineering import compute_features
        
        features_df = compute_features(candles)
        if features_df.empty or len(features_df) < 10:
            raise ValueError("Insufficient features for prediction")
        
        latest = features_df.iloc[-1]
        c = float(latest.get('close', ltp) or ltp)
        
        # Technical scores (-1 to +1)
        scores = []
        
        # EMA Trend (25%)
        ema20 = float(latest.get('ema_20', c))
        if c > ema20 * 1.002: scores.append(1.0)
        elif c < ema20 * 0.998: scores.append(-1.0)
        else: scores.append(0.0)
        
        # RSI Oversold/Overbought (25%)
        rsi = float(latest.get('rsi_14', 50))
        if rsi < 35: scores.append(1.0)  # Oversold BUY
        elif rsi > 65: scores.append(-1.0)  # Overbought SELL
        else: scores.append(0.0)
        
        # MACD Momentum (25%)
        macd = float(latest.get('macd', 0))
        macd_sig = float(latest.get('macd_signal', 0))
        if macd > macd_sig: scores.append(1.0)
        elif macd < macd_sig: scores.append(-1.0)
        else: scores.append(0.0)
        
        # VWAP Support (25%)
        vwap = float(latest.get('vwap', c))
        if c > vwap * 1.002: scores.append(1.0)
        elif c < vwap * 0.998: scores.append(-1.0)
        else: scores.append(0.0)
        
        score = np.mean(scores)
        
        # Signal + Confidence
        if score > 0.65:
            signal = 'BUY'
            confidence = int(65 + (score - 0.65) * 50)  # 65-95%
        elif score < -0.65:
            signal = 'SELL'
            confidence = int(65 + (abs(score) - 0.65) * 50)
        else:
            signal = 'HOLD'
            confidence = int(abs(score) * 80)  # 0-80%
        
        # ATR-based targets (14-period proxy)
        highs = [float(row['high']) for row in candles[-14:]]
        lows = [float(row['low']) for row in candles[-14:]]
        atr_proxy = (sum(highs) / len(highs) - sum(lows) / len(lows)) if candles else c * 0.02
        move_pct = max(atr_proxy / c, 0.01)
        
        if signal == 'BUY':
            target = round(c * (1 + move_pct * 1.5), 2)
            stop = round(c * (1 - move_pct * 0.75), 2)
            prediction = round(c * (1 + move_pct * 0.5), 2)
        elif signal == 'SELL':
            target = round(c * (1 - move_pct * 1.5), 2)
            stop = round(c * (1 + move_pct * 0.75), 2)
            prediction = round(c * (1 - move_pct * 0.5), 2)
        else:
            target = round(c * (1 + move_pct * 0.4), 2)
            stop = round(c * (1 - move_pct * 0.4), 2)
            prediction = round(c, 2)
        
        pred = type('Pred', (), {
            'symbol': symbol,
            'price': prediction,
            'signal': signal,
            'confidence': confidence,
            'target': target,
            'stop': stop,
            'regime': 'Technical',
            'models': {'technical_ensemble': confidence},
            'factors': [f'Score: {score:.2f}', f'RSI: {rsi:.0f}', f'MACD: {macd:.3f}'],
            'explanation': f'Technical ensemble score {score:.2f}: {signal} {confidence}%',
            'indicators': {
                'ema_20': round(ema20, 2),
                'rsi_14': round(rsi, 1),
                'macd': round(macd, 3),
                'macd_signal': round(macd_sig, 3),
                'vwap': round(vwap, 2),
                'score': round(score, 3)
            }
        })()

        # Use technical pred attributes directly
        target_val = float(pred.target) if hasattr(pred, 'target') and pred.target is not None else 0.0
        stop_val = float(pred.stop) if hasattr(pred, 'stop') and pred.stop is not None else 0.0
        
        logger.info("[PREDICT] %s signal=%s conf=%d%% (Technical Ensemble)", symbol, pred.signal, pred.confidence)
        result = {
            "symbol": getattr(pred, 'symbol', symbol),
            "prediction": getattr(pred, 'price', ltp),
            "signal": getattr(pred, 'signal', 'HOLD'),
            "confidence": getattr(pred, 'confidence', 0),
            "stop_loss": stop_val,
            "target_price": target_val,
            "indicators": getattr(pred, 'indicators', {}),
            "models": getattr(pred, 'models', {}),
            "regime": getattr(pred, 'regime', 'Unknown'),
            "factors": getattr(pred, 'factors', []),
            "explanation": getattr(pred, 'explanation', 'Technical analysis'),
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
        return result
    except Exception as e:
        logger.error("Prediction failed: %s", e)
        return {
            "symbol": symbol,
            "prediction": 0,
            "signal": "HOLD",
            "confidence": 0,
            "error": str(e),
        }
