from __future__ import annotations

import json
import logging
import os
import pickle
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_FILE_PATH = Path(__file__).resolve()
_PARENTS = _FILE_PATH.parents
BACKEND_ROOT = _PARENTS[2] if len(_PARENTS) > 2 else _FILE_PATH.parent
PROJECT_ROOT = _PARENTS[3] if len(_PARENTS) > 3 else BACKEND_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from experiments_v2.features.feature_engineering import (
        FEATURE_COLUMNS as EXPERIMENTS_FEATURE_COLUMNS,
        compute_technical_features,
    )
except Exception:
    EXPERIMENTS_FEATURE_COLUMNS = []
    compute_technical_features = None


def _iter_model_dir_candidates() -> List[Path]:
    candidates: List[Path] = []

    for env_key in ("QUANT_MODEL_DIR", "MODEL_PATH"):
        raw_value = os.getenv(env_key, "").strip()
        if raw_value:
            candidates.append(Path(raw_value))

    candidates.extend(
        [
            PROJECT_ROOT / "experiments" / "models",
            BACKEND_ROOT / "experiments" / "models",
            BACKEND_ROOT / "models",
            PROJECT_ROOT / "models",
            Path("/app/experiments/models"),
            Path("/app/models"),
        ]
    )

    deduped: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _looks_like_model_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    if any(path.glob("model_v*.pkl")):
        return True
    if (path / "latest_model.json").exists():
        return True
    if (path / "model.pkl").exists():
        return True
    return False


def _resolve_models_dir() -> Path:
    candidates = _iter_model_dir_candidates()

    for candidate in candidates:
        if _looks_like_model_dir(candidate):
            return candidate.resolve()

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()

    fallback = (BACKEND_ROOT / "models").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


MODELS_DIR = _resolve_models_dir()
LEGACY_MODEL_PATH = MODELS_DIR / "model.pkl"
LATEST_POINTER_PATH = MODELS_DIR / "latest_model.json"
MODEL_VERSION_PATTERN = re.compile(r"model_v(\d+)\.pkl$")
MIN_SIGNAL_CONFIDENCE = 0.55
LIVE_INTERVAL = os.getenv("QUANT_PREDICT_INTERVAL", "5m").strip().lower() or "5m"

_ARTIFACT: Optional[Dict[str, Any]] = None
_ARTIFACT_PATH: Optional[Path] = None
_ARTIFACT_MTIME_NS: Optional[int] = None

logger.info("[QUANT] Using model directory: %s", MODELS_DIR)


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _coerce_price(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
        if np.isfinite(number):
            return number
    except Exception:
        pass
    return fallback


def _standardize_ohlcv(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = raw_df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    mapping = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "adj close": "close",
        "volume": "volume",
    }

    values: Dict[str, pd.Series] = {}
    for source, target in mapping.items():
        if source in df.columns and target not in values:
            values[target] = df[source]

    if not {"open", "high", "low", "close", "volume"}.issubset(values.keys()):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    out = pd.DataFrame(values)
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")]
    out = out.sort_index()

    for column in ["open", "high", "low", "close", "volume"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    return out


def _compute_features(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Compute live features with the 24 stationary features contract."""
    from experiments_v2.features.feature_engineering import compute_features as cpp_compute

    working = df.copy().sort_index()
    working = working.reset_index().rename(columns={"index": "timestamp"})

    for col in ["open", "high", "low", "close", "volume"]:
        working[col] = pd.to_numeric(working[col], errors="coerce")

    working["timestamp"] = pd.to_datetime(working["timestamp"], errors="coerce")
    working["symbol"] = str(symbol).upper()
    working["timeframe"] = "5m"
    working["source_file"] = "live_yfinance"

    required_columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "symbol",
        "timeframe",
        "source_file",
    ]
    prepared = working[required_columns].dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    if prepared.empty:
        raise ValueError(f"No valid OHLCV rows for symbol {symbol}")

    engineered = cpp_compute(prepared)
    if engineered is None or engineered.empty:
        raise RuntimeError(f"Feature engineering failed to generate features for symbol {symbol}")

    engineered = engineered.sort_values("timestamp").reset_index(drop=True)
    return engineered


def _parse_model_version(path: Path) -> int:
    match = MODEL_VERSION_PATTERN.match(path.name)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return 0
    return 0


def _list_versioned_models() -> List[Tuple[int, Path]]:
    found: List[Tuple[int, Path]] = []
    for model_file in MODELS_DIR.glob("model_v*.pkl"):
        version = _parse_model_version(model_file)
        if version <= 0:
            continue
        found.append((version, model_file))
    return sorted(found, key=lambda item: item[0])


def _resolve_pointer_model_path() -> Optional[Path]:
    if not LATEST_POINTER_PATH.exists():
        return None

    try:
        payload = json.loads(LATEST_POINTER_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to parse %s: %s", LATEST_POINTER_PATH, exc)
        return None

    for key in ("model_path", "compat_model_path", "model_file"):
        value = payload.get(key)
        if not value:
            continue

        raw_candidate = Path(str(value))
        lookup_candidates: List[Path] = []

        if raw_candidate.is_absolute():
            lookup_candidates.append(raw_candidate)
        else:
            lookup_candidates.append(MODELS_DIR / raw_candidate)
            lookup_candidates.append(PROJECT_ROOT / raw_candidate)
            lookup_candidates.append(BACKEND_ROOT / raw_candidate)

        lookup_candidates.append(MODELS_DIR / raw_candidate.name)

        seen: set[str] = set()
        for candidate in lookup_candidates:
            key_name = str(candidate)
            if key_name in seen:
                continue
            seen.add(key_name)
            if candidate.exists():
                return candidate.resolve()

    return None


def _resolve_latest_model_path() -> Path:
    versioned = _list_versioned_models()
    if versioned:
        return versioned[-1][1]

    pointer_path = _resolve_pointer_model_path()
    if pointer_path and pointer_path.exists():
        return pointer_path

    if LEGACY_MODEL_PATH.exists():
        return LEGACY_MODEL_PATH

    raise FileNotFoundError(
        f"No quant model artifact found in {MODELS_DIR}. Expected model_vN.pkl or model.pkl"
    )


def _deserialize_file(path: Path) -> Any:
    try:
        return joblib.load(path)
    except Exception:
        with path.open("rb") as fp:
            return pickle.load(fp)


def _normalize_loaded_artifact(payload: Any) -> Dict[str, Any]:
    artifact: Dict[str, Any]
    if isinstance(payload, dict):
        artifact = dict(payload)
    else:
        artifact = {"model": payload}

    if "model" not in artifact and artifact.get("estimator") is not None:
        artifact["model"] = artifact.get("estimator")

    if "feature_columns" not in artifact:
        features = artifact.get("features") or artifact.get("feature_cols")
        if isinstance(features, (list, tuple)):
            artifact["feature_columns"] = list(features)

    if artifact.get("scaler") is None:
        scaler_path = MODELS_DIR / "scaler.pkl"
        if scaler_path.exists():
            artifact["scaler"] = _deserialize_file(scaler_path)

    if "feature_columns" not in artifact:
        features_path = MODELS_DIR / "features.pkl"
        if features_path.exists():
            loaded_features = _deserialize_file(features_path)
            if isinstance(loaded_features, (list, tuple)):
                artifact["feature_columns"] = list(loaded_features)

    return artifact


def _load_artifact() -> Dict[str, Any]:
    global _ARTIFACT, _ARTIFACT_MTIME_NS, _ARTIFACT_PATH

    model_path = _resolve_latest_model_path().resolve()
    mtime_ns = model_path.stat().st_mtime_ns

    if (
        _ARTIFACT is not None
        and _ARTIFACT_PATH is not None
        and _ARTIFACT_PATH.resolve() == model_path
        and _ARTIFACT_MTIME_NS == mtime_ns
    ):
        return _ARTIFACT

    payload = _deserialize_file(model_path)
    artifact = _normalize_loaded_artifact(payload)

    required = ["model", "scaler", "feature_columns"]
    missing = [key for key in required if key not in artifact]
    if missing:
        raise RuntimeError(f"Artifact {model_path} is missing required keys: {missing}")

    _ARTIFACT = artifact
    _ARTIFACT_PATH = model_path
    _ARTIFACT_MTIME_NS = mtime_ns
    logger.info("Loaded quant model artifact from %s", model_path)

    return _ARTIFACT


def _fetch_recent_15m(symbol: str) -> pd.DataFrame:
    ticker = f"{symbol}.NS"
    period = "60d"
    if LIVE_INTERVAL in {"1h", "60m"}:
        period = "730d"

    raw = yf.download(
        ticker,
        period=period,
        interval=LIVE_INTERVAL,
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    clean = _standardize_ohlcv(raw)
    if clean.empty:
        raise ValueError(f"No 15m OHLCV returned for {symbol}")
    return clean


def _decode_market_type(encoded_value: int, mapping: Dict[str, Any]) -> int:
    # mapping is persisted as string-keyed encoded->label dictionary
    if str(int(encoded_value)) in mapping:
        return int(mapping[str(int(encoded_value))])
    return int(encoded_value)


def _confidence_probability(
    model: Any, scaled_row: np.ndarray, encoded_value: int
) -> float:
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(scaled_row)[0]
        classes = getattr(model, "classes_", np.arange(len(probabilities)))
        class_to_index = {int(value): idx for idx, value in enumerate(classes)}
        selected_index = class_to_index.get(
            encoded_value, int(np.argmax(probabilities))
        )
        confidence = float(probabilities[selected_index])
    else:
        confidence = 0.0

    if not np.isfinite(confidence):
        return 0.0

    return float(max(0.0, min(1.0, confidence)))


def _signal_from_market_type(market_type: int) -> str:
    if market_type == 1:
        return "BUY"
    if market_type == -1:
        return "SELL"
    return "HOLD"


def _regime_label(market_type: int) -> str:
    if market_type == 1:
        return "Bullish"
    if market_type == -1:
        return "Bearish"
    return "Range-bound"


def _build_trade_levels(
    current_price: float, signal: str, confidence_prob: float, atr_pct: float = 0.005
) -> Tuple[float, float]:
    safe_price = max(0.0, float(current_price))
    if safe_price <= 0:
        return 0.0, 0.0

    # ATR multiplier for Stop Loss is 1.5, and for Target is 3.0
    if signal == "BUY":
        target_pct = max(0.002, 3.0 * atr_pct * confidence_prob)
        stop_pct = max(0.001, 1.5 * atr_pct * (1.0 - confidence_prob * 0.5))
        return safe_price * (1.0 + target_pct), safe_price * (1.0 - stop_pct)

    if signal == "SELL":
        target_pct = max(0.002, 3.0 * atr_pct * confidence_prob)
        stop_pct = max(0.001, 1.5 * atr_pct * (1.0 - confidence_prob * 0.5))
        return safe_price * (1.0 - target_pct), safe_price * (1.0 + stop_pct)

    return safe_price * 1.004, safe_price * 0.996


def _build_explanation(
    features: pd.Series, signal: str, confidence_pct: int, regime: str
) -> str:
    rsi = _coerce_price(features.get("rsi_14"), np.nan)
    macd_hist = _coerce_price(features.get("macd_hist_pct"), np.nan)
    ema_ratio = _coerce_price(features.get("ema_9_21_ratio"), np.nan)

    if np.isfinite(rsi):
        rsi_text = f"RSI={rsi:.1f}"
    else:
        rsi_text = "RSI unavailable"

    if np.isfinite(macd_hist):
        macd_text = f"MACD Hist%={macd_hist:.3f}%"
    else:
        macd_text = "MACD Hist% unavailable"

    if np.isfinite(ema_ratio):
        ema_text = f"EMA 9/21 Ratio={ema_ratio:.3f}"
    else:
        ema_text = "EMA Ratio unavailable"

    direction = "neutral"
    if signal == "BUY":
        direction = "upside"
    elif signal == "SELL":
        direction = "downside"

    return (
        f"{regime} regime with {rsi_text}, {macd_text}, {ema_text}. "
        f"Model sees {direction} bias ({confidence_pct}% confidence)."
    )


def _hold_fallback(
    symbol: str, reason: str = "Prediction unavailable", current_price: float = 0.0
) -> Dict[str, Any]:
    target, stop = _build_trade_levels(current_price, "HOLD", 0.0, 0.005)
    return {
        "symbol": symbol,
        "signal": "HOLD",
        "confidence": 0,
        "prediction": round(current_price, 2),
        "currentPrice": round(current_price, 2),
        "target_price": round(target, 2),
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "stopLoss": round(stop, 2),
        "regime": "Unknown",
        "explanation": reason,
        "model_version": 0,
        "timestamp": _utc_now_iso(),
    }


def _normalize_feature_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _align_feature_columns(
    features: pd.DataFrame, feature_columns: List[str]
) -> pd.DataFrame:
    """Build a compatibility frame that always matches model feature columns.

    Missing features are backfilled with 0.0 to avoid runtime crashes when
    minor training/live schema drift exists.
    """
    if features.empty:
        return pd.DataFrame(columns=feature_columns)

    lookup_exact = {str(col): col for col in features.columns}
    lookup_norm = {_normalize_feature_key(str(col)): col for col in features.columns}

    aligned = pd.DataFrame(index=features.index)
    for expected in feature_columns:
        if expected in lookup_exact:
            aligned[expected] = features[lookup_exact[expected]]
            continue

        norm_key = _normalize_feature_key(expected)
        alias_col = lookup_norm.get(norm_key)
        if alias_col is not None:
            aligned[expected] = features[alias_col]
            continue

        aligned[expected] = 0.0

    return aligned.fillna(0.0)


def predict_signal(symbol: str) -> Dict[str, Any]:
    normalized_symbol = symbol.strip().upper()

    try:
        artifact = _load_artifact()
        model = artifact["model"]
        scaler = artifact["scaler"]
        feature_columns = artifact["feature_columns"]
        label_mapping = artifact.get("label_mapping", {"0": -1, "1": 0, "2": 1})

        df = _fetch_recent_15m(normalized_symbol)
        features = _compute_features(df, symbol=normalized_symbol)
        if features.empty:
            raise ValueError(
                f"Feature generation produced empty frame for {normalized_symbol}"
            )

        aligned_features = _align_feature_columns(features, feature_columns)
        latest_features = aligned_features.iloc[-1]
        latest_vector = (
            latest_features[feature_columns].astype(float).values.reshape(1, -1)
        )
        if not np.isfinite(latest_vector).all():
            raise ValueError("Live feature vector contains non-finite values")

        scaled = scaler.transform(latest_vector)

        pred_encoded = int(model.predict(scaled)[0])
        market_type = _decode_market_type(pred_encoded, label_mapping)
        confidence_prob = _confidence_probability(model, scaled, pred_encoded)

        signal = _signal_from_market_type(market_type)
        if confidence_prob < MIN_SIGNAL_CONFIDENCE:
            signal = "HOLD"

        current_price = _coerce_price(
            latest_features.get("close"), _coerce_price(df["close"].iloc[-1], 0.0)
        )
        atr_val = latest_features.get("atr_pct")
        atr_pct = float(atr_val) / 100.0 if atr_val is not None else 0.005
        if atr_pct <= 0.0:
            atr_pct = 0.005
        target_price, stop_loss = _build_trade_levels(
            current_price, signal, confidence_prob, atr_pct
        )

        confidence_pct = int(round(confidence_prob * 100.0))
        regime = _regime_label(market_type)
        explanation = _build_explanation(
            latest_features, signal, confidence_pct, regime
        )

        model_path = _ARTIFACT_PATH or LEGACY_MODEL_PATH
        model_version = _parse_model_version(model_path)

        return {
            "symbol": normalized_symbol,
            "signal": signal,
            "confidence": confidence_pct,
            "prediction": round(current_price, 2),
            "currentPrice": round(current_price, 2),
            "target_price": round(target_price, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target_price, 2),
            "stopLoss": round(stop_loss, 2),
            "regime": regime,
            "explanation": explanation,
            "model_version": int(model_version),
            "model_file": model_path.name,
            "timestamp": _utc_now_iso(),
        }
    except Exception as exc:
        logger.error("Quant path prediction failed for %s: %s", normalized_symbol, exc)
        return _hold_fallback(normalized_symbol, reason=f"HOLD fallback: {exc}")
