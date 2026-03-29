"""
Backtesting API wrapper for experiments/intraday_backtest.py logic.
Provides async execution for heavy simulation tasks.
"""
import asyncio
import logging
import os
import numpy as np
import pandas as pd

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from app.inference.feature_engineering import FEATURE_COLUMNS, compute_features
from app.inference.models import load_models
from app.routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# Risk configurations 
SLIPPAGE_BPS = 0.02 / 100 
BROKERAGE_BPS = 0.03 / 100 
TOTAL_COST = SLIPPAGE_BPS + BROKERAGE_BPS
RISK_PER_TRADE = 0.01  
REWARD_RISK_RATIO = 1.5
ATR_STOP_MULTIPLIER = 1.5

# Data directory path
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "experiments", "data", "train_data.csv")

class BacktestRequest(BaseModel):
    symbol: str = Field(..., description="Stock Symbol")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    capital: float = Field(100000.0, ge=1000)

@router.post("")
async def run_backtest(
    req: BacktestRequest,
    current_user=Depends(get_current_user)
):
    """Run an asynchronous backtest simulation using XGBoost models on historical data."""
    try:
        # Run heavy compute in a separate thread to not block the FastAPI event loop
        result = await asyncio.to_thread(_execute_backtest_sync, req.symbol.upper(), req.start_date, req.end_date, req.capital)
        return result
    except FileNotFoundError as e:
        logger.error(f"[BACKTEST] Data file missing: {e}")
        raise HTTPException(status_code=404, detail="Training data not found. Please run build_dataset.py in experiments.")
    except Exception as e:
        logger.error(f"[BACKTEST] Simulation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _load_prediction_pipeline():
    """Load and validate the production model artifacts for backtest parity."""
    from app.inference import models as inference_models

    if not inference_models._ensemble_model:
        load_models()

    model = inference_models._ensemble_model
    scaler = inference_models._scaler
    features_list = inference_models._features_list

    if model is None or scaler is None or not features_list:
        raise RuntimeError("Model artifacts unavailable. Train or mount model.pkl first.")

    if list(features_list) != list(FEATURE_COLUMNS):
        raise RuntimeError(
            f"Feature contract mismatch in backtest. Expected {len(FEATURE_COLUMNS)} canonical features."
        )

    return model, scaler, features_list

def _execute_backtest_sync(target_symbol: str, start_date: str, end_date: str, initial_capital: float) -> dict:
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f"Missing {DATA_FILE}")

    logger.info(f"[BACKTEST] Starting simulation for {target_symbol}")
    df = pd.read_csv(DATA_FILE)
    df.columns = [c.lower() for c in df.columns]

    required_cols = {"date", "ticker", "open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in backtest data: {sorted(missing)}")

    df['date'] = pd.to_datetime(df['date'])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)
    
    df.sort_values(by=['ticker', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Filtering by symbol early reduces load
    df_symbol = df[df['ticker'] == target_symbol].copy()
    
    if df_symbol.empty:
        raise ValueError(f"No data available for symbol {target_symbol}")

    feature_df = compute_features(df_symbol[["open", "high", "low", "close", "volume"]])
    if feature_df.empty:
        raise ValueError("Unable to compute canonical features for backtest window.")

    df_symbol = pd.concat(
        [df_symbol.reset_index(drop=True), feature_df.reset_index(drop=True)],
        axis=1,
    )

    model, scaler, features_list = _load_prediction_pipeline()

    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    mask = (df_symbol['date'] >= start_ts) & (df_symbol['date'] <= end_ts)
    df_test = df_symbol.loc[mask].copy()

    if df_test.empty:
        raise ValueError("Selected date range contains no trading data.")

    x_input = df_test[features_list].astype(float).to_numpy()
    x_scaled = scaler.transform(x_input)
    x_scaled = np.nan_to_num(x_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    proba = model.predict_proba(x_scaled)
    prob_up = proba[:, 1]
    prob_down = 1.0 - prob_up
    df_test['ml_pred'] = np.where(prob_up >= 0.60, 1, np.where(prob_down >= 0.60, 0, -1))

    df_test['signal_buy'] = (
        (df_test['ml_pred'] == 1) & 
        (df_test['close'] > df_test['ema_50']) &
        (df_test['ema_9'] > df_test['ema_21']) &
        (df_test['volume_spike'] == 1) &
        (df_test['rsi_14'] > 55) & (df_test['rsi_14'] < 75) &
        (df_test['atr_14'] > df_test['close'] * 0.003) 
    )

    df_test['signal_sell'] = (
        (df_test['ml_pred'] == 0) & 
        (df_test['close'] < df_test['ema_50']) &
        (df_test['ema_9'] < df_test['ema_21']) &
        (df_test['volume_spike'] == 1) &
        (df_test['rsi_14'] > 25) & (df_test['rsi_14'] < 45) &
        (df_test['atr_14'] > df_test['close'] * 0.003)
    )

    capital = initial_capital
    peak_capital = capital
    max_drawdown = 0.0

    trade_log = []
    equity_curve = [{"time": start_date, "value": capital}]
    winning_trades = 0

    in_pos = False
    trade_type = ""
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0
    pos_size = 0.0  
    locked_stop_dist = 0.0
    entry_time = None

    for idx, row in df_test.iterrows():
        c = row['close']
        h = row['high']
        l = row['low']
        atr = row['atr_14']
        t_str = str(row['date'])
        
        if in_pos:
            exit_flag = False
            exit_price = 0.0
            
            if trade_type == "BUY":
                if c > entry_price + locked_stop_dist:
                    new_stop = c - locked_stop_dist
                    if new_stop > stop_price: stop_price = new_stop
                    
                if h >= target_price: 
                    exit_price = target_price
                    exit_flag = True
                elif l <= stop_price:
                    exit_price = stop_price
                    exit_flag = True
                    
            elif trade_type == "SELL":
                if c < entry_price - locked_stop_dist:
                    new_stop = c + locked_stop_dist
                    if new_stop < stop_price: stop_price = new_stop
                    
                if l <= target_price:
                    exit_price = target_price
                    exit_flag = True
                elif h >= stop_price:
                    exit_price = stop_price
                    exit_flag = True
                    
            if exit_flag:
                if trade_type == "BUY": raw_pnl = (exit_price - entry_price) / entry_price
                else: raw_pnl = (entry_price - exit_price) / entry_price
                
                net_move = raw_pnl - (2 * TOTAL_COST)
                capital_pnl = capital * pos_size * net_move
                capital += capital_pnl
                
                if net_move > 0: winning_trades += 1
                if capital > peak_capital: peak_capital = capital
                
                current_dd = (peak_capital - capital) / peak_capital
                if current_dd > max_drawdown: max_drawdown = current_dd
                    
                trade_log.append({
                    "symbol": target_symbol,
                    "direction": trade_type,
                    "entry_time": entry_time,
                    "exit_time": t_str,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(capital_pnl, 2),
                    "pnl_pct": round(net_move * 100, 2)
                })
                equity_curve.append({
                    "time": t_str,
                    "value": round(capital, 2)
                })
                in_pos = False
                
        if not in_pos and atr > 0:
            if row['signal_buy']:
                in_pos = True
                trade_type = "BUY"
                entry_price = c
                entry_time = t_str
                
                locked_stop_dist = ATR_STOP_MULTIPLIER * atr
                stop_price = c - locked_stop_dist
                target_price = c + (locked_stop_dist * REWARD_RISK_RATIO)
                
                max_shares = (capital * RISK_PER_TRADE) / locked_stop_dist
                pos_size = min(1.0, (max_shares * entry_price) / capital)
                
            elif row['signal_sell']:
                in_pos = True
                trade_type = "SELL"
                entry_price = c
                entry_time = t_str
                
                locked_stop_dist = ATR_STOP_MULTIPLIER * atr
                stop_price = c + locked_stop_dist
                target_price = c - (locked_stop_dist * REWARD_RISK_RATIO)
                
                max_shares = (capital * RISK_PER_TRADE) / locked_stop_dist
                pos_size = min(1.0, (max_shares * entry_price) / capital)

    # Ensure last data point is in equity curve even if no trade closed
    if equity_curve[-1]["time"] != str(df_test.iloc[-1]['date']):
        equity_curve.append({
            "time": str(df_test.iloc[-1]['date']),
            "value": round(capital, 2)
        })

    win_rate = (winning_trades / len(trade_log) * 100) if trade_log else 0
    roi = ((capital - initial_capital) / initial_capital) * 100

    return {
        "symbol": target_symbol,
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "total_trades": len(trade_log),
        "win_rate": round(win_rate, 2),
        "roi_pct": round(roi, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "equity_curve": equity_curve,
        "trades": trade_log[::-1] # Newest first
    }
