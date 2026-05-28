from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
RAW_DIR = ROOT / "app" / "cache" / "raw_data"
MODEL_DIR = ROOT / "models"

import sys

sys.path.insert(0, str(ROOT))

from app.inference.feature_engineering import FEATURE_COLUMNS, FEATURE_VERSION, compute_features


def _load_ohlcv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    required = ["open", "high", "low", "close", "volume"]
    if any(column not in frame.columns for column in required):
        return pd.DataFrame()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=required)
    frame = frame[frame["close"] > 0]
    return frame.reset_index(drop=True)


def _label_from_future(frame: pd.DataFrame, index: int, horizon: int = 5) -> int:
    current = float(frame["close"].iloc[index])
    future_idx = min(len(frame) - 1, index + horizon)
    future = float(frame["close"].iloc[future_idx])
    ret = (future - current) / max(abs(current), 1e-9)
    if ret >= 0.006:
        return 2
    if ret <= -0.006:
        return 0
    return 1


def build_dataset(max_symbols: int = 80, step: int = 5) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[int] = []
    feature_ms: list[float] = []

    csv_files = sorted(RAW_DIR.glob("*.csv"))[:max_symbols]
    for path in csv_files:
        frame = _load_ohlcv(path)
        if len(frame) < 75:
            continue

        last_start = len(frame) - 6
        for end_idx in range(50, last_start, step):
            window = frame.iloc[:end_idx][["open", "high", "low", "close", "volume"]]
            started = time.perf_counter()
            try:
                features = compute_features(window)
            except Exception:
                continue
            feature_ms.append((time.perf_counter() - started) * 1000.0)
            latest = features.iloc[-1]
            rows.append([float(latest[name]) for name in FEATURE_COLUMNS])
            labels.append(_label_from_future(frame, end_idx - 1))

    if not rows:
        raise RuntimeError("No training samples generated from cached raw data")

    return pd.DataFrame(rows, columns=FEATURE_COLUMNS), np.asarray(labels, dtype=np.int64), np.asarray(feature_ms)


def main() -> None:
    started = time.perf_counter()
    x, y, feature_ms = build_dataset()
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    stratify = y if len(set(y.tolist())) > 1 else None
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.2,
        random_state=42,
        stratify=stratify,
    )

    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)
    x_test_scaled = scaler.transform(x_test)

    model = XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        n_estimators=180,
        max_depth=4,
        learning_rate=0.045,
        subsample=0.88,
        colsample_bytree=0.88,
        eval_metric="mlogloss",
        tree_method="hist",
        random_state=42,
        n_jobs=4,
    )
    model.fit(x_train_scaled, y_train)

    pred = model.predict(x_test_scaled)
    accuracy = float(accuracy_score(y_test, pred))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "scaler": scaler,
        "features": list(FEATURE_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "version": FEATURE_VERSION,
        "label_map": {"0": "SELL", "1": "HOLD", "2": "BUY"},
        "target_classes": [0, 1, 2],
        "trained_at": pd.Timestamp.utcnow().isoformat(),
    }
    joblib.dump(payload, MODEL_DIR / "model.pkl")
    joblib.dump(scaler, MODEL_DIR / "scaler.pkl")
    joblib.dump(list(FEATURE_COLUMNS), MODEL_DIR / "features.pkl")
    (MODEL_DIR / "feature_list.json").write_text(json.dumps(list(FEATURE_COLUMNS), indent=2), encoding="utf-8")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metadata = {
        "pipeline": "cpp_contract_v3",
        "model_type": "xgboost_multiclass",
        "feature_version": FEATURE_VERSION,
        "feature_count": len(FEATURE_COLUMNS),
        "features": list(FEATURE_COLUMNS),
        "samples": int(len(x)),
        "class_counts": {str(label): int(count) for label, count in zip(*np.unique(y, return_counts=True))},
        "accuracy_test": accuracy,
        "classification_report": classification_report(y_test, pred, output_dict=True, zero_division=0),
        "benchmarks": {
            "feature_generation_ms_p50": float(np.percentile(feature_ms, 50)),
            "feature_generation_ms_p95": float(np.percentile(feature_ms, 95)),
            "training_elapsed_ms": float(elapsed_ms),
        },
    }
    (MODEL_DIR / "training_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata["benchmarks"] | {"accuracy_test": accuracy, "samples": int(len(x))}, indent=2))


if __name__ == "__main__":
    main()
