from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from ..schemas.trading_api import SignalsResponse
from stockai_shared.db.db import UserModel, get_async_session
from ..trading.trading_read_service import get_signals as get_signals_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["signals"])


@router.get("/signals", response_model=SignalsResponse)
async def get_signals(
    symbol: str | None = Query(default=None, min_length=1),
    horizon: str = Query(default="15m"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        payload = await get_signals_data(
            session=session,
            user_id=current_user.id,
            symbol=symbol,
            horizon=horizon,
            limit=limit,
        )
        return {
            "status": "ok",
            "message": "Signals fetched",
            "data": payload,
        }
    except Exception as exc:
        logger.error("[SIGNALS] fetch failed user_id=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch signals",
        ) from exc
