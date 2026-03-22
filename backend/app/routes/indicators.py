import logging
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional

from app.services.indicators import IndicatorEngine
from app.routes.market import get_history

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/indicators", tags=["indicators"])

@router.get("")
async def get_indicators(
    symbol: str = Query(...),
    interval: str = Query("1m"),
    indicators: str = Query("ema9,rsi9,macd", description="Comma separated indicators")
):
    """
    Get indicator values for a symbol.
    Fetches the history, computes all indicators, and returns the requested ones.
    """
    try:
        # Fetch up to 500 candles
        history_response = await get_history(symbol=symbol, interval=interval, limit=500)
        
        if not history_response or "data" not in history_response:
            raise HTTPException(404, "Data not found")
            
        candles = history_response["data"]
        
        if not candles:
            return {"status": "success", "data": {"symbol": symbol, "data": []}, "message": "No candles found"}
            
        df = IndicatorEngine.compute_all(candles)
        
        # Reset index to get 'time' back as a column if it was used as index
        if 'time' not in df.columns and df.index.name == 'time':
            df.reset_index(inplace=True)
        elif 'time' not in df.columns:
            # If time is neither column nor index, skip (shouldn't happen)
            return {"status": "success", "data": {"symbol": symbol, "data": []}, "message": "Time column missing"}
        
        # Parse requested indicators
        ind_list = [i.strip().lower() for i in indicators.split(",")]
        
        # Ensure we always return the time column
        cols_to_return = ["time"]
        for ind in ind_list:
            if ind in df.columns:
                cols_to_return.append(ind)
                
            # Handle group requests
            if ind == "bb":
                for c in ["bb_upper", "bb_lower", "sma20"]:
                    if c in df.columns:
                        cols_to_return.append(c)
            if ind == "macd":
                for c in ["macd_signal", "macd_hist"]:
                    if c in df.columns:
                        cols_to_return.append(c)
            if ind == "stoch":
                for c in ["stoch_k", "stoch_d"]:
                    if c in df.columns:
                        cols_to_return.append(c)
            if ind == "scalp_pro":
                for sc in ["scalp_macd", "scalp_signal", "scalp_buy", "scalp_sell"]:
                    if sc in df.columns:
                        cols_to_return.append(sc)
            if ind == "supertrend" and "supertrend" in df.columns:
                cols_to_return.append("supertrend")
            if ind == "ichimoku":
                for c in ["tenkan_sen"]:
                    if c in df.columns:
                        cols_to_return.append(c)
                
        # Deduplicate columns
        cols_to_return = list(dict.fromkeys([c for c in cols_to_return if c in df.columns]))
        
        result_df = df[cols_to_return]
        
        # Convert to records
        result_data = result_df.to_dict(orient="records")
        
        return {
            "status": "success",
            "data": {
                "symbol": symbol,
                "interval": interval,
                "data": result_data
            },
            "message": "Indicators calculated successfully"
        }
        
    except Exception as e:
        logger.error(f"Indicator calculation failed: {e}")
        raise HTTPException(500, str(e))
