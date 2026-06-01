"""Market data routes — snapshot, history (DB-first + SmartAPI + yfinance fill)."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from stockai_shared.config.config import SMARTAPI_EXCHANGE
from stockai_shared.connectors import BrokerRouter, get_market_data_connector, get_tradingsymbol
from app.inference.candle_store import get_last_candle
from app.services.bundle_service import (get_history as get_history_service,
                                         get_market_status as get_market_status_service,
                                         get_snapshot as get_snapshot_service)
from stockai_shared.services.instrument_service import get_token_by_symbol
from stockai_shared.services.market_state import get_market_status
from stockai_shared.cache.redis_client import get_cache, set_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# Lazy singleton connector
_connector: BrokerRouter | None = None


def _parse_candle_row(r) -> dict | None:
    """Parse SmartAPI candle row (array or dict)."""
    try:
        if isinstance(r, (list, tuple)) and len(r) >= 5:
            return {
                "time": r[0],
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": int(r[5]) if len(r) > 5 else 0,
            }
        if isinstance(r, dict):
            t = r.get("0") or r.get("time")
            o = float(r.get("1", r.get("open", 0)))
            h = float(r.get("2", r.get("high", 0)))
            l_ = float(r.get("3", r.get("low", 0)))
            c = float(r.get("4", r.get("close", 0)))
            v = int(r.get("5", r.get("volume", 0)) or 0)
            if t is not None:
                return {
                    "time": t,
                    "open": o,
                    "high": h,
                    "low": l_,
                    "close": c,
                    "volume": v,
                }
    except (TypeError, ValueError):
        pass
    return None


def get_connector() -> BrokerRouter:
    global _connector
    if _connector is None:
        _connector = get_market_data_connector()
        _connector.ensure_login()
    return _connector


async def _fetch_snapshot(symbol: str) -> dict:
    """Fetch live price snapshot via SmartAPI."""
    import asyncio

    token = get_token_by_symbol(symbol, exchange=SMARTAPI_EXCHANGE)
    ts = get_tradingsymbol(symbol, exchange=SMARTAPI_EXCHANGE)
    conn = await asyncio.to_thread(get_connector)
    data = await asyncio.to_thread(conn.get_ltp, token, SMARTAPI_EXCHANGE, ts)
    if not data:
        raise ValueError(f"LTP not available for {symbol}")
    return {
        "symbol": symbol,
        "ltp": float(data.get("ltp", 0)),
        "open": float(data.get("open", 0)),
        "high": float(data.get("high", 0)),
        "low": float(data.get("low", 0)),
        "close": float(data.get("close", 0)),
        "volume": int(data.get("volume", 0) or 0),
        "last_ts": datetime.utcnow().isoformat() + "Z",
        "source": "NSE_API",
        "data_source": "NSE_API",
    }


async def _db_snapshot(symbol: str) -> dict | None:
    """Build a snapshot from the last stored candle in DB."""
    candle = await get_last_candle(symbol, "1m")
    if not candle:
        candle = await get_last_candle(symbol, "1d")
    if not candle:
        return None
    return {
        "symbol": symbol,
        "ltp": candle["close"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle.get("volume", 0),
        "last_ts": (
            candle.get("time", datetime.utcnow().isoformat()) + "Z"
            if not candle.get("time", "").endswith("Z")
            else candle.get("time")
        ),
        "source": "CACHE",
        "data_source": "CACHE",
    }


@router.get("/status")
async def market_status():
    """Market open/close status."""
    status_payload = await get_market_status_service()
    return {
        "status": "success",
        "data": status_payload.get("details", get_market_status()),
        "message": "Status OK",
    }


# Deprecated: replaced by /api/v1/bundle
@router.get("/snapshot", deprecated=True)
async def get_snapshot(symbol: str = Query(..., description="e.g. RELIANCE")):
    """Current LTP from live feed with DB fallback."""
    try:
        out = await get_snapshot_service(symbol)
    except KeyError as exc:
        message = str(exc.args[0]) if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=message) from exc

    market_status_payload = await get_market_status_service()
    out["market_status"] = market_status_payload.get("state", "CLOSED")
    return {"status": "success", "data": out, "message": "Snapshot"}


# Deprecated: replaced by /api/v1/bundle
@router.get("/history", deprecated=True)
async def get_history(
    symbol: str = Query(...),
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(100, ge=1, le=1000),
):
    """
    OHLCV candle history — DB-first with SmartAPI gap-fill.
    Pipeline: Check DB → If insufficient, fetch from SmartAPI → Store in DB → Return
    """
    try:
        out = await get_history_service(symbol=symbol, interval=interval, limit=limit)
    except KeyError as exc:
        message = str(exc.args[0]) if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=message) from exc

    return {"status": "success", "data": out, "message": "History"}


# ─── Curated top symbols for quick access ───
_TOP_SYMBOLS = [
    {
        "symbol": "NIFTY 50",
        "name": "Nifty 50 Index",
        "sector": "Index",
        "type": "index",
    },
    {
        "symbol": "BANKNIFTY",
        "name": "Bank Nifty Index",
        "sector": "Index",
        "type": "index",
    },
    {
        "symbol": "RELIANCE",
        "name": "Reliance Industries Ltd",
        "sector": "Oil & Gas",
        "type": "stock",
    },
    {
        "symbol": "TCS",
        "name": "Tata Consultancy Services",
        "sector": "IT",
        "type": "stock",
    },
    {
        "symbol": "HDFCBANK",
        "name": "HDFC Bank Ltd",
        "sector": "Banking",
        "type": "stock",
    },
    {"symbol": "INFY", "name": "Infosys Ltd", "sector": "IT", "type": "stock"},
    {
        "symbol": "ICICIBANK",
        "name": "ICICI Bank Ltd",
        "sector": "Banking",
        "type": "stock",
    },
    {
        "symbol": "SBIN",
        "name": "State Bank of India",
        "sector": "Banking",
        "type": "stock",
    },
    {
        "symbol": "BHARTIARTL",
        "name": "Bharti Airtel Ltd",
        "sector": "Telecom",
        "type": "stock",
    },
    {"symbol": "ITC", "name": "ITC Ltd", "sector": "FMCG", "type": "stock"},
    {
        "symbol": "KOTAKBANK",
        "name": "Kotak Mahindra Bank",
        "sector": "Banking",
        "type": "stock",
    },
    {
        "symbol": "LT",
        "name": "Larsen & Toubro Ltd",
        "sector": "Infrastructure",
        "type": "stock",
    },
    {
        "symbol": "AXISBANK",
        "name": "Axis Bank Ltd",
        "sector": "Banking",
        "type": "stock",
    },
    {
        "symbol": "TATASTEEL",
        "name": "Tata Steel Ltd",
        "sector": "Metals",
        "type": "stock",
    },
    {
        "symbol": "MARUTI",
        "name": "Maruti Suzuki India",
        "sector": "Auto",
        "type": "stock",
    },
    {"symbol": "WIPRO", "name": "Wipro Ltd", "sector": "IT", "type": "stock"},
    {
        "symbol": "HCLTECH",
        "name": "HCL Technologies Ltd",
        "sector": "IT",
        "type": "stock",
    },
    {
        "symbol": "SUNPHARMA",
        "name": "Sun Pharma Industries",
        "sector": "Pharma",
        "type": "stock",
    },
    {
        "symbol": "HINDUNILVR",
        "name": "Hindustan Unilever",
        "sector": "FMCG",
        "type": "stock",
    },

    {
        "symbol": "BAJFINANCE",
        "name": "Bajaj Finance Ltd",
        "sector": "NBFC",
        "type": "stock",
    },
    {
        "symbol": "TITAN",
        "name": "Titan Company Ltd",
        "sector": "Consumer",
        "type": "stock",
    },
    {"symbol": "NTPC", "name": "NTPC Ltd", "sector": "Power", "type": "stock"},
    {
        "symbol": "POWERGRID",
        "name": "Power Grid Corp",
        "sector": "Power",
        "type": "stock",
    },
    {
        "symbol": "ADANIENT",
        "name": "Adani Enterprises Ltd",
        "sector": "Diversified",
        "type": "stock",
    },
]


def _format_volume(volume: int) -> str:
    safe = max(0, int(volume or 0))
    if safe >= 1_000_000_000:
        return f"{safe / 1_000_000_000:.1f}B"
    if safe >= 1_000_000:
        return f"{safe / 1_000_000:.1f}M"
    if safe >= 1_000:
        return f"{safe / 1_000:.1f}K"
    return str(safe)


async def _build_top_volume_rows(limit: int = 5) -> list[dict]:
    top_vol: list[dict] = []
    stock_symbols = [item for item in _TOP_SYMBOLS if item.get("type") == "stock"]

    for meta in stock_symbols:
        symbol = str(meta.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        try:
            snapshot = await get_snapshot_service(symbol)
        except Exception as exc:
            logger.debug("[TOP_VOLUME] snapshot failed for %s: %s", symbol, exc)
            continue

        volume_value = int(float(snapshot.get("volume", 0) or 0))
        if volume_value <= 0:
            continue

        top_vol.append(
            {
                "symbol": symbol,
                "name": meta.get("name", symbol),
                "sector": meta.get("sector", "Unknown"),
                "volume": _format_volume(volume_value),
                "volume_raw": volume_value,
                "change": float(snapshot.get("change", 0) or 0),
                "data_source": snapshot.get("data_source", "UNKNOWN"),
                "ltp": float(snapshot.get("ltp", 0) or 0),
            }
        )

    top_vol.sort(key=lambda item: item.get("volume_raw", 0), reverse=True)
    return top_vol[: max(1, min(limit, 10))]


@router.get("/top-symbols")
async def top_symbols():
    """Curated top market symbols — indices + NIFTY 50 blue chips."""
    return {
        "status": "success",
        "data": {"symbols": _TOP_SYMBOLS},
        "message": "Top symbols",
    }


@router.get("/top-volume")
async def top_volume():
    """Top 5 stocks by real trading volume from snapshot feed."""
    key = "top_volume"
    cached = await get_cache(key)
    if cached:
        return {"status": "success", "data": cached, "message": "Top volume from cache"}

    top_vol = await _build_top_volume_rows(limit=5)

    result = {
        "stocks": [
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "sector": item["sector"],
                "volume": item["volume"],
                "change": item["change"],
                "data_source": item.get("data_source", "UNKNOWN"),
            }
            for item in top_vol
        ]
    }
    await set_cache(key, result, ttl=60)
    return {"status": "success", "data": result, "message": "Top volume"}


@router.get("/overview")
async def market_overview(top_n: int = Query(6, ge=3, le=10)):
    """Aggregated market overview for dashboard terminals."""
    key = f"market_overview:{top_n}"
    cached = await get_cache(key)
    if cached:
        return {"status": "success", "data": cached, "message": "Market overview from cache"}

    status_payload = await get_market_status_service()
    leaders = await _build_top_volume_rows(limit=top_n)

    data = {
        "market_status": status_payload.get("details", get_market_status()),
        "state": status_payload.get("state", "CLOSED"),
        "leaders": [
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "sector": item["sector"],
                "ltp": item.get("ltp", 0.0),
                "change": item.get("change", 0.0),
                "volume": item["volume"],
                "data_source": item.get("data_source", "UNKNOWN"),
            }
            for item in leaders
        ],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    await set_cache(key, data, ttl=20)
    return {"status": "success", "data": data, "message": "Market overview"}


# ─── Frontend-compatible path-based endpoints ───

@router.get("/symbols")
async def get_symbols(limit: int = Query(100, ge=1, le=500)):
    """Get available trading symbols (curated list)."""
    symbols = _TOP_SYMBOLS[:limit]
    return {
        "status": "success",
        "data": symbols,
        "message": "Symbols retrieved",
    }


@router.get("/snapshot/{symbol}")
async def get_snapshot_by_path(symbol: str):
    """Get current snapshot for a specific symbol (path-based)."""
    import re
    if not re.match(r"^[A-Za-z0-9_-]{1,30}$", symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    out = await get_snapshot_service(symbol)
    market_status_payload = await get_market_status_service()
    out["market_status"] = market_status_payload.get("state", "CLOSED")
    return {"status": "success", "data": out, "message": "Snapshot"}


@router.get("/candles/{symbol}")
async def get_candles_by_path(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get OHLCV candle history for a specific symbol (path-based)."""
    import re
    if not re.match(r"^[A-Za-z0-9_-]{1,30}$", symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    out = await get_history_service(symbol=symbol, interval=interval, limit=limit)
    return {"status": "success", "data": out, "message": "Candles"}
