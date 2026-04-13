from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.routes.auth import get_current_user
from app.schemas.trading_api import PortfolioBalanceResponse
from app.services.db import UserModel, get_async_session
from app.services.trading_read_service import get_portfolio_balance as get_portfolio_balance_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["portfolio"])


@router.get("/portfolio/balance", response_model=PortfolioBalanceResponse)
async def get_portfolio_balance(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        payload = await get_portfolio_balance_data(
            session=session,
            user_id=current_user.id,
        )
        return {
            "status": "ok",
            "message": "Portfolio balance fetched",
            "data": payload,
        }
    except Exception as exc:
        logger.error(
            "[PORTFOLIO] balance fetch failed user_id=%s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch portfolio balance",
        ) from exc
