from __future__ import annotations

import logging
import os
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app import config
from app.services.bundle_service import get_bundle
from app.services.native_accelerators import compute_signal_filter
from app.websocket.handler import (get_last_known_price, get_last_tick_age_seconds,
                                   get_ws_state)

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.60
MIN_CANDLES = max(50, int(os.getenv("DECISION_MIN_CANDLES", "200")))
STALE_DATA_SECONDS = 3.0
DEFAULT_RISK_PER_TRADE = config.MAX_RISK_PER_TRADE_PCT
MIN_TRADE_VALUE_INR = 1000.0
MIN_RISK_REWARD = 2.0
MAX_POSITION_SIZE_CAP = 500

_state_lock = threading.Lock()
_last_valid_market_data: dict[str, dict[str, Any]] = {}
_last_market_timestamp_ms: dict[str, int] = {}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_from_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(max(0, ts_ms) / 1000.0, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp_ms(value: Any, fallback: int) -> int:
    if isinstance(value, (int, float)) and math.isfinite(value):
        parsed = float(value)
        return int(parsed if parsed > 1e12 else parsed * 1000)

    raw = str(value or "").strip()
    if not raw:
        return fallback

    try:
        parsed = float(raw)
        if math.isfinite(parsed):
            return int(parsed if parsed > 1e12 else parsed * 1000)
    except ValueError:
        pass

    if raw.endswith("Z"):
        raw = raw.replace("Z", "+00:00")

    try:
        return int(datetime.fromisoformat(raw).timestamp() * 1000)
    except Exception:
        return fallback


def _normalize_signal(value: Any) -> str:
    raw = str(value or "HOLD").strip().upper()
    if raw in {"BUY", "SELL", "HOLD"}:
        return raw
    return "HOLD"


def _normalize_confidence(value: Any) -> float:
    confidence = _to_float(value, 0.0)
    if confidence > 1.0:
        confidence = confidence / 100.0
    return max(0.0, min(1.0, confidence))


def _unique_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        clean = str(reason or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def _get_indicator(indicators: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in indicators:
            return _to_float(indicators.get(key), default)
    return default


def _derive_market_data(symbol: str, bundle: dict[str, Any]) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    now_ms = _now_ms()

    snapshot = bundle.get("snapshot") if isinstance(bundle.get("snapshot"), dict) else {}
    api_price = _to_float(snapshot.get("ltp", snapshot.get("price", 0.0)), 0.0)
    api_ts_ms = _parse_timestamp_ms(
        snapshot.get("last_ts") or snapshot.get("timestamp") or bundle.get("timestamp"),
        fallback=now_ms,
    )

    ws_state = str(get_ws_state() or "DISCONNECTED").upper()
    ws_connected = ws_state == "CONNECTED"
    ws_tick_age = float(get_last_tick_age_seconds())
    ws_price = _to_float(get_last_known_price(normalized_symbol), 0.0)

    can_use_ws = ws_connected and ws_price > 0 and math.isfinite(ws_tick_age) and ws_tick_age <= STALE_DATA_SECONDS

    chosen_price = ws_price if can_use_ws else api_price
    chosen_source = "WS" if can_use_ws else "API"

    if can_use_ws:
        chosen_ts_ms = max(0, now_ms - int(max(0.0, ws_tick_age) * 1000.0))
    else:
        chosen_ts_ms = api_ts_ms

    price_mismatch = False
    if ws_price > 0 and api_price > 0:
        gap = abs(ws_price - api_price)
        price_mismatch = gap / max(ws_price, 1e-9) >= 0.0025

    stale_ignored = False
    with _state_lock:
        previous_ts = _last_market_timestamp_ms.get(normalized_symbol, 0)
        previous_data = _last_valid_market_data.get(normalized_symbol)

        if chosen_ts_ms < previous_ts and previous_data:
            stale_ignored = True
            chosen_price = _to_float(previous_data.get("price"), chosen_price)
            chosen_ts_ms = _to_int(previous_data.get("timestamp_ms"), previous_ts)
            chosen_source = str(previous_data.get("data_source", chosen_source))

        if chosen_price > 0:
            _last_market_timestamp_ms[normalized_symbol] = max(previous_ts, chosen_ts_ms)
            _last_valid_market_data[normalized_symbol] = {
                "price": chosen_price,
                "timestamp_ms": chosen_ts_ms,
                "data_source": chosen_source,
            }
        elif previous_data:
            chosen_price = _to_float(previous_data.get("price"), 0.0)
            chosen_ts_ms = _to_int(previous_data.get("timestamp_ms"), chosen_ts_ms)
            chosen_source = str(previous_data.get("data_source", chosen_source))

    latency_ms = max(0, now_ms - chosen_ts_ms)

    return {
        "symbol": normalized_symbol,
        "price": round(chosen_price, 2),
        "timestamp": _iso_from_ms(chosen_ts_ms),
        "timestamp_ms": chosen_ts_ms,
        "data_source": chosen_source,
        "latency": latency_ms,
        "latency_ms": latency_ms,
        "is_stale": latency_ms > int(STALE_DATA_SECONDS * 1000),
        "ws_connected": ws_connected,
        "ws_state": ws_state,
        "ws_tick_age_seconds": ws_tick_age if math.isfinite(ws_tick_age) else None,
        "api_price": round(api_price, 2),
        "ws_price": round(ws_price, 2) if ws_price > 0 else None,
        "price_mismatch": price_mismatch,
        "stale_ignored": stale_ignored,
    }


def _evaluate_signal_validation(
    signal: str,
    confidence: float,
    candle_count: int,
    market_data: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []

    if signal not in {"BUY", "SELL"}:
        reasons.append("No actionable directional signal")

    if confidence < MIN_CONFIDENCE:
        reasons.append(f"Low confidence ({confidence * 100:.1f}% < 60%)")

    if candle_count < MIN_CANDLES:
        reasons.append(f"Not enough candles ({candle_count} < {MIN_CANDLES})")

    if _to_float(market_data.get("price"), 0.0) <= 0:
        reasons.append("Invalid live price")

    if not math.isfinite(confidence):
        reasons.append("Invalid confidence value")

    return {
        "valid_signal": len(reasons) == 0,
        "reason": reasons[0] if reasons else "Validated",
        "reasons": _unique_reasons(reasons),
        "confidence": confidence,
        "candle_count": candle_count,
    }


def _evaluate_market_filter(
    signal: str,
    market_price: float,
    indicators: dict[str, Any],
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    ema_fast = _get_indicator(indicators, "ema_20", "ema20", "ema9", "ema_9", default=0.0)
    ema_slow = _get_indicator(indicators, "ema_50", "ema50", "ema15", "ema_15", default=0.0)
    rsi = _get_indicator(indicators, "rsi", "rsi_14", "rsi9", default=0.0)

    reasons: list[str] = []
    trend = "SIDEWAYS"

    structure_up = False
    structure_down = False
    if len(candles) >= 3:
        c0 = candles[-3]
        c1 = candles[-2]
        c2 = candles[-1]

        h0, h1, h2 = _to_float(c0.get("high"), 0.0), _to_float(c1.get("high"), 0.0), _to_float(c2.get("high"), 0.0)
        l0, l1, l2 = _to_float(c0.get("low"), 0.0), _to_float(c1.get("low"), 0.0), _to_float(c2.get("low"), 0.0)

        structure_up = h2 > h1 > h0 and l2 > l1 > l0
        structure_down = h2 < h1 < h0 and l2 < l1 < l0

    native_filter = None
    try:
        native_filter = compute_signal_filter(
            signal=signal,
            confidence=1.0,
            trend_strength=((ema_fast - ema_slow) / max(market_price, 1e-9)) if market_price > 0 else 0.0,
            volatility=abs(ema_fast - ema_slow) / max(market_price, 1e-9) if market_price > 0 else 0.0,
            volume_ratio=_get_indicator(indicators, "volume_ratio", default=1.0),
            mtf_score=_get_indicator(indicators, "mtf_score", default=0.5),
            rr_ratio=2.0,
            market_open=True,
            stale=False,
        )
    except Exception:
        native_filter = None

    native_allow_trade = None
    native_score = None
    if isinstance(native_filter, dict):
        native_allow_trade = bool(native_filter.get("allow_trade", False))
        native_score = _to_float(native_filter.get("score", 0.0), 0.0)
        reasons.extend([str(reason) for reason in native_filter.get("reasons", [])])

    if market_price <= 0 or ema_fast <= 0 or ema_slow <= 0:
        reasons.append("Insufficient indicator quality")
        trend = "SIDEWAYS"
    else:
        ema_gap = abs(ema_fast - ema_slow) / max(market_price, 1e-9)

        if ema_gap < 0.0015:
            reasons.append("EMA compression indicates sideways structure")

        if 45.0 <= rsi <= 55.0:
            reasons.append("RSI in neutral zone (45-55)")

        if ema_fast > ema_slow and rsi >= 55.0 and structure_up and market_price >= ema_fast:
            trend = "UP"
        elif ema_fast < ema_slow and rsi <= 45.0 and structure_down and market_price <= ema_fast:
            trend = "DOWN"
        else:
            trend = "SIDEWAYS"
            reasons.append("Indicators are conflicting or trendless")

    if signal == "BUY" and trend != "UP":
        reasons.append("BUY signal blocked by non-UP trend")
    if signal == "SELL" and trend != "DOWN":
        reasons.append("SELL signal blocked by non-DOWN trend")

    tradable = trend in {"UP", "DOWN"} and not reasons
    if native_allow_trade is False:
        tradable = False

    return {
        "trend": trend,
        "tradable": tradable,
        "reasons": _unique_reasons(reasons),
        "score": native_score if native_score is not None else float(trend in {"UP", "DOWN"}),
        "ema_fast": round(ema_fast, 4),
        "ema_slow": round(ema_slow, 4),
        "rsi": round(rsi, 2),
        "structure_up": structure_up,
        "structure_down": structure_down,
    }


def _evaluate_risk(
    signal: str,
    entry: float,
    stop_loss: float,
    target: float,
    capital: float,
    risk_per_trade: float,
) -> dict[str, Any]:
    reasons: list[str] = []

    safe_capital = max(0.0, _to_float(capital, config.STARTING_CAPITAL))
    safe_risk_per_trade = max(0.001, min(0.05, _to_float(risk_per_trade, DEFAULT_RISK_PER_TRADE)))
    risk_amount = safe_capital * safe_risk_per_trade

    entry = _to_float(entry, 0.0)
    stop_loss = _to_float(stop_loss, 0.0)
    target = _to_float(target, 0.0)

    if entry <= 0:
        reasons.append("Invalid entry price")

    risk_per_unit = 0.0
    reward_per_unit = 0.0
    if signal == "BUY":
        risk_per_unit = entry - stop_loss
        reward_per_unit = target - entry
    elif signal == "SELL":
        risk_per_unit = stop_loss - entry
        reward_per_unit = entry - target
    else:
        reasons.append("Unsupported signal direction for risk calculation")

    if risk_per_unit <= 0:
        reasons.append("Stop loss does not define positive risk")

    if reward_per_unit <= 0:
        reasons.append("Target does not define positive reward")

    risk_reward_ratio = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0.0
    if risk_reward_ratio < MIN_RISK_REWARD:
        reasons.append(f"Risk/reward too low ({risk_reward_ratio:.2f} < 2.00)")

    position_size_raw = int(risk_amount / risk_per_unit) if risk_per_unit > 0 else 0
    by_capital_cap = int(safe_capital / entry) if entry > 0 else 0
    position_size_cap = min(MAX_POSITION_SIZE_CAP, max(0, by_capital_cap))
    position_size = max(0, min(position_size_raw, position_size_cap))

    if position_size <= 0:
        reasons.append("Position size resolved to zero")

    trade_value = entry * position_size
    if trade_value < MIN_TRADE_VALUE_INR:
        reasons.append(f"Trade value below minimum (INR {trade_value:.2f} < INR 1000)")

    max_loss = risk_per_unit * position_size

    return {
        "passed": len(reasons) == 0,
        "position_size": int(position_size),
        "position_size_raw": int(max(0, position_size_raw)),
        "position_size_cap": int(position_size_cap),
        "max_loss": round(max_loss, 2),
        "risk_amount": round(risk_amount, 2),
        "risk_per_trade": round(safe_risk_per_trade, 4),
        "risk_reward_ratio": round(risk_reward_ratio, 4),
        "trade_value": round(trade_value, 2),
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "reasons": _unique_reasons(reasons),
    }


async def evaluate_trade_decision(
    symbol: str,
    interval: str = "1m",
    horizon: str = "15m",
    capital: float | None = None,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        raise ValueError("Symbol is required")

    bundle = await get_bundle(
        normalized_symbol,
        interval=interval,
        limit=max(MIN_CANDLES, 120),
        horizon=horizon,
        allow_live=True,
    )

    history = bundle.get("history") if isinstance(bundle.get("history"), dict) else {}
    candles = history.get("candles") if isinstance(history.get("candles"), list) else []
    candle_count = _to_int(history.get("count"), len(candles))

    prediction = bundle.get("prediction") if isinstance(bundle.get("prediction"), dict) else {}
    signal = _normalize_signal(prediction.get("signal"))
    confidence = _normalize_confidence(prediction.get("confidence", prediction.get("confidence_pct", 0.0)))

    market_data = _derive_market_data(normalized_symbol, bundle)
    indicators = bundle.get("indicators") if isinstance(bundle.get("indicators"), dict) else {}

    validation = _evaluate_signal_validation(signal, confidence, candle_count, market_data)
    market_filter = _evaluate_market_filter(
        signal,
        _to_float(market_data.get("price"), 0.0),
        indicators,
        candles,
    )

    evaluated_capital = _to_float(capital, config.STARTING_CAPITAL)
    risk = _evaluate_risk(
        signal=signal,
        entry=_to_float(market_data.get("price"), 0.0),
        stop_loss=_to_float(prediction.get("stop_loss", prediction.get("stopLoss", 0.0)), 0.0),
        target=_to_float(prediction.get("target", prediction.get("target_price", 0.0)), 0.0),
        capital=evaluated_capital,
        risk_per_trade=risk_per_trade,
    )

    safety_warnings: list[str] = []
    if not bool(market_data.get("ws_connected")):
        safety_warnings.append("WebSocket disconnected - using API fallback")
    if bool(market_data.get("price_mismatch")) and market_data.get("data_source") == "WS":
        safety_warnings.append("API/WS price mismatch detected - WS enforced")

    decision_reasons = _unique_reasons(
        [*validation.get("reasons", []), *market_filter.get("reasons", []), *risk.get("reasons", [])]
    )
    if bool(market_data.get("is_stale")):
        decision_reasons = _unique_reasons([
            *decision_reasons,
            "Market data stale (>3s)",
        ])

    status = "READY" if not decision_reasons else "BLOCKED"

    return {
        "symbol": normalized_symbol,
        "evaluated_at": _utc_now_iso(),
        "market_data": {
            "price": market_data.get("price"),
            "timestamp": market_data.get("timestamp"),
            "data_source": market_data.get("data_source"),
            "latency": market_data.get("latency"),
            "latency_ms": market_data.get("latency_ms"),
            "ws_state": market_data.get("ws_state"),
            "ws_connected": market_data.get("ws_connected"),
            "ws_tick_age_seconds": market_data.get("ws_tick_age_seconds"),
            "is_stale": market_data.get("is_stale"),
            "price_mismatch": market_data.get("price_mismatch"),
            "api_price": market_data.get("api_price"),
            "ws_price": market_data.get("ws_price"),
        },
        "signal": {
            "signal": signal,
            "confidence": round(confidence, 4),
            "confidence_pct": int(round(confidence * 100.0)),
            "target": _to_float(prediction.get("target", prediction.get("target_price", 0.0)), 0.0),
            "stop_loss": _to_float(prediction.get("stop_loss", prediction.get("stopLoss", 0.0)), 0.0),
            "reason": str(prediction.get("reason", prediction.get("reasoning", prediction.get("explanation", ""))))[:300],
        },
        "validation": validation,
        "market_filter": market_filter,
        "risk": risk,
        "safety": {
            "stale_threshold_seconds": STALE_DATA_SECONDS,
            "reasons": safety_warnings,
        },
        "decision": {
            "status": status,
            "allow_trade": status == "READY",
            "reasons": decision_reasons,
            "warnings": safety_warnings,
        },
    }
