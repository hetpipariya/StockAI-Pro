"""Symbol search route — uses instrument master for real NSE symbol data."""

import logging

from fastapi import APIRouter, Query

from stockai_shared.services.instrument_service import (get_instrument_count,
                                             get_last_refresh_at,
                                             search_symbols, suggest_symbols)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/symbols", tags=["symbols"])


@router.get("/search")
async def search(
    q: str = Query("", description="Search query"),
    exchange: str = Query("NSE", description="Exchange segment"),
):
    """Search symbols by symbol/name with fuzzy matching and suggestions."""
    query = q.strip()
    results = search_symbols(query=query, limit=50, exchange=exchange)
    suggestions = suggest_symbols(prefix=query, limit=10, exchange=exchange)
    return {
        "symbols": results,
        "suggestions": suggestions,
        "total": len(results),
        "exchange": exchange.upper(),
        "last_refresh_at": get_last_refresh_at(),
    }


@router.get("/all")
async def all_symbols(exchange: str = Query("NSE", description="Exchange segment")):
    """Return instrument count and first 100 symbols for selected exchange."""
    results = search_symbols(query="", limit=100, exchange=exchange)
    return {
        "symbols": results,
        "total": get_instrument_count(),
        "exchange": exchange.upper(),
        "last_refresh_at": get_last_refresh_at(),
    }
