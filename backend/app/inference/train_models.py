"""
Auto-training pipeline — trains XGBoost and RandomForest models
using the CANONICAL feature set from feature_engineering.py.

Usage:
    python -m app.inference.train_models          (trains for top stocks)
    python -m app.inference.train_models --symbol RELIANCE
    python -m app.inference.train_models --mtf     (use multi-timeframe dataset)

The trained models are saved to root/models/ and automatically loaded
by the inference engine on next startup.
"""

from __future__ import annotations
from app.inference.feature_engineering import (FEATURE_COLUMNS,
                                               FEATURE_VERSION,
                                               compute_features,
                                               validate_features)

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root))


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s"
)

MODEL_DIR = Path(__file__).resolve().parents[3] / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Top symbols to train on (diversified across sectors)
DEFAULT_SYMBOLS = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "SBIN",
    "ICICIBANK",
    "TATASTEEL",
    "ITC",
    "AXISBANK",
    "KOTAKBANK",
    "WIPRO",
    "BHARTIARTL",
    "HINDUNILVR",
    "LT",
    "MARUTI",
    "SUNPHARMA",
    "TATAMOTORS",
    "TITAN",
    "BAJFINANCE",
    "HCLTECH",
    "NTPC",
    "POWERGRID",
    "ADANIENT",
    "ULTRACEMCO",
    "BAJAJFINSV",
    "NESTLEIND",
    "DRREDDY",
    "TECHM",
    "CIPLA",
    "DIVISLAB",
]


def _fetch_training_data(symbols: list[str]) -> pd.DataFrame:
    """Fetch historical data for multiple symbols using yfinance.

    Returns a combined DataFrame with computed canonical features.
    """
    import yfinance as yf

    all_data = []
    for sym in symbols:
        try:
            yf_ticker = f"{sym}.NS"
            logger.info("[TRAIN] Fetching %s ...", yf_ticker)
            ticker = yf.Ticker(yf_ticker)
            df = ticker.history(period="60d", interval="15m")

            if df.empty or len(df) < 100:
                logger.warning(
                    "[TRAIN] Insufficient data for %s (%d rows)", sym, len(df)
                )
                continue

            # Build clean OHLCV DataFrame
            ohlcv_df = pd.DataFrame(
                {
                    "open": df["Open"].astype(float),
                    "high": df["High"].astype(float),
                    "low": df["Low"].astype(float),
                    "close": df["Close"].astype(float),
                    "volume": df["Volume"].astype(int),
                }
            )

            # Compute features using the SHARED canonical function
            feature_df = compute_features(ohlcv_df)

            if feature_df.empty:
                logger.warning("[TRAIN] Feature computation returned empty for %s", sym)
                continue

            feature_df["symbol"] = sym
            # Preserve original close for label computation
            feature_df["_raw_close"] = ohlcv_df["close"].values[: len(feature_df)]
            all_data.append(feature_df)
            logger.info(
                "[TRAIN] %s: %d rows with %d features",
                sym,
                len(feature_df),
                len(FEATURE_COLUMNS),
            )

        except Exception as e:
            logger.warning("[TRAIN] Failed to fetch %s: %s", sym, e)
            continue

    if not all_data:
        raise ValueError("No training data could be fetched")

    combined = pd.concat(all_data, ignore_index=True)
    logger.info(
        "[TRAIN] Combined dataset: %d rows from %d symbols",
        len(combined),
        len(all_data),
    )
    return combined


def _prepare_features(
    df: pd.DataFrame, horizon: int = 15
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Prepare feature matrix X and label vector y from the canonical features.

    Uses EXACTLY the same FEATURE_COLUMNS as inference — no drift possible.
    Label: 1 if close[t+horizon] > close[t], else 0.
    """
    # Use canonical feature columns only
    X = df[FEATURE_COLUMNS].copy()

    # Label: price direction after horizon candles
    # Use _raw_close if available (matches original close), else fall back to "close"
    close_col = df["_raw_close"] if "_raw_close" in df.columns else df["close"]
    y = (close_col.shift(-horizon) > close_col).astype(int)

    # Drop NaN rows
    valid = X.notna().all(axis=1) & y.notna()
    X = X[valid]
    y = y[valid]

    # Replace infinities
    X = X.replace([np.inf, -np.inf], 0).fillna(0)

    # Validate that our columns match the canonical set
    validate_features(
        list(X.columns), FEATURE_COLUMNS, context="training _prepare_features"
    )

    logger.info(
        "[TRAIN] Feature matrix: %s, Label distribution: %s",
        X.shape,
        y.value_counts().to_dict(),
    )
    return X, y


def train(symbols: list[str] | None = None):
    """Train XGBoost and RandomForest models and save to disk.

    Saves:
        - model.pkl      — best performing model (RF by default)
        - scaler.pkl      — StandardScaler fitted on training data
        - features.pkl    — canonical feature column list from FEATURE_COLUMNS
        - xgb_model.pkl   — XGBoost model
        - rf_model.pkl    — RandomForest model
    """
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report
    from sklearn.preprocessing import StandardScaler

    symbols = symbols or DEFAULT_SYMBOLS
    logger.info("[TRAIN] Starting training for %d symbols", len(symbols))
    logger.info(
        "[TRAIN] Feature version: %s (%d columns)",
        FEATURE_VERSION,
        len(FEATURE_COLUMNS),
    )

    # 1. Fetch data and compute canonical features
    df = _fetch_training_data(symbols)

    # 2. Prepare features (uses FEATURE_COLUMNS — guaranteed aligned)
    X, y = _prepare_features(df)

    if len(X) < 200:
        logger.error("[TRAIN] Insufficient data for training (%d samples)", len(X))
        return

    # 3. Train/test split (chronological — no shuffle)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    logger.info("[TRAIN] Train: %d, Test: %d", len(X_train), len(X_test))

    # 4. Fit scaler on training data
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Replace any NaN/Inf from scaling
    X_train_scaled = np.nan_to_num(X_train_scaled, nan=0.0, posinf=0.0, neginf=0.0)
    X_test_scaled = np.nan_to_num(X_test_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    best_model = None
    best_acc = 0.0

    # 5. Train XGBoost
    try:
        from xgboost import XGBClassifier

        xgb = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
        )
        xgb.fit(X_train_scaled, y_train)
        xgb_pred = xgb.predict(X_test_scaled)
        xgb_acc = accuracy_score(y_test, xgb_pred)
        logger.info("[TRAIN] XGBoost accuracy: %.4f", xgb_acc)
        logger.info(
            "[TRAIN] XGBoost report:\n%s", classification_report(y_test, xgb_pred)
        )

        xgb_path = MODEL_DIR / "xgb_model.pkl"
        joblib.dump(xgb, xgb_path)
        logger.info("[TRAIN] Saved XGBoost to %s", xgb_path)

        if xgb_acc > best_acc:
            best_model = xgb
            best_acc = xgb_acc
    except Exception as e:
        logger.error("[TRAIN] XGBoost training failed: %s", e)

    # 6. Train RandomForest
    try:
        rf = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(X_train_scaled, y_train)
        rf_pred = rf.predict(X_test_scaled)
        rf_acc = accuracy_score(y_test, rf_pred)
        logger.info("[TRAIN] RandomForest accuracy: %.4f", rf_acc)
        logger.info(
            "[TRAIN] RandomForest report:\n%s", classification_report(y_test, rf_pred)
        )

        rf_path = MODEL_DIR / "rf_model.pkl"
        joblib.dump(rf, rf_path)
        logger.info("[TRAIN] Saved RandomForest to %s", rf_path)

        if rf_acc > best_acc:
            best_model = rf
            best_acc = rf_acc
    except Exception as e:
        logger.error("[TRAIN] RandomForest training failed: %s", e)

    # 7. Save the best model as the primary model.pkl dictionary
    if best_model is not None:
        payload = {
            "model": best_model,
            "scaler": scaler,
            "features": FEATURE_COLUMNS,
            "version": FEATURE_VERSION,
        }
        joblib.dump(payload, MODEL_DIR / "model.pkl")
        joblib.dump(FEATURE_COLUMNS, MODEL_DIR / "features.pkl")
        with open(MODEL_DIR / "feature_cols.json", "w", encoding="utf-8") as f:
            json.dump(
                {"version": FEATURE_VERSION, "features": FEATURE_COLUMNS}, f, indent=2
            )
        logger.info(
            "[TRAIN] ✓ Saved primary model payload (best_acc=%.4f) with version %s",
            best_acc,
            FEATURE_VERSION,
        )

        # Final validation: ensure what we saved matches what inference expects
        saved_payload = joblib.load(MODEL_DIR / "model.pkl")
        validate_features(
            saved_payload["features"], FEATURE_COLUMNS, context="post-save validation"
        )
        logger.info("[TRAIN] ✓ Post-save validation passed — features aligned")
    else:
        logger.error("[TRAIN] ✗ No model was successfully trained")

    logger.info("[TRAIN] ✓ Training complete")


def train_mtf(symbols: list[str] | None = None):
    """Train XGBoost and RandomForest using the multi-timeframe dataset.

    Uses :mod:`app.services.multi_timeframe_dataset` to build a high-quality
    labelled dataset (5m base + 1m aggregated + 1h context) with ATR-based
    dynamic barrier labels (BUY / SELL / HOLD).

    Saves:
        - mtf_model.pkl       — best performing model
        - mtf_scaler.pkl      — StandardScaler fitted on training data
        - mtf_features.pkl    — MTF_FEATURE_COLUMNS list
        - mtf_feature_cols.json — human-readable feature manifest
    """
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report
    from sklearn.preprocessing import StandardScaler

    from app.services.multi_timeframe_dataset import (
        MTF_FEATURE_COLUMNS,
        MultiTimeframeDatasetBuilder,
        build_mtf_dataset_from_yfinance,
    )

    symbols = symbols or DEFAULT_SYMBOLS
    logger.info("[TRAIN-MTF] Starting multi-timeframe training for %d symbols", len(symbols))
    logger.info("[TRAIN-MTF] Feature columns: %d", len(MTF_FEATURE_COLUMNS))

    builder = MultiTimeframeDatasetBuilder(
        label_horizon=3,       # 3 × 5m = 15 min ahead
        atr_barrier_mult=0.5,  # 50% of ATR as barrier
        min_atr_pct=0.001,     # filter ultra-low volatility bars
    )

    all_data: list[pd.DataFrame] = []
    for sym in symbols:
        yf_ticker = f"{sym}.NS"
        try:
            dataset = build_mtf_dataset_from_yfinance(yf_ticker, period="60d", builder=builder)
            if dataset.empty or len(dataset) < 50:
                logger.warning("[TRAIN-MTF] Insufficient data for %s", sym)
                continue
            dataset["symbol"] = sym
            all_data.append(dataset)
            logger.info(
                "[TRAIN-MTF] %s: %d rows, label dist: %s",
                sym,
                len(dataset),
                dataset["label"].value_counts().to_dict(),
            )
        except Exception as exc:
            logger.warning("[TRAIN-MTF] Failed to build dataset for %s: %s", sym, exc)

    if not all_data:
        logger.error("[TRAIN-MTF] No training data could be fetched")
        return

    combined = pd.concat(all_data, ignore_index=True)
    logger.info(
        "[TRAIN-MTF] Combined: %d rows, %d symbols, label dist: %s",
        len(combined),
        len(all_data),
        combined["label"].value_counts().to_dict(),
    )

    X = combined[MTF_FEATURE_COLUMNS].replace([np.inf, -np.inf], 0).fillna(0)
    y = combined["label"].astype(int)

    if len(X) < 200:
        logger.error("[TRAIN-MTF] Insufficient samples (%d)", len(X))
        return

    # Chronological split (no shuffle — respects time-series order)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    logger.info("[TRAIN-MTF] Train: %d, Test: %d", len(X_train), len(X_test))

    scaler = StandardScaler()
    X_train_sc = np.nan_to_num(scaler.fit_transform(X_train), nan=0.0, posinf=0.0, neginf=0.0)
    X_test_sc = np.nan_to_num(scaler.transform(X_test), nan=0.0, posinf=0.0, neginf=0.0)

    best_model = None
    best_acc = 0.0

    # XGBoost
    try:
        from sklearn.metrics import accuracy_score
        from xgboost import XGBClassifier

        # Map labels {-1, 0, 1} to {0, 1, 2} for XGBoost (requires non-negative)
        label_map = {-1: 0, 0: 1, 1: 2}
        inv_map = {0: -1, 1: 0, 2: 1}
        y_train_xgb = y_train.map(label_map)
        y_test_xgb = y_test.map(label_map)

        xgb = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="mlogloss",
            random_state=42,
        )
        xgb.fit(X_train_sc, y_train_xgb)
        xgb_pred_mapped = xgb.predict(X_test_sc)
        xgb_pred = pd.Series(xgb_pred_mapped).map(inv_map).values
        xgb_acc = accuracy_score(y_test, xgb_pred)
        logger.info("[TRAIN-MTF] XGBoost accuracy: %.4f", xgb_acc)
        logger.info(
            "[TRAIN-MTF] XGBoost report:\n%s",
            classification_report(y_test, xgb_pred, labels=[-1, 0, 1], target_names=["SELL", "HOLD", "BUY"]),
        )

        xgb_path = MODEL_DIR / "mtf_xgb_model.pkl"
        joblib.dump(xgb, xgb_path)
        logger.info("[TRAIN-MTF] Saved XGBoost to %s", xgb_path)

        if xgb_acc > best_acc:
            best_model = xgb
            best_acc = xgb_acc
    except Exception as exc:
        logger.error("[TRAIN-MTF] XGBoost training failed: %s", exc)

    # RandomForest
    try:
        from sklearn.metrics import accuracy_score

        rf = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(X_train_sc, y_train)
        rf_pred = rf.predict(X_test_sc)
        rf_acc = accuracy_score(y_test, rf_pred)
        logger.info("[TRAIN-MTF] RandomForest accuracy: %.4f", rf_acc)
        logger.info(
            "[TRAIN-MTF] RandomForest report:\n%s",
            classification_report(y_test, rf_pred, labels=[-1, 0, 1], target_names=["SELL", "HOLD", "BUY"]),
        )

        rf_path = MODEL_DIR / "mtf_rf_model.pkl"
        joblib.dump(rf, rf_path)
        logger.info("[TRAIN-MTF] Saved RandomForest to %s", rf_path)

        if rf_acc > best_acc:
            best_model = rf
            best_acc = rf_acc
    except Exception as exc:
        logger.error("[TRAIN-MTF] RandomForest training failed: %s", exc)

    if best_model is not None:
        payload = {
            "model": best_model,
            "scaler": scaler,
            "features": MTF_FEATURE_COLUMNS,
            "label_map": {1: "BUY", -1: "SELL", 0: "HOLD"},
        }
        joblib.dump(payload, MODEL_DIR / "mtf_model.pkl")
        joblib.dump(MTF_FEATURE_COLUMNS, MODEL_DIR / "mtf_features.pkl")
        with open(MODEL_DIR / "mtf_feature_cols.json", "w", encoding="utf-8") as f:
            json.dump({"features": MTF_FEATURE_COLUMNS, "label_map": {"1": "BUY", "-1": "SELL", "0": "HOLD"}}, f, indent=2)
        logger.info(
            "[TRAIN-MTF] ✓ Saved best MTF model (acc=%.4f) to %s",
            best_acc,
            MODEL_DIR / "mtf_model.pkl",
        )
    else:
        logger.error("[TRAIN-MTF] ✗ No MTF model was successfully trained")

    logger.info("[TRAIN-MTF] ✓ Multi-timeframe training complete")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train StockAI Pro ML models")
    parser.add_argument("--symbol", type=str, help="Train on a single symbol")
    parser.add_argument(
        "--mtf",
        action="store_true",
        help="Use multi-timeframe dataset builder (5m + 1m + 1h, ATR labeling)",
    )
    args = parser.parse_args()

    if args.mtf:
        syms = [args.symbol.upper()] if args.symbol else None
        train_mtf(syms)
    elif args.symbol:
        train([args.symbol.upper()])
    else:
        train()
