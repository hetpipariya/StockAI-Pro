"""
Trading API routes — live signal evaluation, paper trading status, trade journal.
Includes safety controls, order confirmation, and audit log endpoints.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional

from app import config
from app.trading.live_executor import get_executor
from app.trading.candle_builder import candle_builder_15m
from app.routes.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])


@router.get("/status")
async def trading_status():
    """Full trading engine status: capital, PnL, open positions, journal."""
    executor = get_executor()
    return executor.get_status()


@router.get("/signal")
async def evaluate_signal(symbol: str = Query(..., description="Stock symbol e.g. RELIANCE")):
    """Evaluate whether a trade signal exists for the given symbol right now."""
    executor = get_executor()
    signal = executor.evaluate_signal(symbol.upper())
    if signal:
        return {"has_signal": True, **signal}
    return {
        "has_signal": False,
        "symbol": symbol.upper(),
        "message": "No trade signal at this time",
    }


@router.post("/execute")
async def execute_trade(
    symbol: str = Query(...),
    current_user = Depends(get_current_user)
):
    """Evaluate and execute a signal for the given symbol if one exists."""
    executor = get_executor()
    result = executor.on_candle_complete(symbol.upper())
    if result:
        return {"executed": True, **result}
    return {"executed": False, "symbol": symbol.upper(), "message": "No actionable signal"}


@router.get("/positions")
async def open_positions():
    """List all currently open paper/live positions."""
    executor = get_executor()
    return {"positions": executor.router.get_open_positions()}


@router.get("/journal")
async def trade_journal(limit: int = Query(50, ge=1, le=500)):
    """Return the trade journal (last N trades)."""
    executor = get_executor()
    journal = executor.router.get_journal()
    return {"trades": journal[-limit:], "total": len(journal)}


@router.get("/risk")
async def risk_status():
    """Current risk manager state."""
    executor = get_executor()
    return executor.risk.get_status()


@router.get("/candles")
async def live_candles(symbol: str = Query(...), limit: int = Query(100, ge=1, le=200)):
    """Get the 15m candle history being built from live ticks."""
    history = candle_builder_15m.get_history(symbol.upper(), limit)
    current = candle_builder_15m.get_current_candle(symbol.upper())
    return {
        "symbol": symbol.upper(),
        "completed": history,
        "in_progress": current,
        "total_completed": len(history),
    }


# ─── New Production Endpoints ───


@router.get("/orders")
async def list_orders(
    status: Optional[str] = Query(None, description="Filter by status: PENDING_CONFIRMATION, FILLED, FAILED, etc."),
    limit: int = Query(50, ge=1, le=500),
):
    """List all orders, optionally filtered by status."""
    from app.services.db import async_session, OrderModel
    from sqlalchemy import desc

    if not async_session:
        raise HTTPException(503, "Database unavailable")

    async with async_session() as session:
        from sqlalchemy.future import select
        query = select(OrderModel).order_by(desc(OrderModel.timestamp)).limit(limit)
        if status:
            query = query.where(OrderModel.status == status.upper())
        result = await session.execute(query)
        orders = result.scalars().all()
        return {
            "orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "direction": o.transaction_type,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "price": o.price,
                    "stop_loss": o.stop_loss,
                    "target": o.target,
                    "status": o.status,
                    "mode": o.mode,
                    "reason": o.reason,
                    "confidence": o.confidence,
                    "error": o.error,
                    "timestamp": str(o.timestamp),
                    "updated_at": str(o.updated_at),
                }
                for o in orders
            ],
            "total": len(orders),
        }


@router.get("/pnl")
async def daily_pnl():
    """Today's PnL summary — realized from closed trades + unrealized from open positions."""
    executor = get_executor()
    risk = executor.risk.get_status()
    positions = executor.router.get_open_positions()

    return {
        "capital": risk["capital"],
        "daily_pnl_pct": risk["daily_pnl_pct"],
        "trades_today": risk["trades_today"],
        "open_positions_count": risk["open_positions"],
        "halted": risk["halted"],
        "positions": positions,
    }


@router.post("/confirm/{order_id}")
async def confirm_order(
    order_id: str,
    current_user = Depends(get_current_user)
):
    """Confirm a PENDING_CONFIRMATION order and trigger execution."""
    executor = get_executor()
    result = executor.router.confirm_and_execute(order_id)
    if result:
        if result.status == "FILLED":
            executor.risk.on_trade_opened()
        return {
            "confirmed": True,
            "order_id": result.order_id,
            "status": result.status,
            "mode": result.mode,
            "error": result.error,
        }
    return {"confirmed": False, "order_id": order_id, "message": "Order not found or not in PENDING_CONFIRMATION state"}


@router.get("/logs")
async def trade_logs(limit: int = Query(100, ge=1, le=1000)):
    """Return the trade audit log (structured JSON entries)."""
    from app.services.db import async_session, TradeLogModel
    from sqlalchemy import desc

    if not async_session:
        raise HTTPException(503, "Database unavailable")

    async with async_session() as session:
        from sqlalchemy.future import select
        query = select(TradeLogModel).order_by(desc(TradeLogModel.timestamp)).limit(limit)
        result = await session.execute(query)
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": l.id,
                    "timestamp": str(l.timestamp),
                    "event": l.event,
                    "order_id": l.order_id,
                    "symbol": l.symbol,
                    "direction": l.direction,
                    "quantity": l.quantity,
                    "price": l.price,
                    "stop_loss": l.stop_loss,
                    "target": l.target,
                    "confidence": l.confidence,
                    "reason": l.reason,
                    "mode": l.mode,
                    "status": l.status,
                    "pnl": l.pnl,
                    "error": l.error,
                }
                for l in logs
            ],
            "total": len(logs),
        }


@router.get("/safety")
async def safety_status():
    """Safety overview — kill-switch, mode, balance checks."""
    executor = get_executor()
    risk = executor.risk.get_status()
    return {
        "trading_enabled": config.TRADING_ENABLED,
        "trading_mode": config.TRADING_MODE,
        "live_confirmed": config.LIVE_CONFIRMED,
        "effective_mode": executor.router.mode,
        "capital": risk["capital"],
        "min_account_balance": risk["min_account_balance"],
        "balance_ok": risk["capital"] > config.MIN_ACCOUNT_BALANCE,
        "halted": risk["halted"],
        "can_trade": not risk["halted"] and config.TRADING_ENABLED,
    }


@router.post("/kill-switch")
async def toggle_kill_switch(
    enable: bool = Query(..., description="true = enable trading, false = kill all"),
    current_user = Depends(get_current_user)
):
    """Toggle the trading kill-switch at runtime. Does NOT persist across restarts."""
    config.TRADING_ENABLED = enable
    state = "ENABLED" if enable else "DISABLED"
    logger.warning(f"[SAFETY] Kill-switch toggled: TRADING_ENABLED = {enable}")
    return {
        "trading_enabled": config.TRADING_ENABLED,
        "message": f"Trading {state}. This change is runtime-only and will reset on restart.",
    }
