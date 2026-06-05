from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from sklearn.preprocessing import StandardScaler

try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.inference.feature_engineering import (  # type: ignore
    FEATURE_COLUMNS as BACKEND_FEATURE_COLUMNS,
    compute_base_features,
    finalize_feature_matrix,
)
from app.inference.feature_engineering import FEATURE_VERSION as BACKEND_FEATURE_VERSION  # type: ignore
from app.inference.feature_contract import validate_feature_contract  # type: ignore
from app.inference.dataset_validation import validate_and_clean_feature_rows, validate_and_clean_ohlcv  # type: ignore

LOGGER = logging.getLogger("experiments_v2.training")

TIMEFRAME_VALUES = ("1m", "5m", "1h")
REQUIRED_OHLCV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
ALLOWED_READ_COLUMNS = {
    "timestamp",
    "datetime",
    "date",
    "time",
    "symbol",
    "ticker",
    "timeframe",
    "tf",
    "interval",
    "open",
    "high",
    "low",
    "close",
    "volume",
}

COLUMN_ALIASES = {
    "datetime": "timestamp",
    "date": "timestamp",
    "time": "timestamp",
    "ticker": "symbol",
    "tf": "timeframe",
    "interval": "timeframe",
}

TIMEFRAME_PATTERN = re.compile(r"(?<!\w)(1m|5m|1h)(?!\w)", re.IGNORECASE)

CLASS_TO_ENCODED = {-1: 0, 0: 1, 1: 2}
ENCODED_TO_CLASS = {value: key for key, value in CLASS_TO_ENCODED.items()}


def setup_logging(level: str = "INFO") -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


@dataclass
class PipelineConfig:
    timeframe: str
    raw_dir: Path | None = None
    models_root: Path | None = None
    horizon: int = 5
    up_return_threshold: float = 0.002
    down_return_threshold: float = 0.002
    hold_confidence_threshold: float = 0.65
    test_fraction: float = 0.20
    n_estimators: int = 420
    max_depth: int = 6
    learning_rate: float = 0.05
    subsample: float = 0.90
    colsample_bytree: float = 0.90
    random_state: int = 42
    max_files: int | None = None
    max_rows_per_symbol: int | None = None
    chunksize: int | None = None
    min_rows_per_symbol: int = 300
    symbol_allowlist: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        self.timeframe = str(self.timeframe).strip().lower()
        if self.timeframe not in TIMEFRAME_VALUES:
            raise ValueError(f"Unsupported timeframe: {self.timeframe}")

        if self.horizon < 1:
            raise ValueError("horizon must be >= 1")

        self.test_fraction = float(np.clip(self.test_fraction, 0.05, 0.50))
        self.hold_confidence_threshold = float(
            np.clip(self.hold_confidence_threshold, 0.50, 0.95)
        )


def resolve_raw_directory(raw_dir: Path | str | None = None) -> Path:
    if raw_dir is not None:
        candidate = Path(raw_dir)
        if not candidate.exists():
            raise FileNotFoundError(f"Raw directory not found: {candidate}")
        return candidate

    candidates = [
        REPO_ROOT / "experiments_v2" / "raw",
        REPO_ROOT / "experiments_v2" / "data" / "raw",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        "No raw directory found. Expected experiments_v2/raw or experiments_v2/data/raw."
    )


def resolve_models_root(models_root: Path | str | None = None) -> Path:
    root = Path(models_root) if models_root is not None else REPO_ROOT / "experiments_v2" / "models"
    root.mkdir(parents=True, exist_ok=True)
    return root


def infer_timeframe_from_path(csv_path: Path) -> str | None:
    for part in csv_path.parts:
        token = str(part).strip().lower()
        if token in TIMEFRAME_VALUES:
            return token

    match = TIMEFRAME_PATTERN.search(csv_path.stem)
    if match:
        return str(match.group(1)).lower()
    return None


def infer_symbol_from_path(csv_path: Path) -> str:
    symbol = csv_path.stem.upper()
    symbol = re.sub(r"[-_]EQ$", "", symbol, flags=re.IGNORECASE)
    symbol = re.sub(r"[-_]RAW$", "", symbol, flags=re.IGNORECASE)
    symbol = re.sub(r"[-_](1M|5M|1H)$", "", symbol, flags=re.IGNORECASE)
    return symbol.strip() or "UNKNOWN"


def discover_csv_files_by_timeframe(raw_dir: Path) -> dict[str, list[Path]]:
    grouped = {timeframe: [] for timeframe in TIMEFRAME_VALUES}
    for csv_path in sorted(raw_dir.rglob("*.csv")):
        timeframe = infer_timeframe_from_path(csv_path)
        if timeframe in grouped:
            grouped[timeframe].append(csv_path)
    return grouped


def _rename_columns(frame: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in frame.columns:
        token = str(col).strip().lower()
        rename_map[col] = COLUMN_ALIASES.get(token, token)
    return frame.rename(columns=rename_map)


def _to_kolkata_timestamps(timestamp_series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(timestamp_series, errors="coerce")
    if parsed.dt.tz is None:
        return parsed.dt.tz_localize("Asia/Kolkata", nonexistent="shift_forward", ambiguous="NaT")
    return parsed.dt.tz_convert("Asia/Kolkata")


def _filter_indian_market_hours(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    minute_of_day = (out["timestamp"].dt.hour * 60 + out["timestamp"].dt.minute).astype(int)
    in_session = minute_of_day.between(9 * 60 + 15, 15 * 60 + 30)
    on_weekday = out["timestamp"].dt.dayofweek < 5
    return out[in_session & on_weekday].copy()


def _normalize_ohlcv_frame(
    frame: pd.DataFrame,
    csv_path: Path,
    timeframe_hint: str,
) -> pd.DataFrame:
    out = _rename_columns(frame)

    missing = sorted(col for col in REQUIRED_OHLCV_COLUMNS if col not in out.columns)
    if missing:
        raise ValueError(
            f"CSV {csv_path} missing required columns: {missing}. "
            "Expected timestamp/open/high/low/close/volume."
        )

    out = out[list(REQUIRED_OHLCV_COLUMNS) + [col for col in ["symbol", "timeframe"] if col in out.columns]].copy()
    out["timestamp"] = _to_kolkata_timestamps(out["timestamp"])

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    symbol_hint = infer_symbol_from_path(csv_path)
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str).str.upper().str.strip().replace("", symbol_hint)
    else:
        out["symbol"] = symbol_hint

    if "timeframe" in out.columns:
        out["timeframe"] = out["timeframe"].astype(str).str.lower().str.strip()
        invalid_mask = ~out["timeframe"].isin(TIMEFRAME_VALUES)
        out.loc[invalid_mask, "timeframe"] = timeframe_hint
    else:
        out["timeframe"] = timeframe_hint

    out["source_file"] = csv_path.name

    out = out.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    out = _filter_indian_market_hours(out)

    out = out.sort_values("timestamp").drop_duplicates(subset=["symbol", "timestamp"], keep="last")
    if out.empty:
        return out

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = out[col].astype("float32")

    return out.reset_index(drop=True)


def _read_csv_with_optional_chunks(
    csv_path: Path,
    timeframe_hint: str,
    chunksize: int | None = None,
) -> pd.DataFrame:
    usecols = lambda col: str(col).strip().lower() in ALLOWED_READ_COLUMNS

    if chunksize is None or chunksize <= 0:
        frame = pd.read_csv(csv_path, usecols=usecols, low_memory=False)
        return _normalize_ohlcv_frame(frame, csv_path=csv_path, timeframe_hint=timeframe_hint)

    chunks: list[pd.DataFrame] = []
    iterator = pd.read_csv(
        csv_path,
        usecols=usecols,
        low_memory=False,
        chunksize=int(chunksize),
    )
    for chunk in iterator:
        normalized = _normalize_ohlcv_frame(chunk, csv_path=csv_path, timeframe_hint=timeframe_hint)
        if not normalized.empty:
            chunks.append(normalized)

    if not chunks:
        return pd.DataFrame(columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "symbol",
            "timeframe",
            "source_file",
        ])

    return pd.concat(chunks, ignore_index=True, copy=False)


def load_timeframe_ohlcv(config: PipelineConfig) -> pd.DataFrame:
    raw_dir = resolve_raw_directory(config.raw_dir)
    grouped = discover_csv_files_by_timeframe(raw_dir)
    timeframe_files = list(grouped.get(config.timeframe, []))

    if config.max_files is not None and config.max_files > 0:
        timeframe_files = timeframe_files[: int(config.max_files)]

    if not timeframe_files:
        raise FileNotFoundError(
            f"No CSV files found for timeframe {config.timeframe} under {raw_dir}."
        )

    symbol_allowlist = None
    if config.symbol_allowlist:
        symbol_allowlist = {token.upper().strip() for token in config.symbol_allowlist if str(token).strip()}

    frames: list[pd.DataFrame] = []
    errors: list[str] = []

    for csv_path in timeframe_files:
        try:
            frame = _read_csv_with_optional_chunks(
                csv_path=csv_path,
                timeframe_hint=config.timeframe,
                chunksize=config.chunksize,
            )
            if frame.empty:
                continue

            if symbol_allowlist is not None:
                frame = frame[frame["symbol"].isin(symbol_allowlist)].copy()

            if frame.empty:
                continue

            if config.max_rows_per_symbol is not None and config.max_rows_per_symbol > 0:
                frame = (
                    frame.sort_values(["symbol", "timestamp"])
                    .groupby("symbol", sort=False, group_keys=False)
                    .tail(int(config.max_rows_per_symbol))
                    .reset_index(drop=True)
                )

            frames.append(frame)
        except Exception as exc:
            errors.append(f"{csv_path.name}: {exc}")

    if not frames:
        preview = "; ".join(errors[:5])
        raise RuntimeError(f"Failed to load any CSV file for timeframe {config.timeframe}. {preview}")

    merged = pd.concat(frames, ignore_index=True, copy=False)
    merged = merged.sort_values(["symbol", "timestamp"]).drop_duplicates(
        subset=["symbol", "timestamp"],
        keep="last",
    )

    # Filter out symbols with insufficient bars for robust rolling indicators.
    counts = merged.groupby("symbol")["timestamp"].transform("count")
    merged = merged[counts >= int(config.min_rows_per_symbol)].copy()

    if merged.empty:
        raise RuntimeError(
            f"No symbols have >= {config.min_rows_per_symbol} rows for timeframe {config.timeframe}."
        )

    return merged.reset_index(drop=True)


def build_backend_feature_frame(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(ohlcv_df.columns))
    if missing:
        raise ValueError(f"OHLCV frame missing required columns: {missing}")

    cleaned_ohlcv, quality = validate_and_clean_ohlcv(ohlcv_df, timeframe=str(ohlcv_df["timeframe"].iloc[0]))
    LOGGER.info("[PIPELINE] OHLCV validation report: %s", quality.as_dict())

    feature_frame = compute_base_features(cleaned_ohlcv)
    if feature_frame.empty:
        return pd.DataFrame()

    feature_frame = finalize_feature_matrix(feature_frame, BACKEND_FEATURE_COLUMNS)
    feature_frame, feature_quality = validate_and_clean_feature_rows(
        feature_frame,
        BACKEND_FEATURE_COLUMNS,
        timeframe=str(cleaned_ohlcv["timeframe"].iloc[0]),
    )
    LOGGER.info("[PIPELINE] Feature validation report: %s", feature_quality.as_dict())
    validate_feature_contract(feature_frame[BACKEND_FEATURE_COLUMNS], BACKEND_FEATURE_COLUMNS, context="experiments_v2")
    return feature_frame


def ensure_feature_matrix(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    if not feature_columns:
        raise ValueError("No feature columns were supplied.")

    out = frame.copy()
    for col in feature_columns:
        if col not in out.columns:
            out[col] = 0.0

    matrix = out[feature_columns].copy()
    matrix = matrix.apply(pd.to_numeric, errors="coerce")
    matrix = matrix.replace([np.inf, -np.inf], np.nan)
    matrix = matrix.dropna().copy()
    validate_feature_contract(matrix, feature_columns, context="ensure_feature_matrix")
    return matrix


def build_three_class_targets(
    frame: pd.DataFrame,
    horizon: int,
    up_return_threshold: float,
    down_return_threshold: float,
) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []

    for _, group in frame.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").copy()
        future_close = g["close"].shift(-int(horizon))
        future_return = (future_close / g["close"]) - 1.0

        g["future_return"] = future_return
        g["target_class"] = np.select(
            [future_return >= up_return_threshold, future_return <= -down_return_threshold],
            [1, -1],
            default=0,
        ).astype(int)

        g = g.iloc[:-int(horizon)] if horizon > 0 else g
        g = g.dropna(subset=["future_return"])
        if not g.empty:
            blocks.append(g)

    if not blocks:
        return pd.DataFrame()

    out = pd.concat(blocks, ignore_index=True, copy=False)
    out = out.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return out


def split_train_test(
    X: pd.DataFrame,
    y: pd.Series,
    test_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    if len(X) != len(y):
        raise ValueError("Feature matrix and labels have different lengths.")
    if len(X) < 20:
        raise ValueError("Need at least 20 samples for a stable train/test split.")

    split_index = int(len(X) * (1.0 - test_fraction))
    split_index = max(1, min(len(X) - 1, split_index))

    X_train = X.iloc[:split_index].copy()
    X_test = X.iloc[split_index:].copy()
    y_train = y.iloc[:split_index].copy()
    y_test = y.iloc[split_index:].copy()
    return X_train, X_test, y_train, y_test


def encode_labels(labels: pd.Series) -> pd.Series:
    encoded = labels.map(CLASS_TO_ENCODED)
    if encoded.isna().any():
        bad = sorted(labels[encoded.isna()].unique().tolist())
        raise RuntimeError(f"Unsupported target labels found: {bad}")
    return encoded.astype(int)


def decode_labels(encoded_labels: np.ndarray) -> np.ndarray:
    mapper = np.vectorize(lambda value: ENCODED_TO_CLASS.get(int(value), 0))
    return mapper(encoded_labels).astype(int)


def _compute_sample_weights(encoded_labels: np.ndarray) -> np.ndarray:
    counts = np.bincount(encoded_labels, minlength=3).astype(float)
    counts[counts == 0] = 1.0
    total = counts.sum()
    class_weights = total / (len(counts) * counts)
    return np.array([class_weights[label] for label in encoded_labels], dtype=np.float32)


def train_xgboost_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: PipelineConfig,
) -> tuple[Any, StandardScaler]:
    if XGBClassifier is None:
        raise RuntimeError("xgboost is not installed. Install xgboost>=2.0.0.")

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_train_scaled = np.nan_to_num(X_train_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    y_train_encoded = encode_labels(y_train).to_numpy(dtype=int)
    sample_weights = _compute_sample_weights(y_train_encoded)

    model = XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        n_estimators=int(config.n_estimators),
        max_depth=int(config.max_depth),
        learning_rate=float(config.learning_rate),
        subsample=float(config.subsample),
        colsample_bytree=float(config.colsample_bytree),
        random_state=int(config.random_state),
        n_jobs=-1,
        tree_method="hist",
    )
    model.fit(X_train_scaled, y_train_encoded, sample_weight=sample_weights)
    return model, scaler


def predict_with_hold_threshold(
    model: Any,
    scaler: StandardScaler,
    X: pd.DataFrame,
    hold_confidence_threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X_scaled = scaler.transform(X)
    X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    probabilities = model.predict_proba(X_scaled)
    probabilities = np.asarray(probabilities, dtype=np.float32)

    if probabilities.ndim != 2 or probabilities.shape[1] < 3:
        raise RuntimeError("Model predict_proba must return [n_samples, 3] for SELL/HOLD/BUY.")

    encoded_pred = probabilities.argmax(axis=1).astype(int)
    confidence = probabilities.max(axis=1)

    hold_encoded = CLASS_TO_ENCODED[0]
    encoded_pred[confidence < float(hold_confidence_threshold)] = hold_encoded

    decoded_pred = decode_labels(encoded_pred)
    return decoded_pred, confidence, probabilities


def evaluate_predictions(
    y_true: pd.Series,
    y_pred: np.ndarray,
    confidence: np.ndarray,
) -> dict[str, Any]:
    labels = [-1, 0, 1]
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=["SELL", "HOLD", "BUY"],
        output_dict=True,
        zero_division=0,
    )

    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "hold_rate": float(np.mean(np.asarray(y_pred) == 0)),
        "confidence_mean": float(np.mean(confidence)),
        "confidence_p25": float(np.quantile(confidence, 0.25)),
        "confidence_p50": float(np.quantile(confidence, 0.50)),
        "confidence_p75": float(np.quantile(confidence, 0.75)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": _to_native(report),
    }
    return metrics


def load_model_payload(model_dir: Path) -> dict[str, Any] | None:
    model_path = model_dir / "model.pkl"
    if not model_path.exists():
        return None

    payload = joblib.load(model_path)
    if not isinstance(payload, dict):
        return None
    return payload


def merge_asof_by_symbol(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    right_columns: list[str],
    fill_value: float = 0.0,
) -> pd.DataFrame:
    required_left = {"timestamp", "symbol"}
    required_right = {"timestamp", "symbol", *right_columns}

    left_missing = sorted(required_left - set(left_frame.columns))
    if left_missing:
        raise ValueError(f"Left frame missing required columns: {left_missing}")

    right_missing = sorted(required_right - set(right_frame.columns))
    if right_missing:
        raise ValueError(f"Right frame missing required columns: {right_missing}")

    merged_blocks: list[pd.DataFrame] = []
    for symbol, left_group in left_frame.groupby("symbol", sort=False):
        left_sorted = left_group.sort_values("timestamp").copy()
        right_sorted = right_frame[right_frame["symbol"] == symbol].sort_values("timestamp").copy()

        if right_sorted.empty:
            for column in right_columns:
                left_sorted[column] = fill_value
            merged_blocks.append(left_sorted)
            continue

        joined = pd.merge_asof(
            left_sorted,
            right_sorted[["timestamp", *right_columns]],
            on="timestamp",
            direction="backward",
            allow_exact_matches=True,
        )
        joined["symbol"] = symbol
        for column in right_columns:
            joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(fill_value)
        merged_blocks.append(joined)

    if not merged_blocks:
        return left_frame.copy()

    out = pd.concat(merged_blocks, ignore_index=True, copy=False)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out


def save_pipeline_artifacts(
    model: Any,
    scaler: StandardScaler,
    feature_columns: list[str],
    model_dir: Path,
    config: PipelineConfig,
    metrics: dict[str, Any],
    train_rows: int,
    test_rows: int,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    model_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "model": model,
        "scaler": scaler,
        "features": feature_columns,
        "version": BACKEND_FEATURE_VERSION,
        "timeframe": config.timeframe,
        "hold_confidence_threshold": config.hold_confidence_threshold,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    model_path = model_dir / "model.pkl"
    xgb_path = model_dir / "xgb_model.pkl"
    scaler_path = model_dir / "scaler.pkl"
    features_path = model_dir / "features.pkl"
    metadata_path = model_dir / "metadata.json"

    joblib.dump(payload, model_path)
    joblib.dump(model, xgb_path)
    joblib.dump(scaler, scaler_path)
    joblib.dump(feature_columns, features_path)

    metadata: dict[str, Any] = {
        "timeframe": config.timeframe,
        "feature_version": BACKEND_FEATURE_VERSION,
        "feature_columns": feature_columns,
        "backend_canonical_feature_columns": list(BACKEND_FEATURE_COLUMNS),
        "hold_confidence_threshold": config.hold_confidence_threshold,
        "horizon": config.horizon,
        "up_return_threshold": config.up_return_threshold,
        "down_return_threshold": config.down_return_threshold,
        "train_rows": int(train_rows),
        "test_rows": int(test_rows),
        "metrics": metrics,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    metadata_path.write_text(json.dumps(_to_native(metadata), indent=2), encoding="utf-8")

    return {
        "model": str(model_path),
        "xgb_model": str(xgb_path),
        "scaler": str(scaler_path),
        "features": str(features_path),
        "metadata": str(metadata_path),
    }


class BaseTrainingPipeline:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.raw_dir = resolve_raw_directory(config.raw_dir)
        self.models_root = resolve_models_root(config.models_root)
        self.model_dir = self.models_root / config.timeframe
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.feature_columns: list[str] = []

    def engineer_features(self, frame: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def select_feature_columns(self, frame: pd.DataFrame) -> list[str]:
        raise NotImplementedError

    def extra_metadata(self) -> dict[str, Any]:
        return {}

    def load_timeframe_data(self) -> pd.DataFrame:
        return load_timeframe_ohlcv(self.config)

    def run(self) -> dict[str, Any]:
        setup_logging()

        LOGGER.info("[PIPELINE] Loading %s OHLCV from %s", self.config.timeframe, self.raw_dir)
        ohlcv_df = self.load_timeframe_data()
        LOGGER.info("[PIPELINE] Loaded %d OHLCV rows", len(ohlcv_df))

        base_feature_df = build_backend_feature_frame(ohlcv_df)
        if base_feature_df.empty:
            raise RuntimeError("Base feature generation returned empty frame.")
        LOGGER.info("[PIPELINE] Base feature frame rows=%d", len(base_feature_df))

        engineered_df = self.engineer_features(base_feature_df)
        if engineered_df.empty:
            raise RuntimeError("Timeframe-specific feature engineering returned empty frame.")

        self.feature_columns = list(dict.fromkeys(self.select_feature_columns(engineered_df)))
        if not self.feature_columns:
            raise RuntimeError("No model feature columns were selected.")
        LOGGER.info("[PIPELINE] Training with %d features", len(self.feature_columns))

        labeled_df = build_three_class_targets(
            engineered_df,
            horizon=self.config.horizon,
            up_return_threshold=self.config.up_return_threshold,
            down_return_threshold=self.config.down_return_threshold,
        )
        if labeled_df.empty:
            raise RuntimeError("Label generation returned empty dataset.")
        LOGGER.info("[PIPELINE] Labeled rows=%d", len(labeled_df))

        feature_matrix = ensure_feature_matrix(labeled_df, self.feature_columns)
        targets = labeled_df["target_class"].astype(int)

        X_train, X_test, y_train, y_test = split_train_test(
            feature_matrix,
            targets,
            test_fraction=self.config.test_fraction,
        )

        model, scaler = train_xgboost_model(X_train, y_train, self.config)
        y_pred, confidence, _ = predict_with_hold_threshold(
            model,
            scaler,
            X_test,
            hold_confidence_threshold=self.config.hold_confidence_threshold,
        )

        metrics = evaluate_predictions(y_true=y_test, y_pred=y_pred, confidence=confidence)
        artifacts = save_pipeline_artifacts(
            model=model,
            scaler=scaler,
            feature_columns=self.feature_columns,
            model_dir=self.model_dir,
            config=self.config,
            metrics=metrics,
            train_rows=len(X_train),
            test_rows=len(X_test),
            extra_metadata=self.extra_metadata(),
        )

        result = {
            "timeframe": self.config.timeframe,
            "rows_ohlcv": int(len(ohlcv_df)),
            "rows_features": int(len(engineered_df)),
            "rows_labeled": int(len(labeled_df)),
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
            "feature_count": int(len(self.feature_columns)),
            "label_distribution": {
                str(key): int(value)
                for key, value in labeled_df["target_class"].value_counts().sort_index().to_dict().items()
            },
            "metrics": metrics,
            "artifacts": artifacts,
        }

        LOGGER.info(
            "[PIPELINE] %s complete. accuracy=%.4f f1_macro=%.4f",
            self.config.timeframe,
            result["metrics"]["accuracy"],
            result["metrics"]["f1_macro"],
        )

        return _to_native(result)
