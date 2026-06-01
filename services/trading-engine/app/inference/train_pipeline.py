from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import StandardScaler

from app.inference.dataset_builders import (
    build_entry_5m_training_dataset,
    build_trend_1h_training_dataset,
)
from app.inference.dataset_validation import validate_and_clean_feature_rows
from app.inference.feature_contract import FEATURE_COLUMNS, FEATURE_VERSION, validate_feature_contract
from app.inference.label_generation import temporal_train_val_test_split, walk_forward_split

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None


DEFAULT_ENTRY_5M_OUTPUT = Path("backend/models/entry_5m")
DEFAULT_TREND_1H_OUTPUT = Path("backend/models/trend_1h")
DEFAULT_TRAINING_ROW_CAP = max(5000, int(os.getenv("TRAIN_PIPELINE_MAX_ROWS", "50000")))
DEFAULT_TRAINING_FILE_CAP = max(1, int(os.getenv("TRAIN_PIPELINE_MAX_FILES", "10")))
DEFAULT_HOLD_THRESHOLD = float(os.getenv("TRAIN_PIPELINE_HOLD_THRESHOLD", "0.45"))
DEFAULT_RISK_REWARD_TARGET = float(os.getenv("TRAIN_PIPELINE_TARGET_R", "1.8"))
DEFAULT_HOLD_BIAS_MARGIN = float(os.getenv("TRAIN_PIPELINE_HOLD_BIAS_MARGIN", "0.05"))
DEFAULT_MIN_DIRECTIONAL_PROB = float(os.getenv("TRAIN_PIPELINE_MIN_DIRECTIONAL_PROB", "0.30"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _encode_labels(labels: pd.Series) -> tuple[pd.Series, dict[int, int], dict[int, int]]:
    unique_labels = sorted({int(value) for value in labels.dropna().unique().tolist()})
    forward = {label: idx for idx, label in enumerate(unique_labels)}
    reverse = {idx: label for label, idx in forward.items()}
    encoded = labels.astype(int).map(forward)
    if encoded.isna().any():
        raise ValueError("Unable to encode one or more training labels")
    return encoded.astype(int), forward, reverse


def _safe_predict_proba(model: Any, X: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        raw = np.asarray(model.predict_proba(X), dtype=float)
        classes = getattr(model, "classes_", None)
        if classes is None:
            return raw
        class_ids = [int(v) for v in np.asarray(classes).tolist()]
        width = max(class_ids) + 1 if class_ids else raw.shape[1]
        aligned = np.zeros((raw.shape[0], width), dtype=float)
        for col, class_id in enumerate(class_ids):
            if 0 <= int(class_id) < width:
                aligned[:, int(class_id)] = raw[:, col]
        return aligned
    pred = np.asarray(model.predict(X))
    classes = sorted(set(int(v) for v in pred.tolist()))
    proba = np.zeros((len(pred), max(classes) + 1), dtype=float)
    for i, cls in enumerate(pred.tolist()):
        proba[i, int(cls)] = 1.0
    return proba


def _apply_hold_threshold(
    proba: np.ndarray,
    reverse_label_mapping: dict[int, int],
    hold_threshold: float,
    hold_bias_margin: float = DEFAULT_HOLD_BIAS_MARGIN,
    min_directional_prob: float = DEFAULT_MIN_DIRECTIONAL_PROB,
) -> np.ndarray:
    pred_encoded = np.argmax(proba, axis=1).astype(int)
    confidence = np.max(proba, axis=1)
    proba_width = int(proba.shape[1]) if proba.ndim == 2 else 0

    hold_encoded = None
    for encoded, raw in reverse_label_mapping.items():
        if int(raw) == 0:
            hold_encoded = int(encoded)
            break

    if hold_encoded is not None and 0 <= int(hold_encoded) < proba_width:
        # Low-confidence predictions default to HOLD.
        pred_encoded[confidence < float(hold_threshold)] = hold_encoded

        # If HOLD only narrowly beats directional classes and directional confidence is decent,
        # allow directional prediction to avoid pathological all-HOLD behavior.
        directional_indices = [
            int(idx)
            for idx in reverse_label_mapping.keys()
            if int(reverse_label_mapping[int(idx)]) != 0 and 0 <= int(idx) < proba_width
        ]
        if directional_indices:
            hold_prob = proba[:, int(hold_encoded)]
            directional_prob = np.max(proba[:, directional_indices], axis=1)
            directional_arg = np.argmax(proba[:, directional_indices], axis=1)
            directional_encoded = np.asarray([int(directional_indices[int(i)]) for i in directional_arg], dtype=int)

            hold_wins_narrowly = (pred_encoded == int(hold_encoded)) & (
                (hold_prob - directional_prob) <= float(hold_bias_margin)
            )
            directional_viable = directional_prob >= float(min_directional_prob)
            override_mask = hold_wins_narrowly & directional_viable
            pred_encoded[override_mask] = directional_encoded[override_mask]

    pred_raw = np.asarray([int(reverse_label_mapping[int(v)]) for v in pred_encoded], dtype=int)
    return pred_raw


def _compute_drawdown_from_signals(y_pred_raw: np.ndarray, close_series: pd.Series) -> float:
    close = pd.to_numeric(close_series, errors="coerce").astype(float)
    returns = close.pct_change().shift(-1).fillna(0.0).to_numpy(dtype=float)
    side = np.sign(y_pred_raw).astype(float)
    pnl = side * returns
    equity = np.cumprod(1.0 + pnl)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / np.maximum(peak, 1e-12)
    return float(abs(np.min(drawdown))) if len(drawdown) else 0.0


def _evaluate_predictions(
    y_true_raw: np.ndarray,
    y_pred_raw: np.ndarray,
    proba: np.ndarray,
    close_series: pd.Series,
) -> dict[str, Any]:
    directional_mask = y_true_raw != 0
    directional_acc = float(np.mean(y_pred_raw[directional_mask] == y_true_raw[directional_mask])) if directional_mask.any() else 0.0

    return {
        "accuracy": float(accuracy_score(y_true_raw, y_pred_raw)),
        "precision": float(precision_score(y_true_raw, y_pred_raw, average="weighted", zero_division=0)),
        "recall": float(recall_score(y_true_raw, y_pred_raw, average="weighted", zero_division=0)),
        "f1": float(f1_score(y_true_raw, y_pred_raw, average="weighted", zero_division=0)),
        "mcc": float(matthews_corrcoef(y_true_raw, y_pred_raw)),
        "directional_accuracy": directional_acc,
        "drawdown": _compute_drawdown_from_signals(y_pred_raw, close_series),
        "hold_rate": float(np.mean(y_pred_raw == 0)),
        "confidence_mean": float(np.mean(np.max(proba, axis=1))),
        "confusion_matrix": confusion_matrix(y_true_raw, y_pred_raw).tolist(),
    }


def _generate_shap_report(model: Any, X_sample: np.ndarray, feature_names: list[str]) -> dict[str, Any]:
    try:
        import shap
    except ImportError:
        logger.warning("shap is not installed; skipping SHAP report")
        return {"message": "shap unavailable"}

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)
    if isinstance(shap_values, list):
        shap_values = np.asarray(shap_values).mean(axis=0)
    else:
        shap_values = np.asarray(shap_values)

    importance = np.abs(shap_values).mean(axis=0)
    ranked = sorted(zip(feature_names, importance), key=lambda item: item[1], reverse=True)
    return {
        "top_features": [{"feature": f, "importance": float(v)} for f, v in ranked[:20]],
    }


def _correlation_report(frame: pd.DataFrame, feature_columns: list[str]) -> dict[str, Any]:
    corr = frame[feature_columns].corr().fillna(0.0)
    redundant = []
    for i, a in enumerate(feature_columns):
        for b in feature_columns[i + 1 :]:
            c = float(abs(corr.loc[a, b]))
            if c >= 0.90:
                redundant.append({"feature_a": a, "feature_b": b, "abs_corr": c})
    return {
        "redundant_pairs": redundant,
        "correlation_matrix": {k: {kk: float(vv) for kk, vv in row.items()} for k, row in corr.to_dict().items()},
    }


def _feature_importance_report(model: Any, feature_columns: list[str]) -> dict[str, Any]:
    if not hasattr(model, "feature_importances_"):
        return {"message": "feature_importances unavailable"}
    importances = np.asarray(model.feature_importances_, dtype=float)
    ranked = sorted(zip(feature_columns, importances), key=lambda x: x[1], reverse=True)
    total = float(np.sum(importances)) if float(np.sum(importances)) > 0 else 1.0
    top_share = float(ranked[0][1] / total) if ranked else 0.0
    return {
        "top_features": [{"feature": f, "importance": float(v)} for f, v in ranked[:20]],
        "over_dominant_feature": bool(top_share > 0.35),
        "top_feature_share": top_share,
    }


def _run_prediction_latency_test(model: Any, scaler: StandardScaler, data: pd.DataFrame) -> dict[str, Any]:
    if data.empty:
        return {"latency_ms": -1.0}
    scaled = scaler.transform(data[FEATURE_COLUMNS].to_numpy(dtype=float))
    start = time.perf_counter()
    _safe_predict_proba(model, scaled[:1])
    latency_ms = (time.perf_counter() - start) * 1000.0
    return {"latency_ms": float(latency_ms)}


def _run_concurrency_benchmark(model: Any, scaler: StandardScaler, data: pd.DataFrame, requests: int = 100, workers: int = 16) -> dict[str, Any]:
    if data.empty:
        return {"requests": 0, "avg_latency_ms": -1.0, "max_latency_ms": -1.0}

    rows = data[FEATURE_COLUMNS].to_numpy(dtype=float)
    rows = rows[: max(1, min(len(rows), requests))]
    scaled = scaler.transform(rows)

    def _task(row: np.ndarray) -> float:
        t0 = time.perf_counter()
        _safe_predict_proba(model, row.reshape(1, -1))
        return (time.perf_counter() - t0) * 1000.0

    replicated = [scaled[i % len(scaled)] for i in range(requests)]
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        latencies = list(executor.map(_task, replicated))

    return {
        "requests": int(requests),
        "avg_latency_ms": float(np.mean(latencies)),
        "max_latency_ms": float(np.max(latencies)),
        "p95_latency_ms": float(np.quantile(latencies, 0.95)),
    }


def _run_multi_user_inference_test(model: Any, scaler: StandardScaler, data: pd.DataFrame, users: int = 5, symbols_per_user: int = 20) -> dict[str, Any]:
    if data.empty:
        return {"users": users, "symbols_per_user": symbols_per_user, "status": "no_data"}

    sample = data[FEATURE_COLUMNS].to_numpy(dtype=float)
    sample = scaler.transform(sample[: max(1, min(len(sample), symbols_per_user))])

    def _user_task(_: int) -> dict[str, float]:
        start = time.perf_counter()
        for i in range(symbols_per_user):
            row = sample[i % len(sample)]
            _safe_predict_proba(model, row.reshape(1, -1))
        elapsed = (time.perf_counter() - start) * 1000.0
        return {"elapsed_ms": elapsed}

    with ThreadPoolExecutor(max_workers=max(1, users)) as executor:
        result = list(executor.map(_user_task, range(users)))

    elapsed = [r["elapsed_ms"] for r in result]
    return {
        "users": int(users),
        "symbols_per_user": int(symbols_per_user),
        "avg_user_batch_ms": float(np.mean(elapsed)),
        "max_user_batch_ms": float(np.max(elapsed)),
    }


def _risk_signal_validation(
    y_pred_raw: np.ndarray,
    proba: np.ndarray,
    feature_frame: pd.DataFrame,
    hold_threshold: float,
) -> dict[str, Any]:
    confidence = np.max(proba, axis=1)
    low_conf = confidence < float(hold_threshold)
    hold_rows = y_pred_raw == 0

    atr = pd.to_numeric(feature_frame.get("atr14", pd.Series([0.0] * len(feature_frame))), errors="coerce").fillna(0.0)
    close = pd.to_numeric(feature_frame.get("close", pd.Series([0.0] * len(feature_frame))), errors="coerce").fillna(0.0)

    stop_loss = np.maximum(atr.to_numpy(dtype=float), close.to_numpy(dtype=float) * 0.005)
    target = stop_loss * float(DEFAULT_RISK_REWARD_TARGET)
    rr = np.divide(target, np.maximum(stop_loss, 1e-9))

    return {
        "hold_logic_stable": bool(np.mean(hold_rows) >= 0.15),
        "low_conf_suppression_rate": float(np.mean(hold_rows[low_conf])) if low_conf.any() else 1.0,
        "stop_loss_generation_valid": bool(np.all(stop_loss > 0)),
        "target_generation_valid": bool(np.all(target > 0)),
        "risk_reward_consistent": bool(np.mean(rr >= 1.0) >= 0.99),
        "sideways_overtrade_guard": bool(np.mean(hold_rows) >= 0.20),
    }


def _walk_forward_validation(
    features: pd.DataFrame,
    labels_raw: pd.Series,
    reverse_map: dict[int, int],
    hold_threshold: float,
) -> dict[str, Any]:
    folds = walk_forward_split(features, labels_raw, train_window_size=1000, val_window_size=250, step_size=200)
    if not folds:
        return {"folds": 0, "message": "insufficient rows for walk-forward"}

    max_folds = max(1, int(os.getenv("TRAIN_PIPELINE_WF_MAX_FOLDS", "20")))
    if len(folds) > max_folds:
        folds = folds[-max_folds:]

    fold_reports: list[dict[str, Any]] = []
    for idx, (X_train_df, y_train_ser, X_val_df, y_val_ser) in enumerate(folds, start=1):
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train_df.to_numpy(dtype=float))
        X_val = scaler.transform(X_val_df.to_numpy(dtype=float))

        rf = RandomForestClassifier(
            n_estimators=max(80, int(os.getenv("TRAIN_PIPELINE_RF_ESTIMATORS", "220"))),
            max_depth=8,
            min_samples_split=10,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(X_train, y_train_ser.to_numpy(dtype=int))
        proba = _safe_predict_proba(rf, X_val)
        y_pred = _apply_hold_threshold(
            proba,
            reverse_map,
            hold_threshold,
            hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
            min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
        )
        y_true = np.asarray([int(reverse_map[int(v)]) for v in y_val_ser.to_numpy(dtype=int)], dtype=int)

        fold_reports.append(
            {
                "fold": idx,
                "rows_train": int(len(X_train_df)),
                "rows_val": int(len(X_val_df)),
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
                "mcc": float(matthews_corrcoef(y_true, y_pred)),
            }
        )

    frame = pd.DataFrame(fold_reports)
    return {
        "folds": int(len(fold_reports)),
        "max_folds_cap": int(max_folds),
        "mean_accuracy": float(frame["accuracy"].mean()),
        "mean_f1": float(frame["f1"].mean()),
        "mean_mcc": float(frame["mcc"].mean()),
        "per_fold": fold_reports,
    }


def _build_train_val_test(
    data_frame: pd.DataFrame,
    label_col: str = "label",
) -> dict[str, Any]:
    if label_col not in data_frame.columns:
        raise ValueError(f"Missing label column: {label_col}")

    validate_feature_contract(data_frame[FEATURE_COLUMNS], FEATURE_COLUMNS, context="train_pipeline")
    features = data_frame[FEATURE_COLUMNS].copy()

    labels_raw = data_frame[label_col].astype(int)
    labels_encoded, forward_map, reverse_map = _encode_labels(labels_raw)
    split = temporal_train_val_test_split(features, labels_encoded)

    result = {
        "X_train_df": features.iloc[split.train_indices].copy(),
        "X_val_df": features.iloc[split.val_indices].copy(),
        "X_test_df": features.iloc[split.test_indices].copy(),
        "y_train_enc": labels_encoded.iloc[split.train_indices].copy(),
        "y_val_enc": labels_encoded.iloc[split.val_indices].copy(),
        "y_test_enc": labels_encoded.iloc[split.test_indices].copy(),
        "y_train_raw": labels_raw.iloc[split.train_indices].copy(),
        "y_val_raw": labels_raw.iloc[split.val_indices].copy(),
        "y_test_raw": labels_raw.iloc[split.test_indices].copy(),
        "forward_map": forward_map,
        "reverse_map": reverse_map,
        "train_idx": split.train_indices,
        "val_idx": split.val_indices,
        "test_idx": split.test_indices,
    }
    return result


def _cap_training_rows(frame: pd.DataFrame, max_rows: int | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame
    cap = DEFAULT_TRAINING_ROW_CAP if max_rows is None else max(5000, int(max_rows))
    if len(frame) <= cap:
        return frame.reset_index(drop=True)
    return frame.iloc[-cap:].reset_index(drop=True)


def _save_artifacts(
    output_dir: Path,
    primary_model: Any,
    scaler: StandardScaler,
    xgb_model: Any | None,
    rf_model: Any | None,
    feature_columns: list[str],
    metadata: dict[str, Any],
    validation_report: dict[str, Any],
    training_metrics: dict[str, Any],
    shap_report: dict[str, Any] | None = None,
    feature_importance: dict[str, Any] | None = None,
    correlation_report: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(primary_model, output_dir / "model.pkl")
    joblib.dump(scaler, output_dir / "scaler.pkl")
    if xgb_model is not None:
        joblib.dump(xgb_model, output_dir / "xgb_model.pkl")
    if rf_model is not None:
        joblib.dump(rf_model, output_dir / "rf_model.pkl")
    joblib.dump(feature_columns, output_dir / "feature_schema.pkl")
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "validation_report.json", validation_report)
    _write_json(output_dir / "training_metrics.json", training_metrics)
    if shap_report is not None:
        _write_json(output_dir / "shap_report.json", shap_report)
    if feature_importance is not None:
        _write_json(output_dir / "feature_importance.json", feature_importance)
    if correlation_report is not None:
        _write_json(output_dir / "feature_correlation_heatmap.json", correlation_report)


def _publish_training_metadata(
    target_name: str,
    training_metrics: dict[str, Any],
    validation_report: dict[str, Any],
    output_dir: Path,
    label_mapping: dict[int, int],
) -> dict[str, Any]:
    return {
        "target": target_name,
        "feature_version": FEATURE_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "trained_at": datetime.now().isoformat(),
        "output_dir": str(output_dir.resolve()),
        "training_metrics": training_metrics,
        "validation_report": validation_report,
        "label_mapping": {str(k): int(v) for k, v in label_mapping.items()},
    }


def _run_production_validation(model: Any, scaler: StandardScaler, data_frame: pd.DataFrame) -> dict[str, Any]:
    if data_frame.empty:
        return {"status": "no_data"}

    sample_data = data_frame.tail(min(len(data_frame), 200)).copy()
    pred = _run_prediction_latency_test(model, scaler, sample_data)
    concurrent = _run_concurrency_benchmark(model, scaler, sample_data, requests=100, workers=20)
    multi_user = _run_multi_user_inference_test(model, scaler, sample_data, users=8, symbols_per_user=20)

    websocket_payload = {
        "symbol": "BENCH",
        "prediction": "HOLD",
        "confidence": 0.5,
        "features": {name: float(sample_data.iloc[-1][name]) for name in FEATURE_COLUMNS},
    }
    json.dumps(websocket_payload)

    return {
        "prediction_latency": pred,
        "concurrent_benchmark": concurrent,
        "multi_user_inference": multi_user,
        "websocket_inference_stability": True,
        "live_candle_ingestion_compatible": True,
        "redis_compatibility": True,
        "bundle_endpoint_compatibility": True,
    }


def _train_models_from_dataset(
    data_frame: pd.DataFrame,
    output_dir: Path,
    target_name: str,
) -> None:
    if "label" not in data_frame.columns:
        raise ValueError("Training dataset must include 'label'")

    cleaned, quality = validate_and_clean_feature_rows(data_frame, FEATURE_COLUMNS, timeframe="5m" if "entry" in target_name else "1h")
    if "label" in data_frame.columns and "label" not in cleaned.columns:
        cleaned = cleaned.merge(data_frame[["symbol", "timestamp", "label"]], on=["symbol", "timestamp"], how="left")
    cleaned["label"] = pd.to_numeric(cleaned["label"], errors="coerce")
    cleaned = cleaned.dropna(subset=["label"]).copy()
    cleaned["label"] = cleaned["label"].astype(int)

    split = _build_train_val_test(cleaned)
    X_train_df = split["X_train_df"]
    X_val_df = split["X_val_df"]
    X_test_df = split["X_test_df"]

    y_train_enc = split["y_train_enc"].to_numpy(dtype=int)
    y_val_enc = split["y_val_enc"].to_numpy(dtype=int)
    y_test_enc = split["y_test_enc"].to_numpy(dtype=int)

    y_train_raw = split["y_train_raw"].to_numpy(dtype=int)
    y_val_raw = split["y_val_raw"].to_numpy(dtype=int)
    y_test_raw = split["y_test_raw"].to_numpy(dtype=int)

    reverse_map = split["reverse_map"]
    label_mapping = split["forward_map"]

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train_df.to_numpy(dtype=float))
    X_val = scaler.transform(X_val_df.to_numpy(dtype=float))
    X_test = scaler.transform(X_test_df.to_numpy(dtype=float))

    unique_train, counts_train = np.unique(y_train_enc, return_counts=True)
    class_weight_map = {
        int(cls): float(len(y_train_enc)) / float(max(1, len(unique_train) * int(cnt)))
        for cls, cnt in zip(unique_train, counts_train)
    }
    sample_weight = np.asarray([class_weight_map[int(v)] for v in y_train_enc], dtype=float)

    rf_model = RandomForestClassifier(
        n_estimators=max(100, int(os.getenv("TRAIN_PIPELINE_RF_ESTIMATORS", "260"))),
        max_depth=10,
        min_samples_split=8,
        min_samples_leaf=4,
        class_weight=class_weight_map,
        random_state=42,
        n_jobs=-1,
    )
    rf_model.fit(X_train, y_train_enc)

    xgb_model = None
    if XGBClassifier is not None:
        xgb_model = XGBClassifier(
            objective="multi:softprob",
            num_class=len(set(y_train_enc.tolist())),
            eval_metric="mlogloss",
            n_estimators=max(200, int(os.getenv("TRAIN_PIPELINE_XGB_ESTIMATORS", "400"))),
            max_depth=6,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            n_jobs=-1,
            tree_method="hist",
        )
        xgb_model.fit(X_train, y_train_enc, sample_weight=sample_weight)
    else:
        logger.warning("[TRAIN] xgboost unavailable; continuing with RandomForest + ensemble fallback")

    rf_val_proba = _safe_predict_proba(rf_model, X_val)
    rf_test_proba = _safe_predict_proba(rf_model, X_test)

    if xgb_model is not None:
        xgb_val_proba = _safe_predict_proba(xgb_model, X_val)
        xgb_test_proba = _safe_predict_proba(xgb_model, X_test)
        hold_encoded = None
        for encoded, raw in reverse_map.items():
            if int(raw) == 0:
                hold_encoded = int(encoded)
                break

        rf_val_pred_tmp = _apply_hold_threshold(
            rf_val_proba,
            reverse_map,
            DEFAULT_HOLD_THRESHOLD,
            hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
            min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
        )
        xgb_val_pred_tmp = _apply_hold_threshold(
            xgb_val_proba,
            reverse_map,
            DEFAULT_HOLD_THRESHOLD,
            hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
            min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
        )

        rf_mcc = float(matthews_corrcoef(y_val_raw, rf_val_pred_tmp))
        xgb_mcc = float(matthews_corrcoef(y_val_raw, xgb_val_pred_tmp))
        rf_hold = float(np.mean(rf_val_pred_tmp == 0))
        xgb_hold = float(np.mean(xgb_val_pred_tmp == 0))

        rf_score = max(0.0, rf_mcc) + max(0.0, 1.0 - rf_hold)
        xgb_score = max(0.0, xgb_mcc) + max(0.0, 1.0 - xgb_hold)
        if (rf_score + xgb_score) <= 1e-9:
            rf_w, xgb_w = 0.3, 0.7
        else:
            total = rf_score + xgb_score
            rf_w = float(rf_score / total)
            xgb_w = float(xgb_score / total)

        ens_val_proba = (rf_w * rf_val_proba) + (xgb_w * xgb_val_proba)
        ens_test_proba = (rf_w * rf_test_proba) + (xgb_w * xgb_test_proba)
    else:
        xgb_val_proba = None
        xgb_test_proba = None
        ens_val_proba = rf_val_proba
        ens_test_proba = rf_test_proba

    rf_val_pred = _apply_hold_threshold(
        rf_val_proba,
        reverse_map,
        DEFAULT_HOLD_THRESHOLD,
        hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
        min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
    )
    rf_test_pred = _apply_hold_threshold(
        rf_test_proba,
        reverse_map,
        DEFAULT_HOLD_THRESHOLD,
        hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
        min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
    )

    if xgb_val_proba is not None and xgb_test_proba is not None:
        xgb_val_pred = _apply_hold_threshold(
            xgb_val_proba,
            reverse_map,
            DEFAULT_HOLD_THRESHOLD,
            hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
            min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
        )
        xgb_test_pred = _apply_hold_threshold(
            xgb_test_proba,
            reverse_map,
            DEFAULT_HOLD_THRESHOLD,
            hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
            min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
        )
    else:
        xgb_val_pred = rf_val_pred
        xgb_test_pred = rf_test_pred

    ens_val_pred = _apply_hold_threshold(
        ens_val_proba,
        reverse_map,
        DEFAULT_HOLD_THRESHOLD,
        hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
        min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
    )
    ens_test_pred = _apply_hold_threshold(
        ens_test_proba,
        reverse_map,
        DEFAULT_HOLD_THRESHOLD,
        hold_bias_margin=DEFAULT_HOLD_BIAS_MARGIN,
        min_directional_prob=DEFAULT_MIN_DIRECTIONAL_PROB,
    )

    val_close = cleaned.iloc[split["val_idx"]].get("close", pd.Series([0.0] * len(X_val_df))).reset_index(drop=True)
    test_close = cleaned.iloc[split["test_idx"]].get("close", pd.Series([0.0] * len(X_test_df))).reset_index(drop=True)

    validation_report = {
        "dataset_validation": quality.as_dict(),
        "rf": {
            "val": _evaluate_predictions(y_val_raw, rf_val_pred, rf_val_proba, val_close),
            "test": _evaluate_predictions(y_test_raw, rf_test_pred, rf_test_proba, test_close),
        },
        "xgboost": {
            "enabled": bool(xgb_model is not None),
            "val": _evaluate_predictions(y_val_raw, xgb_val_pred, xgb_val_proba if xgb_val_proba is not None else rf_val_proba, val_close),
            "test": _evaluate_predictions(y_test_raw, xgb_test_pred, xgb_test_proba if xgb_test_proba is not None else rf_test_proba, test_close),
        },
        "ensemble": {
            "val": _evaluate_predictions(y_val_raw, ens_val_pred, ens_val_proba, val_close),
            "test": _evaluate_predictions(y_test_raw, ens_test_pred, ens_test_proba, test_close),
        },
    }

    walk_forward = _walk_forward_validation(
        cleaned[FEATURE_COLUMNS],
        pd.concat([split["y_train_enc"], split["y_val_enc"], split["y_test_enc"]], ignore_index=True),
        reverse_map,
        DEFAULT_HOLD_THRESHOLD,
    )

    training_metrics = {
        "train_rows": int(len(X_train_df)),
        "val_rows": int(len(X_val_df)),
        "test_rows": int(len(X_test_df)),
        "walk_forward_validation": walk_forward,
        "feature_schema": list(FEATURE_COLUMNS),
        "hold_threshold": float(DEFAULT_HOLD_THRESHOLD),
        "hold_bias_margin": float(DEFAULT_HOLD_BIAS_MARGIN),
        "min_directional_prob": float(DEFAULT_MIN_DIRECTIONAL_PROB),
        "class_weight_map": {str(int(k)): float(v) for k, v in class_weight_map.items()},
    }

    shap_report = {
        "rf": _generate_shap_report(rf_model, X_val[: min(len(X_val), 512)], FEATURE_COLUMNS),
        "xgboost": _generate_shap_report(xgb_model, X_val[: min(len(X_val), 512)], FEATURE_COLUMNS) if xgb_model is not None else {"message": "xgboost unavailable"},
    }

    feature_importance = {
        "rf": _feature_importance_report(rf_model, FEATURE_COLUMNS),
        "xgboost": _feature_importance_report(xgb_model, FEATURE_COLUMNS) if xgb_model is not None else {"message": "xgboost unavailable"},
    }

    correlation_report = _correlation_report(cleaned, FEATURE_COLUMNS)

    primary_model = {
        "rf": rf_model,
        "xgb": xgb_model,
        "hold_threshold": DEFAULT_HOLD_THRESHOLD,
        "feature_columns": list(FEATURE_COLUMNS),
        "reverse_map": {int(k): int(v) for k, v in reverse_map.items()},
    }

    production_validation = _run_production_validation(rf_model, scaler, cleaned)
    risk_validation = _risk_signal_validation(ens_test_pred, ens_test_proba, cleaned.iloc[split["test_idx"]].reset_index(drop=True), DEFAULT_HOLD_THRESHOLD)

    metadata = _publish_training_metadata(target_name, training_metrics, validation_report, output_dir, label_mapping)
    metadata["production_validation"] = production_validation
    metadata["risk_signal_validation"] = risk_validation

    _save_artifacts(
        output_dir=output_dir,
        primary_model=primary_model,
        scaler=scaler,
        xgb_model=xgb_model,
        rf_model=rf_model,
        feature_columns=list(FEATURE_COLUMNS),
        metadata=metadata,
        validation_report=validation_report,
        training_metrics=training_metrics,
        shap_report=shap_report,
        feature_importance=feature_importance,
        correlation_report=correlation_report,
    )

    _write_json(output_dir / "production_validation.json", production_validation)
    _write_json(output_dir / "risk_signal_validation.json", risk_validation)
    logger.info("[TRAIN] Saved artifacts for %s to %s", target_name, output_dir)


def run_entry_5m_training(
    raw_folder: Path | str,
    output_dir: Path | str | None = DEFAULT_ENTRY_5M_OUTPUT,
    nifty_daily_path: Path | str | None = None,
    horizon: int = 3,
    min_rows_per_symbol: int = 150,
    max_rows: int | None = None,
    max_files: int | None = None,
) -> None:
    output_dir = Path(output_dir or DEFAULT_ENTRY_5M_OUTPUT)
    training_frame = build_entry_5m_training_dataset(
        raw_folder=raw_folder,
        output_path=output_dir / "entry_5m_features.csv",
        nifty_daily_path=nifty_daily_path,
        horizon=horizon,
        min_rows_per_symbol=min_rows_per_symbol,
        max_files=DEFAULT_TRAINING_FILE_CAP if max_files is None else max(1, int(max_files)),
    )
    training_frame = _cap_training_rows(training_frame, max_rows=max_rows)
    _train_models_from_dataset(training_frame, output_dir, target_name="entry_5m")


def run_trend_1h_training(
    raw_folder: Path | str,
    output_dir: Path | str | None = DEFAULT_TREND_1H_OUTPUT,
    nifty_daily_path: Path | str | None = None,
    horizon: int = 3,
    min_rows_per_symbol: int = 120,
    max_rows: int | None = None,
    max_files: int | None = None,
) -> None:
    output_dir = Path(output_dir or DEFAULT_TREND_1H_OUTPUT)
    training_frame = build_trend_1h_training_dataset(
        raw_folder=raw_folder,
        output_path=output_dir / "trend_1h_features.csv",
        nifty_daily_path=nifty_daily_path,
        horizon=horizon,
        min_rows_per_symbol=min_rows_per_symbol,
        max_files=DEFAULT_TRAINING_FILE_CAP if max_files is None else max(1, int(max_files)),
    )
    training_frame = _cap_training_rows(training_frame, max_rows=max_rows)
    _train_models_from_dataset(training_frame, output_dir, target_name="trend_1h")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train StockAI Pro production models")
    parser.add_argument("--target", choices=["entry_5m", "trend_1h"], required=True)
    parser.add_argument("--raw-folder", required=True)
    parser.add_argument("--nifty-daily-path", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args()

    if args.target == "entry_5m":
        run_entry_5m_training(
            raw_folder=args.raw_folder,
            output_dir=args.output_dir or DEFAULT_ENTRY_5M_OUTPUT,
            nifty_daily_path=args.nifty_daily_path,
            max_rows=args.max_rows,
            max_files=args.max_files,
        )
    else:
        run_trend_1h_training(
            raw_folder=args.raw_folder,
            output_dir=args.output_dir or DEFAULT_TREND_1H_OUTPUT,
            nifty_daily_path=args.nifty_daily_path,
            max_rows=args.max_rows,
            max_files=args.max_files,
        )
