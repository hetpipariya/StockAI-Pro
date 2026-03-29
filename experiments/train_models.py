import os
import sys
import pandas as pd
import numpy as np
import logging
import joblib

from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Fix Paths relative to current directory
EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(EXPERIMENTS_DIR, "data", "train_data.csv")
MODELS_DIR = os.path.join(os.path.dirname(EXPERIMENTS_DIR), "models")

MODEL_OUT = os.path.join(MODELS_DIR, "model.pkl")
SCALER_OUT = os.path.join(MODELS_DIR, "scaler.pkl")
FEATURES_OUT = os.path.join(MODELS_DIR, "features.pkl")

def engineer_features(df):
    """
    Add advanced features safely without data leakage grouping by ticker.
    Required: price change, volatility, rolling mean, rolling std, momentum, trend strength
    """
    df = df.copy()
    
    # Calculate per-ticker to prevent rolling windows from bleeding between stocks
    def add_features(group):
        group = group.sort_values("date")
        c = group['close']
        
        # Price change (momentum)
        group['pct_change_1d'] = c.pct_change(1)
        group['pct_change_5d'] = c.pct_change(5)
        
        # Volatility (Rolling Std)
        group['roll_std_5d'] = group['pct_change_1d'].rolling(5).std()
        group['roll_std_20d'] = group['pct_change_1d'].rolling(20).std()
        
        # Rolling Mean
        group['roll_mean_5d'] = c.rolling(5).mean()
        group['roll_mean_20d'] = c.rolling(20).mean()
        
        # Trend strength (Distance from EMA20)
        if 'ema_20' not in group.columns:
            group['ema_20'] = c.ewm(span=20, adjust=False).mean()
        group['trend_strength'] = (c - group['ema_20']) / group['ema_20']
        
        # Momentum (RSI change)
        if 'rsi_14' in group.columns:
            group['rsi_momentum'] = group['rsi_14'].diff()
        else:
            group['rsi_momentum'] = 0.0
            
        return group
    
    df = df.groupby('ticker', group_keys=False).apply(add_features)
    
    # Drop rows with NaNs created by rolling windows (e.g. first 20 days)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)
    return df

def run_training():
    if not os.path.exists(DATA_PATH):
        logging.error(f"Dataset not found at {DATA_PATH}. Run build_dataset.py first.")
        return

    logging.info("Loading dataset...")
    df = pd.read_csv(DATA_PATH)
    
    logging.info("Engineering advanced features...")
    df = engineer_features(df)
    
    # Sort strictly by date to ensure proper time-based split
    logging.info("Sorting by Time to prevent data leakage...")
    df.sort_values(by="date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # Identify feature columns
    exclude_cols = ['ticker', 'date', 'target']
    feature_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in [np.float64, np.float32, np.int64, np.int32]]
    
    logging.info(f"Total features utilized: {len(feature_cols)}")
    
    X = df[feature_cols].values
    y = df['target'].values
    
    # Time-based split: 80% Train, 20% Test sequentially
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    logging.info(f"Train samples: {len(X_train)} | Test samples: {len(X_test)}")
    
    # Normalize / Scale Features safely (RobustScaler handles huge financial outliers perfectly)
    logging.info("Scaling features (RobustScaler)...")
    scaler = RobustScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Clean any residual infinities mathematically evaluating to zero
    X_train_scaled = np.nan_to_num(X_train_scaled, nan=0.0, posinf=0.0, neginf=0.0)
    X_test_scaled = np.nan_to_num(X_test_scaled, nan=0.0, posinf=0.0, neginf=0.0)
    
    # --- MODEL DEFINITIONS ---
    logging.info("Training Model 1: XGBoost...")
    xgb = XGBClassifier(
        n_estimators=300, 
        max_depth=5, 
        learning_rate=0.05, 
        random_state=42, 
        use_label_encoder=False, 
        eval_metric='logloss',
        n_jobs=-1
    )
    
    logging.info("Training Model 2: RandomForest...")
    rf = RandomForestClassifier(
        n_estimators=300, 
        max_depth=8, 
        min_samples_split=10, 
        random_state=42,
        n_jobs=-1
    )
    
    logging.info("Training Model 3: LogisticRegression...")
    lr = LogisticRegression(
        max_iter=1000, 
        C=0.1, 
        class_weight='balanced', 
        random_state=42
    )
    
    logging.info("Building & Training Ensemble (Soft Voting)...")
    ensemble = VotingClassifier(
        estimators=[('xgb', xgb), ('rf', rf), ('lr', lr)],
        voting='soft',
        n_jobs=-1
    )
    
    ensemble.fit(X_train_scaled, y_train)
    
    # --- EVALUATION ---
    logging.info("Generating Predictions...")
    preds = ensemble.predict(X_test_scaled)
    probs = ensemble.predict_proba(X_test_scaled)[:, 1]
    
    acc = accuracy_score(y_test, preds)
    prec = precision_score(y_test, preds, zero_division=0)
    rec = recall_score(y_test, preds, zero_division=0)
    f1 = f1_score(y_test, preds, zero_division=0)
    
    logging.info(f"--- MODEL EVALUATION ---")
    logging.info(f"Accuracy : {acc:.4f}")
    logging.info(f"Precision: {prec:.4f}")
    logging.info(f"Recall   : {rec:.4f}")
    logging.info(f"F1 Score : {f1:.4f}")
    
    # Save the robust trained ensemble and the required feature transformers
    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(ensemble, MODEL_OUT)
    joblib.dump(scaler, SCALER_OUT)
    joblib.dump(feature_cols, FEATURES_OUT)
    
    logging.info(f"✔ Best Model saved: {MODEL_OUT}")
    logging.info(f"✔ Scaler pipeline saved: {SCALER_OUT}")
    logging.info(f"✔ Feature Map saved: {FEATURES_OUT}")

if __name__ == "__main__":
    run_training()
