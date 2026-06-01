"""
Complete Model Training Script
===============================

End-to-end example showing how to train a production-grade XGBoost model
with the StockAI Pro feature engineering system.

Usage:
    python train_production_model.py

This will:
1. Load historical OHLCV data
2. Compute 20 production features
3. Generate labels (3-candle horizon)
4. Temporal train/val/test split
5. Train XGBoost with early stopping
6. Walk-forward validation
7. Save model + scaler
8. Report metrics

Version: v1.0
Updated: 2026-05-12
"""

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)

from app.inference.feature_engineering import (
    compute_features,
    validate_features,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
)
from app.inference.label_generation import (
    generate_labels,
    temporal_train_val_test_split,
    walk_forward_split,
    get_label_stats,
)

# ────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Model configuration
MODEL_VERSION = "v1.0"
MODEL_NAME = "reliance_5m_model"
MODEL_DIR = Path("backend/app/inference/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# XGBoost hyperparameters
XGBOOST_PARAMS = {
    "n_estimators": 250,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "multi:softprob",
    "num_class": 3,
    "random_state": 42,
    "tree_method": "hist",
    "eval_metric": "mlogloss",
}

# Label thresholds
LABEL_HORIZON = 3  # 3-4 candle prediction


# ────────────────────────────────────────────────────────────────────────────
# STEP 1: LOAD DATA
# ────────────────────────────────────────────────────────────────────────────


def load_historical_data(symbol: str, csv_path: str) -> pd.DataFrame:
    """
    Load historical OHLCV data.
    
    Args:
        symbol: Stock symbol
        csv_path: Path to CSV file
    
    Expected columns: time, open, high, low, close, volume
    """
    logger.info(f"[LOAD] Loading data for {symbol} from {csv_path}")
    
    ohlcv = pd.read_csv(csv_path)
    
    # Ensure required columns
    required_cols = ["open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in ohlcv.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Ensure correct data types
    for col in required_cols:
        ohlcv[col] = pd.to_numeric(ohlcv[col], errors="coerce")
    
    # Drop NaN rows
    ohlcv = ohlcv.dropna(subset=required_cols)
    
    logger.info(f"[LOAD] Loaded {len(ohlcv)} candles")
    return ohlcv.reset_index(drop=True)


# ────────────────────────────────────────────────────────────────────────────
# STEP 2: COMPUTE FEATURES
# ────────────────────────────────────────────────────────────────────────────


def engineer_features(ohlcv: pd.DataFrame, nifty_data: pd.DataFrame = None) -> pd.DataFrame:
    """
    Compute 20 production features.
    
    Args:
        ohlcv: OHLCV DataFrame
        nifty_data: Optional NIFTY data for context
    
    Returns:
        DataFrame with 20 features
    """
    logger.info("[ENGINEER] Computing 20 production features")
    
    features = compute_features(
        ohlcv_5m=ohlcv,
        ohlcv_15m=None,  # Use only 5m if 15m not available
        ohlcv_daily=None,  # Use only 5m if daily not available
        nifty_data=nifty_data,
    )
    
    # Validate
    if not validate_features(features):
        logger.error("[ENGINEER] Feature validation failed")
        raise ValueError("Feature validation failed")
    
    logger.info(f"[ENGINEER] Generated {len(features.columns)} features")
    logger.info(f"[ENGINEER] Features: {', '.join(FEATURE_COLUMNS)}")
    
    return features


# ────────────────────────────────────────────────────────────────────────────
# STEP 3: GENERATE LABELS
# ────────────────────────────────────────────────────────────────────────────


def prepare_labels(ohlcv: pd.DataFrame, horizon: int = LABEL_HORIZON) -> pd.Series:
    """
    Generate labels from future returns.
    
    Args:
        ohlcv: OHLCV DataFrame
        horizon: Prediction horizon (candles)
    
    Returns:
        Series with labels: 1 (BUY), 0 (HOLD), -1 (SELL)
    """
    logger.info(f"[LABELS] Generating labels (horizon={horizon} candles)")
    
    labels = generate_labels(ohlcv, horizon=horizon)
    stats = get_label_stats(labels)
    
    logger.info(
        f"[LABELS] Distribution: "
        f"BUY={stats.buy_count} ({stats.buy_pct:.1%}), "
        f"HOLD={stats.hold_count} ({stats.hold_pct:.1%}), "
        f"SELL={stats.sell_count} ({stats.sell_pct:.1%})"
    )
    
    if stats.has_imbalance:
        logger.warning("[LABELS] Label imbalance detected — consider class weighting")
    
    return labels


# ────────────────────────────────────────────────────────────────────────────
# STEP 4: NORMALIZATION & SCALING
# ────────────────────────────────────────────────────────────────────────────


def fit_scaler(features: pd.DataFrame) -> StandardScaler:
    """Fit feature scaler (on training data only)."""
    logger.info("[SCALE] Fitting StandardScaler")
    scaler = StandardScaler()
    scaler.fit(features)
    return scaler


def apply_scaler(features: pd.DataFrame, scaler: StandardScaler) -> np.ndarray:
    """Apply scaler to features."""
    return scaler.transform(features)


# ────────────────────────────────────────────────────────────────────────────
# STEP 5: TRAIN/VAL/TEST SPLIT
# ────────────────────────────────────────────────────────────────────────────


def split_data(features: pd.DataFrame, labels: pd.Series):
    """
    Temporal train/val/test split (NO RANDOM SHUFFLE).
    
    Returns:
        Train/val/test sets with indices
    """
    logger.info("[SPLIT] Creating temporal train/val/test split (70/15/15)")
    
    split = temporal_train_val_test_split(features, labels)
    
    logger.info(f"[SPLIT] Train: {len(split.train_features)} samples")
    logger.info(f"[SPLIT] Val: {len(split.val_features)} samples")
    logger.info(f"[SPLIT] Test: {len(split.test_features)} samples")
    
    # Show dates
    if hasattr(features, "index"):
        logger.info(
            f"[SPLIT] Date range: "
            f"{split.split_dates.get('train_start')} → {split.split_dates.get('train_end')}"
        )
    
    return split


# ────────────────────────────────────────────────────────────────────────────
# STEP 6: TRAIN MODEL
# ────────────────────────────────────────────────────────────────────────────


def train_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> xgb.XGBClassifier:
    """
    Train XGBoost model with early stopping.
    
    Args:
        X_train: Training features
        y_train: Training labels
        X_val: Validation features
        y_val: Validation labels
    
    Returns:
        Trained model
    """
    logger.info("[TRAIN] Training XGBoost model")
    logger.info(f"[TRAIN] Params: {XGBOOST_PARAMS}")
    
    model = xgb.XGBClassifier(**XGBOOST_PARAMS)
    
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        early_stopping_rounds=25,
        verbose=10,
    )
    
    best_score = model.best_score
    best_iteration = model.best_iteration
    
    logger.info(f"[TRAIN] Best validation score: {best_score:.4f} (iter {best_iteration})")
    
    return model


# ────────────────────────────────────────────────────────────────────────────
# STEP 7: EVALUATE MODEL
# ────────────────────────────────────────────────────────────────────────────


def evaluate_model(
    model: xgb.XGBClassifier,
    X_test: np.ndarray,
    y_test: np.ndarray,
    set_name: str = "Test",
) -> dict:
    """Evaluate model on test set."""
    logger.info(f"[EVAL] Evaluating on {set_name} set")
    
    # Predictions
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    
    # Metrics
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average="weighted", zero_division=0)
    recall = recall_score(y_test, y_pred, average="weighted", zero_division=0)
    f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)
    
    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    
    logger.info(f"[EVAL] {set_name} Accuracy: {accuracy:.4f}")
    logger.info(f"[EVAL] {set_name} Precision: {precision:.4f}")
    logger.info(f"[EVAL] {set_name} Recall: {recall:.4f}")
    logger.info(f"[EVAL] {set_name} F1: {f1:.4f}")
    logger.info(f"[EVAL] {set_name} Confusion Matrix:\n{cm}")
    
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": cm.tolist(),
    }


# ────────────────────────────────────────────────────────────────────────────
# STEP 8: WALK-FORWARD VALIDATION
# ────────────────────────────────────────────────────────────────────────────


def walk_forward_validate(
    features: pd.DataFrame,
    labels: pd.Series,
    scaler: StandardScaler,
) -> list[dict]:
    """
    Walk-forward validation for robustness testing.
    
    Trains multiple models on expanding windows and validates.
    """
    logger.info("[WFV] Running walk-forward validation")
    
    splits = walk_forward_split(features, labels, step_size=200)
    results = []
    
    for i, (X_train, y_train, X_val, y_val) in enumerate(splits):
        logger.info(f"[WFV] Split {i+1}/{len(splits)}")
        
        # Scale
        X_train_scaled = apply_scaler(X_train, scaler)
        X_val_scaled = apply_scaler(X_val, scaler)
        
        # Train
        model = xgb.XGBClassifier(**XGBOOST_PARAMS)
        model.fit(
            X_train_scaled,
            y_train,
            eval_set=[(X_val_scaled, y_val)],
            early_stopping_rounds=20,
            verbose=0,
        )
        
        # Evaluate
        y_pred = model.predict(X_val_scaled)
        accuracy = accuracy_score(y_val, y_pred)
        
        results.append({
            "split": i + 1,
            "train_size": len(X_train),
            "val_size": len(X_val),
            "accuracy": accuracy,
        })
        
        logger.info(f"[WFV] Split {i+1} Accuracy: {accuracy:.4f}")
    
    # Summary
    accuracies = [r["accuracy"] for r in results]
    mean_acc = np.mean(accuracies)
    std_acc = np.std(accuracies)
    
    logger.info(f"[WFV] Walk-Forward Validation Summary:")
    logger.info(f"[WFV] Mean Accuracy: {mean_acc:.4f} ± {std_acc:.4f}")
    logger.info(f"[WFV] Min: {np.min(accuracies):.4f}, Max: {np.max(accuracies):.4f}")
    
    return results


# ────────────────────────────────────────────────────────────────────────────
# STEP 9: SAVE ARTIFACTS
# ────────────────────────────────────────────────────────────────────────────


def save_model_artifacts(
    model: xgb.XGBClassifier,
    scaler: StandardScaler,
    metrics: dict,
):
    """Save model, scaler, and metadata."""
    logger.info("[SAVE] Saving model artifacts")
    
    # Model
    model_path = MODEL_DIR / f"{MODEL_NAME}.json"
    model.save_model(str(model_path))
    logger.info(f"[SAVE] Model saved to {model_path}")
    
    # Scaler
    scaler_path = MODEL_DIR / f"{MODEL_NAME}_scaler.pkl"
    joblib.dump(scaler, scaler_path)
    logger.info(f"[SAVE] Scaler saved to {scaler_path}")
    
    # Metadata
    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_count": len(FEATURE_COLUMNS),
        "feature_names": FEATURE_COLUMNS,
        "label_classes": [-1, 0, 1],  # SELL, HOLD, BUY
        "label_names": ["SELL", "HOLD", "BUY"],
        "xgboost_params": XGBOOST_PARAMS,
        "train_date": pd.Timestamp.now().isoformat(),
        "metrics": metrics,
    }
    
    metadata_path = MODEL_DIR / f"{MODEL_NAME}_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"[SAVE] Metadata saved to {metadata_path}")
    
    logger.info("[SAVE] All artifacts saved successfully")


# ────────────────────────────────────────────────────────────────────────────
# MAIN TRAINING FUNCTION
# ────────────────────────────────────────────────────────────────────────────


def train_production_model(
    csv_path: str,
    symbol: str = "RELIANCE",
    nifty_csv_path: str = None,
):
    """
    Complete end-to-end model training pipeline.
    
    Args:
        csv_path: Path to OHLCV CSV
        symbol: Stock symbol
        nifty_csv_path: Optional NIFTY data path
    """
    logger.info("=" * 80)
    logger.info("STOCKAI PRO — PRODUCTION MODEL TRAINING")
    logger.info("=" * 80)
    
    # Step 1: Load data
    ohlcv = load_historical_data(symbol, csv_path)
    nifty_data = load_historical_data("NIFTY", nifty_csv_path) if nifty_csv_path else None
    
    # Step 2: Engineer features
    features = engineer_features(ohlcv, nifty_data)
    
    # Step 3: Generate labels
    labels = prepare_labels(ohlcv, horizon=LABEL_HORIZON)
    
    # Step 4: Fit scaler (on ALL data for now, but ideally on train only)
    # Step 5: Split data
    split = split_data(features, labels)
    scaler = fit_scaler(split.train_features)
    
    # Scale each set
    X_train = apply_scaler(split.train_features, scaler)
    X_val = apply_scaler(split.val_features, scaler)
    X_test = apply_scaler(split.test_features, scaler)
    
    # Step 6: Train
    model = train_model(X_train, split.train_labels.values, X_val, split.val_labels.values)
    
    # Step 7: Evaluate
    logger.info("[MAIN] Evaluating model...")
    train_metrics = evaluate_model(model, X_train, split.train_labels.values, "Train")
    val_metrics = evaluate_model(model, X_val, split.val_labels.values, "Validation")
    test_metrics = evaluate_model(model, X_test, split.test_labels.values, "Test")
    
    # Step 8: Walk-forward validation
    wfv_results = walk_forward_validate(features, labels, scaler)
    
    # Combine metrics
    all_metrics = {
        "train": train_metrics,
        "validation": val_metrics,
        "test": test_metrics,
        "walk_forward_validation": wfv_results,
    }
    
    # Step 9: Save artifacts
    save_model_artifacts(model, scaler, all_metrics)
    
    logger.info("=" * 80)
    logger.info("TRAINING COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Test Accuracy: {test_metrics['accuracy']:.1%}")
    logger.info(f"Test F1-Score: {test_metrics['f1']:.4f}")
    logger.info(
        f"Walk-Forward Mean Accuracy: "
        f"{np.mean([r['accuracy'] for r in wfv_results]):.1%}"
    )
    
    return model, scaler


# ────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    # TODO: Update these paths to your data files
    CSV_PATH = "data/reliance_5m_2years.csv"  # Your OHLCV CSV file
    NIFTY_CSV_PATH = "data/nifty_5m_2years.csv"  # Optional NIFTY data
    
    # Check file exists
    if not Path(CSV_PATH).exists():
        logger.error(f"CSV file not found: {CSV_PATH}")
        logger.info("Please provide valid CSV file paths")
        raise FileNotFoundError(CSV_PATH)
    
    # Train
    model, scaler = train_production_model(
        csv_path=CSV_PATH,
        symbol="RELIANCE",
        nifty_csv_path=NIFTY_CSV_PATH,
    )
