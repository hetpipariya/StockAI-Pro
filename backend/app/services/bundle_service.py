from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from app import config
from app.connectors import get_market_data_connector
from app.inference.runner import PredictionResult, predict_symbol
from app.services.candle_store import get_candles, get_last_candle, store_candles
from app.services.db import PredictionModel, async_session, is_transient_db_error
from app.services.native_accelerators import compute_feature_frame, compute_indicator_frame
from app.services.indicators import IndicatorEngine
from app.services.instrument_service import normalize_symbol_input
from app.services.market_state import get_market_status as _raw_market_status
from app.services.realtime_data_service import LiveMarketDataService
from app.services.redis_client import get_cache, set_cache

logger = logging.getLogger(__name__)

# Bundle-specific cache profile for low-latency UI refreshes.
HISTORY_CACHE_TTL_SECONDS = max(5, min(config.CACHE_TTL_CANDLES_SECONDS, 10))
SNAPSHOT_CACHE_TTL_SECONDS = max(2, min(config.CACHE_TTL_SNAPSHOT_SECONDS, 5))
PREDICTION_CACHE_TTL_SECONDS = max(10, int(os.getenv("BUNDLE_PREDICTION_CACHE_TTL_SECONDS", "10")))
BUNDLE_CACHE_TTL_SECONDS = max(5, min(config.CACHE_TTL_BUNDLE_SECONDS, 8))
HISTORY_STALE_CACHE_TTL_SECONDS = max(30, int(os.getenv("BUNDLE_HISTORY_STALE_TTL_SECONDS", "120")))
SNAPSHOT_STALE_CACHE_TTL_SECONDS = max(15, int(os.getenv("BUNDLE_SNAPSHOT_STALE_TTL_SECONDS", "45")))
PREDICTION_STALE_CACHE_TTL_SECONDS = max(20, int(os.getenv("BUNDLE_PREDICTION_STALE_TTL_SECONDS", "60")))
BUNDLE_STALE_CACHE_TTL_SECONDS = max(20, int(os.getenv("BUNDLE_STALE_TTL_SECONDS", "60")))

# Guardrails for low-latency bundle responses under partial outages.
DB_READ_TIMEOUT_SECONDS = max(1.0, float(os.getenv("BUNDLE_DB_TIMEOUT_SECONDS", "1.0")))
SNAPSHOT_LIVE_TIMEOUT_SECONDS = max(3.0, float(os.getenv("BUNDLE_SNAPSHOT_TIMEOUT_SECONDS", "3.0")))
HISTORY_LIVE_TIMEOUT_SECONDS = max(4.0, float(os.getenv("BUNDLE_HISTORY_TIMEOUT_SECONDS", "4.0")))
PREDICTION_TIMEOUT_SECONDS = max(2.0, float(os.getenv("BUNDLE_PREDICTION_TIMEOUT_SECONDS", "2.0")))
INDICATORS_TIMEOUT_SECONDS = max(2.0, float(os.getenv("BUNDLE_INDICATORS_TIMEOUT_SECONDS", "2.0")))
CONNECTOR_COOLDOWN_SECONDS = 60.0
MIN_CANDLES_FOR_FEATURES = max(50, int(os.getenv("MIN_CANDLES_FOR_FEATURES", "200")))
MIN_CANDLES_FOR_BUNDLE = max(
    MIN_CANDLES_FOR_FEATURES,
    int(os.getenv("MIN_CANDLES_FOR_BUNDLE", str(MIN_CANDLES_FOR_FEATURES))),
)
PREWARM_TIMEOUT_SECONDS = 6.0
COMPONENT_CONCURRENCY_LIMIT = max(
    1,
    min(3, int(os.getenv("BUNDLE_COMPONENT_CONCURRENCY", "3"))),
)
DEFAULT_PREWARM_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in os.getenv(
        "BUNDLE_PREWARM_SYMBOLS",
        "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,SBIN",
    ).split(",")
    if symbol.strip()
)

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
_connector: Any | None = None
_connector_blocked_until: float = 0.0
_live_market_data_service: LiveMarketDataService | None = None
_bundle_log_last_emitted: dict[str, float] = {}
_BUNDLE_LOG_THROTTLE_SECONDS = 30.0
_component_semaphore = asyncio.Semaphore(COMPONENT_CONCURRENCY_LIMIT)
_bundle_metrics: dict[str, int] = {
    "requests": 0,
    "history_ok": 0,
    "history_fail": 0,
    "snapshot_ok": 0,
    "snapshot_fail": 0,
    "prediction_ok": 0,
    "prediction_fail": 0,
    "indicators_ok": 0,
    "indicators_fail": 0,
}


def _should_emit_bundle_log(key: str) -> bool:
    now = time.monotonic()
    last = _bundle_log_last_emitted.get(key, 0.0)
    if now - last >= _BUNDLE_LOG_THROTTLE_SECONDS:
        _bundle_log_last_emitted[key] = now
        return True
    return False


def _bundle_cache_key(symbol: str, interval: str, limit: int, horizon: str) -> str:
    normalized_interval = str(interval or "1m").strip().lower() or "1m"
    normalized_horizon = str(horizon or "15m").strip().lower() or "15m"
    safe_limit = max(1, _to_int(limit, 100))
    return f"bundle:v4:{symbol}:{normalized_interval}:{safe_limit}:{normalized_horizon}"


def _stale_cache_key(cache_key: str) -> str:
    return f"{cache_key}:stale"


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
    return normalize_symbol_input(symbol)


async def _set_cached_payload(
    cache_key: str,
    payload: Any,
    *,
    ttl: int,
    stale_ttl: int | None = None,
) -> None:
    await set_cache(cache_key, payload, ttl=ttl)
    if stale_ttl and stale_ttl > ttl:
        await set_cache(_stale_cache_key(cache_key), payload, ttl=stale_ttl)


async def _get_stale_cached_payload(cache_key: str) -> Any:
    return await get_cache(_stale_cache_key(cache_key))


async def _run_component(name: str, coro):
    async with _component_semaphore:
        logger.debug("[BUNDLE] component_start name=%s", name)
        return await coro


async def _timed_component(name: str, coro):
    started = time.perf_counter()
    try:
        result = await coro
        duration_ms = (time.perf_counter() - started) * 1000.0
        return name, result, None, duration_ms
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000.0
        return name, exc, exc, duration_ms


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
    low_price = _to_float(candle.get("low"), -1.0)
    c = _to_float(candle.get("close"), -1.0)
    v = _to_float(candle.get("volume", 0.0), -1.0)

    if o <= 0 or h <= 0 or low_price <= 0 or c <= 0:
        return False
    if h < low_price:
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
    *,
    cancel_on_timeout: bool = True,
) -> Any:
    """Run awaited work with a strict timeout and deterministic fallback."""
    task = asyncio.ensure_future(coro)
    wait_target = task if cancel_on_timeout else asyncio.shield(task)

    try:
        return await asyncio.wait_for(wait_target, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        is_expected_data_timeout = context.startswith(("db_", "yf_"))
        timeout_logger = logger.info if is_expected_data_timeout else logger.warning

        if _should_emit_bundle_log(f"timeout:{context}"):
            timeout_logger("[BUNDLE] Timeout in %s after %.2fs", context, timeout_seconds)
        else:
            logger.debug("[BUNDLE] Timeout in %s after %.2fs", context, timeout_seconds)

        if cancel_on_timeout:
            if not task.done():
                task.cancel()
        elif not task.done():
            def _consume_late_result(done_task: asyncio.Future[Any]) -> None:
                try:
                    done_task.result()
                except BaseException as late_exc:
                    logger.debug(
                        "[BUNDLE] Late completion error in %s: %s",
                        context,
                        late_exc,
                    )

            task.add_done_callback(_consume_late_result)

        return default
    except Exception as exc:
        if not task.done():
            task.cancel()
        if _should_emit_bundle_log(f"error:{context}"):
            logger.warning("[BUNDLE] %s failed: %s", context, exc)
        else:
            logger.debug("[BUNDLE] %s failed: %s", context, exc)
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


def _parse_timestamp(value: Any) -> datetime | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts.to_pydatetime()
    return None


def _apply_history_requirements(
    payload: dict[str, Any],
    required_count: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    candles = payload.get("candles") if isinstance(payload.get("candles"), list) else []
    count = len(candles)
    if count >= required_count:
        return payload

    warning = f"Insufficient candles ({count}/{required_count})"
    updated = _as_partial_payload(payload, warning=warning, stale=bool(payload.get("stale")))
    updated["count"] = count
    return updated


def _align_snapshot_with_history(
    symbol: str,
    snapshot: dict[str, Any],
    history_payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return snapshot

    candles = history_payload.get("candles") if isinstance(history_payload.get("candles"), list) else []
    if not candles:
        return snapshot

    last_candle = candles[-1] if isinstance(candles[-1], dict) else None
    if not last_candle:
        return snapshot

    snapshot_ts = _parse_timestamp(snapshot.get("last_ts") or snapshot.get("timestamp"))
    candle_ts = _parse_timestamp(last_candle.get("time"))

    should_override = False
    if str(snapshot.get("data_source", "")).upper() in {"UNAVAILABLE", "STALE_CACHE"}:
        should_override = True
    if candle_ts and snapshot_ts and snapshot_ts < candle_ts:
        should_override = True
    if snapshot.get("ltp", 0.0) in (0, 0.0) and candle_ts:
        should_override = True

    if not should_override:
        return snapshot

    derived = _snapshot_from_candles(
        symbol,
        candles,
        source=str(history_payload.get("source", "CACHE")),
        data_source=str(history_payload.get("data_source", "CACHE")),
    )
    if not derived:
        return snapshot

    merged = {
        **snapshot,
        **derived,
    }
    if snapshot.get("partial") or history_payload.get("partial"):
        merged["partial"] = True
        merged["warning"] = merged.get("warning") or "Snapshot aligned with latest candle"
    return merged


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
        "partial": True,
        "stale": False,
        "warning": "Live snapshot unavailable",
    }


def _empty_history_payload(symbol: str, interval: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "interval": interval,
        "candles": [],
        "data": [],
        "count": 0,
        "source": "UNAVAILABLE",
        "data_source": "UNAVAILABLE",
        "partial": True,
        "stale": False,
        "warning": "History unavailable",
    }


def _empty_market_status_payload() -> dict[str, Any]:
    return {
        "state": "CLOSED",
        "details": {},
    }


def _empty_indicators_payload(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "ema_20": 0.0,
        "ema_50": 0.0,
        "ema9": 0.0,
        "ema15": 0.0,
        "rsi": 0.0,
        "rsi9": 0.0,
        "macd": {
            "value": 0.0,
            "signal": 0.0,
            "histogram": 0.0,
        },
        "bollinger": {
            "upper": 0.0,
            "middle": 0.0,
            "lower": 0.0,
        },
        "partial": True,
        "warning": "Indicators unavailable",
    }


def _as_partial_payload(
    payload: dict[str, Any],
    *,
    source: str | None = None,
    data_source: str | None = None,
    warning: str | None = None,
    stale: bool = True,
) -> dict[str, Any]:
    updated = dict(payload or {})
    if source:
        updated["source"] = source
    if data_source:
        updated["data_source"] = data_source
    updated["partial"] = True
    updated["stale"] = stale
    if warning:
        updated["warning"] = warning
    return updated


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
        "partial": True,
        "stale": False,
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
        "warning": reason,
    }


def _normalize_prediction(symbol: str, prediction: PredictionResult, ltp: float) -> dict[str, Any]:
    signal = str(prediction.signal or "HOLD").upper()
    if signal not in {"BUY", "SELL", "HOLD"}:
        signal = "HOLD"

    confidence = _normalize_confidence_score(prediction.confidence)
    confidence_pct = int(round(confidence * 100))
    execution_threshold = float(
        np.clip(
            _to_float(os.getenv("MIN_EXECUTION_CONFIDENCE", "0.55"), 0.55),
            0.45,
            0.75,
        )
    )
    confidence_gate_reason = ""
    if signal != "HOLD" and confidence < execution_threshold:
        signal = "HOLD"
        confidence_gate_reason = (
            f"Confidence below execution threshold ({execution_threshold:.2f})"
        )

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
    if confidence_gate_reason:
        if reasoning:
            reasoning = f"{reasoning} | {confidence_gate_reason}"
        else:
            reasoning = confidence_gate_reason

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

    max_attempts = max(1, int(config.DB_MAX_RETRIES))
    base_delay = max(0.05, float(config.DB_RETRY_BASE_DELAY_SECONDS))

    for attempt in range(1, max_attempts + 1):
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
            return
        except Exception as exc:
            transient = is_transient_db_error(exc)
            if transient and attempt < max_attempts:
                wait_seconds = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[BUNDLE] Transient prediction-write failure for %s (attempt %d/%d): %s. Retrying in %.2fs",
                    symbol,
                    attempt,
                    max_attempts,
                    exc,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
                continue

            logger.warning(
                "[BUNDLE] Failed to persist prediction for %s after %d attempt(s): %s",
                symbol,
                attempt,
                exc,
            )
            return


def _get_connector() -> Any:
    global _connector, _connector_blocked_until

    now = time.monotonic()
    if now < _connector_blocked_until:
        wait_seconds = round(_connector_blocked_until - now, 2)
        raise RuntimeError(f"Connector cooldown active ({wait_seconds}s)")

    if _connector is None:
        try:
            _connector = get_market_data_connector()
            _connector.ensure_login()
            _connector_blocked_until = 0.0
        except Exception:
            _connector_blocked_until = time.monotonic() + CONNECTOR_COOLDOWN_SECONDS
            raise
    return _connector


def _get_live_market_data_service() -> LiveMarketDataService:
    global _live_market_data_service

    if _live_market_data_service is None:
        _live_market_data_service = LiveMarketDataService(
            connector_provider=_get_connector,
            exchange=config.SMARTAPI_EXCHANGE,
        )
    return _live_market_data_service


async def _fetch_snapshot(symbol: str) -> dict[str, Any]:
    live_data_service = _get_live_market_data_service()
    normalized_symbol = _normalize_symbol(symbol)
    data = await live_data_service.fetch_snapshot(symbol)
    if not data:
        raise ValueError(f"LTP not available for {normalized_symbol}")

    return {
        "symbol": normalized_symbol,
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
        cancel_on_timeout=False,
    )
    if not candle:
        candle = await _with_timeout(
            get_last_candle(symbol, "1d"),
            DB_READ_TIMEOUT_SECONDS,
            None,
            f"db_snapshot_1d:{symbol}",
            cancel_on_timeout=False,
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


async def get_snapshot(symbol: str, allow_live: bool = True) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    cache_key = f"snap:v4:{normalized_symbol}"

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        return cached
    stale_cached = await _get_stale_cached_payload(cache_key)

    market_open = bool(_raw_market_status().get("is_open"))
    snapshot: dict[str, Any] | None = None
    db_snapshot = await _db_snapshot(normalized_symbol)

    # Prefer live quote during market hours.
    if market_open and allow_live:
        snapshot = await _with_timeout(
            _fetch_snapshot(symbol),
            SNAPSHOT_LIVE_TIMEOUT_SECONDS,
            None,
            f"live_snapshot:{normalized_symbol}",
        )

    if not snapshot and db_snapshot:
        snapshot = db_snapshot

    # If DB is empty after-hours, opportunistically try live quote once.
    if not snapshot and not market_open and allow_live:
        snapshot = await _with_timeout(
            _fetch_snapshot(symbol),
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
            get_history(
                symbol,
                interval="1m",
                limit=2,
                allow_live=allow_live,
            ),
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
        if isinstance(stale_cached, dict):
            snapshot = _as_partial_payload(
                stale_cached,
                source="STALE_CACHE",
                data_source=stale_cached.get("data_source") or "STALE_CACHE",
                warning="Serving last known snapshot",
            )
        else:
            snapshot = _unavailable_snapshot(normalized_symbol)

    normalized = _normalize_snapshot(snapshot)
    if snapshot.get("partial"):
        normalized["partial"] = True
        normalized["stale"] = bool(snapshot.get("stale"))
        normalized["warning"] = snapshot.get("warning")
    await _set_cached_payload(
        cache_key,
        normalized,
        ttl=SNAPSHOT_CACHE_TTL_SECONDS,
        stale_ttl=SNAPSHOT_STALE_CACHE_TTL_SECONDS,
    )
    return normalized


async def get_history(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    allow_live: bool = True,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    live_data_service = _get_live_market_data_service()
    requested_limit = max(1, min(int(limit), 1000))
    effective_limit = max(requested_limit, MIN_CANDLES_FOR_BUNDLE)
    cache_key = f"hist:v4:{normalized_symbol}:{interval}:{effective_limit}"

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        return cached
    stale_cached = await _get_stale_cached_payload(cache_key)

    db_candles = await _with_timeout(
        get_candles(normalized_symbol, interval, limit=effective_limit),
        DB_READ_TIMEOUT_SECONDS,
        [],
        f"db_candles:{normalized_symbol}:{interval}",
        cancel_on_timeout=True,
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

    if len(db_candles) >= effective_limit * 0.8 and not db_is_stale:
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
        payload = _apply_history_requirements(payload, MIN_CANDLES_FOR_BUNDLE)
        await _set_cached_payload(
            cache_key,
            payload,
            ttl=HISTORY_CACHE_TTL_SECONDS,
            stale_ttl=HISTORY_STALE_CACHE_TTL_SECONDS,
        )
        return payload

    should_try_live = len(db_candles) < effective_limit * 0.8 or db_is_stale
    if should_try_live:
        if allow_live:
            try:
                to_dt = datetime.now()

                if interval in {"1m", "3m", "5m", "15m", "30m"}:
                    from_dt = to_dt - timedelta(days=7)
                elif interval == "1h":
                    from_dt = to_dt - timedelta(days=30)
                else:
                    from_dt = to_dt - timedelta(days=365)

                rows = await _with_timeout(
                    live_data_service.fetch_history_rows(
                        symbol,
                        interval,
                        from_dt,
                        to_dt,
                        effective_limit,
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
                            await _with_timeout(
                                store_candles(normalized_symbol, interval, ohlcv),
                                DB_READ_TIMEOUT_SECONDS,
                                0,
                                f"db_store_candles:{normalized_symbol}:{interval}",
                            )
                            payload = {
                                "symbol": normalized_symbol,
                                "interval": interval,
                                "candles": ohlcv,
                                "data": ohlcv,
                                "count": len(ohlcv),
                                "source": "NSE_API",
                                "data_source": "NSE_API",
                            }
                            payload = _apply_history_requirements(payload, MIN_CANDLES_FOR_BUNDLE)
                            await _set_cached_payload(
                                cache_key,
                                payload,
                                ttl=HISTORY_CACHE_TTL_SECONDS,
                                stale_ttl=HISTORY_STALE_CACHE_TTL_SECONDS,
                            )
                            return payload
            except Exception as exc:
                logger.warning("[BUNDLE] History fetch failed for %s: %s", normalized_symbol, exc)

        yf_candles = await _with_timeout(
            asyncio.to_thread(
                _fetch_history_yfinance,
                normalized_symbol,
                interval,
                effective_limit,
            ),
            HISTORY_LIVE_TIMEOUT_SECONDS,
            [],
            f"yf_history:{normalized_symbol}:{interval}",
        )

        if isinstance(yf_candles, list) and yf_candles:
            await _with_timeout(
                store_candles(normalized_symbol, interval, yf_candles),
                DB_READ_TIMEOUT_SECONDS,
                0,
                f"db_store_yf_candles:{normalized_symbol}:{interval}",
            )
            payload = {
                "symbol": normalized_symbol,
                "interval": interval,
                "candles": yf_candles,
                "data": yf_candles,
                "count": len(yf_candles),
                "source": "YFINANCE",
                "data_source": "YFINANCE",
            }
            payload = _apply_history_requirements(payload, MIN_CANDLES_FOR_BUNDLE)
            await _set_cached_payload(
                cache_key,
                payload,
                ttl=HISTORY_CACHE_TTL_SECONDS,
                stale_ttl=HISTORY_STALE_CACHE_TTL_SECONDS,
            )
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
        payload = _apply_history_requirements(payload, MIN_CANDLES_FOR_BUNDLE)
        await _set_cached_payload(
            cache_key,
            payload,
            ttl=HISTORY_CACHE_TTL_SECONDS,
            stale_ttl=HISTORY_STALE_CACHE_TTL_SECONDS,
        )
        return payload

    if isinstance(stale_cached, dict):
        payload = _as_partial_payload(
            stale_cached,
            source="STALE_CACHE",
            data_source=stale_cached.get("data_source") or "STALE_CACHE",
            warning="Serving last cached candles",
        )
    else:
        payload = _empty_history_payload(normalized_symbol, interval)
    payload = _apply_history_requirements(payload, MIN_CANDLES_FOR_BUNDLE)
    await _set_cached_payload(
        cache_key,
        payload,
        ttl=HISTORY_CACHE_TTL_SECONDS,
        stale_ttl=HISTORY_STALE_CACHE_TTL_SECONDS,
    )
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
        symbol,
        interval=interval,
        limit=MIN_CANDLES_FOR_BUNDLE,
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

    indicators_df = None
    try:
        indicators_df = compute_indicator_frame(candles)
    except Exception as exc:
        logger.debug("[BUNDLE] Native indicators failed for %s: %s", normalized_symbol, exc)

    if indicators_df is None or indicators_df.empty:
        indicators_df = await _with_timeout(
            asyncio.to_thread(IndicatorEngine.compute_all, candles),
            INDICATORS_TIMEOUT_SECONDS,
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
    allow_live: bool = True,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    resolved_history = history or await get_history(
        symbol,
        interval="1m",
        limit=MIN_CANDLES_FOR_BUNDLE,
        allow_live=allow_live,
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
    cache_key = f"pred:v4:{normalized_symbol}:{horizon}:{last_candle_time}"

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        return cached
    stale_cached = await _get_stale_cached_payload(cache_key)

    resolved_snapshot = snapshot or await get_snapshot(symbol)
    ltp = _to_float(
        resolved_snapshot.get("price", resolved_snapshot.get("ltp", 0.0)),
        _to_float(candles[-1].get("close", 0.0), 0.0),
    )

    feature_df = None
    try:
        feature_df = compute_feature_frame(candles)
    except Exception as exc:
        logger.debug("[BUNDLE] Native feature frame failed for %s: %s", normalized_symbol, exc)

    if len(candles) < MIN_CANDLES_FOR_FEATURES:
        fallback = _prediction_fallback(normalized_symbol, ltp, "Insufficient data")
        await _set_cached_payload(
            cache_key,
            fallback,
            ttl=PREDICTION_CACHE_TTL_SECONDS,
            stale_ttl=PREDICTION_STALE_CACHE_TTL_SECONDS,
        )
        return fallback

    try:
        prediction = await _with_timeout(
            asyncio.to_thread(
                predict_symbol,
                symbol=normalized_symbol,
                timeframe=horizon,
                latest_ltp=ltp,
                features_df=feature_df,
                ohlcv=candles,
            ),
            PREDICTION_TIMEOUT_SECONDS,
            None,
            f"prediction:{normalized_symbol}:{horizon}",
        )
        if prediction is None:
            fallback = (
                _as_partial_payload(
                    stale_cached,
                    warning="Serving last cached prediction",
                )
                if isinstance(stale_cached, dict)
                else _prediction_fallback(normalized_symbol, ltp, "Prediction timed out")
            )
            await _set_cached_payload(
                cache_key,
                fallback,
                ttl=PREDICTION_CACHE_TTL_SECONDS,
                stale_ttl=PREDICTION_STALE_CACHE_TTL_SECONDS,
            )
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
            if allow_live and bool(_raw_market_status().get("is_open")):
                await _with_timeout(
                    _refresh_market_session(),
                    SNAPSHOT_LIVE_TIMEOUT_SECONDS,
                    None,
                    f"prediction_refresh:{normalized_symbol}",
                )
            refreshed_history = await get_history(
                symbol,
                interval="1m",
                limit=MIN_CANDLES_FOR_BUNDLE,
                allow_live=allow_live,
            )
            candles = refreshed_history.get("candles") or refreshed_history.get("data") or candles
            candles = _sanitize_candles(candles)
            feature_df = None
            try:
                feature_df = compute_feature_frame(candles)
            except Exception:
                feature_df = None
            prediction = await _with_timeout(
                asyncio.to_thread(
                    predict_symbol,
                    symbol=normalized_symbol,
                    timeframe=horizon,
                    latest_ltp=ltp,
                    features_df=feature_df,
                    ohlcv=candles,
                ),
                PREDICTION_TIMEOUT_SECONDS,
                None,
                f"prediction_retry:{normalized_symbol}:{horizon}",
            )
            if prediction is None:
                fallback = (
                    _as_partial_payload(
                        stale_cached,
                        warning="Serving last cached prediction",
                    )
                    if isinstance(stale_cached, dict)
                    else _prediction_fallback(normalized_symbol, ltp, "Prediction unavailable")
                )
                await _set_cached_payload(
                    cache_key,
                    fallback,
                    ttl=PREDICTION_CACHE_TTL_SECONDS,
                    stale_ttl=PREDICTION_STALE_CACHE_TTL_SECONDS,
                )
                return fallback
        except Exception as second_error:
            logger.error(
                "[BUNDLE] Prediction failed after refresh for %s: %s",
                normalized_symbol,
                second_error,
            )
            fallback = (
                _as_partial_payload(
                    stale_cached,
                    warning="Serving last cached prediction",
                )
                if isinstance(stale_cached, dict)
                else _prediction_fallback(normalized_symbol, ltp, "Prediction pipeline failed")
            )
            await _set_cached_payload(
                cache_key,
                fallback,
                ttl=PREDICTION_CACHE_TTL_SECONDS,
                stale_ttl=PREDICTION_STALE_CACHE_TTL_SECONDS,
            )
            return fallback

    normalized = _normalize_prediction(normalized_symbol, prediction, ltp)
    await _save_prediction_record(normalized_symbol, horizon, normalized)
    await _set_cached_payload(
        cache_key,
        normalized,
        ttl=PREDICTION_CACHE_TTL_SECONDS,
        stale_ttl=PREDICTION_STALE_CACHE_TTL_SECONDS,
    )
    return normalized


async def get_bundle(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    horizon: str = "15m",
    allow_live: bool = True,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    normalized_symbol = _normalize_symbol(symbol)
    effective_limit = max(_to_int(limit, 100), MIN_CANDLES_FOR_BUNDLE)
    cache_key = _bundle_cache_key(normalized_symbol, interval, effective_limit, horizon)

    _bundle_metrics["requests"] += 1

    logger.info(
        "[PIPELINE] symbol_received raw=%s normalized=%s interval=%s limit=%s effective_limit=%s horizon=%s",
        symbol,
        normalized_symbol,
        interval,
        limit,
        effective_limit,
        horizon,
    )

    cached_bundle = await get_cache(cache_key)
    if isinstance(cached_bundle, dict):
        logger.debug(
            "[BUNDLE] cache hit symbol=%s interval=%s horizon=%s",
            normalized_symbol,
            interval,
            horizon,
        )
        return cached_bundle
    stale_bundle = await _get_stale_cached_payload(cache_key)

    phase_one_results = await asyncio.gather(
        _run_component(
            "history",
            _timed_component(
                "history",
                get_history(
                    symbol,
                    interval=interval,
                    limit=effective_limit,
                    allow_live=allow_live,
                ),
            ),
        ),
        _run_component(
            "snapshot",
            _timed_component(
                "snapshot",
                get_snapshot(symbol, allow_live=allow_live),
            ),
        ),
        _run_component(
            "market_status",
            _timed_component(
                "market_status",
                get_market_status(),
            ),
        ),
    )

    component_timings: dict[str, dict[str, Any]] = {}
    history_payload = None
    snapshot_payload = None
    market_status = None

    for name, result, error, duration_ms in phase_one_results:
        component_timings[name] = {
            "status": "error" if error else "ok",
            "duration_ms": round(duration_ms, 2),
        }
        if name == "history":
            history_payload = result if not error else error
            _bundle_metrics["history_fail" if error else "history_ok"] += 1
        elif name == "snapshot":
            snapshot_payload = result if not error else error
            _bundle_metrics["snapshot_fail" if error else "snapshot_ok"] += 1
        elif name == "market_status":
            market_status = result if not error else error

    if isinstance(history_payload, Exception):
        logger.warning(
            "[BUNDLE] History stage failed for %s: %s",
            normalized_symbol,
            history_payload,
        )
        history_payload = _empty_history_payload(normalized_symbol, interval)
    elif not isinstance(history_payload, dict):
        history_payload = _empty_history_payload(normalized_symbol, interval)

    if isinstance(snapshot_payload, Exception):
        logger.warning(
            "[BUNDLE] Snapshot stage failed for %s: %s",
            normalized_symbol,
            snapshot_payload,
        )
        snapshot_payload = _unavailable_snapshot(normalized_symbol)
    elif not isinstance(snapshot_payload, dict):
        snapshot_payload = _unavailable_snapshot(normalized_symbol)

    if isinstance(market_status, Exception):
        logger.warning(
            "[BUNDLE] Market-status stage failed for %s: %s",
            normalized_symbol,
            market_status,
        )
        market_status = _empty_market_status_payload()
    elif not isinstance(market_status, dict):
        market_status = _empty_market_status_payload()

    snapshot_payload = _align_snapshot_with_history(
        normalized_symbol,
        snapshot_payload,
        history_payload,
    )

    history_candles = history_payload.get("candles", []) if isinstance(history_payload, dict) else []
    history_count = len(history_candles) if isinstance(history_candles, list) else 0

    logger.info(
        "[PIPELINE] candles_fetched symbol=%s count=%d source=%s",
        normalized_symbol,
        history_count,
        history_payload.get("data_source", "UNKNOWN"),
    )

    snapshot_payload = {
        **snapshot_payload,
        "market_status": market_status.get("state", "CLOSED"),
    }

    logger.info(
        "[PIPELINE] snapshot_ready symbol=%s ltp=%.2f source=%s",
        normalized_symbol,
        _to_float(snapshot_payload.get("ltp", 0.0), 0.0),
        snapshot_payload.get("data_source", "UNKNOWN"),
    )

    phase_two_results = await asyncio.gather(
        _run_component(
            "indicators",
            _timed_component(
                "indicators",
                get_indicators(
                    normalized_symbol,
                    interval=interval,
                    history=history_payload,
                ),
            ),
        ),
        _run_component(
            "prediction",
            _timed_component(
                "prediction",
                get_prediction(
                    normalized_symbol,
                    horizon=horizon,
                    history=history_payload,
                    snapshot=snapshot_payload,
                    allow_live=allow_live,
                ),
            ),
        ),
    )

    indicators_payload = None
    prediction_payload = None

    for name, result, error, duration_ms in phase_two_results:
        component_timings[name] = {
            "status": "error" if error else "ok",
            "duration_ms": round(duration_ms, 2),
        }
        if name == "indicators":
            indicators_payload = result if not error else error
            _bundle_metrics["indicators_fail" if error else "indicators_ok"] += 1
        elif name == "prediction":
            prediction_payload = result if not error else error
            _bundle_metrics["prediction_fail" if error else "prediction_ok"] += 1

    if isinstance(indicators_payload, Exception):
        logger.warning(
            "[BUNDLE] Indicators stage failed for %s: %s",
            normalized_symbol,
            indicators_payload,
        )
        indicators_payload = _empty_indicators_payload(normalized_symbol)
    elif not isinstance(indicators_payload, dict):
        indicators_payload = _empty_indicators_payload(normalized_symbol)

    if isinstance(prediction_payload, Exception):
        logger.warning(
            "[BUNDLE] Prediction stage failed for %s: %s",
            normalized_symbol,
            prediction_payload,
        )
        prediction_payload = _prediction_fallback(
            normalized_symbol,
            _to_float(snapshot_payload.get("ltp", 0.0), 0.0),
            "Prediction unavailable",
        )
    elif not isinstance(prediction_payload, dict):
        prediction_payload = _prediction_fallback(
            normalized_symbol,
            _to_float(snapshot_payload.get("ltp", 0.0), 0.0),
            "Prediction unavailable",
        )

    if history_count < MIN_CANDLES_FOR_BUNDLE:
        prediction_payload = _prediction_fallback(
            normalized_symbol,
            _to_float(snapshot_payload.get("ltp", 0.0), 0.0),
            f"Insufficient validated history (< {MIN_CANDLES_FOR_BUNDLE} candles)",
        )

    logger.info(
        "[PIPELINE] prediction_generated symbol=%s signal=%s confidence=%.2f",
        normalized_symbol,
        str(prediction_payload.get("signal", "HOLD")).upper(),
        _to_float(prediction_payload.get("confidence", 0.0), 0.0),
    )

    latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
    warnings: list[str] = []

    for component_name, payload, empty_warning in (
        ("history", history_payload, "History unavailable"),
        ("snapshot", snapshot_payload, "Snapshot unavailable"),
        ("prediction", prediction_payload, "Prediction unavailable"),
        ("indicators", indicators_payload, "Indicators unavailable"),
    ):
        if isinstance(payload, dict):
            warning = str(payload.get("warning") or "").strip()
            if warning:
                warnings.append(f"{component_name}: {warning}")
            elif payload.get("partial"):
                warnings.append(f"{component_name}: {empty_warning}")

    if history_count == 0:
        warnings.append("history: No candles available")

    response_payload = {
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
        "partial": bool(warnings),
        "warnings": list(dict.fromkeys(warnings)),
        "components": {
            "history": "partial" if bool(history_payload.get("partial")) else "ok",
            "snapshot": "partial" if bool(snapshot_payload.get("partial")) else "ok",
            "prediction": "partial" if bool(prediction_payload.get("partial")) else "ok",
            "indicators": "partial" if bool(indicators_payload.get("partial")) else "ok",
        },
        "component_timings": component_timings,
    }

    should_fallback_to_stale_bundle = (
        isinstance(stale_bundle, dict)
        and (
            history_count == 0
            or str(snapshot_payload.get("data_source", "UNKNOWN")).upper() == "UNAVAILABLE"
        )
    )

    if response_payload["partial"] and should_fallback_to_stale_bundle:
        fallback_bundle = dict(stale_bundle)
        fallback_bundle["partial"] = True
        fallback_bundle["warnings"] = list(
            dict.fromkeys(
                [
                    *(
                        fallback_bundle.get("warnings")
                        if isinstance(fallback_bundle.get("warnings"), list)
                        else []
                    ),
                    *response_payload["warnings"],
                    "bundle: Serving last cached bundle while dependencies recover",
                ]
            )
        )
        fallback_bundle["timestamp"] = _utc_now_iso()
        fallback_bundle["latency_ms"] = latency_ms
        fallback_bundle["component_timings"] = component_timings
        response_payload = fallback_bundle

    logger.info(
        "[BUNDLE] complete symbol=%s interval=%s horizon=%s count=%d partial=%s latency_ms=%.2f",
        normalized_symbol,
        interval,
        horizon,
        history_count,
        response_payload.get("partial"),
        latency_ms,
    )
    logger.debug(
        "[BUNDLE] components symbol=%s timings=%s",
        normalized_symbol,
        component_timings,
    )

    await _set_cached_payload(
        cache_key,
        response_payload,
        ttl=BUNDLE_CACHE_TTL_SECONDS,
        stale_ttl=BUNDLE_STALE_CACHE_TTL_SECONDS,
    )
    return response_payload


async def prewarm_bundle_cache(
    symbols: list[str] | None = None,
    interval: str = "1m",
    limit: int = 120,
    horizon: str = "15m",
    allow_live: bool = True,
) -> dict[str, Any]:
    """Warm bundle cache in parallel for frequently viewed symbols."""
    candidates = symbols or list(DEFAULT_PREWARM_SYMBOLS)
    normalized_candidates = [
        _normalize_symbol(symbol) for symbol in candidates if _normalize_symbol(symbol)
    ]
    normalized_candidates = list(dict.fromkeys(normalized_candidates))

    if not normalized_candidates:
        return {
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "symbols": [],
        }

    started_at = time.perf_counter()
    concurrency = max(1, min(config.BUNDLE_PREWARM_CONCURRENCY, len(normalized_candidates)))
    sem = asyncio.Semaphore(concurrency)

    async def _prewarm_symbol(symbol: str):
        async with sem:
            return await _with_timeout(
                get_bundle(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    horizon=horizon,
                    allow_live=allow_live,
                ),
                PREWARM_TIMEOUT_SECONDS,
                None,
                f"bundle_prewarm:{symbol}",
                cancel_on_timeout=False,
            )

    tasks = [asyncio.create_task(_prewarm_symbol(symbol)) for symbol in normalized_candidates]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    succeeded = 0
    failed = 0
    for item in results:
        if isinstance(item, Exception):
            failed += 1
        elif isinstance(item, dict):
            succeeded += 1
        else:
            failed += 1

    elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
    logger.info(
        "[BUNDLE] Prewarm complete requested=%d succeeded=%d failed=%d latency_ms=%.2f",
        len(normalized_candidates),
        succeeded,
        failed,
        elapsed_ms,
    )

    return {
        "requested": len(normalized_candidates),
        "succeeded": succeeded,
        "failed": failed,
        "symbols": normalized_candidates,
        "latency_ms": elapsed_ms,
    }
