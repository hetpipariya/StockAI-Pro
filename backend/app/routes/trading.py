"""
Trading API routes — user-isolated signal evaluation, paper trading, and trade journal.
Includes safety controls, order confirmation, and audit log endpoints.

SECURITY: All endpoints require JWT authentication. Each user's trading state
(capital, positions, risk) is fully isolated via TradingManager.
All DB queries filter by current_user.id.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.routes.auth import get_current_user
from app.services.db import (OrderModel, PositionModel, TradeLogModel,
                             UserModel, get_async_session)
from app.services.trade_decision_engine import evaluate_trade_decision
from app.trading.candle_builder import candle_builder_15m, candle_builder_5m
from app.trading.live_executor import get_executor
from app.trading.live_executor_5m import get_executor_5m
from app.trading.user_state import UserPosition, trading_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])


@router.get("/status")
async def trading_status(current_user: UserModel = Depends(get_current_user)):
    """Full trading engine status for the authenticated user."""
    state = await trading_manager.get_state(user_id=current_user.id)
    summary = state.get_summary()

    executor = await asyncio.to_thread(
        get_executor,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    summary["model_loaded"] = executor._model is not None
    summary["system_trading_enabled"] = config.TRADING_ENABLED
    summary["system_live_confirmed"] = config.LIVE_CONFIRMED

    return summary


@router.get("/status-5m")
async def trading_status_5m(current_user: UserModel = Depends(get_current_user)):
    """5m executor status for the authenticated user."""
    state = await trading_manager.get_state(user_id=current_user.id)
    summary = state.get_summary()

    executor = await asyncio.to_thread(
        get_executor_5m,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    summary["live_5m"] = executor.get_status(user_id=current_user.id)
    summary["live_5m_auto_execution_enabled"] = bool(
        config.LIVE_5M_AUTO_EXECUTION_ENABLED
    )
    return summary


@router.get("/signal")
async def evaluate_signal(
    symbol: str = Query(..., description="Stock symbol e.g. RELIANCE"),
    current_user: UserModel = Depends(get_current_user),
):
    """Evaluate whether a trade signal exists for the given symbol right now."""
    executor = await asyncio.to_thread(
        get_executor,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    signal = await asyncio.to_thread(
        executor.evaluate_signal,
        symbol.upper(),
        current_user.id,
    )
    if signal:
        return {"has_signal": True, **signal}
    return {
        "has_signal": False,
        "symbol": symbol.upper(),
        "message": "No trade signal at this time",
    }


@router.get("/signal-5m")
async def evaluate_signal_5m(
    symbol: str = Query(..., description="Stock symbol e.g. RELIANCE"),
    current_user: UserModel = Depends(get_current_user),
):
    """Evaluate 5m signal + regime filters for the given symbol."""
    executor = await asyncio.to_thread(
        get_executor_5m,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    signal = await asyncio.to_thread(
        executor.evaluate_signal,
        symbol.upper(),
        current_user.id,
    )
    if signal:
        return {"has_signal": True, **signal}
    return {
        "has_signal": False,
        "symbol": symbol.upper(),
        "message": "No 5m trade signal at this time",
    }


@router.post("/execute")
async def execute_trade(
    symbol: str = Query(...),
    current_user: UserModel = Depends(get_current_user),
):
    """
    Evaluate and execute a signal for the given symbol.
    The order is placed within the authenticated user's isolated trading state.
    """
    state = await trading_manager.get_state(user_id=current_user.id)

    can, reason = state.can_trade()
    if not can:
        return {"executed": False, "symbol": symbol.upper(), "message": reason}

    if state.has_position(symbol.upper()):
        return {
            "executed": False,
            "symbol": symbol.upper(),
            "message": f"Position already open for {symbol.upper()}",
        }

    decision_payload = await evaluate_trade_decision(
        symbol=symbol.upper(),
        interval="1m",
        horizon="15m",
        capital=float(current_user.starting_capital),
        risk_per_trade=0.01,
    )
    if decision_payload.get("decision", {}).get("status") != "READY":
        return {
            "executed": False,
            "symbol": symbol.upper(),
            "message": "Trade blocked by decision engine",
            "decision": decision_payload.get("decision"),
            "reasons": decision_payload.get("decision", {}).get("reasons", []),
        }

    executor = await asyncio.to_thread(
        get_executor,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    signal_data = await asyncio.to_thread(
        executor.evaluate_signal,
        symbol.upper(),
        current_user.id,
    )

    if not signal_data:
        return {
            "executed": False,
            "symbol": symbol.upper(),
            "message": "No actionable signal",
        }

    exec_result = await asyncio.to_thread(
        executor.execute_signal,
        signal_data,
        current_user.id,
    )

    if exec_result.get("status") in ("FILLED", "COMPLETED"):
        pos = UserPosition(
            user_id=current_user.id,
            symbol=signal_data["symbol"],
            direction=signal_data["signal"],
            quantity=signal_data["quantity"],
            entry_price=signal_data["entry"],
            stop_loss=signal_data["stop_loss"],
            target=signal_data["target"],
            confidence=signal_data.get("confidence", 0),
            mode=state.mode,
            reason=signal_data.get("reason", ""),
            order_id=exec_result.get("order_id", ""),
        )
        await state.open_position(pos)

    return {
        "executed": True,
        "user_id": current_user.id,
        **signal_data,
        **exec_result,
    }


@router.post("/execute-5m")
async def execute_trade_5m(
    symbol: str = Query(...),
    current_user: UserModel = Depends(get_current_user),
):
    """Evaluate and execute 5m strategy signal for the given symbol."""
    state = await trading_manager.get_state(user_id=current_user.id)

    can, reason = state.can_trade()
    if not can:
        return {"executed": False, "symbol": symbol.upper(), "message": reason}

    if state.has_position(symbol.upper()):
        return {
            "executed": False,
            "symbol": symbol.upper(),
            "message": f"Position already open for {symbol.upper()}",
        }

    decision_payload = await evaluate_trade_decision(
        symbol=symbol.upper(),
        interval="5m",
        horizon="15m",
        capital=float(current_user.starting_capital),
        risk_per_trade=0.01,
    )
    if decision_payload.get("decision", {}).get("status") != "READY":
        return {
            "executed": False,
            "symbol": symbol.upper(),
            "message": "Trade blocked by decision engine",
            "decision": decision_payload.get("decision"),
            "reasons": decision_payload.get("decision", {}).get("reasons", []),
        }

    executor = await asyncio.to_thread(
        get_executor_5m,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    signal_data = await asyncio.to_thread(
        executor.evaluate_signal,
        symbol.upper(),
        current_user.id,
    )

    if not signal_data:
        return {
            "executed": False,
            "symbol": symbol.upper(),
            "message": "No actionable 5m signal",
        }

    exec_result = await asyncio.to_thread(
        executor.execute_signal,
        signal_data,
        current_user.id,
    )

    if exec_result.get("status") in ("FILLED", "COMPLETED"):
        pos = UserPosition(
            user_id=current_user.id,
            symbol=signal_data["symbol"],
            direction=signal_data["signal"],
            quantity=signal_data["quantity"],
            entry_price=signal_data["entry"],
            stop_loss=signal_data["stop_loss"],
            target=signal_data["target"],
            confidence=signal_data.get("confidence", 0),
            mode=state.mode,
            reason=signal_data.get("reason", ""),
            order_id=exec_result.get("order_id", ""),
        )
        await state.open_position(pos)

    return {
        "executed": True,
        "user_id": current_user.id,
        **signal_data,
        **exec_result,
    }


@router.get("/positions")
async def open_positions(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List all currently open positions from DB for the authenticated user."""
    result = await session.execute(
        select(PositionModel)
        .where(PositionModel.user_id == current_user.id)
        .order_by(desc(PositionModel.opened_at))
    )
    rows = result.scalars().all()
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "direction": p.direction,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "stop_loss": p.stop_loss,
                "target": p.target,
                "mode": p.mode,
                "opened_at": str(p.opened_at),
                "updated_at": str(p.updated_at) if p.updated_at else None,
            }
            for p in rows
        ],
        "count": len(rows),
    }


@router.get("/journal")
async def trade_journal(
    limit: int = Query(50, ge=1, le=500),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return the trade journal from DB (last N entries) for the authenticated user."""
    result = await session.execute(
        select(TradeLogModel)
        .where(TradeLogModel.user_id == current_user.id)
        .order_by(desc(TradeLogModel.timestamp))
        .limit(limit)
    )
    rows = result.scalars().all()
    return {
        "trades": [
            {
                "id": log.id,
                "timestamp": str(log.timestamp),
                "event": log.event,
                "order_id": log.order_id,
                "symbol": log.symbol,
                "direction": log.direction,
                "quantity": log.quantity,
                "price": log.price,
                "stop_loss": log.stop_loss,
                "target": log.target,
                "confidence": log.confidence,
                "reason": log.reason,
                "mode": log.mode,
                "status": log.status,
                "pnl": log.pnl,
                "error": log.error,
            }
            for log in rows
        ],
        "total": len(rows),
    }


@router.get("/risk")
async def risk_status(current_user: UserModel = Depends(get_current_user)):
    """Current risk state for the authenticated user."""
    state = await trading_manager.get_state(user_id=current_user.id)
    return state.get_summary()


@router.get("/candles")
async def live_candles(
    symbol: str = Query(...),
    limit: int = Query(100, ge=1, le=200),
    current_user: UserModel = Depends(get_current_user),
):
    """Get the 15m candle history being built from live ticks."""
    history = candle_builder_15m.get_history(symbol.upper(), limit)
    current = candle_builder_15m.get_current_candle(symbol.upper())
    return {
        "symbol": symbol.upper(),
        "completed": history,
        "in_progress": current,
        "total_completed": len(history),
    }


@router.get("/candles-5m")
async def live_candles_5m(
    symbol: str = Query(...),
    limit: int = Query(100, ge=1, le=300),
    current_user: UserModel = Depends(get_current_user),
):
    """Get the 5m candle history being built from live ticks."""
    history = candle_builder_5m.get_history(symbol.upper(), limit)
    current = candle_builder_5m.get_current_candle(symbol.upper())
    return {
        "symbol": symbol.upper(),
        "completed": history,
        "in_progress": current,
        "total_completed": len(history),
    }


# ─── Order & Audit Endpoints (DB queries filtered by user_id) ───


@router.get("/orders")
async def list_orders(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List orders for the authenticated user, optionally filtered by status."""
    query = (
        select(OrderModel)
        .where(OrderModel.user_id == current_user.id)
        .order_by(desc(OrderModel.timestamp))
        .limit(limit)
    )
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
                "updated_at": str(o.updated_at) if o.updated_at else None,
            }
            for o in orders
        ],
        "total": len(orders),
    }


@router.get("/pnl")
async def daily_pnl(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Today's PnL summary from per-user DB data."""
    state = await trading_manager.get_state(user_id=current_user.id)
    summary = state.get_summary()
    positions_result = await session.execute(
        select(PositionModel).where(PositionModel.user_id == current_user.id)
    )
    positions_rows = positions_result.scalars().all()

    today_logs_result = await session.execute(
        select(TradeLogModel)
        .where(TradeLogModel.user_id == current_user.id)
        .where(TradeLogModel.pnl.is_not(None))
        .order_by(desc(TradeLogModel.timestamp))
    )
    pnl_logs = today_logs_result.scalars().all()
    realized_pnl = float(sum((log.pnl or 0.0) for log in pnl_logs))

    return {
        "capital": summary["capital"],
        "daily_pnl": realized_pnl,
        "daily_pnl_pct": summary["daily_pnl_pct"],
        "trades_today": len(pnl_logs),
        "open_positions_count": len(positions_rows),
        "halted": summary["is_halted"],
        "positions": [
            {
                "symbol": p.symbol,
                "direction": p.direction,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "stop_loss": p.stop_loss,
                "target": p.target,
                "mode": p.mode,
                "opened_at": str(p.opened_at),
            }
            for p in positions_rows
        ],
    }


@router.post("/confirm/{order_id}")
async def confirm_order(
    order_id: str,
    current_user: UserModel = Depends(get_current_user),
):
    """Confirm a PENDING_CONFIRMATION order and trigger execution."""
    executor = await asyncio.to_thread(
        get_executor,
        user_id=current_user.id,
        mode=current_user.trading_mode or config.TRADING_MODE,
        capital=current_user.starting_capital,
    )
    result = await asyncio.to_thread(
        executor.router.confirm_and_execute,
        order_id,
        current_user.id,
    )
    if result:
        return {
            "confirmed": True,
            "order_id": result.order_id,
            "status": result.status,
            "mode": result.mode,
            "error": result.error,
        }
    return {
        "confirmed": False,
        "order_id": order_id,
        "message": "Order not found or not in PENDING_CONFIRMATION state",
    }


@router.get("/logs")
async def trade_logs(
    limit: int = Query(100, ge=1, le=1000),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return the trade audit log for the authenticated user."""
    query = (
        select(TradeLogModel)
        .where(TradeLogModel.user_id == current_user.id)
        .order_by(desc(TradeLogModel.timestamp))
        .limit(limit)
    )
    result = await session.execute(query)
    logs = result.scalars().all()
    return {
        "logs": [
            {
                "id": log.id,
                "timestamp": str(log.timestamp),
                "event": log.event,
                "order_id": log.order_id,
                "symbol": log.symbol,
                "direction": log.direction,
                "quantity": log.quantity,
                "price": log.price,
                "stop_loss": log.stop_loss,
                "target": log.target,
                "confidence": log.confidence,
                "reason": log.reason,
                "mode": log.mode,
                "status": log.status,
                "pnl": log.pnl,
                "error": log.error,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.get("/safety")
async def safety_status(current_user: UserModel = Depends(get_current_user)):
    """Safety overview — user-level and system-level."""
    state = await trading_manager.get_state(user_id=current_user.id)
    summary = state.get_summary()
    return {
        "trading_enabled": config.TRADING_ENABLED,
        "trading_mode": config.TRADING_MODE,
        "live_confirmed": config.LIVE_CONFIRMED,
        "user_mode": state.mode,
        "capital": summary["capital"],
        "min_account_balance": state.risk.min_account_balance,
        "balance_ok": summary["capital"] > config.MIN_ACCOUNT_BALANCE,
        "halted": summary["is_halted"],
        "can_trade": summary["can_trade"],
        "can_trade_reason": summary["can_trade_reason"],
    }


@router.post("/kill-switch")
async def toggle_kill_switch(
    enable: bool = Query(..., description="true = enable trading, false = kill all"),
    current_user: UserModel = Depends(get_current_user),
):
    """Toggle the kill-switch for the authenticated user's trading state."""
    state = await trading_manager.get_state(user_id=current_user.id)
    state.toggle_kill_switch(halt=not enable)

    action = "ENABLED" if enable else "DISABLED"
    logger.warning(
        f"[SAFETY] User {current_user.id} ({current_user.email}) "
        f"toggled kill-switch: trading {action}"
    )
    return {
        "trading_enabled": enable,
        "user_halted": state.risk.halted,
        "message": f"Trading {action} for your account.",
    }
