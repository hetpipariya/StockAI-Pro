from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from xgboost import XGBClassifier

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.inference.feature_contract import FEATURE_COLUMNS as CANONICAL_FEATURE_COLUMNS  # type: ignore


DROP_BASE_COLUMNS = {
    "timestamp",
    "symbol",
    "sector",
    "timeframe",
    "source_file",
    "split",
    "wf_fold",
    "label_method",
    "label",
}


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _resolve_label_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "label" in out.columns:
        return out

    if "target_class" in out.columns:
        out["label"] = pd.to_numeric(out["target_class"], errors="coerce")
        return out

    if "target_signal" in out.columns:
        out["label"] = out["target_signal"].astype(str)
        return out

    raise RuntimeError(
        "No target column found. Expected one of: label, target_class, target_signal"
    )


def _build_feature_columns(df: pd.DataFrame) -> list[str]:
    missing = [col for col in CANONICAL_FEATURE_COLUMNS if col not in df.columns]
    if missing:
        raise RuntimeError(
            "Dataset is not compatible with strict 20-feature schema. "
            f"Missing columns: {missing}"
        )
    return list(CANONICAL_FEATURE_COLUMNS)


def _encode_categoricals(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, int]]]:
    X_train = train_df.copy()
    X_test = test_df.copy()
    encoders: dict[str, dict[str, int]] = {}

    for col in X_train.columns:
        if pd.api.types.is_numeric_dtype(X_train[col]):
            continue

        train_vals = X_train[col].astype(str).fillna("__NA__")
        test_vals = X_test[col].astype(str).fillna("__NA__")

        categories = pd.Index(sorted(train_vals.unique().tolist()))
        mapping = {key: idx for idx, key in enumerate(categories)}
        encoders[col] = mapping

        X_train[col] = train_vals.map(mapping).fillna(-1).astype(np.int32)
        X_test[col] = test_vals.map(mapping).fillna(-1).astype(np.int32)

    return X_train, X_test, encoders


def _impute_numeric_train_test(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    X_train = train_df.copy()
    X_test = test_df.copy()
    numeric_fill_values: dict[str, float] = {}

    for col in X_train.columns:
        if not pd.api.types.is_numeric_dtype(X_train[col]):
            continue

        fill_value = float(pd.to_numeric(X_train[col], errors="coerce").median())
        if not np.isfinite(fill_value):
            fill_value = 0.0

        numeric_fill_values[col] = fill_value
        X_train[col] = pd.to_numeric(X_train[col], errors="coerce").fillna(fill_value)
        X_test[col] = pd.to_numeric(X_test[col], errors="coerce").fillna(fill_value)

    return X_train, X_test, numeric_fill_values


def _encode_labels(y: pd.Series) -> tuple[np.ndarray, dict[Any, int], dict[int, Any]]:
    unique_labels = sorted(y.dropna().unique().tolist(), key=lambda x: str(x))
    label_to_idx = {label: idx for idx, label in enumerate(unique_labels)}
    idx_to_label = {idx: label for label, idx in label_to_idx.items()}
    encoded = y.map(label_to_idx)

    if encoded.isna().any():
        raise RuntimeError("Failed to encode all target labels.")
    return encoded.to_numpy(dtype=np.int32), label_to_idx, idx_to_label


def _infer_buy_sell_labels(labels: list[Any]) -> list[Any]:
    text_map = {str(x).upper(): x for x in labels}
    if "BUY" in text_map and "SELL" in text_map:
        return [text_map["SELL"], text_map["BUY"]]

    numeric = []
    for value in labels:
        try:
            numeric.append(float(value))
        except Exception:
            pass

    if any(v == -1 for v in numeric) and any(v == 1 for v in numeric):
        return [-1, 1]

    if len(labels) >= 2:
        return labels[:2]
    return labels


def run_training(
    dataset_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    df = pd.read_parquet(dataset_path)

    if "timeframe" not in df.columns:
        raise RuntimeError("Missing required column: timeframe")
    if "timestamp" not in df.columns:
        raise RuntimeError("Missing required column: timestamp")

    df = _resolve_label_column(df)

    # 1) Filter 1h and sort chronologically to preserve trading realism.
    df = df[df["timeframe"].astype(str).str.lower() == "1h"].copy()
    if df.empty:
        raise RuntimeError("No rows found for timeframe=1h")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", "label"]).copy()
    df = df.sort_values("timestamp").reset_index(drop=True)

    feature_columns = _build_feature_columns(df)
    if not feature_columns:
        raise RuntimeError("No usable feature columns found after filtering.")

    # Remove fully missing columns, then impute remaining gaps from train-only statistics later.
    non_all_nan_features = [col for col in feature_columns if not df[col].isna().all()]
    if not non_all_nan_features:
        raise RuntimeError("All feature columns are fully missing for timeframe=1h.")
    feature_columns = non_all_nan_features

    X = df[feature_columns].copy()
    y = df["label"].copy()

    split_idx = int(len(df) * 0.8)
    split_idx = max(1, min(len(df) - 1, split_idx))

    X_train_raw = X.iloc[:split_idx].copy()
    X_test_raw = X.iloc[split_idx:].copy()
    y_train_raw = y.iloc[:split_idx].copy()
    y_test_raw = y.iloc[split_idx:].copy()

    X_train_imputed, X_test_imputed, numeric_fill_values = _impute_numeric_train_test(
        X_train_raw,
        X_test_raw,
    )
    X_train, X_test, feature_encoders = _encode_categoricals(
        X_train_imputed,
        X_test_imputed,
    )

    y_train, label_to_idx, idx_to_label = _encode_labels(y_train_raw)
    y_test = y_test_raw.map(label_to_idx)
    if y_test.isna().any():
        missing = sorted(y_test_raw[y_test.isna()].astype(str).unique().tolist())
        raise RuntimeError(
            "Test set contains unseen labels absent from train set. "
            f"Unseen labels: {missing}"
        )
    y_test = y_test.to_numpy(dtype=np.int32)

    num_classes = len(label_to_idx)

    if num_classes <= 1:
        raise RuntimeError("Need at least 2 target classes to train classifier.")

    if num_classes == 2:
        model = XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            tree_method="hist",
            subsample=0.8,
            colsample_bytree=0.8,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
    else:
        model = XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            tree_method="hist",
            subsample=0.8,
            colsample_bytree=0.8,
            objective="multi:softprob",
            num_class=num_classes,
            eval_metric="mlogloss",
            random_state=42,
            n_jobs=-1,
        )

    model.fit(X_train, y_train)
    y_pred = model.predict(X_test).astype(np.int32)

    y_test_labels = np.array([str(idx_to_label[int(i)]) for i in y_test], dtype=str)
    y_pred_labels = np.array([str(idx_to_label[int(i)]) for i in y_pred], dtype=str)

    buy_sell_labels = _infer_buy_sell_labels(sorted(label_to_idx.keys(), key=lambda x: str(x)))
    buy_sell_labels = [str(value) for value in buy_sell_labels]

    metrics = {
        "accuracy": float(accuracy_score(y_test_labels, y_pred_labels)),
        "precision_buy_sell": float(
            precision_score(
                y_test_labels,
                y_pred_labels,
                labels=buy_sell_labels,
                average="macro",
                zero_division=0,
            )
        ),
        "recall_buy_sell": float(
            recall_score(
                y_test_labels,
                y_pred_labels,
                labels=buy_sell_labels,
                average="macro",
                zero_division=0,
            )
        ),
        "f1_buy_sell": float(
            f1_score(
                y_test_labels,
                y_pred_labels,
                labels=buy_sell_labels,
                average="macro",
                zero_division=0,
            )
        ),
    }

    feature_importance = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": model.feature_importances_.astype(float),
        }
    ).sort_values("importance", ascending=False)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "xgb_1h_baseline_model.joblib"
    metrics_path = output_dir / "xgb_1h_baseline_metrics.json"
    feature_importance_path = output_dir / "xgb_1h_baseline_feature_importance.csv"

    payload = {
        "model": model,
        "feature_columns": feature_columns,
        "feature_encoders": feature_encoders,
        "numeric_fill_values": numeric_fill_values,
        "label_to_idx": label_to_idx,
        "idx_to_label": idx_to_label,
        "buy_sell_labels": buy_sell_labels,
    }
    joblib.dump(payload, model_path)
    feature_importance.to_csv(feature_importance_path, index=False)

    report = {
        "dataset": str(dataset_path),
        "timeframe": "1h",
        "rows_total_1h": int(len(df)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "train_start": str(df.iloc[0]["timestamp"]),
        "train_end": str(df.iloc[split_idx - 1]["timestamp"]),
        "test_start": str(df.iloc[split_idx]["timestamp"]),
        "test_end": str(df.iloc[-1]["timestamp"]),
        "feature_count": int(len(feature_columns)),
        "metrics": metrics,
        "top_features": _to_native(feature_importance.head(20).to_dict(orient="records")),
        "artifacts": {
            "model": str(model_path),
            "metrics": str(metrics_path),
            "feature_importance": str(feature_importance_path),
        },
    }

    metrics_path.write_text(json.dumps(_to_native(report), indent=2), encoding="utf-8")
    return _to_native(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train 1h-only XGBoost baseline from combined_dataset.parquet."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("experiments_v2/data/combined_dataset.parquet"),
        help="Path to combined parquet dataset.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments_v2/outputs/models/1h_baseline"),
        help="Directory for model and reports.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_training(dataset_path=args.dataset, output_dir=args.output_dir)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
