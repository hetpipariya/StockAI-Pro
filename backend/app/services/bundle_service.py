from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from app import config
from app.connectors import SmartAPIConnector, get_symbol_token, get_tradingsymbol
from app.inference.runner import PredictionResult, predict_symbol
from app.services.candle_store import get_candles, get_last_candle, store_candles
from app.services.db import PredictionModel, async_session
from app.services.indicators import IndicatorEngine
from app.services.instrument_master import get_token
from app.services.market_state import get_market_status as _raw_market_status
from app.services.redis_client import get_cache, set_cache

logger = logging.getLogger(__name__)

# Bundle-specific cache profile for low-latency UI refreshes.
HISTORY_CACHE_TTL_SECONDS = 10
SNAPSHOT_CACHE_TTL_SECONDS = 3
PREDICTION_CACHE_TTL_SECONDS = 5

# Guardrails for low-latency bundle responses under partial outages.
DB_READ_TIMEOUT_SECONDS = 0.12
SNAPSHOT_LIVE_TIMEOUT_SECONDS = 1.25
HISTORY_LIVE_TIMEOUT_SECONDS = 2.0
PREDICTION_TIMEOUT_SECONDS = 1.0
CONNECTOR_COOLDOWN_SECONDS = 60.0
MIN_CANDLES_FOR_FEATURES = 50
MIN_CANDLES_FOR_BUNDLE = 100

YF_INTERVAL_MAP = {
    "1m": "1m",
    "3m": "5m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "1d": "1d",
}

YF_PERIOD_BY_INTERVAL = {
    "1m": "7d",
    "3m": "30d",
    "5m": "30d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "1d": "5y",
}

YF_INDEX_SYMBOLS = {
    "NIFTY": "^NSEI",
    "NIFTY 50": "^NSEI",
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTY BANK": "^NSEBANK",
}

# Connector singleton.
_connector: SmartAPIConnector | None = None
_connector_blocked_until: float = 0.0


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_confidence_score(value: Any) -> float:
    raw = _to_float(value, 0.0)
    if raw > 1.0:
        raw = raw / 100.0
    return float(np.clip(raw, 0.0, 1.0))


def _normalize_signed_score(value: Any) -> float:
    return float(np.clip(_to_float(value, 0.0), -1.0, 1.0))


def _normalize_signal_ternary(value: Any) -> int:
    raw = _to_float(value, 0.0)
    if raw > 0:
        return 1
    if raw < 0:
        return -1
    return 0


def _is_valid_candle(candle: dict[str, Any]) -> bool:
    if not isinstance(candle, dict):
        return False

    required = ["time", "open", "high", "low", "close"]
    for key in required:
        if candle.get(key) is None:
            return False

    o = _to_float(candle.get("open"), -1.0)
    h = _to_float(candle.get("high"), -1.0)
    l = _to_float(candle.get("low"), -1.0)
    c = _to_float(candle.get("close"), -1.0)
    v = _to_float(candle.get("volume", 0.0), -1.0)

    if o <= 0 or h <= 0 or l <= 0 or c <= 0:
        return False
    if h < l:
        return False
    if v < 0:
        return False

    return True


def _sanitize_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    dropped = 0

    for candle in candles:
        if not _is_valid_candle(candle):
            dropped += 1
            continue
        sanitized.append(
            {
                "time": str(candle.get("time")),
                "open": _to_float(candle.get("open"), 0.0),
                "high": _to_float(candle.get("high"), 0.0),
                "low": _to_float(candle.get("low"), 0.0),
                "close": _to_float(candle.get("close"), 0.0),
                "volume": _to_int(candle.get("volume", 0), 0),
            }
        )

    if dropped > 0:
        logger.warning("[BUNDLE] Dropped %d invalid candles from response", dropped)

    return sanitized


async def _with_timeout(
    coro,
    timeout_seconds: float,
    default: Any,
    context: str,
) -> Any:
    """Run awaited work with a strict timeout and deterministic fallback."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("[BUNDLE] Timeout in %s after %.2fs", context, timeout_seconds)
        return default
    except Exception as exc:
        logger.warning("[BUNDLE] %s failed: %s", context, exc)
        return default


def _parse_candle_row(row: Any) -> dict[str, Any] | None:
    try:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            return {
                "time": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5]) if len(row) > 5 else 0,
            }

        if isinstance(row, dict):
            time_value = row.get("0") or row.get("time")
            if time_value is None:
                return None
            return {
                "time": time_value,
                "open": float(row.get("1", row.get("open", 0))),
                "high": float(row.get("2", row.get("high", 0))),
                "low": float(row.get("3", row.get("low", 0))),
                "close": float(row.get("4", row.get("close", 0))),
                "volume": int(row.get("5", row.get("volume", 0)) or 0),
            }
    except (TypeError, ValueError):
        return None

    return None


def _to_yf_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if normalized in YF_INDEX_SYMBOLS:
        return YF_INDEX_SYMBOLS[normalized]
    return f"{normalized}.NS"


def _to_candle_time_string(value: Any) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return _utc_now_iso()
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert("Asia/Kolkata").tz_localize(None)
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _frame_to_candles(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []

    working = frame.copy()
    if isinstance(working.columns, pd.MultiIndex):
        working.columns = [str(col[0]) for col in working.columns]

    if "Datetime" not in working.columns and "Date" not in working.columns:
        working = working.reset_index()

    working.columns = [str(col).lower() for col in working.columns]
    time_col = "datetime" if "datetime" in working.columns else "date" if "date" in working.columns else None
    if time_col is None:
        return []

    required = {"open", "high", "low", "close"}
    if not required.issubset(set(working.columns)):
        return []

    sliced = working.tail(max(1, int(limit))).copy()
    candles: list[dict[str, Any]] = []
    for _, row in sliced.iterrows():
        candles.append(
            {
                "time": _to_candle_time_string(row.get(time_col)),
                "open": _to_float(row.get("open", 0.0), 0.0),
                "high": _to_float(row.get("high", 0.0), 0.0),
                "low": _to_float(row.get("low", 0.0), 0.0),
                "close": _to_float(row.get("close", 0.0), 0.0),
                "volume": _to_int(row.get("volume", 0), 0),
            }
        )

    return _sanitize_candles(candles)


def _fetch_history_yfinance(
    symbol: str,
    interval: str,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except Exception:
        return []

    yf_symbol = _to_yf_symbol(symbol)
    yf_interval = YF_INTERVAL_MAP.get(interval, "1m")
    period = YF_PERIOD_BY_INTERVAL.get(interval, "60d")

    try:
        frame = yf.Ticker(yf_symbol).history(
            period=period,
            interval=yf_interval,
            auto_adjust=False,
            actions=False,
            prepost=False,
        )
    except Exception:
        return []

    return _frame_to_candles(frame, limit)


def _fetch_snapshot_yfinance(symbol: str) -> dict[str, Any] | None:
    candles = _fetch_history_yfinance(symbol, interval="1d", limit=5)
    if not candles:
        return None
    return _snapshot_from_candles(
        symbol,
        candles,
        source="YFINANCE",
        data_source="YFINANCE",
    )


def _market_state_label(status_payload: dict[str, Any]) -> str:
    return "OPEN" if bool(status_payload.get("is_open")) else "CLOSED"


def _normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    ltp = _to_float(snapshot.get("ltp", snapshot.get("price", 0.0)), 0.0)
    if ltp <= 0:
        ltp = _to_float(snapshot.get("close", 0.0), 0.0)
    if ltp < 0:
        ltp = 0.0

    close = _to_float(snapshot.get("close", ltp), ltp)
    if close < 0:
        close = ltp

    change = _to_float(snapshot.get("change", ltp - close), ltp - close)

    return {
        "symbol": snapshot.get("symbol"),
        "price": round(ltp, 2),
        "ltp": round(ltp, 2),
        "open": max(0.0, _to_float(snapshot.get("open", 0.0), 0.0)),
        "high": max(0.0, _to_float(snapshot.get("high", 0.0), 0.0)),
        "low": max(0.0, _to_float(snapshot.get("low", 0.0), 0.0)),
        "close": round(close, 2),
        "change": round(change, 2),
        "volume": max(0, _to_int(snapshot.get("volume", 0), 0)),
        "source": snapshot.get("source", "UNKNOWN"),
        "data_source": snapshot.get("data_source", "UNKNOWN"),
        "last_ts": snapshot.get("last_ts") or _utc_now_iso(),
    }


def _unavailable_snapshot(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "ltp": 0.0,
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "volume": 0,
        "last_ts": _utc_now_iso(),
        "source": "UNAVAILABLE",
        "data_source": "UNAVAILABLE",
    }


def _snapshot_from_candles(
    symbol: str,
    candles: list[dict[str, Any]],
    source: str,
    data_source: str,
) -> dict[str, Any] | None:
    """Build a price snapshot from the latest available candle(s)."""
    if not candles:
        return None

    last = candles[-1] if isinstance(candles[-1], dict) else None
    if not last:
        return None

    prev = candles[-2] if len(candles) >= 2 and isinstance(candles[-2], dict) else last

    close = _to_float(last.get("close", 0.0), 0.0)
    if close <= 0:
        return None

    prev_close = _to_float(prev.get("close", close), close)
    raw_ts = str(last.get("time") or _utc_now_iso())
    if not raw_ts.endswith("Z"):
        raw_ts = f"{raw_ts}Z"

    return {
        "symbol": symbol,
        "ltp": close,
        "open": _to_float(last.get("open", close), close),
        "high": _to_float(last.get("high", close), close),
        "low": _to_float(last.get("low", close), close),
        "close": close,
        "change": close - prev_close,
        "volume": _to_int(last.get("volume", 0), 0),
        "last_ts": raw_ts,
        "source": source,
        "data_source": data_source,
    }


def _prediction_fallback(symbol: str, ltp: float, reason: str) -> dict[str, Any]:
    safe_ltp = _to_float(ltp, 0.0)
    target = round(safe_ltp * 1.004, 2) if safe_ltp > 0 else 0.0
    stop = round(safe_ltp * 0.996, 2) if safe_ltp > 0 else 0.0
    return {
        "symbol": symbol,
        "signal": "HOLD",
        "confidence": 0.0,
        "confidence_pct": 0,
        "momentum_score": 0.5,
        "trend_score": 0.5,
        "volatility_score": 0.5,
        "volatility_state": "MISSING",
        "volume_score": 0.5,
        "price_action_score": 0.5,
        "candle_type": "NEUTRAL",
        "engulfing": "NONE",
        "doji": False,
        "candle_strength": "MODERATE",
        "body_strength_score": 0.5,
        "upper_wick_pct": 0.0,
        "lower_wick_pct": 0.0,
        "streak_strength_score": 0.0,
        "consecutive_green": 0,
        "consecutive_red": 0,
        "rsi_macd_signal": 0,
        "rsi_macd_strength": 0.0,
        "ema_crossover_signal": 0,
        "ema_crossover_strength": 0.0,
        "rsi_divergence": 0,
        "divergence_strength": 0.0,
        "macd_histogram_trend": 0,
        "macd_momentum_strength": 0.0,
        "fusion_score": 0.0,
        "structure_score": 0.5,
        "structure": "NEUTRAL",
        "last_pattern": "NONE",
        "support_levels": [],
        "resistance_levels": [],
        "nearest_support": None,
        "nearest_resistance": None,
        "support_distance": 1.0,
        "resistance_distance": 1.0,
        "breakout": False,
        "breakout_type": "NONE",
        "range_or_trend": "RANGE",
        "volume_ratio": 1.0,
        "volume_ratio_flag": "NORMAL",
        "volume_spike": False,
        "volume_spike_strength": 0.0,
        "vwap_deviation": 0.0,
        "vwap_bias": "NEUTRAL",
        "obv_slope": 0.0,
        "obv_divergence": False,
        "volume_trend_slope": 0.0,
        "volume_trend_direction": "FLAT",
        "position_size_factor": 0.75,
        "mtf_alignment": "MISSING",
        "mtf_score": 0.0,
        "ema_structure": "NEUTRAL",
        "session": "MID",
        "time_bucket": "SIDEWAYS",
        "day_of_week": 0,
        "day_bias_score": 0.5,
        "expiry_flag": False,
        "expiry_type": "NONE",
        "time_score": 0.5,
        "time_bias": "NEUTRAL",
        "liquidity_score": 0.5,
        "regime_score": 0.5,
        "risk_score": 0.5,
        "ai_score": 0.5,
        "regime_state": "UNKNOWN",
        "price_impact": 0.0,
        "jump_flag": False,
        "gap_flag": "NO_GAP",
        "liquidity_sweep": False,
        "sweep_type": "NONE",
        "flow_state": "NEUTRAL",
        "engines": {
            "momentum": 0.5,
            "trend": 0.5,
            "volatility": 0.5,
            "volume": 0.5,
            "price_action": 0.5,
            "structure": 0.5,
            "regime": 0.5,
            "time": 0.5,
            "liquidity": 0.5,
            "risk": 0.5,
            "mtf": 0.5,
            "ai": 0.5,
        },
        "prediction": round(safe_ltp, 2),
        "target": target,
        "target_price": target,
        "stop_loss": stop,
        "RR": 0.0,
        "position_size": 0,
        "regime": "Unknown",
        "factors": [reason],
        "reason": reason,
        "reasoning": reason,
        "explanation": reason,
    }


def _normalize_prediction(symbol: str, prediction: PredictionResult, ltp: float) -> dict[str, Any]:
    signal = str(prediction.signal or "HOLD").upper()
    if signal not in {"BUY", "SELL", "HOLD"}:
        signal = "HOLD"

    confidence = _normalize_confidence_score(prediction.confidence)
    confidence_pct = int(round(confidence * 100))
    if confidence < 0.6:
        signal = "HOLD"

    target = _to_float(prediction.target, 0.0)
    stop_loss = _to_float(prediction.stop, 0.0)

    if signal == "BUY" and (target <= ltp or stop_loss >= ltp):
        signal = "HOLD"
    elif signal == "SELL" and (target >= ltp or stop_loss <= ltp):
        signal = "HOLD"

    if signal == "HOLD":
        target = round(ltp * 1.004, 2) if ltp > 0 else 0.0
        stop_loss = round(ltp * 0.996, 2) if ltp > 0 else 0.0

    reasoning = prediction.reason or prediction.explanation or "Technical analysis"

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": round(confidence, 4),
        "confidence_pct": confidence_pct,
        "momentum_score": round(_normalize_confidence_score(prediction.momentum_score), 4),
        "trend_score": round(_normalize_confidence_score(prediction.trend_score), 4),
        "volatility_score": round(_normalize_confidence_score(prediction.volatility_score), 4),
        "volatility_state": str(prediction.volatility_state or "MISSING"),
        "volume_score": round(_normalize_confidence_score(prediction.volume_score), 4),
        "price_action_score": round(_normalize_confidence_score(prediction.price_action_score), 4),
        "candle_type": str(prediction.candle_type or "NEUTRAL"),
        "engulfing": str(prediction.engulfing or "NONE"),
        "doji": bool(prediction.doji),
        "candle_strength": str(prediction.candle_strength or "MODERATE"),
        "body_strength_score": round(_normalize_confidence_score(prediction.body_strength_score), 4),
        "upper_wick_pct": round(_normalize_confidence_score(prediction.upper_wick_pct), 4),
        "lower_wick_pct": round(_normalize_confidence_score(prediction.lower_wick_pct), 4),
        "streak_strength_score": round(_normalize_confidence_score(prediction.streak_strength_score), 4),
        "consecutive_green": max(0, _to_int(prediction.consecutive_green, 0)),
        "consecutive_red": max(0, _to_int(prediction.consecutive_red, 0)),
        "rsi_macd_signal": _normalize_signal_ternary(prediction.rsi_macd_signal),
        "rsi_macd_strength": round(_normalize_confidence_score(prediction.rsi_macd_strength), 4),
        "ema_crossover_signal": _normalize_signal_ternary(prediction.ema_crossover_signal),
        "ema_crossover_strength": round(
            _normalize_confidence_score(prediction.ema_crossover_strength),
            4,
        ),
        "rsi_divergence": _normalize_signal_ternary(prediction.rsi_divergence),
        "divergence_strength": round(_normalize_confidence_score(prediction.divergence_strength), 4),
        "macd_histogram_trend": _normalize_signal_ternary(prediction.macd_histogram_trend),
        "macd_momentum_strength": round(_normalize_signed_score(prediction.macd_momentum_strength), 4),
        "fusion_score": round(_normalize_signed_score(prediction.fusion_score), 4),
        "structure_score": round(_normalize_confidence_score(prediction.structure_score), 4),
        "structure": str(prediction.structure or "NEUTRAL"),
        "last_pattern": str(prediction.last_pattern or "NONE"),
        "support_levels": [
            round(_to_float(level, 0.0), 4) for level in (prediction.support_levels or [])
        ],
        "resistance_levels": [
            round(_to_float(level, 0.0), 4) for level in (prediction.resistance_levels or [])
        ],
        "nearest_support": round(_to_float(prediction.nearest_support, 0.0), 4),
        "nearest_resistance": round(_to_float(prediction.nearest_resistance, 0.0), 4),
        "support_distance": round(_to_float(prediction.support_distance, 1.0), 4),
        "resistance_distance": round(_to_float(prediction.resistance_distance, 1.0), 4),
        "breakout": bool(prediction.breakout),
        "breakout_type": str(prediction.breakout_type or "NONE"),
        "range_or_trend": str(prediction.range_or_trend or "RANGE"),
        "volume_ratio": round(_to_float(prediction.volume_ratio, 1.0), 4),
        "volume_ratio_flag": str(prediction.volume_ratio_flag or "NORMAL"),
        "volume_spike": bool(prediction.volume_spike),
        "volume_spike_strength": round(_to_float(prediction.volume_spike_strength, 0.0), 4),
        "vwap_deviation": round(_to_float(prediction.vwap_deviation, 0.0), 6),
        "vwap_bias": str(prediction.vwap_bias or "NEUTRAL"),
        "obv_slope": round(_to_float(prediction.obv_slope, 0.0), 4),
        "obv_divergence": bool(prediction.obv_divergence),
        "volume_trend_slope": round(_to_float(prediction.volume_trend_slope, 0.0), 4),
        "volume_trend_direction": str(prediction.volume_trend_direction or "FLAT"),
        "position_size_factor": round(_to_float(prediction.position_size_factor, 0.75), 2),
        "mtf_alignment": str(prediction.mtf_alignment or "NEUTRAL"),
        "mtf_score": round(_normalize_confidence_score(prediction.mtf_score), 4),
        "ema_structure": str(prediction.ema_structure or "MIXED STACK"),
        "session": str(prediction.session or "MID"),
        "time_bucket": str(prediction.time_bucket or "SIDEWAYS"),
        "day_of_week": max(0, min(6, _to_int(prediction.day_of_week, 0))),
        "day_bias_score": round(_normalize_confidence_score(prediction.day_bias_score), 4),
        "expiry_flag": bool(prediction.expiry_flag),
        "expiry_type": str(prediction.expiry_type or "NONE"),
        "time_score": round(_normalize_confidence_score(prediction.time_score), 4),
        "time_bias": str(prediction.time_bias or "NEUTRAL"),
        "liquidity_score": round(_normalize_confidence_score(prediction.liquidity_score), 4),
        "regime_score": round(_normalize_confidence_score(prediction.regime_score), 4),
        "risk_score": round(_normalize_confidence_score(prediction.risk_score), 4),
        "ai_score": round(_normalize_confidence_score(prediction.ai_score), 4),
        "regime_state": str(prediction.regime_state or "UNKNOWN"),
        "price_impact": round(_to_float(prediction.price_impact, 0.0), 8),
        "jump_flag": bool(prediction.jump_flag),
        "gap_flag": str(prediction.gap_flag or "NO_GAP"),
        "liquidity_sweep": bool(prediction.liquidity_sweep),
        "sweep_type": str(prediction.sweep_type or "NONE"),
        "flow_state": str(prediction.flow_state or "NEUTRAL"),
        "engines": prediction.engines or {},
        "prediction": round(_to_float(prediction.price, ltp), 2),
        "target": round(target, 2),
        "target_price": round(target, 2),
        "stop_loss": round(stop_loss, 2),
        "RR": round(_to_float(prediction.RR, 0.0), 4),
        "position_size": max(0, _to_int(prediction.position_size, 0)),
        "regime": prediction.regime or "Unknown",
        "factors": prediction.factors or [],
        "models": prediction.models or {},
        "reason": reasoning,
        "reasoning": reasoning,
        "explanation": reasoning,
    }


async def _save_prediction_record(
    symbol: str,
    horizon: str,
    prediction: dict[str, Any],
) -> None:
    if not async_session:
        return

    try:
        async with async_session() as session:
            record = PredictionModel(
                symbol=symbol,
                horizon=horizon,
                predicted_price=_to_float(prediction.get("prediction", 0.0), 0.0),
                signal=str(prediction.get("signal", "HOLD")),
                confidence=_to_int(prediction.get("confidence_pct", 0), 0),
                stop_loss=_to_float(prediction.get("stop_loss", 0.0), 0.0),
                target=_to_float(prediction.get("target", 0.0), 0.0),
                explanation=str(prediction.get("reasoning", "")),
            )
            session.add(record)
            await session.commit()
    except Exception as exc:
        logger.warning("[BUNDLE] Failed to persist prediction for %s: %s", symbol, exc)


def _get_connector() -> SmartAPIConnector:
    global _connector, _connector_blocked_until

    now = time.monotonic()
    if now < _connector_blocked_until:
        wait_seconds = round(_connector_blocked_until - now, 2)
        raise RuntimeError(f"Connector cooldown active ({wait_seconds}s)")

    if _connector is None:
        _connector = SmartAPIConnector()
        try:
            _connector.login()
            _connector_blocked_until = 0.0
        except Exception:
            _connector_blocked_until = time.monotonic() + CONNECTOR_COOLDOWN_SECONDS
            raise
    return _connector


async def _fetch_snapshot(symbol: str) -> dict[str, Any]:
    token = get_token(symbol) or get_symbol_token(symbol)
    tradingsymbol = get_tradingsymbol(symbol)
    connector = await asyncio.to_thread(_get_connector)

    data = await asyncio.to_thread(
        connector.get_ltp,
        token,
        config.SMARTAPI_EXCHANGE,
        tradingsymbol,
    )
    if not data:
        raise ValueError(f"LTP not available for {symbol}")

    return {
        "symbol": symbol,
        "ltp": _to_float(data.get("ltp", 0.0), 0.0),
        "open": _to_float(data.get("open", 0.0), 0.0),
        "high": _to_float(data.get("high", 0.0), 0.0),
        "low": _to_float(data.get("low", 0.0), 0.0),
        "close": _to_float(data.get("close", data.get("ltp", 0.0)), 0.0),
        "volume": _to_int(data.get("volume", 0), 0),
        "last_ts": _utc_now_iso(),
        "source": "NSE_API",
        "data_source": "NSE_API",
    }


async def _db_snapshot(symbol: str) -> dict[str, Any] | None:
    candle = await _with_timeout(
        get_last_candle(symbol, "1m"),
        DB_READ_TIMEOUT_SECONDS,
        None,
        f"db_snapshot_1m:{symbol}",
    )
    if not candle:
        candle = await _with_timeout(
            get_last_candle(symbol, "1d"),
            DB_READ_TIMEOUT_SECONDS,
            None,
            f"db_snapshot_1d:{symbol}",
        )
    if not candle:
        return None

    raw_time = str(candle.get("time") or _utc_now_iso())
    if not raw_time.endswith("Z"):
        raw_time = f"{raw_time}Z"

    close = _to_float(candle.get("close", 0.0), 0.0)

    return {
        "symbol": symbol,
        "ltp": close,
        "open": _to_float(candle.get("open", close), close),
        "high": _to_float(candle.get("high", close), close),
        "low": _to_float(candle.get("low", close), close),
        "close": close,
        "volume": _to_int(candle.get("volume", 0), 0),
        "last_ts": raw_time,
        "source": "CACHE",
        "data_source": "CACHE",
    }


async def _refresh_market_session() -> None:
    """Best-effort SmartAPI token/session refresh without hard dependency cycles."""
    try:
        from app.services.scheduler import regen_token as scheduler_regen_token

        await scheduler_regen_token()
    except Exception as exc:
        logger.warning("[BUNDLE] Session refresh skipped: %s", exc)


async def get_market_status() -> dict[str, Any]:
    status_payload = _raw_market_status()
    return {
        "state": _market_state_label(status_payload),
        "details": status_payload,
    }


async def get_snapshot(symbol: str) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    cache_key = f"snap:v3:{normalized_symbol}"

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        return cached

    market_open = bool(_raw_market_status().get("is_open"))
    snapshot: dict[str, Any] | None = None
    db_snapshot = await _db_snapshot(normalized_symbol)

    # Prefer live quote during market hours.
    if market_open:
        snapshot = await _with_timeout(
            _fetch_snapshot(normalized_symbol),
            SNAPSHOT_LIVE_TIMEOUT_SECONDS,
            None,
            f"live_snapshot:{normalized_symbol}",
        )

    if not snapshot and db_snapshot:
        snapshot = db_snapshot

    # If DB is empty after-hours, opportunistically try live quote once.
    if not snapshot and not market_open:
        snapshot = await _with_timeout(
            _fetch_snapshot(normalized_symbol),
            SNAPSHOT_LIVE_TIMEOUT_SECONDS,
            None,
            f"live_snapshot_offhours:{normalized_symbol}",
        )

    # Public market-data fallback when broker credentials/session are unavailable.
    if not snapshot:
        snapshot = await _with_timeout(
            asyncio.to_thread(_fetch_snapshot_yfinance, normalized_symbol),
            SNAPSHOT_LIVE_TIMEOUT_SECONDS,
            None,
            f"yf_snapshot:{normalized_symbol}",
        )

    # Final fallback: derive snapshot from the latest available candles.
    if not snapshot:
        history_payload = await _with_timeout(
            get_history(normalized_symbol, interval="1m", limit=2),
            HISTORY_LIVE_TIMEOUT_SECONDS,
            None,
            f"snapshot_history_fallback:{normalized_symbol}",
        )
        if isinstance(history_payload, dict):
            history_candles = history_payload.get("candles", [])
            snapshot = _snapshot_from_candles(
                normalized_symbol,
                history_candles if isinstance(history_candles, list) else [],
                str(history_payload.get("source", "CACHE")),
                str(history_payload.get("data_source", "CACHE")),
            )

    if not snapshot:
        snapshot = _unavailable_snapshot(normalized_symbol)

    normalized = _normalize_snapshot(snapshot)
    await set_cache(cache_key, normalized, ttl=SNAPSHOT_CACHE_TTL_SECONDS)
    return normalized


async def get_history(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    requested_limit = max(1, min(int(limit), 1000))
    cache_key = f"hist:v3:{normalized_symbol}:{interval}:{requested_limit}"

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        return cached

    db_candles = await _with_timeout(
        get_candles(normalized_symbol, interval, limit=requested_limit),
        DB_READ_TIMEOUT_SECONDS,
        [],
        f"db_candles:{normalized_symbol}:{interval}",
    )

    db_is_stale = True
    if db_candles:
        try:
            last_time = datetime.strptime(
                str(db_candles[-1]["time"]).split("+")[0].strip(),
                "%Y-%m-%d %H:%M:%S",
            )
            db_is_stale = (datetime.now() - last_time) > timedelta(days=2)
        except (ValueError, KeyError):
            db_is_stale = True

    if len(db_candles) >= requested_limit * 0.8 and not db_is_stale:
        sanitized_db = _sanitize_candles(db_candles)
        payload = {
            "symbol": normalized_symbol,
            "interval": interval,
            "candles": sanitized_db,
            "data": sanitized_db,
            "count": len(sanitized_db),
            "source": "CACHE",
            "data_source": "CACHE",
        }
        await set_cache(cache_key, payload, ttl=HISTORY_CACHE_TTL_SECONDS)
        return payload

    should_try_live = len(db_candles) < requested_limit * 0.8 or db_is_stale
    if should_try_live:
        try:
            token = get_token(normalized_symbol) or get_symbol_token(normalized_symbol)
            connector = await _with_timeout(
                asyncio.to_thread(_get_connector),
                SNAPSHOT_LIVE_TIMEOUT_SECONDS,
                None,
                f"connector_init:{normalized_symbol}",
            )

            if connector is not None:
                to_dt = datetime.now()

                if interval in {"1m", "3m", "5m", "15m", "30m"}:
                    from_dt = to_dt - timedelta(days=7)
                elif interval == "1h":
                    from_dt = to_dt - timedelta(days=30)
                else:
                    from_dt = to_dt - timedelta(days=365)

                rows = await _with_timeout(
                    asyncio.to_thread(
                        connector.fetch_history,
                        token,
                        config.SMARTAPI_EXCHANGE,
                        interval,
                        from_dt,
                        to_dt,
                        requested_limit,
                    ),
                    HISTORY_LIVE_TIMEOUT_SECONDS,
                    [],
                    f"live_history:{normalized_symbol}:{interval}",
                )

                if rows:
                    ohlcv: list[dict[str, Any]] = []
                    for row in rows:
                        parsed = _parse_candle_row(row)
                        if parsed:
                            ohlcv.append(parsed)

                    if ohlcv:
                        ohlcv = _sanitize_candles(ohlcv)
                        if ohlcv:
                            await store_candles(normalized_symbol, interval, ohlcv)
                            payload = {
                                "symbol": normalized_symbol,
                                "interval": interval,
                                "candles": ohlcv,
                                "data": ohlcv,
                                "count": len(ohlcv),
                                "source": "NSE_API",
                                "data_source": "NSE_API",
                            }
                            await set_cache(cache_key, payload, ttl=HISTORY_CACHE_TTL_SECONDS)
                            return payload
        except Exception as exc:
            logger.warning("[BUNDLE] History fetch failed for %s: %s", normalized_symbol, exc)

        yf_candles = await _with_timeout(
            asyncio.to_thread(
                _fetch_history_yfinance,
                normalized_symbol,
                interval,
                requested_limit,
            ),
            HISTORY_LIVE_TIMEOUT_SECONDS,
            [],
            f"yf_history:{normalized_symbol}:{interval}",
        )

        if isinstance(yf_candles, list) and yf_candles:
            await store_candles(normalized_symbol, interval, yf_candles)
            payload = {
                "symbol": normalized_symbol,
                "interval": interval,
                "candles": yf_candles,
                "data": yf_candles,
                "count": len(yf_candles),
                "source": "YFINANCE",
                "data_source": "YFINANCE",
            }
            await set_cache(cache_key, payload, ttl=HISTORY_CACHE_TTL_SECONDS)
            return payload

    if db_candles:
        db_candles = _sanitize_candles(db_candles)
        payload = {
            "symbol": normalized_symbol,
            "interval": interval,
            "candles": db_candles,
            "data": db_candles,
            "count": len(db_candles),
            "source": "CACHE",
            "data_source": "CACHE",
        }
        await set_cache(cache_key, payload, ttl=HISTORY_CACHE_TTL_SECONDS)
        return payload

    payload = {
        "symbol": normalized_symbol,
        "interval": interval,
        "candles": [],
        "data": [],
        "count": 0,
        "source": "UNAVAILABLE",
        "data_source": "UNAVAILABLE",
    }
    await set_cache(cache_key, payload, ttl=HISTORY_CACHE_TTL_SECONDS)
    return payload


def _compute_ema(candles: list[dict[str, Any]], span: int) -> float:
    if not candles:
        return 0.0

    alpha = 2 / (span + 1)
    ema = _to_float(candles[0].get("close", 0.0), 0.0)
    for candle in candles[1:]:
        close = _to_float(candle.get("close", ema), ema)
        ema = (close * alpha) + (ema * (1 - alpha))
    return round(ema, 2)


async def get_indicators(
    symbol: str,
    interval: str = "1m",
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    resolved_history = history or await get_history(
        normalized_symbol,
        interval=interval,
        limit=200,
    )
    candles = resolved_history.get("candles") or resolved_history.get("data") or []

    if not isinstance(candles, list) or len(candles) < 20:
        return {
            "symbol": normalized_symbol,
            "ema_20": 0.0,
            "ema_50": 0.0,
            "ema9": 0.0,
            "ema15": 0.0,
            "rsi": 0.0,
            "rsi9": 0.0,
            "macd": {"value": 0.0, "signal": 0.0, "histogram": 0.0},
            "bollinger": {"upper": 0.0, "middle": 0.0, "lower": 0.0},
        }

    indicators_df = await _with_timeout(
        asyncio.to_thread(IndicatorEngine.compute_all, candles),
        PREDICTION_TIMEOUT_SECONDS,
        None,
        f"indicators_compute:{normalized_symbol}",
    )
    if indicators_df is None:
        return {
            "symbol": normalized_symbol,
            "ema_20": 0.0,
            "ema_50": 0.0,
            "ema9": 0.0,
            "ema15": 0.0,
            "rsi": 0.0,
            "rsi9": 0.0,
            "macd": {"value": 0.0, "signal": 0.0, "histogram": 0.0},
            "bollinger": {"upper": 0.0, "middle": 0.0, "lower": 0.0},
        }
    if indicators_df.empty:
        return {
            "symbol": normalized_symbol,
            "ema_20": 0.0,
            "ema_50": 0.0,
            "ema9": 0.0,
            "ema15": 0.0,
            "rsi": 0.0,
            "rsi9": 0.0,
            "macd": {"value": 0.0, "signal": 0.0, "histogram": 0.0},
            "bollinger": {"upper": 0.0, "middle": 0.0, "lower": 0.0},
        }

    latest = indicators_df.iloc[-1].to_dict()

    return {
        "symbol": normalized_symbol,
        "ema_20": _compute_ema(candles, 20),
        "ema_50": _compute_ema(candles, 50),
        "ema9": round(_to_float(latest.get("ema9", 0.0), 0.0), 2),
        "ema15": round(_to_float(latest.get("ema15", 0.0), 0.0), 2),
        "rsi": round(_to_float(latest.get("rsi9", 0.0), 0.0), 2),
        "rsi9": round(_to_float(latest.get("rsi9", 0.0), 0.0), 2),
        "macd": {
            "value": round(_to_float(latest.get("macd", 0.0), 0.0), 4),
            "signal": round(_to_float(latest.get("macd_signal", 0.0), 0.0), 4),
            "histogram": round(_to_float(latest.get("macd_hist", 0.0), 0.0), 4),
        },
        "macd_signal": round(_to_float(latest.get("macd_signal", 0.0), 0.0), 4),
        "macd_hist": round(_to_float(latest.get("macd_hist", 0.0), 0.0), 4),
        "bollinger": {
            "upper": round(_to_float(latest.get("bb_upper", 0.0), 0.0), 2),
            "middle": round(_to_float(latest.get("sma20", 0.0), 0.0), 2),
            "lower": round(_to_float(latest.get("bb_lower", 0.0), 0.0), 2),
        },
        "bb_upper": round(_to_float(latest.get("bb_upper", 0.0), 0.0), 2),
        "bb_lower": round(_to_float(latest.get("bb_lower", 0.0), 0.0), 2),
        "sma20": round(_to_float(latest.get("sma20", 0.0), 0.0), 2),
    }


async def get_prediction(
    symbol: str,
    horizon: str = "15m",
    history: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    resolved_history = history or await get_history(
        normalized_symbol,
        interval="1m",
        limit=200,
    )
    candles = resolved_history.get("candles") or resolved_history.get("data") or []

    if not isinstance(candles, list) or not candles:
        return _prediction_fallback(normalized_symbol, 0.0, "No market data available")

    candles = _sanitize_candles(candles)
    if not candles:
        return _prediction_fallback(
            normalized_symbol,
            0.0,
            "No valid candles available after validation",
        )

    last_candle_time = str(candles[-1].get("time", "na"))
    cache_key = f"pred:v3:{normalized_symbol}:{horizon}:{last_candle_time}"

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        return cached

    resolved_snapshot = snapshot or await get_snapshot(normalized_symbol)
    ltp = _to_float(
        resolved_snapshot.get("price", resolved_snapshot.get("ltp", 0.0)),
        _to_float(candles[-1].get("close", 0.0), 0.0),
    )

    if len(candles) < MIN_CANDLES_FOR_FEATURES:
        fallback = _prediction_fallback(normalized_symbol, ltp, "Insufficient data")
        await set_cache(cache_key, fallback, ttl=PREDICTION_CACHE_TTL_SECONDS)
        return fallback

    try:
        prediction = await _with_timeout(
            asyncio.to_thread(
                predict_symbol,
                symbol=normalized_symbol,
                timeframe=horizon,
                latest_ltp=ltp,
                ohlcv=candles,
            ),
            PREDICTION_TIMEOUT_SECONDS,
            None,
            f"prediction:{normalized_symbol}:{horizon}",
        )
        if prediction is None:
            fallback = _prediction_fallback(normalized_symbol, ltp, "Prediction timed out")
            await set_cache(cache_key, fallback, ttl=PREDICTION_CACHE_TTL_SECONDS)
            return fallback
    except Exception as first_error:
        logger.warning(
            "[BUNDLE] Prediction pipeline failed for %s (%s). Trying token refresh.",
            normalized_symbol,
            first_error,
        )
        try:
            # Refresh broker session only during market hours; model inference itself
            # can still run from cached/yfinance candles off-hours.
            if bool(_raw_market_status().get("is_open")):
                await _with_timeout(
                    _refresh_market_session(),
                    SNAPSHOT_LIVE_TIMEOUT_SECONDS,
                    None,
                    f"prediction_refresh:{normalized_symbol}",
                )
            refreshed_history = await get_history(normalized_symbol, interval="1m", limit=200)
            candles = refreshed_history.get("candles") or refreshed_history.get("data") or candles
            candles = _sanitize_candles(candles)
            prediction = await _with_timeout(
                asyncio.to_thread(
                    predict_symbol,
                    symbol=normalized_symbol,
                    timeframe=horizon,
                    latest_ltp=ltp,
                    ohlcv=candles,
                ),
                PREDICTION_TIMEOUT_SECONDS,
                None,
                f"prediction_retry:{normalized_symbol}:{horizon}",
            )
            if prediction is None:
                fallback = _prediction_fallback(normalized_symbol, ltp, "Prediction unavailable")
                await set_cache(cache_key, fallback, ttl=PREDICTION_CACHE_TTL_SECONDS)
                return fallback
        except Exception as second_error:
            logger.error(
                "[BUNDLE] Prediction failed after refresh for %s: %s",
                normalized_symbol,
                second_error,
            )
            fallback = _prediction_fallback(normalized_symbol, ltp, "Prediction pipeline failed")
            await set_cache(cache_key, fallback, ttl=PREDICTION_CACHE_TTL_SECONDS)
            return fallback

    normalized = _normalize_prediction(normalized_symbol, prediction, ltp)
    await _save_prediction_record(normalized_symbol, horizon, normalized)
    await set_cache(cache_key, normalized, ttl=PREDICTION_CACHE_TTL_SECONDS)
    return normalized


async def get_bundle(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    horizon: str = "15m",
) -> dict[str, Any]:
    started_at = time.perf_counter()
    normalized_symbol = _normalize_symbol(symbol)

    history_task = asyncio.create_task(
        get_history(normalized_symbol, interval=interval, limit=limit)
    )
    snapshot_task = asyncio.create_task(get_snapshot(normalized_symbol))
    status_task = asyncio.create_task(get_market_status())

    history_payload, snapshot_payload, market_status = await asyncio.gather(
        history_task,
        snapshot_task,
        status_task,
    )

    history_candles = history_payload.get("candles", []) if isinstance(history_payload, dict) else []
    history_count = len(history_candles) if isinstance(history_candles, list) else 0

    snapshot_payload = {
        **snapshot_payload,
        "market_status": market_status.get("state", "CLOSED"),
    }

    indicators_task = asyncio.create_task(
        get_indicators(
            normalized_symbol,
            interval=interval,
            history=history_payload,
        )
    )
    prediction_task = asyncio.create_task(
        get_prediction(
            normalized_symbol,
            horizon=horizon,
            history=history_payload,
            snapshot=snapshot_payload,
        )
    )

    indicators_payload, prediction_payload = await asyncio.gather(indicators_task, prediction_task)

    if history_count < MIN_CANDLES_FOR_BUNDLE:
        prediction_payload = _prediction_fallback(
            normalized_symbol,
            _to_float(snapshot_payload.get("ltp", 0.0), 0.0),
            f"Insufficient validated history (< {MIN_CANDLES_FOR_BUNDLE} candles)",
        )

    latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)

    return {
        "symbol": normalized_symbol,
        "timestamp": _utc_now_iso(),
        "candles": history_payload.get("candles", []),
        "latest_price": _to_float(snapshot_payload.get("ltp", 0.0), 0.0),
        "data_source": history_payload.get("data_source", "UNKNOWN"),
        "history": {
            "candles": history_payload.get("candles", []),
            "count": _to_int(history_payload.get("count", 0), 0),
            "source": history_payload.get("source", "UNKNOWN"),
            "data_source": history_payload.get("data_source", "UNKNOWN"),
            "required_count": MIN_CANDLES_FOR_BUNDLE,
            "validated": history_count >= MIN_CANDLES_FOR_BUNDLE,
        },
        "snapshot": snapshot_payload,
        "prediction": prediction_payload,
        "indicators": indicators_payload,
        "market_status": market_status.get("state", "CLOSED"),
        "market": market_status.get("details", {}),
        "latency_ms": latency_ms,
    }
