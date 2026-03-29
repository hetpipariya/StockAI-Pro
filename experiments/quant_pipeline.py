from __future__ import annotations

import argparse
import json
import logging
import pickle
import re
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_score, recall_score
from sklearn.preprocessing import LabelEncoder, StandardScaler

try:
    from xgboost import XGBClassifier

    HAS_XGBOOST = True
except Exception:  # pragma: no cover - runtime optional dependency
    HAS_XGBOOST = False


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("quant_pipeline")

MODEL_VERSION_PATTERN = re.compile(r"model_v(\d+)\.pkl$")


SYMBOLS = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "AXISBANK",
    "KOTAKBANK",
]

FEATURE_COLUMNS = [
    "ema_20",
    "ema_50",
    "rsi",
    "macd",
    "macd_signal",
    "vwap",
    "returns",
    "volatility",
    "price_change_pct",
    "rolling_volatility",
    "higher_high_ratio",
    "lower_low_ratio",
]


@dataclass
class CandidateResult:
    name: str
    iteration: int
    accuracy: float
    precision: float
    recall: float
    confusion_matrix: List[List[int]]
    model: Any


def _to_serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_serializable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_serializable(v) for v in value]
    if isinstance(value, (np.generic,)):
        return value.item()
    return value


def ensure_dirs(base_dir: Path) -> Dict[str, Path]:
    raw = base_dir / "data" / "raw"
    processed = base_dir / "data" / "processed"
    models = base_dir / "models"
    reports = base_dir / "reports"
    logs = base_dir / "logs"

    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    return {
        "raw": raw,
        "processed": processed,
        "models": models,
        "reports": reports,
        "logs": logs,
    }


def _setup_run_logging(logs_dir: Path, run_id: str) -> logging.Handler:
    log_path = logs_dir / f"pipeline_{run_id}.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.info("Run logger attached at %s", log_path)
    return handler


def _teardown_run_logging(handler: Optional[logging.Handler]) -> None:
    if handler is None:
        return
    try:
        logger.removeHandler(handler)
        handler.close()
    except Exception:
        pass


def _assert_no_nan(df: pd.DataFrame, columns: List[str], context: str) -> None:
    missing_cols = [col for col in columns if col not in df.columns]
    if missing_cols:
        raise RuntimeError(f"{context}: missing required columns {missing_cols}")

    null_counts = df[columns].isnull().sum()
    bad = {col: int(count) for col, count in null_counts.items() if int(count) > 0}
    if bad:
        raise RuntimeError(f"{context}: NaN values detected {bad}")


def _assert_finite_metrics(metrics: Dict[str, Any], context: str) -> None:
    for metric_name in ("accuracy", "precision", "recall"):
        value = float(metrics.get(metric_name, np.nan))
        if not np.isfinite(value):
            raise RuntimeError(f"{context}: non-finite metric {metric_name}={value}")


def _assert_no_time_leakage(train_df: pd.DataFrame, test_df: pd.DataFrame, unseen_df: pd.DataFrame) -> None:
    train_max = train_df["timestamp"].max()
    test_min = test_df["timestamp"].min()
    test_max = test_df["timestamp"].max()

    if train_max > test_min:
        raise RuntimeError(
            f"Temporal leakage detected: train max timestamp {train_max} overlaps test min timestamp {test_min}"
        )

    if not unseen_df.empty:
        unseen_min = unseen_df["timestamp"].min()
        if test_max > unseen_min:
            raise RuntimeError(
                f"Temporal leakage detected: test max timestamp {test_max} overlaps unseen min timestamp {unseen_min}"
            )

    key_cols: List[str] = []
    if "symbol" in train_df.columns and "symbol" in test_df.columns:
        key_cols.append("symbol")
    if "timeframe" in train_df.columns and "timeframe" in test_df.columns:
        key_cols.append("timeframe")
    key_cols.append("timestamp")

    def _build_keys(frame: pd.DataFrame, cols: List[str]) -> set:
        return set(frame[cols].astype(str).agg("|".join, axis=1))

    train_keys = _build_keys(train_df, key_cols)
    test_keys = _build_keys(test_df, key_cols)
    if train_keys.intersection(test_keys):
        raise RuntimeError("Temporal leakage detected: duplicate sample keys across train and test splits")

    if not unseen_df.empty:
        unseen_keys = _build_keys(unseen_df, key_cols)
        if train_keys.intersection(unseen_keys) or test_keys.intersection(unseen_keys):
            raise RuntimeError("Temporal leakage detected: duplicate sample keys across train/test and unseen splits")


def _next_model_version(models_dir: Path) -> int:
    versions: List[int] = []
    for model_file in models_dir.glob("model_v*.pkl"):
        match = MODEL_VERSION_PATTERN.match(model_file.name)
        if not match:
            continue
        try:
            versions.append(int(match.group(1)))
        except Exception:
            continue
    return (max(versions) + 1) if versions else 1


def _save_versioned_model(artifact: Dict[str, Any], models_dir: Path) -> Dict[str, Any]:
    version = _next_model_version(models_dir)
    model_file = models_dir / f"model_v{version}.pkl"
    compat_file = models_dir / "model.pkl"

    with model_file.open("wb") as fp:
        pickle.dump(artifact, fp)

    shutil.copyfile(model_file, compat_file)

    latest_meta = {
        "version": int(version),
        "model_file": model_file.name,
        "model_path": str(model_file),
        "compat_model_path": str(compat_file),
        "trained_at": artifact.get("trained_at"),
    }
    latest_meta_path = models_dir / "latest_model.json"
    with latest_meta_path.open("w", encoding="utf-8") as fp:
        json.dump(_to_serializable(latest_meta), fp, indent=2)

    return {
        "version": int(version),
        "versioned_model_path": str(model_file),
        "compat_model_path": str(compat_file),
        "latest_meta_path": str(latest_meta_path),
    }


def _standardize_ohlcv(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = raw_df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    col_map = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "adj close": "close",
        "volume": "volume",
    }

    selected = {}
    for source_name, target_name in col_map.items():
        if source_name in df.columns and target_name not in selected:
            selected[target_name] = df[source_name]

    if not {"open", "high", "low", "close", "volume"}.issubset(selected.keys()):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    out = pd.DataFrame(selected)
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    return out


def download_intraday_5m(symbol: str, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    ticker = f"{symbol}.NS"
    frames: List[pd.DataFrame] = []
    chunk_days = 58
    empty_streak = 0
    window_end = end_dt

    while window_end > start_dt:
        window_start = max(start_dt, window_end - timedelta(days=chunk_days))
        logger.info("Downloading %s 5m: %s -> %s", symbol, window_start.date(), window_end.date())
        try:
            raw = yf.download(
                ticker,
                start=window_start,
                end=window_end,
                interval="5m",
                auto_adjust=False,
                prepost=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            logger.warning("Download error for %s chunk %s-%s: %s", symbol, window_start, window_end, exc)
            raw = pd.DataFrame()

        clean = _standardize_ohlcv(raw)
        if clean.empty:
            empty_streak += 1
        else:
            frames.append(clean)
            empty_streak = 0

        # yfinance intraday history is limited; stop after repeated empty chunks.
        if frames and empty_streak >= 4:
            logger.warning(
                "%s older 5m chunks unavailable after %d empty chunks; stopping historical crawl early.",
                symbol,
                empty_streak,
            )
            break

        window_end = window_start

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    merged = pd.concat(frames)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged


def build_15m_from_5m(df_5m: pd.DataFrame) -> pd.DataFrame:
    if df_5m.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    out = (
        df_5m.resample("15min", label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
    )
    return out


def classify_market(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    out = df.copy()
    out["returns"] = out["close"].pct_change()
    out["price_change_pct"] = out["close"].pct_change(window)
    out["rolling_volatility"] = out["returns"].rolling(window).std()
    out["higher_high_ratio"] = out["high"].diff().gt(0).rolling(window).mean()
    out["lower_low_ratio"] = out["low"].diff().lt(0).rolling(window).mean()

    bullish = (out["price_change_pct"] > 0.006) & (out["higher_high_ratio"] > 0.55)
    bearish = (out["price_change_pct"] < -0.006) & (out["lower_low_ratio"] > 0.55)

    out["market_type"] = np.select([bullish, bearish], [1, -1], default=0)

    low_movement = out["price_change_pct"].abs() < 0.003
    dynamic_vol_threshold = out["rolling_volatility"].rolling(100, min_periods=20).median()
    range_bound = out["rolling_volatility"] <= dynamic_vol_threshold
    out.loc[low_movement | range_bound, "market_type"] = 0

    return out


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["ema_20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema_50"] = out["close"].ewm(span=50, adjust=False).mean()

    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs))

    ema_fast = out["close"].ewm(span=12, adjust=False).mean()
    ema_slow = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema_fast - ema_slow
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()

    session = pd.Series(out.index.date, index=out.index)
    tp = (out["high"] + out["low"] + out["close"]) / 3.0
    cumulative_volume = out["volume"].groupby(session).cumsum()
    cumulative_tpv = (tp * out["volume"]).groupby(session).cumsum()
    out["vwap"] = cumulative_tpv / cumulative_volume.replace(0, np.nan)

    out["volatility"] = out["returns"].rolling(20).std()

    # Predict next market phase (3 bars ahead).
    out["target_market_type"] = out["market_type"].shift(-3)

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.dropna(
        subset=FEATURE_COLUMNS
        + [
            "market_type",
            "target_market_type",
            "price_change_pct",
            "rolling_volatility",
            "higher_high_ratio",
            "lower_low_ratio",
        ],
        inplace=True,
    )

    out["target_market_type"] = out["target_market_type"].astype(int)
    out["market_type"] = out["market_type"].astype(int)
    return out


def save_raw_csv(df: pd.DataFrame, path: Path) -> None:
    save_df = df.copy()
    save_df.insert(0, "timestamp", save_df.index)
    save_df.to_csv(path, index=False)


def prepare_dataset(base_dir: Path, years: int) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]]]:
    dirs = ensure_dirs(base_dir)
    now = datetime.utcnow()
    start = now - timedelta(days=365 * years)

    all_frames: List[pd.DataFrame] = []
    coverage: Dict[str, Dict[str, float]] = {}

    for symbol in SYMBOLS:
        logger.info("Processing symbol: %s", symbol)
        symbol_5m = download_intraday_5m(symbol, start, now)
        symbol_15m = build_15m_from_5m(symbol_5m)

        save_raw_csv(symbol_5m, dirs["raw"] / f"{symbol}_5m.csv")
        save_raw_csv(symbol_15m, dirs["raw"] / f"{symbol}_15m.csv")

        coverage[symbol] = {}
        for timeframe, df in (("5m", symbol_5m), ("15m", symbol_15m)):
            if df.empty:
                coverage[symbol][timeframe] = 0.0
                continue

            years_covered = (df.index.max() - df.index.min()).days / 365.0
            coverage[symbol][timeframe] = float(years_covered)

            processed = add_features(classify_market(df))
            if processed.empty:
                continue

            processed = processed.copy()
            processed["symbol"] = symbol
            processed["timeframe"] = timeframe
            processed["timestamp"] = processed.index

            processed_path = dirs["processed"] / f"{symbol}_{timeframe}_processed.csv"
            processed.to_csv(processed_path, index=False)
            all_frames.append(processed.reset_index(drop=True))

    if not all_frames:
        raise RuntimeError("No processed rows generated. Dataset pipeline produced no training data.")

    final_df = pd.concat(all_frames, ignore_index=True)
    final_df["timestamp"] = pd.to_datetime(final_df["timestamp"], errors="coerce")
    final_df = final_df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    _assert_no_nan(final_df, FEATURE_COLUMNS + ["target_market_type", "timestamp"], "final_dataset")

    final_path = dirs["processed"] / "final_dataset.csv"
    final_df.to_csv(final_path, index=False)
    logger.info("Saved final dataset: %s (rows=%d)", final_path, len(final_df))

    return final_df, coverage


def _evaluate(y_true: np.ndarray, y_pred: np.ndarray, labels: List[int]) -> Dict[str, Any]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
    }


def _candidate_models(iteration: int) -> List[Tuple[str, Any]]:
    c_values = [0.2, 0.5, 1.0, 2.0]
    c_value = c_values[min(iteration, len(c_values) - 1)]

    models: List[Tuple[str, Any]] = [
        (
            "logistic_regression",
            LogisticRegression(
                max_iter=2500,
                C=c_value,
                class_weight="balanced",
                multi_class="auto",
                random_state=42,
            ),
        ),
        (
            "random_forest",
            RandomForestClassifier(
                n_estimators=300 + (iteration * 200),
                max_depth=7 + (iteration * 2),
                min_samples_split=max(2, 8 - iteration),
                min_samples_leaf=1,
                class_weight="balanced_subsample",
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ]

    if HAS_XGBOOST:
        models.append(
            (
                "xgboost",
                XGBClassifier(
                    objective="multi:softprob",
                    num_class=3,
                    n_estimators=350 + (iteration * 200),
                    max_depth=4 + min(iteration, 3),
                    learning_rate=max(0.03, 0.1 - (iteration * 0.015)),
                    subsample=0.85,
                    colsample_bytree=0.85,
                    random_state=42,
                    eval_metric="mlogloss",
                    n_jobs=-1,
                ),
            )
        )

    return models


def train_with_auto_improvement(df: pd.DataFrame, base_dir: Path, max_iterations: int) -> Dict[str, Any]:
    dirs = ensure_dirs(base_dir)

    if df.empty:
        raise RuntimeError("Cannot train model: dataset is empty")

    label_encoder = LabelEncoder()
    label_encoder.fit(np.array([-1, 0, 1], dtype=int))
    encoded_order = label_encoder.transform(np.array([-1, 0, 1], dtype=int)).tolist()

    train_end = int(len(df) * 0.8)
    unseen_start = int(len(df) * 0.9)

    if train_end < 200:
        raise RuntimeError("Insufficient rows for train/test split. Need more than 200 rows.")

    train_df = df.iloc[:train_end].copy()
    test_df = df.iloc[train_end:unseen_start].copy()
    unseen_df = df.iloc[unseen_start:].copy()

    _assert_no_nan(train_df, FEATURE_COLUMNS + ["target_market_type", "timestamp"], "train_split")
    _assert_no_nan(test_df, FEATURE_COLUMNS + ["target_market_type", "timestamp"], "test_split")
    if not unseen_df.empty:
        _assert_no_nan(unseen_df, FEATURE_COLUMNS + ["target_market_type", "timestamp"], "unseen_split")

    _assert_no_time_leakage(train_df, test_df, unseen_df)

    y_train = label_encoder.transform(train_df["target_market_type"].astype(int).values)
    y_test = label_encoder.transform(test_df["target_market_type"].astype(int).values)
    y_unseen = label_encoder.transform(unseen_df["target_market_type"].astype(int).values) if not unseen_df.empty else np.array([])

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_df[FEATURE_COLUMNS].astype(float).values)
    X_test = scaler.transform(test_df[FEATURE_COLUMNS].astype(float).values)
    X_unseen = scaler.transform(unseen_df[FEATURE_COLUMNS].astype(float).values) if not unseen_df.empty else np.empty((0, len(FEATURE_COLUMNS)))

    best: CandidateResult | None = None
    history: List[Dict[str, Any]] = []

    for iteration in range(max_iterations):
        logger.info("Auto-improvement iteration %d/%d", iteration + 1, max_iterations)

        for model_name, model in _candidate_models(iteration):
            logger.info("Training candidate model: %s", model_name)
            model.fit(X_train, y_train)
            pred_test = model.predict(X_test)
            metrics = _evaluate(y_test, pred_test, encoded_order)
            _assert_finite_metrics(metrics, f"candidate={model_name} iteration={iteration}")

            row = {
                "iteration": iteration,
                "model": model_name,
                **metrics,
            }
            history.append(row)
            logger.info(
                "Candidate %s iteration=%d accuracy=%.6f precision=%.6f recall=%.6f",
                model_name,
                iteration,
                metrics["accuracy"],
                metrics["precision"],
                metrics["recall"],
            )

            current = CandidateResult(
                name=model_name,
                iteration=iteration,
                accuracy=metrics["accuracy"],
                precision=metrics["precision"],
                recall=metrics["recall"],
                confusion_matrix=metrics["confusion_matrix"],
                model=model,
            )

            if best is None or current.accuracy > best.accuracy:
                best = current

        if best and best.accuracy > 0.50:
            logger.info("Stopping loop: reached accuracy threshold with %.6f", best.accuracy)
            break

    if best is None:
        raise RuntimeError("Auto-improvement loop did not produce a trained model")

    best_model = best.model

    train_metrics = _evaluate(y_train, best_model.predict(X_train), encoded_order)
    test_metrics = _evaluate(y_test, best_model.predict(X_test), encoded_order)
    _assert_finite_metrics(train_metrics, "train_metrics")
    _assert_finite_metrics(test_metrics, "test_metrics")

    unseen_metrics = None
    if len(y_unseen) > 0:
        unseen_metrics = _evaluate(y_unseen, best_model.predict(X_unseen), encoded_order)
        _assert_finite_metrics(unseen_metrics, "unseen_metrics")

    overfit_gap = None
    stable_predictions = None
    if unseen_metrics is not None:
        overfit_gap = float(train_metrics["accuracy"] - unseen_metrics["accuracy"])
        stable_predictions = bool(abs(test_metrics["accuracy"] - unseen_metrics["accuracy"]) <= 0.15 and overfit_gap <= 0.15)

    artifact = {
        "model": best_model,
        "scaler": scaler,
        "feature_columns": FEATURE_COLUMNS,
        "label_mapping": {str(int(i)): int(label_encoder.inverse_transform([i])[0]) for i in encoded_order},
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "target_horizon_bars": 3,
        "timeframe": "15m",
    }
    model_meta = _save_versioned_model(artifact, dirs["models"])

    report = {
        "best_model": {
            "name": best.name,
            "iteration": best.iteration,
            "accuracy": best.accuracy,
            "precision": best.precision,
            "recall": best.recall,
            "confusion_matrix": best.confusion_matrix,
        },
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "unseen_metrics": unseen_metrics,
        "overfit_gap": overfit_gap,
        "stable_predictions": stable_predictions,
        "history": history,
        "model": model_meta,
        "target_accuracy_threshold": 0.50,
    }

    report_path = dirs["reports"] / f"evaluation_report_v{model_meta['version']}.json"
    with report_path.open("w", encoding="utf-8") as fp:
        json.dump(_to_serializable(report), fp, indent=2)

    compat_report_path = dirs["models"] / "evaluation_report.json"
    with compat_report_path.open("w", encoding="utf-8") as fp:
        json.dump(_to_serializable(report), fp, indent=2)

    logger.info("Saved model artifact: %s", model_meta["versioned_model_path"])
    logger.info("Saved compatibility model artifact: %s", model_meta["compat_model_path"])
    logger.info("Saved evaluation report: %s", report_path)
    logger.info("Updated compatibility evaluation report: %s", compat_report_path)

    report["report_path"] = str(report_path)
    report["compat_report_path"] = str(compat_report_path)
    report["model_path"] = model_meta["compat_model_path"]
    return report


def run(years: int, max_iterations: int, retrain_attempts: int = 2, target_accuracy: float = 0.50) -> Dict[str, Any]:
    base_dir = Path(__file__).resolve().parent
    dirs = ensure_dirs(base_dir)
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    log_handler = _setup_run_logging(dirs["logs"], run_id)

    summary_path = dirs["reports"] / f"pipeline_summary_{run_id}.json"
    compat_summary_path = dirs["models"] / "pipeline_summary.json"

    if retrain_attempts < 1:
        raise ValueError("retrain_attempts must be >= 1")

    if target_accuracy <= 0.0 or target_accuracy > 1.0:
        raise ValueError("target_accuracy must be in (0, 1]")

    try:
        final_df, coverage = prepare_dataset(base_dir=base_dir, years=years)

        training_report: Dict[str, Any] | None = None
        training_attempts: List[Dict[str, Any]] = []

        for attempt_idx in range(retrain_attempts):
            tuned_iterations = max_iterations + attempt_idx
            logger.info(
                "Training attempt %d/%d with max_iterations=%d",
                attempt_idx + 1,
                retrain_attempts,
                tuned_iterations,
            )

            attempt_report = train_with_auto_improvement(
                df=final_df,
                base_dir=base_dir,
                max_iterations=tuned_iterations,
            )
            attempt_accuracy = float(attempt_report["best_model"]["accuracy"])

            training_attempts.append(
                {
                    "attempt": int(attempt_idx + 1),
                    "max_iterations": int(tuned_iterations),
                    "best_model": attempt_report["best_model"],
                    "model": attempt_report.get("model"),
                    "report_path": attempt_report.get("report_path"),
                }
            )

            if training_report is None or attempt_accuracy > float(training_report["best_model"]["accuracy"]):
                training_report = attempt_report

            if attempt_accuracy >= target_accuracy:
                logger.info(
                    "Target accuracy %.4f reached at attempt %d (accuracy=%.6f)",
                    target_accuracy,
                    attempt_idx + 1,
                    attempt_accuracy,
                )
                break

            logger.warning(
                "Attempt %d accuracy %.6f below threshold %.4f; retrying with expanded search",
                attempt_idx + 1,
                attempt_accuracy,
                target_accuracy,
            )

        if training_report is None:
            raise RuntimeError("Training did not produce any report")

        best_accuracy = float(training_report["best_model"]["accuracy"])
        if best_accuracy < target_accuracy:
            raise RuntimeError(
                f"Best accuracy {best_accuracy:.6f} below threshold {target_accuracy:.4f} after {retrain_attempts} attempts"
            )

        summary = {
            "status": "success",
            "run_id": run_id,
            "dataset_rows": int(len(final_df)),
            "dataset_path": str(base_dir / "data" / "processed" / "final_dataset.csv"),
            "coverage_years": coverage,
            "best_accuracy": best_accuracy,
            "best_model": training_report["best_model"]["name"],
            "test_accuracy": float(training_report["test_metrics"]["accuracy"]),
            "unseen_accuracy": float(training_report["unseen_metrics"]["accuracy"]) if training_report["unseen_metrics"] else None,
            "model_path": training_report["model_path"],
            "model": training_report.get("model"),
            "report_path": training_report.get("report_path"),
            "attempts": training_attempts,
            "target_accuracy": float(target_accuracy),
            "finished_at": datetime.utcnow().isoformat() + "Z",
        }

        with summary_path.open("w", encoding="utf-8") as fp:
            json.dump(_to_serializable(summary), fp, indent=2)

        with compat_summary_path.open("w", encoding="utf-8") as fp:
            json.dump(_to_serializable(summary), fp, indent=2)

        logger.info("Pipeline summary written to %s", summary_path)
        logger.info("Compatibility summary written to %s", compat_summary_path)
        logger.info("Best accuracy (real): %s", summary["best_accuracy"])

        return summary
    except Exception as exc:
        failure = {
            "status": "failed",
            "run_id": run_id,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "failed_at": datetime.utcnow().isoformat() + "Z",
        }

        failure_path = dirs["reports"] / f"pipeline_failure_{run_id}.json"
        with failure_path.open("w", encoding="utf-8") as fp:
            json.dump(_to_serializable(failure), fp, indent=2)

        with compat_summary_path.open("w", encoding="utf-8") as fp:
            json.dump(_to_serializable(failure), fp, indent=2)

        logger.error("Pipeline failed; failure report written to %s", failure_path)
        raise
    finally:
        _teardown_run_logging(log_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="StockAI-Pro quant intraday pipeline")
    parser.add_argument("--years", type=int, default=5, help="How many years to request for intraday crawl")
    parser.add_argument("--max-iterations", type=int, default=5, help="Max auto-improvement iterations")
    parser.add_argument("--retrain-attempts", type=int, default=2, help="Retry training attempts if best accuracy is below threshold")
    parser.add_argument("--target-accuracy", type=float, default=0.50, help="Required minimum best accuracy to accept trained model")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(
        years=args.years,
        max_iterations=args.max_iterations,
        retrain_attempts=args.retrain_attempts,
        target_accuracy=args.target_accuracy,
    )
