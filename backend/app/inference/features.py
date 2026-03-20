import pandas as pd
import numpy as np
from typing import List, Dict, Any

from app.services.indicators import IndicatorEngine

def extract_features(ohlcv: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Given raw OHLCV data, calculates indicators and extracts feature vectors
    for model inference. Returns a DataFrame with normalized features.
    """
    if not ohlcv or len(ohlcv) < 50:
        return pd.DataFrame()
        
    # Calculate indicators
    df = IndicatorEngine.compute_all(ohlcv)
    if 'time' in df.columns:
        df.set_index('time', inplace=True)
        
    # Drop rows with NaNs from rolling windows
    df.dropna(inplace=True)
    if len(df) == 0:
        return pd.DataFrame()
        
    # Feature columns we care about
    feature_cols = [
        'open', 'high', 'low', 'close', 'volume',
        'ema9', 'ema15', 'sma20', 'vwap', 
        'rsi9', 'macd', 'macd_hist', 'stoch_k', 'stoch_d', 'cci20', 'roc9',
        'bb_upper', 'bb_lower', 'atr14',
        'adx14', 'obv'
    ]
    
    available_cols = [c for c in feature_cols if c in df.columns]
    features_df = df[available_cols].copy()
    
    # Simple percentage changes relative to close
    for col in ['ema9', 'ema15', 'sma20', 'vwap', 'bb_upper', 'bb_lower']:
        if col in features_df.columns:
            features_df[f'{col}_dist'] = (features_df[col] - features_df['close']) / features_df['close']
            
    # Calculate log returns
    features_df['log_ret'] = np.log(features_df['close'] / features_df['close'].shift(1))
    
    # Fill remaining NaNs
    features_df.fillna(0, inplace=True)
    
    # Scale features (StandardScaler logic but hardcoded here for simplicity if no scikit fitted scaler is saved)
    # In production, you would load the fitted scaler from training.
    for col in features_df.columns:
        if features_df[col].std() > 0:
            features_df[col] = (features_df[col] - features_df[col].mean()) / features_df[col].std()
            
    return features_df

def get_latest_sequence(features_df: pd.DataFrame, sequence_length: int = 20) -> np.ndarray:
    """Returns the most recent sequence for RNN/LSTM/GRU inputs."""
    if len(features_df) < sequence_length:
        return np.array([])
    return features_df.iloc[-sequence_length:].values

def get_latest_tabular(features_df: pd.DataFrame) -> np.ndarray:
    """Returns the most recent row for XGBoost inputs."""
    if len(features_df) == 0:
        return np.array([])
    return features_df.iloc[-1:].values
