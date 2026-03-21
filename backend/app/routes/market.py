"""Market data routes — snapshot, history (DB-first + SmartAPI + yfinance fill)."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

from app.connectors import SmartAPIConnector, get_symbol_token, get_tradingsymbol
from app.services.redis_client import get_cache, set_cache
from app.services.market_state import get_market_status, is_market_open
from app.services.instrument_master import get_token, search_symbols
from app.services.candle_store import store_candles, get_candles, get_candle_count, get_last_candle
from app.config import SMARTAPI_EXCHANGE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# Lazy singleton connector
_connector: SmartAPIConnector | None = None

# Base prices for mock fallback (used ONLY when market is closed AND no DB data)
_MOCK_BASE = {
    "RELIANCE": 2500, "TCS": 3800, "INFY": 1550, "HDFCBANK": 1680, "SBIN": 780,
    "ICICIBANK": 1180, "TATASTEEL": 145, "ITC": 465, "NIFTY 50": 24000, "BANKNIFTY": 52000,
}


def _mock_ohlcv(symbol: str, interval: str, limit: int) -> list[dict]:
    """Fallback mock OHLCV when SmartAPI fails AND no DB data."""
    base = _MOCK_BASE.get(symbol.upper(), 1000)
    data = []
    now = datetime.now()
    step = timedelta(minutes={"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}.get(interval, 1))
    open_p = base
    for i in range(limit):
        t = now - (limit - i) * step
        change = (random.random() - 0.48) * base * 0.002
        close = max(base * 0.9, min(base * 1.1, open_p + change))
        high = max(open_p, close) + random.random() * base * 0.001
        low = min(open_p, close) - random.random() * base * 0.001
        vol = int(10000 + random.random() * 500000)
        data.append({
            "time": t.strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(open_p, 2), "high": round(high, 2),
            "low": round(low, 2), "close": round(close, 2), "volume": vol,
        })
        open_p = close
    return data


def _parse_candle_row(r) -> dict | None:
    """Parse SmartAPI candle row (array or dict)."""
    try:
        if isinstance(r, (list, tuple)) and len(r) >= 5:
            return {
                "time": r[0], "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
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
                return {"time": t, "open": o, "high": h, "low": l_, "close": c, "volume": v}
    except (TypeError, ValueError):
        pass
    return None


def get_connector() -> SmartAPIConnector:
    global _connector
    if _connector is None:
        _connector = SmartAPIConnector()
        _connector.login()
    return _connector


async def _fetch_snapshot(symbol: str) -> dict:
    """Fetch live price snapshot via SmartAPI."""
    import asyncio
    token = get_token(symbol) or get_symbol_token(symbol)
    ts = get_tradingsymbol(symbol)
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
        "source": "smartapi",
    }


def _mock_snapshot(symbol: str) -> dict:
    """Fallback snapshot using last known DB close price."""
    base = _MOCK_BASE.get(symbol.upper(), 1000)
    return {
        "symbol": symbol, "ltp": base,
        "open": base * 0.998, "high": base * 1.01,
        "low": base * 0.995, "close": base,
        "volume": 0, "last_ts": datetime.utcnow().isoformat() + "Z",
        "source": "mock",
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
        "last_ts": candle.get("time", datetime.utcnow().isoformat()) + "Z"
            if not candle.get("time", "").endswith("Z")
            else candle.get("time"),
        "source": "database",
    }


@router.get("/status")
async def market_status():
    """Market open/close status."""
    return get_market_status()


@router.get("/snapshot")
async def get_snapshot(symbol: str = Query(..., description="e.g. RELIANCE")):
    """Current LTP. Falls back to DB last-close, then mock."""
    key = f"snap:{symbol}"
    cached = await get_cache(key)
    if cached:
        return cached
    try:
        out = await _fetch_snapshot(symbol)
        await set_cache(key, out, ttl=5)
        return out
    except Exception as e:
        logger.warning(f"[MARKET] SmartAPI snapshot failed for {symbol}: {e}")

    # Try last-known close from DB
    db_snap = await _db_snapshot(symbol)
    if db_snap:
        await set_cache(key, db_snap, ttl=30)
        return db_snap

    return _mock_snapshot(symbol)


@router.get("/history")
async def get_history(
    symbol: str = Query(...),
    interval: str = Query("1m", pattern="^(1m|3m|5m|15m|30m|1h|1d)$"),
    limit: int = Query(500, ge=1, le=1000),
):
    """
    OHLCV candle history — DB-first with SmartAPI gap-fill.
    Pipeline: Check DB → If insufficient, fetch from SmartAPI → Store in DB → Return
    """
    # 1. Check Redis cache first (short TTL)
    key = f"hist:{symbol}:{interval}:{limit}"
    cached = await get_cache(key)
    if cached:
        return cached

    # 2. Try DB
    db_candles = await get_candles(symbol, interval, limit=limit)

    # Check if DB data is stale (latest candle > 1 trading day old)
    db_is_stale = True
    if db_candles:
        try:
            last_time = datetime.strptime(db_candles[-1]["time"].split("+")[0].strip(), "%Y-%m-%d %H:%M:%S")
            db_is_stale = (datetime.now() - last_time) > timedelta(days=2)
        except (ValueError, KeyError):
            pass

    if len(db_candles) >= limit * 0.8 and not db_is_stale:
        out = {"symbol": symbol, "interval": interval, "data": db_candles, "source": "database", "count": len(db_candles)}
        await set_cache(key, out, ttl=30)
        return out

    # 3. Fetch from SmartAPI (fill gaps)
    try:
        import asyncio
        token = get_token(symbol) or get_symbol_token(symbol)
        logger.info(f"[MARKET] Fetching history: symbol={symbol}, token={token}, interval={interval}")
        conn = await asyncio.to_thread(get_connector)
        to_dt = datetime.now()
        # Use 7 days for intraday to guarantee hitting trading days
        if interval in ("1m", "3m", "5m", "15m", "30m"):
            from_dt = to_dt - timedelta(days=7)
        elif interval == "1h":
            from_dt = to_dt - timedelta(days=30)
        else:
            from_dt = to_dt - timedelta(days=365)
        rows = await asyncio.to_thread(conn.fetch_history, token, SMARTAPI_EXCHANGE, interval, from_dt, to_dt, limit)

        if rows:
            ohlcv = []
            for r in rows:
                parsed = _parse_candle_row(r)
                if parsed:
                    ohlcv.append(parsed)

            if ohlcv:
                # Store to DB for future requests
                stored = await store_candles(symbol, interval, ohlcv)
                logger.info(f"[MARKET] Stored {stored} candles for {symbol}/{interval}")

                out = {"symbol": symbol, "interval": interval, "data": ohlcv, "source": "smartapi", "count": len(ohlcv)}
                await set_cache(key, out, ttl=60)
                return out

    except Exception as e:
        logger.warning(f"[MARKET] SmartAPI history error for {symbol}: {e}")

    # 4. Fall back to DB data if we have any
    if db_candles:
        out = {"symbol": symbol, "interval": interval, "data": db_candles, "source": "database", "count": len(db_candles)}
        return out

    # 5. Last resort: mock data
    logger.warning(f"[MARKET] Using mock data for {symbol}/{interval}")
    ohlcv = _mock_ohlcv(symbol, interval, limit)
    return {"symbol": symbol, "interval": interval, "data": ohlcv, "source": "mock", "count": len(ohlcv)}


# ─── Curated top symbols for quick access ───
_TOP_SYMBOLS = [
    {"symbol": "NIFTY 50", "name": "Nifty 50 Index", "sector": "Index", "type": "index"},
    {"symbol": "BANKNIFTY", "name": "Bank Nifty Index", "sector": "Index", "type": "index"},
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "sector": "Oil & Gas", "type": "stock"},
    {"symbol": "TCS", "name": "Tata Consultancy Services", "sector": "IT", "type": "stock"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "sector": "Banking", "type": "stock"},
    {"symbol": "INFY", "name": "Infosys Ltd", "sector": "IT", "type": "stock"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "sector": "Banking", "type": "stock"},
    {"symbol": "SBIN", "name": "State Bank of India", "sector": "Banking", "type": "stock"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "sector": "Telecom", "type": "stock"},
    {"symbol": "ITC", "name": "ITC Ltd", "sector": "FMCG", "type": "stock"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank", "sector": "Banking", "type": "stock"},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "sector": "Infrastructure", "type": "stock"},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "sector": "Banking", "type": "stock"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Ltd", "sector": "Metals", "type": "stock"},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India", "sector": "Auto", "type": "stock"},
    {"symbol": "WIPRO", "name": "Wipro Ltd", "sector": "IT", "type": "stock"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd", "sector": "IT", "type": "stock"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharma Industries", "sector": "Pharma", "type": "stock"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever", "sector": "FMCG", "type": "stock"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "sector": "Auto", "type": "stock"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "sector": "NBFC", "type": "stock"},
    {"symbol": "TITAN", "name": "Titan Company Ltd", "sector": "Consumer", "type": "stock"},
    {"symbol": "NTPC", "name": "NTPC Ltd", "sector": "Power", "type": "stock"},
    {"symbol": "POWERGRID", "name": "Power Grid Corp", "sector": "Power", "type": "stock"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "sector": "Diversified", "type": "stock"},
]


@router.get("/top-symbols")
async def top_symbols():
    """Curated top market symbols — indices + NIFTY 50 blue chips."""
    return {"symbols": _TOP_SYMBOLS}


@router.get("/top-volume")
async def top_volume():
    """Top 5 stocks by trading volume (rotates on frontend)."""
    # During market hours, this would be populated from SmartAPI
    # For now, return curated high-volume stocks with mock volume
    key = "top_volume"
    cached = await get_cache(key)
    if cached:
        return cached

    top_vol = [
        {"symbol": "TATASTEEL", "name": "Tata Steel Ltd", "sector": "Metals", "volume": "42.3M", "change": 2.15},
        {"symbol": "SBIN", "name": "State Bank of India", "sector": "Banking", "volume": "38.7M", "change": 1.02},
        {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "sector": "Auto", "volume": "35.1M", "change": -0.84},
        {"symbol": "RELIANCE", "name": "Reliance Industries", "sector": "Oil & Gas", "volume": "28.9M", "change": 0.56},
        {"symbol": "ITC", "name": "ITC Ltd", "sector": "FMCG", "volume": "25.4M", "change": -0.32},
    ]
    result = {"stocks": top_vol}
    await set_cache(key, result, ttl=60)
    return result

