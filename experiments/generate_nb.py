import json
import os

cells = []

def add_md(text):
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in text.splitlines()]
    })

def add_code(text):
    # Ensure final line doesn't have \n
    lines = [line + "\n" for line in text.splitlines()]
    if lines:
        lines[-1] = lines[-1].rstrip("\n")
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": lines
    })

# 1. Imports
add_md("## 1. Imports & Configuration")
add_code("""import os
import sys
import pandas as pd
import numpy as np
import warnings
import joblib

from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

warnings.filterwarnings('ignore')

# Print working directory and verify paths explicitly as requested
EXPERIMENTS_DIR = os.getcwd()
DATA_FILE = os.path.join(EXPERIMENTS_DIR, "data", "train_data.csv")
MODELS_DIR = os.path.join(EXPERIMENTS_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

print(f"Working Directory: {EXPERIMENTS_DIR}")
print(f"Dataset Path: {DATA_FILE}")
print(f"Models Export Path: {MODELS_DIR}")""")

# 2. Load Data
add_md("## 2. Load Data")
add_code("""if not os.path.exists(DATA_FILE):
    raise FileNotFoundError(f"Dataset missing! Could not find: {DATA_FILE}")

# Engine Python is used to avoid parsing warnings
df = pd.read_csv(DATA_FILE)
print(f"Successfully loaded dataset: {len(df)} rows | {df.shape[1]} columns.")
display(df.tail(3))""")

# 3. Clean Data & Validate core features
add_md("## 3. Data Cleaning & Base Feature Validation")
add_code("""# Handle missing values and normalize structures
df.columns = [str(c).lower().strip() for c in df.columns]

if 'close' in df.columns and 'target' in df.columns:
    df.dropna(subset=['close', 'target'], inplace=True)
else:
    raise ValueError("Dataset missing vital 'close' or 'target' target columns!")

# Ensure required features exist natively
necessary_cols = ['open', 'high', 'low', 'close', 'volume']
for req in necessary_cols:
    if req not in df.columns:
        raise ValueError(f"CRITICAL: Missing required numeric column '{req}'")

# Force conversions to float where appropriate
for col in necessary_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce')

df.dropna(subset=necessary_cols, inplace=True)

# Recreate Base Indicators if missing
if 'ema_20' not in df.columns: df['ema_20'] = df['close'].ewm(span=20).mean()
if 'ema_50' not in df.columns: df['ema_50'] = df['close'].ewm(span=50).mean()
if 'macd' not in df.columns: df['macd'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
if 'macd_hist' not in df.columns: df['macd_hist'] = df['macd'] - df['macd'].ewm(span=9).mean()
if 'vwap' not in df.columns:
    # Volume weighted average price approximation
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

print("Base features validated securely.")""")

# 4. Feature Engineering
add_md("## 4. Advanced Feature Engineering\\nAdd: `price_change`, `volatility`, `momentum`, `rolling_mean_5`, `rolling_std_5` per ticker")
add_code("""def engineer_advanced_features(group):
    group = group.copy()
    c = group['close']
    h = group['high']
    l = group['low']
    
    group['price_change'] = c - group['open']
    
    # Avoid zero-division with clip
    safe_c = c.clip(lower=1e-5)
    group['volatility'] = (h - l) / safe_c
    group['momentum'] = c - c.shift(3)
    group['rolling_mean_5'] = c.rolling(window=5, min_periods=1).mean()
    group['rolling_std_5'] = c.rolling(window=5, min_periods=2).std()
    
    return group

# Use modern group mapping
new_df = []
for ticker, group in df.groupby('ticker'):
    new_df.append(engineer_advanced_features(group))
    
df = pd.concat(new_df).reset_index(drop=True)

# Thoroughly wipe generated infinity/NaN from shifting calculations
df.replace([np.inf, -np.inf], np.nan, inplace=True)
df.fillna(0, inplace=True)

print(f"Data remaining after engineering: {len(df)} rows ready for modeling.")""")

# 5. Time Series Split
add_md("## 5. Time Series Train/Test Split\\nProper sequential split (`shuffle=False`)")
add_code("""# Strict Time-bound sorting to eliminate data leakage
if 'date' in df.columns:
    df.sort_values(by='date', inplace=True)
df.reset_index(drop=True, inplace=True)

# Exclude identifier/target columns
exclude_cols = ['ticker', 'date', 'target']
feature_cols = [c for c in df.columns if c not in exclude_cols and np.issubdtype(df[c].dtype, np.number)]
print(f"Selected {len(feature_cols)} robust predictors.")

X = df[feature_cols].values
y = df['target'].values

# Split exactly chronologically 80% Train, 20% Test (shuffle=False implicit to slicing)
split_idx = int(len(X) * 0.80)
X_train, X_test = X[:split_idx], X[split_idx:]
y_train, y_test = y[:split_idx], y[split_idx:]

print(f"Training samples: {len(X_train)}")
print(f"Testing samples : {len(X_test)}")

# Safely Scale utilizing mathematical resilience
scaler = RobustScaler()
X_train_sc = scaler.fit_transform(X_train)
X_test_sc  = scaler.transform(X_test)

X_train_sc = np.nan_to_num(X_train_sc, nan=0.0)
X_test_sc  = np.nan_to_num(X_test_sc, nan=0.0)""")

# 6. Model Training
add_md("## 6. Model Training\\nTrain XGBoost, RandomForest, and LogisticRegression natively.")
add_code("""models = {
    'XGBoost': XGBClassifier(n_estimators=100, max_depth=5, learning_rate=0.05, use_label_encoder=False, eval_metric='logloss'),
    'RandomForest': RandomForestClassifier(n_estimators=100, max_depth=6, min_samples_split=10, n_jobs=-1),
    'LogisticRegression': LogisticRegression(max_iter=500, class_weight='balanced')
}

predictions = {}

for name, model in models.items():
    print(f"Training {name}...")
    model.fit(X_train_sc, y_train)
    predictions[name] = model.predict(X_test_sc)

print("All algorithms optimized and mapped.")""")

# 7. Model Comparison
add_md("## 7. Model Comparison\\nCalculate Accuracy, Precision, Recall, and F1 Score.")
add_code("""results = []

for name, preds in predictions.items():
    acc = accuracy_score(y_test, preds)
    prec = precision_score(y_test, preds, zero_division=0)
    rec = recall_score(y_test, preds, zero_division=0)
    f1 = f1_score(y_test, preds, zero_division=0)
    
    results.append({
        'Model': name,
        'Accuracy': acc,
        'Precision': prec,
        'Recall': rec,
        'F1_Score': f1
    })

results_df = pd.DataFrame(results).set_index('Model')
display(results_df.round(4))""")

# 8. Select & Save Best
add_md("## 8. Select & Save Best Model\\nPick the winner natively and write `model.pkl` to `experiments/models/`")
add_code("""# Automatically choose the model with the highest structural F1 Score
best_model_name = results_df['F1_Score'].idxmax()
best_model = models[best_model_name]

print(f"\\\\n\\u2605 BEST PERFORMER: {best_model_name} (F1 Score: {results_df.loc[best_model_name, 'F1_Score']:.4f})")

# Export to exactly the requested path: experiments/models/model.pkl
model_path = os.path.join(MODELS_DIR, "model.pkl")

# We highly recommend dumping the scaler and features vector list for API bindings as well
scaler_path = os.path.join(MODELS_DIR, "scaler.pkl")
features_path = os.path.join(MODELS_DIR, "features.pkl")

joblib.dump(best_model, model_path)
joblib.dump(scaler, scaler_path)
joblib.dump(feature_cols, features_path)

print(f"\\\\nSUCCESS! Model accurately saved securely to:")
print(f" -> {model_path}")
print("Ready for live trading deployment.")""")

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "codemirror_mode": {"name": "ipython", "version": 3},
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.9.11"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 4
}

# The user explicitly requires 'training_template.ipynb'
out_path = os.path.join(os.path.dirname(__file__), 'training_template.ipynb')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(notebook, f, indent=2)

print(f"training_template.ipynb successfully built at {out_path}!")
