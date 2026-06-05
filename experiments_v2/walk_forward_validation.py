from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from experiments_v2.data_utils import (
    PipelineConfig,
    ensure_feature_matrix,
    setup_logging,
    train_xgboost_model,
    predict_with_hold_threshold,
)

from app.inference.feature_contract import FEATURE_COLUMNS as CANONICAL_FEATURE_COLUMNS  # type: ignore


NON_FEATURE_COLUMNS = {
    "timestamp",
    "symbol",
    "timeframe",
    "source_file",
    "split",
    "wf_fold",
    "label_method",
    "target_signal",
    "target_class",
    "tb_event",
    "tb_profit_barrier",
    "tb_stop_barrier",
    "tb_time_steps",
    "tb_up_return_pct",
    "tb_down_return_pct",
    "tb_regime_scale",
    "future_return",
    "dynamic_threshold",
}


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _load_metadata(metadata_path: Path | None) -> dict[str, Any]:
    if metadata_path is None or not metadata_path.exists():
        return {}
    with metadata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_feature_columns(
    dataset_df: pd.DataFrame,
    metadata: dict[str, Any],
    explicit_features: list[str] | None,
) -> list[str]:
    del metadata
    if explicit_features:
        requested = [col for col in explicit_features if col in CANONICAL_FEATURE_COLUMNS]
        missing = [col for col in requested if col not in dataset_df.columns]
        if missing:
            raise RuntimeError(f"Explicit canonical features missing in dataset: {missing}")
        return list(requested)
    missing = [col for col in CANONICAL_FEATURE_COLUMNS if col not in dataset_df.columns]
    if missing:
        raise RuntimeError(
            "Dataset does not satisfy canonical feature schema. "
            f"Missing: {missing}"
        )
    return list(CANONICAL_FEATURE_COLUMNS)


def _prepare_dataset(dataset_path: Path) -> pd.DataFrame:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    if dataset_path.is_dir():
        parquet_files = sorted(dataset_path.rglob("*.parquet"))
        if not parquet_files:
            raise RuntimeError(f"No parquet files found under: {dataset_path}")
        df = pd.concat((pd.read_parquet(path) for path in parquet_files), ignore_index=True)
    elif dataset_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(dataset_path)
    else:
        df = pd.read_csv(dataset_path, low_memory=False)

    if "target_class" not in df.columns:
        raise RuntimeError("Dataset must include 'target_class' column.")

    if "timestamp" not in df.columns:
        raise RuntimeError("Dataset must include 'timestamp' column.")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", "target_class"]).copy()
    df["target_class"] = pd.to_numeric(df["target_class"], errors="coerce")
    df = df.dropna(subset=["target_class"]).copy()
    df["target_class"] = df["target_class"].astype(int)

    if "timeframe" in df.columns:
        df = df[df["timeframe"].astype(str).str.lower().eq("5m")].copy()

    return df.sort_values(["timestamp", "symbol" if "symbol" in df.columns else "timestamp"]).reset_index(drop=True)


def _build_expanding_folds(
    df: pd.DataFrame,
    n_folds: int,
    min_train_fraction: float,
    test_fraction: float,
    min_train_rows: int,
    min_test_rows: int,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    folds: list[tuple[str, np.ndarray, np.ndarray]] = []
    
    if "timestamp" not in df.columns:
        raise RuntimeError("WFV requires timestamp for chronological folding.")

    df = df.sort_values(["timestamp"]).reset_index(drop=True)
    df["year_month"] = df["timestamp"].dt.to_period("M")
    unique_months = sorted(df["year_month"].unique())
    
    if len(unique_months) < 4:
        raise RuntimeError("Not enough unique months for WFV expanding folds.")
        
    for i in range(2, len(unique_months) - 1):
        train_months = unique_months[:i]
        val_month = unique_months[i]
        
        train_mask = df["year_month"].isin(train_months).to_numpy()
        test_mask = (df["year_month"] == val_month).to_numpy()
        
        if train_mask.sum() >= min_train_rows and test_mask.sum() >= min_test_rows:
            # Automated validation: No future exposure
            train_dates = df.loc[train_mask, "timestamp"]
            test_dates = df.loc[test_mask, "timestamp"]
            assert train_dates.max() < test_dates.min(), "Leakage detected: train dates overlap with test dates!"
            
            folds.append((str(val_month), train_mask, test_mask))
            
    if not folds:
        raise RuntimeError("Unable to create valid time-based folds.")
        
    return folds


def _evaluate_fold(
    fold_name: str,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_columns: list[str],
    config: PipelineConfig,
    hold_threshold: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    X_train = ensure_feature_matrix(train_df, feature_columns)
    y_train = train_df["target_class"].astype(int)

    X_test = ensure_feature_matrix(test_df, feature_columns)
    y_test = test_df["target_class"].astype(int)

    unique_train_labels = set(y_train.unique().tolist())
    if unique_train_labels.issubset({-1, 1}) and unique_train_labels:
        if XGBClassifier is None:
            raise RuntimeError("xgboost is not installed. Install xgboost>=2.0.0.")

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        X_train_scaled = np.nan_to_num(X_train_scaled, nan=0.0, posinf=0.0, neginf=0.0)
        X_test_scaled = np.nan_to_num(X_test_scaled, nan=0.0, posinf=0.0, neginf=0.0)

        y_train_bin = (y_train.to_numpy(dtype=int) == 1).astype(int)
        class_counts = np.bincount(y_train_bin, minlength=2).astype(float)
        class_counts[class_counts == 0] = 1.0
        class_weights = class_counts.sum() / (2.0 * class_counts)
        sample_weights = np.array([class_weights[label] for label in y_train_bin], dtype=np.float32)

        model = XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            n_estimators=int(config.n_estimators),
            max_depth=int(config.max_depth),
            learning_rate=float(config.learning_rate),
            subsample=float(config.subsample),
            colsample_bytree=float(config.colsample_bytree),
            random_state=int(config.random_state),
            n_jobs=-1,
            tree_method="hist",
        )
        model.fit(X_train_scaled, y_train_bin, sample_weight=sample_weights)

        prob_buy = model.predict_proba(X_test_scaled)[:, 1].astype(np.float32)
        prob_sell = (1.0 - prob_buy).astype(np.float32)
        prob_hold = np.zeros_like(prob_buy, dtype=np.float32)
        probabilities = np.column_stack([prob_sell, prob_hold, prob_buy]).astype(np.float32)

        y_pred = np.where(prob_buy >= 0.5, 1, -1).astype(int)
        confidence = np.maximum(prob_buy, prob_sell).astype(np.float32)
        y_pred[confidence < float(hold_threshold)] = 0
    else:
        model, scaler = train_xgboost_model(X_train, y_train, config)
        y_pred, confidence, probabilities = predict_with_hold_threshold(
            model,
            scaler,
            X_test,
            hold_confidence_threshold=hold_threshold,
        )

    y_true = y_test.to_numpy(dtype=int)
    trade_mask = y_pred != 0

    sell_count = int(np.sum(y_pred == -1))
    hold_count = int(np.sum(y_pred == 0))
    buy_count = int(np.sum(y_pred == 1))
    total = max(len(y_pred), 1)

    if trade_mask.any():
        y_true_trade = y_true[trade_mask]
        y_pred_trade = y_pred[trade_mask]
        high_conf_acc = float(accuracy_score(y_true_trade, y_pred_trade))
        precision_trade = float(
            precision_score(y_true_trade, y_pred_trade, labels=[-1, 1], average="macro", zero_division=0)
        )
        recall_trade = float(
            recall_score(y_true_trade, y_pred_trade, labels=[-1, 1], average="macro", zero_division=0)
        )
        f1_trade = float(
            f1_score(y_true_trade, y_pred_trade, labels=[-1, 1], average="macro", zero_division=0)
        )
    else:
        high_conf_acc = 0.0
        precision_trade = 0.0
        recall_trade = 0.0
        f1_trade = 0.0

    fold_metrics = {
        "fold": fold_name,
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "train_start": str(train_df["timestamp"].min()),
        "train_end": str(train_df["timestamp"].max()),
        "test_start": str(test_df["timestamp"].min()),
        "test_end": str(test_df["timestamp"].max()),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_buy_sell": precision_trade,
        "recall_buy_sell": recall_trade,
        "f1_buy_sell": f1_trade,
        "high_confidence_accuracy": high_conf_acc,
        "trades_taken": int(trade_mask.sum()),
        "signal_distribution": {
            "buy_pct": _safe_div(buy_count * 100.0, total),
            "sell_pct": _safe_div(sell_count * 100.0, total),
            "hold_pct": _safe_div(hold_count * 100.0, total),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "hold_count": hold_count,
        },
        "confidence": {
            "mean": float(np.mean(confidence)),
            "median": float(np.median(confidence)),
            "p25": float(np.quantile(confidence, 0.25)),
            "p75": float(np.quantile(confidence, 0.75)),
        },
    }

    pred_frame = test_df[["timestamp", "symbol"]].copy() if "symbol" in test_df.columns else test_df[["timestamp"]].copy()
    pred_frame["fold"] = fold_name
    pred_frame["y_true"] = y_true
    pred_frame["y_pred"] = y_pred
    pred_frame["confidence"] = confidence
    pred_frame["prob_sell"] = probabilities[:, 0]
    pred_frame["prob_hold"] = probabilities[:, 1]
    pred_frame["prob_buy"] = probabilities[:, 2]
    pred_frame["is_trade"] = trade_mask.astype(int)

    return fold_metrics, pred_frame


def run_walk_forward(args: argparse.Namespace) -> dict[str, Any]:
    setup_logging()

    dataset_path = Path(args.dataset)
    metadata_path = Path(args.metadata) if args.metadata else None
    output_json = Path(args.output_json) if args.output_json else None
    predictions_csv = Path(args.predictions_csv) if args.predictions_csv else None

    dataset_df = _prepare_dataset(dataset_path)
    metadata = _load_metadata(metadata_path)

    explicit_features = None
    if args.feature_columns:
        explicit_features = [token.strip() for token in str(args.feature_columns).split(",") if token.strip()]

    feature_columns = _resolve_feature_columns(dataset_df, metadata, explicit_features)
    if not feature_columns:
        raise RuntimeError("No feature columns resolved for model training.")

    folds = _build_expanding_folds(
        dataset_df,
        n_folds=int(args.n_folds),
        min_train_fraction=float(args.min_train_fraction),
        test_fraction=float(args.test_fraction),
        min_train_rows=int(args.min_train_rows),
        min_test_rows=int(args.min_test_rows),
    )

    config = PipelineConfig(
        timeframe="5m",
        horizon=int(args.horizon),
        up_return_threshold=float(args.up_threshold),
        down_return_threshold=float(args.down_threshold),
        hold_confidence_threshold=float(args.hold_threshold),
        n_estimators=int(args.n_estimators),
        max_depth=int(args.max_depth),
        learning_rate=float(args.learning_rate),
        subsample=float(args.subsample),
        colsample_bytree=float(args.colsample_bytree),
        random_state=int(args.random_state),
    )

    fold_results: list[dict[str, Any]] = []
    pred_frames: list[pd.DataFrame] = []

    for fold_name, train_mask, test_mask in folds:
        train_df = dataset_df.loc[train_mask].copy()
        test_df = dataset_df.loc[test_mask].copy()

        metrics, pred_frame = _evaluate_fold(
            fold_name=fold_name,
            train_df=train_df,
            test_df=test_df,
            feature_columns=feature_columns,
            config=config,
            hold_threshold=float(args.hold_threshold),
        )
        fold_results.append(metrics)
        pred_frames.append(pred_frame)

    fold_df = pd.DataFrame(fold_results)
    total_trades = int(fold_df["trades_taken"].sum())

    weighted_high_conf_acc = 0.0
    if total_trades > 0:
        weighted_high_conf_acc = float(
            (fold_df["high_confidence_accuracy"] * fold_df["trades_taken"]).sum() / total_trades
        )

    summary = {
        "dataset": str(dataset_path),
        "metadata": str(metadata_path) if metadata_path else None,
        "fold_count": int(len(fold_results)),
        "feature_count": int(len(feature_columns)),
        "hold_threshold": float(args.hold_threshold),
        "xgboost_config": {
            "n_estimators": int(args.n_estimators),
            "max_depth": int(args.max_depth),
            "learning_rate": float(args.learning_rate),
            "subsample": float(args.subsample),
            "colsample_bytree": float(args.colsample_bytree),
            "random_state": int(args.random_state),
        },
        "average_metrics": {
            "accuracy": float(fold_df["accuracy"].mean()),
            "precision_buy_sell": float(fold_df["precision_buy_sell"].mean()),
            "recall_buy_sell": float(fold_df["recall_buy_sell"].mean()),
            "f1_buy_sell": float(fold_df["f1_buy_sell"].mean()),
            "high_confidence_accuracy_mean": float(fold_df["high_confidence_accuracy"].mean()),
            "high_confidence_accuracy_weighted": weighted_high_conf_acc,
            "buy_pct_mean": float(fold_df["signal_distribution"].apply(lambda x: x["buy_pct"]).mean()),
            "sell_pct_mean": float(fold_df["signal_distribution"].apply(lambda x: x["sell_pct"]).mean()),
            "hold_pct_mean": float(fold_df["signal_distribution"].apply(lambda x: x["hold_pct"]).mean()),
        },
        "total_trades_taken": total_trades,
        "per_fold_metrics": fold_results,
        "feature_columns": feature_columns,
    }

    if predictions_csv is not None:
        predictions_csv.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(pred_frames, ignore_index=True).to_csv(predictions_csv, index=False)
        summary["predictions_csv"] = str(predictions_csv)

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(_to_native(summary), indent=2), encoding="utf-8")

    return _to_native(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward validation for 5m base dataset with 1m aggregation + 1h context."
    )

    parser.add_argument(
        "--dataset",
        type=str,
        default="experiments_v2/data/processed_parquet/datasets_parquet/labeled_5m_signal_fixed2_strict",
        help="Path to labeled 5m dataset (CSV, parquet file, or parquet directory).",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default="experiments_v2/data/processed_parquet/dataset_metadata.json",
        help="Dataset metadata JSON used to resolve canonical feature columns.",
    )
    parser.add_argument(
        "--feature-columns",
        type=str,
        default="",
        help="Optional comma-separated explicit feature columns.",
    )

    parser.add_argument("--hold-threshold", type=float, default=0.65)
    parser.add_argument("--n-folds", type=int, default=5)
    parser.add_argument("--min-train-fraction", type=float, default=0.50)
    parser.add_argument("--test-fraction", type=float, default=0.10)
    parser.add_argument("--min-train-rows", type=int, default=5000)
    parser.add_argument("--min-test-rows", type=int, default=1000)

    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--up-threshold", type=float, default=0.02)
    parser.add_argument("--down-threshold", type=float, default=0.02)

    parser.add_argument("--n-estimators", type=int, default=420)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--subsample", type=float, default=0.90)
    parser.add_argument("--colsample-bytree", type=float, default=0.90)
    parser.add_argument("--random-state", type=int, default=42)

    parser.add_argument(
        "--output-json",
        type=str,
        default="experiments_v2/outputs/reports/walk_forward_5m_mtf_report.json",
        help="Where to save summary metrics.",
    )
    parser.add_argument(
        "--predictions-csv",
        type=str,
        default="experiments_v2/outputs/reports/walk_forward_5m_mtf_predictions.csv",
        help="Where to save per-row fold predictions/probabilities.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_walk_forward(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
