from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from ..schemas.trading_api import TradesActiveResponse
from stockai_shared.db.db import UserModel, get_async_session
from ..trading.trading_read_service import get_active_trades as get_active_trades_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["trades"])


@router.get("/trades/active", response_model=TradesActiveResponse)
async def get_trades_active(
    limit: int = Query(100, ge=1, le=500),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        payload = await get_active_trades_data(
            session=session,
            user_id=current_user.id,
            limit=limit,
        )
        return {
            "status": "ok",
            "message": "Active trades fetched",
            "data": payload,
        }
    except Exception as exc:
        logger.error("[TRADES] active fetch failed user_id=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch active trades",
        ) from exc
