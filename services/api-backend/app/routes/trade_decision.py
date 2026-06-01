from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from .auth import get_current_user
from stockai_shared.db.db import UserModel
from ..trading.trade_decision_engine import evaluate_trade_decision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["trade-decision"])


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _success_response(data: dict) -> dict:
    return {
        "success": True,
        "data": data,
        "error": None,
        "timestamp": _utc_now_iso(),
    }


def _error_response(code: str, message: str) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
        "timestamp": _utc_now_iso(),
    }


@router.get("/trade-decision/{symbol}")
async def get_trade_decision(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    horizon: str = Query("15m"),
    capital: float | None = Query(default=None, gt=0),
    risk_per_trade: float = Query(default=0.01, ge=0.001, le=0.05),
    current_user: UserModel = Depends(get_current_user),
):
    normalized_symbol = symbol.strip().upper()

    try:
        effective_capital = float(capital or current_user.starting_capital)
        payload = await evaluate_trade_decision(
            symbol=normalized_symbol,
            interval=interval,
            horizon=horizon,
            capital=effective_capital,
            risk_per_trade=risk_per_trade,
        )
        return _success_response(payload)
    except ValueError as exc:
        logger.warning("[DECISION] Invalid request symbol=%s error=%s", normalized_symbol, exc)
        return JSONResponse(
            status_code=400,
            content=_error_response("DECISION_BAD_REQUEST", str(exc)),
        )
    except Exception as exc:
        logger.error("[DECISION] Failed symbol=%s error=%s", normalized_symbol, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_error_response("DECISION_ERROR", "Failed to evaluate trade decision"),
        )
