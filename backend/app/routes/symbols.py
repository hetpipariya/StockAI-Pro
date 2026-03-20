"""Symbol search route — uses instrument master for real NSE symbol data."""
import logging
from fastapi import APIRouter, Query

from app.services.instrument_master import search_symbols, get_instrument_count

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/symbols", tags=["symbols"])


@router.get("/search")
async def search(q: str = Query("", description="Search query")):
    """Search NSE symbols by name or symbol via instrument master."""
    results = search_symbols(q.strip(), limit=50)
    return {"symbols": results, "total": len(results)}


@router.get("/all")
async def all_symbols():
    """Return instrument count and first 100 symbols."""
    results = search_symbols("", limit=100)
    return {"symbols": results, "total": get_instrument_count()}
