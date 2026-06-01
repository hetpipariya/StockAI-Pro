from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from stockai_shared.db.db import OrderModel, PositionModel, PredictionModel, TradeLogModel
from stockai_shared.cache.redis_client import get_cache, set_cache

async def get_snapshot(symbol: str) -> dict[str, Any]:
    try:
        cached = await get_cache(f"snap:v4:{symbol.upper()}")
        if isinstance(cached, dict):
            return cached
    except Exception:
        pass
    return {}

async def get_prediction(symbol: str, horizon: str = "15m") -> dict[str, Any]:
    symbol_upper = symbol.upper()
    limits = [200, 240, 100, 120]
    for limit in limits:
        key = f"bundle:v4:{symbol_upper}:1m:{limit}:{horizon}"
        try:
            bundle = await get_cache(key)
            if isinstance(bundle, dict) and bundle.get("prediction"):
                return bundle["prediction"]
        except Exception:
            pass
    return {}

logger = logging.getLogger(__name__)

TRADES_CACHE_TTL_SECONDS = 1
PORTFOLIO_CACHE_TTL_SECONDS = 1
SIGNALS_CACHE_TTL_SECONDS = 3

_OPEN_ORDER_STATUSES = {
    "OPEN",
    "PENDING",
    "PENDING_CONFIRMATION",
    "TRIGGER_PENDING",
}


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


def _position_to_payload(row: PositionModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "direction": row.direction,
        "quantity": row.quantity,
        "entry_price": row.entry_price,
        "stop_loss": row.stop_loss,
        "target": row.target,
        "mode": row.mode,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _order_to_payload(row: OrderModel) -> dict[str, Any]:
    return {
        "order_id": row.order_id,
        "symbol": row.symbol,
        "direction": row.transaction_type,
        "quantity": row.quantity,
        "filled_quantity": row.filled_quantity,
        "price": row.price,
        "status": row.status,
        "mode": row.mode,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


async def get_active_trades(
    session: AsyncSession,
    user_id: int,
    limit: int = 100,
) -> dict[str, Any]:
    cache_key = f"api:trades:active:{user_id}:{limit}"
    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        logger.debug("[CACHE] hit key=%s", cache_key)
        return cached

    logger.debug("[CACHE] miss key=%s", cache_key)

    positions_result = await session.execute(
        select(PositionModel)
        .where(PositionModel.user_id == user_id)
        .order_by(desc(PositionModel.opened_at))
        .limit(limit)
    )
    positions = positions_result.scalars().all()

    orders_result = await session.execute(
        select(OrderModel)
        .where(OrderModel.user_id == user_id)
        .where(OrderModel.status.in_(_OPEN_ORDER_STATUSES))
        .order_by(desc(OrderModel.timestamp))
        .limit(limit)
    )
    orders = orders_result.scalars().all()

    payload = {
        "user_id": user_id,
        "positions": [_position_to_payload(row) for row in positions],
        "pending_orders": [_order_to_payload(row) for row in orders],
        "positions_count": len(positions),
        "pending_orders_count": len(orders),
        "as_of": _utc_now_iso(),
    }
    await set_cache(cache_key, payload, ttl=TRADES_CACHE_TTL_SECONDS)
    return payload


async def get_portfolio_balance(
    session: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    cache_key = f"api:portfolio:balance:{user_id}"
    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        logger.debug("[CACHE] hit key=%s", cache_key)
        return cached

    logger.debug("[CACHE] miss key=%s", cache_key)

    from .user_state import trading_manager

    state = await trading_manager.get_state(user_id=user_id)
    summary = state.get_summary()

    positions_result = await session.execute(
        select(PositionModel).where(PositionModel.user_id == user_id)
    )
    positions = positions_result.scalars().all()

    realized_result = await session.execute(
        select(func.coalesce(func.sum(TradeLogModel.pnl), 0.0)).where(
            TradeLogModel.user_id == user_id,
            TradeLogModel.pnl.is_not(None),
        )
    )
    realized_pnl = _to_float(realized_result.scalar(), 0.0)

    async def _resolve_position_value(position: PositionModel) -> tuple[float, float]:
        try:
            snapshot = await asyncio.wait_for(get_snapshot(position.symbol), timeout=1.25)
        except Exception:
            snapshot = {}

        market_price = _to_float(
            snapshot.get("price", snapshot.get("ltp", position.entry_price)),
            position.entry_price,
        )
        qty = _to_int(position.quantity, 0)
        side = str(position.direction or "").upper()

        multiplier = 1.0 if side in {"BUY", "LONG"} else -1.0
        unrealized = (market_price - _to_float(position.entry_price, market_price)) * qty * multiplier
        notional = market_price * qty
        return unrealized, notional

    if positions:
        values = await asyncio.gather(
            *[_resolve_position_value(position) for position in positions],
            return_exceptions=True,
        )
    else:
        values = []

    unrealized_pnl = 0.0
    gross_exposure = 0.0
    for item in values:
        if isinstance(item, Exception):
            continue
        unrealized_pnl += _to_float(item[0], 0.0)
        gross_exposure += _to_float(item[1], 0.0)

    available_balance = _to_float(summary.get("capital", 0.0), 0.0)
    equity = available_balance + unrealized_pnl

    payload = {
        "user_id": user_id,
        "available_balance": round(available_balance, 2),
        "equity": round(equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "gross_exposure": round(gross_exposure, 2),
        "open_positions": len(positions),
        "can_trade": bool(summary.get("can_trade", False)),
        "can_trade_reason": str(summary.get("can_trade_reason", "")),
        "trading_halted": bool(summary.get("is_halted", False)),
        "as_of": _utc_now_iso(),
    }

    await set_cache(cache_key, payload, ttl=PORTFOLIO_CACHE_TTL_SECONDS)
    return payload


def _prediction_row_to_payload(row: PredictionModel) -> dict[str, Any]:
    confidence_pct = _to_int(row.confidence, 0)
    confidence = confidence_pct / 100.0 if confidence_pct > 1 else _to_float(row.confidence, 0.0)
    confidence = max(0.0, min(1.0, confidence))

    return {
        "symbol": row.symbol,
        "signal": row.signal,
        "confidence": round(confidence, 4),
        "confidence_pct": int(round(confidence * 100.0)),
        "prediction": _to_float(row.predicted_price, 0.0),
        "target": _to_float(row.target, 0.0),
        "stop_loss": _to_float(row.stop_loss, 0.0),
        "horizon": row.horizon or "15m",
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "source": "DB",
    }


def _prediction_payload_to_signal(prediction: dict[str, Any], horizon: str) -> dict[str, Any]:
    confidence = _to_float(prediction.get("confidence", 0.0), 0.0)
    if confidence > 1.0:
        confidence = confidence / 100.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "symbol": str(prediction.get("symbol", "")).upper(),
        "signal": str(prediction.get("signal", "HOLD")).upper(),
        "confidence": round(confidence, 4),
        "confidence_pct": int(round(confidence * 100.0)),
        "prediction": _to_float(prediction.get("prediction", 0.0), 0.0),
        "target": _to_float(
            prediction.get("target", prediction.get("target_price", 0.0)),
            0.0,
        ),
        "stop_loss": _to_float(prediction.get("stop_loss", 0.0), 0.0),
        "horizon": horizon,
        "timestamp": prediction.get("timestamp") or _utc_now_iso(),
        "source": str(prediction.get("data_source", "LIVE")),
    }


async def get_signals(
    session: AsyncSession,
    user_id: int,
    symbol: str | None,
    horizon: str,
    limit: int,
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper() or None
    cache_key = (
        f"api:signals:{user_id}:{normalized_symbol or 'all'}:{horizon}:{limit}"
    )

    cached = await get_cache(cache_key)
    if isinstance(cached, dict):
        logger.debug("[CACHE] hit key=%s", cache_key)
        return cached

    logger.debug("[CACHE] miss key=%s", cache_key)

    if normalized_symbol:
        prediction = await get_prediction(normalized_symbol, horizon=horizon)
        payload = {
            "signals": [_prediction_payload_to_signal(prediction, horizon)],
            "count": 1,
            "as_of": _utc_now_iso(),
        }
        await set_cache(cache_key, payload, ttl=SIGNALS_CACHE_TTL_SECONDS)
        return payload

    rows_result = await session.execute(
        select(PredictionModel)
        .where(
            or_(
                PredictionModel.user_id == user_id,
                PredictionModel.user_id.is_(None),
            )
        )
        .order_by(desc(PredictionModel.timestamp))
        .limit(limit)
    )
    rows = rows_result.scalars().all()

    signals = [_prediction_row_to_payload(row) for row in rows]

    if not signals:
        positions_result = await session.execute(
            select(PositionModel.symbol)
            .where(PositionModel.user_id == user_id)
            .order_by(desc(PositionModel.opened_at))
            .limit(min(limit, 5))
        )
        symbols = [row[0] for row in positions_result.all() if row and row[0]]

        if symbols:
            live_predictions = await asyncio.gather(
                *[get_prediction(str(item).upper(), horizon=horizon) for item in symbols],
                return_exceptions=True,
            )
            for result in live_predictions:
                if isinstance(result, Exception):
                    continue
                if isinstance(result, dict):
                    signals.append(_prediction_payload_to_signal(result, horizon))

    payload = {
        "signals": signals,
        "count": len(signals),
        "as_of": _utc_now_iso(),
    }
    await set_cache(cache_key, payload, ttl=SIGNALS_CACHE_TTL_SECONDS)
    return payload
