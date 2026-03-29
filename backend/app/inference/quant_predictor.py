from __future__ import annotations

import json
import logging
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_ROOT / "experiments" / "models"
LEGACY_MODEL_PATH = MODELS_DIR / "model.pkl"
LATEST_POINTER_PATH = MODELS_DIR / "latest_model.json"
MODEL_VERSION_PATTERN = re.compile(r"model_v(\d+)\.pkl$")
MIN_SIGNAL_CONFIDENCE = 0.55

_ARTIFACT: Optional[Dict[str, Any]] = None
_ARTIFACT_PATH: Optional[Path] = None
_ARTIFACT_MTIME_NS: Optional[int] = None


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["returns"] = out["close"].pct_change()

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
    typical_price = (out["high"] + out["low"] + out["close"]) / 3.0
    cumulative_volume = out["volume"].groupby(session).cumsum()
    cumulative_tpv = (typical_price * out["volume"]).groupby(session).cumsum()
    out["vwap"] = cumulative_tpv / cumulative_volume.replace(0, np.nan)

    out["volatility"] = out["returns"].rolling(20).std()
    out["price_change_pct"] = out["close"].pct_change(20)
    out["rolling_volatility"] = out["returns"].rolling(20).std()
    out["higher_high_ratio"] = out["high"].diff().gt(0).rolling(20).mean()
    out["lower_low_ratio"] = out["low"].diff().lt(0).rolling(20).mean()

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.dropna(inplace=True)
    return out


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

        candidate = Path(str(value))
        if not candidate.is_absolute():
            candidate = MODELS_DIR / candidate

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

    with model_path.open("rb") as fp:
        artifact = pickle.load(fp)

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
    raw = yf.download(
        ticker,
        period="60d",
        interval="15m",
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


def _confidence_probability(model: Any, scaled_row: np.ndarray, encoded_value: int) -> float:
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(scaled_row)[0]
        classes = getattr(model, "classes_", np.arange(len(probabilities)))
        class_to_index = {int(value): idx for idx, value in enumerate(classes)}
        selected_index = class_to_index.get(encoded_value, int(np.argmax(probabilities)))
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


def _build_trade_levels(current_price: float, signal: str, confidence_prob: float) -> Tuple[float, float]:
    safe_price = max(0.0, float(current_price))
    if safe_price <= 0:
        return 0.0, 0.0

    if signal == "BUY":
        target_pct = 0.005 + (confidence_prob * 0.006)
        stop_pct = 0.003 + ((1.0 - confidence_prob) * 0.004)
        return safe_price * (1.0 + target_pct), safe_price * (1.0 - stop_pct)

    if signal == "SELL":
        target_pct = 0.005 + (confidence_prob * 0.006)
        stop_pct = 0.003 + ((1.0 - confidence_prob) * 0.004)
        return safe_price * (1.0 - target_pct), safe_price * (1.0 + stop_pct)

    return safe_price * 1.004, safe_price * 0.996


def _build_explanation(features: pd.Series, signal: str, confidence_pct: int, regime: str) -> str:
    rsi = _coerce_price(features.get("rsi"), np.nan)
    macd = _coerce_price(features.get("macd"), np.nan)
    ema_20 = _coerce_price(features.get("ema_20"), np.nan)
    ema_50 = _coerce_price(features.get("ema_50"), np.nan)

    if np.isfinite(rsi):
        rsi_text = f"RSI={rsi:.1f}"
    else:
        rsi_text = "RSI unavailable"

    if np.isfinite(macd):
        macd_text = "MACD positive" if macd >= 0 else "MACD negative"
    else:
        macd_text = "MACD unavailable"

    if np.isfinite(ema_20) and np.isfinite(ema_50):
        ema_text = "EMA20 above EMA50" if ema_20 >= ema_50 else "EMA20 below EMA50"
    else:
        ema_text = "EMA trend unavailable"

    direction = "neutral"
    if signal == "BUY":
        direction = "upside"
    elif signal == "SELL":
        direction = "downside"

    return f"{regime} regime with {rsi_text}, {macd_text}, {ema_text}. Model sees {direction} bias ({confidence_pct}% confidence)."


def _hold_fallback(symbol: str, reason: str = "Prediction unavailable", current_price: float = 0.0) -> Dict[str, Any]:
    target, stop = _build_trade_levels(current_price, "HOLD", 0.0)
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


def predict_signal(symbol: str) -> Dict[str, Any]:
    normalized_symbol = symbol.strip().upper()

    try:
        artifact = _load_artifact()
        model = artifact["model"]
        scaler = artifact["scaler"]
        feature_columns = artifact["feature_columns"]
        label_mapping = artifact.get("label_mapping", {"0": -1, "1": 0, "2": 1})

        df = _fetch_recent_15m(normalized_symbol)
        features = _compute_features(df)
        if features.empty:
            raise ValueError(f"Feature generation produced empty frame for {normalized_symbol}")

        missing_feature_cols = [col for col in feature_columns if col not in features.columns]
        if missing_feature_cols:
            raise ValueError(f"Missing feature columns in live data: {missing_feature_cols}")

        latest_features = features.iloc[-1]
        latest_vector = latest_features[feature_columns].astype(float).values.reshape(1, -1)
        if not np.isfinite(latest_vector).all():
            raise ValueError("Live feature vector contains non-finite values")

        scaled = scaler.transform(latest_vector)

        pred_encoded = int(model.predict(scaled)[0])
        market_type = _decode_market_type(pred_encoded, label_mapping)
        confidence_prob = _confidence_probability(model, scaled, pred_encoded)

        signal = _signal_from_market_type(market_type)
        if confidence_prob < MIN_SIGNAL_CONFIDENCE:
            signal = "HOLD"

        current_price = _coerce_price(latest_features.get("close"), _coerce_price(df["close"].iloc[-1], 0.0))
        target_price, stop_loss = _build_trade_levels(current_price, signal, confidence_prob)

        confidence_pct = int(round(confidence_prob * 100.0))
        regime = _regime_label(market_type)
        explanation = _build_explanation(latest_features, signal, confidence_pct, regime)

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
