from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes import trading as trading_routes
from app.routes.auth import get_current_user
from app.services.db import UserModel, get_async_session
from app.services.trading_read_service import get_active_trades as get_active_trades_data

router = APIRouter(prefix="/api/v1", tags=["trade-api"])


@router.post("/trade")
async def execute_trade_alias(
    symbol: str = Query(..., min_length=1),
    current_user: UserModel = Depends(get_current_user),
):
    """Alias endpoint for single-trade execution using authenticated user context."""
    return await trading_routes.execute_trade(symbol=symbol, current_user=current_user)


@router.get("/positions")
async def get_positions_alias(
    limit: int = Query(default=100, ge=1, le=500),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Alias endpoint for user-scoped position snapshot."""
    payload = await get_active_trades_data(
        session=session,
        user_id=current_user.id,
        limit=limit,
    )
    return {
        "status": "ok",
        "message": "Positions fetched",
        "data": {
            "user_id": current_user.id,
            "positions": payload.get("positions", []),
            "count": payload.get("positions_count", 0),
            "as_of": payload.get("as_of"),
        },
    }
