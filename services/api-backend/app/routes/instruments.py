from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from stockai_shared.services.instrument_service import (get_last_refresh_at,
                                             get_token_by_symbol,
                                             search_symbols,
                                             suggest_symbols)

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])
legacy_router = APIRouter(prefix="/api/instruments", tags=["instruments"])


@router.get("/search")
@legacy_router.get("/search")
async def search_instruments(
    symbol: str = Query("", description="Symbol or partial text, e.g. RELI"),
    exchange: str = Query("NSE", description="Exchange segment"),
    limit: int = Query(50, ge=1, le=100),
):
    query = symbol.strip()
    results = search_symbols(query=query, limit=limit, exchange=exchange)
    return {
        "query": query,
        "exchange": exchange.upper(),
        "results": results,
        "suggestions": suggest_symbols(prefix=query, limit=min(limit, 15), exchange=exchange),
        "total": len(results),
        "last_refresh_at": get_last_refresh_at(),
    }


@router.get("/token")
@legacy_router.get("/token")
async def get_instrument_token(
    symbol: str = Query(..., min_length=1, description="Trading symbol, e.g. RELIANCE"),
    exchange: str = Query("NSE", description="Exchange segment"),
):
    normalized_symbol = symbol.strip().upper()
    normalized_exchange = exchange.strip().upper() or "NSE"

    try:
        token = get_token_by_symbol(normalized_symbol, exchange=normalized_exchange)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "symbol": normalized_symbol,
        "token": token,
        "exchange": normalized_exchange,
        "last_refresh_at": get_last_refresh_at(),
    }


@router.get("/suggestions")
@legacy_router.get("/suggestions")
async def instrument_suggestions(
    q: str = Query("", description="Partial symbol text"),
    exchange: str = Query("NSE", description="Exchange segment"),
    limit: int = Query(10, ge=1, le=25),
):
    query = q.strip()
    return {
        "query": query,
        "exchange": exchange.upper(),
        "suggestions": suggest_symbols(prefix=query, limit=limit, exchange=exchange),
    }
