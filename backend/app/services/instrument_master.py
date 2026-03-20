"""
Instrument Master — downloads Angel One's full instrument list and provides
symbol↔token mapping for all NSE equities.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ─── In-memory maps ───
_symbol_to_token: dict[str, str] = {}
_token_to_symbol: dict[str, str] = {}
_symbol_to_info: dict[str, dict] = {}
_load_lock = threading.Lock()
_loaded = False

# Angel One ScripMaster URL
SCRIPMASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


def load_instruments(force: bool = False) -> int:
    """
    Download ScripMaster JSON and build symbol↔token maps.
    Filters to NSE EQ instruments only.
    Returns count of loaded instruments.
    Thread-safe — only loads once unless forced.
    """
    global _symbol_to_token, _token_to_symbol, _symbol_to_info, _loaded

    with _load_lock:
        if _loaded and not force:
            return len(_symbol_to_token)

        logger.info("[INSTRUMENTS] Downloading ScripMaster from Angel One...")
        t0 = time.monotonic()

        try:
            import httpx
            resp = httpx.get(SCRIPMASTER_URL, timeout=30.0)
            resp.raise_for_status()
            instruments = resp.json()
        except Exception as e:
            logger.error(f"[INSTRUMENTS] Failed to download ScripMaster: {e}")
            # Load fallback minimal set
            _load_fallback()
            _loaded = True
            return len(_symbol_to_token)

        elapsed = (time.monotonic() - t0) * 1000
        logger.info(f"[INSTRUMENTS] Downloaded {len(instruments)} total instruments in {elapsed:.0f}ms")

        # Filter NSE equities
        sym_map = {}
        tok_map = {}
        info_map = {}

        for inst in instruments:
            exch = inst.get("exch_seg", "")
            symbol = inst.get("symbol", "")
            token = inst.get("token", "")
            name = inst.get("name", "")
            inst_type = inst.get("instrumenttype", "")
            
            # We want NSE equities: exch_seg=NSE, and symbol ends with -EQ or instrumenttype is empty/EQ
            if exch != "NSE":
                continue
            
            # Filter to EQ (equity) instruments
            # Angel One formats: symbol="RELIANCE-EQ", name="RELIANCE", instrumenttype="" or "EQ"
            if not symbol.endswith("-EQ") and inst_type not in ("", "EQ"):
                continue

            # Clean symbol: "RELIANCE-EQ" → "RELIANCE"
            clean_sym = symbol.replace("-EQ", "").strip()
            if not clean_sym or not token:
                continue

            sym_map[clean_sym] = token
            tok_map[token] = clean_sym
            info_map[clean_sym] = {
                "symbol": clean_sym,
                "token": token,
                "name": name or clean_sym,
                "tradingsymbol": symbol,  # e.g. "RELIANCE-EQ"
                "exchange": "NSE",
                "isin": inst.get("isin", ""),
                "lotsize": inst.get("lotsize", "1"),
            }

        # Also add index symbols
        for inst in instruments:
            exch = inst.get("exch_seg", "")
            if exch != "NSE":
                continue
            symbol = inst.get("symbol", "")
            token = inst.get("token", "")
            name = inst.get("name", "")
            
            if symbol in ("Nifty 50", "Nifty Bank", "NIFTY", "BANKNIFTY"):
                clean = symbol.upper().replace(" ", " ")
                if clean == "NIFTY":
                    clean = "NIFTY 50"
                sym_map[clean] = token
                tok_map[token] = clean
                info_map[clean] = {
                    "symbol": clean, "token": token, "name": name or clean,
                    "tradingsymbol": symbol, "exchange": "NSE", "isin": "", "lotsize": "1",
                }

        _symbol_to_token = sym_map
        _token_to_symbol = tok_map
        _symbol_to_info = info_map
        _loaded = True

        logger.info(f"[INSTRUMENTS] ✓ Loaded {len(sym_map)} NSE EQ instruments")
        return len(sym_map)


def _load_fallback():
    """Minimal hardcoded fallback if ScripMaster download fails."""
    global _symbol_to_token, _token_to_symbol, _symbol_to_info
    
    fallback = {
        "RELIANCE": "2881", "SBIN": "3045", "TCS": "11536", "INFY": "1594",
        "HDFCBANK": "1330", "ICICIBANK": "1333", "TATASTEEL": "895", "ITC": "1660",
        "AXISBANK": "590", "KOTAKBANK": "1922", "BHARTIARTL": "10604", "WIPRO": "3787",
        "HINDUNILVR": "1394", "LT": "11483", "MARUTI": "10999", "SUNPHARMA": "3351",
        "TATAMOTORS": "3432", "TITAN": "3506", "BAJFINANCE": "317", "HCLTECH": "7229",
        "NTPC": "11630", "POWERGRID": "14977", "ULTRACEMCO": "11532",
        "NIFTY 50": "99926000", "BANKNIFTY": "99926009",
    }
    _symbol_to_token = fallback
    _token_to_symbol = {v: k for k, v in fallback.items()}
    _symbol_to_info = {
        sym: {"symbol": sym, "token": tok, "name": sym, "tradingsymbol": f"{sym}-EQ", "exchange": "NSE", "isin": "", "lotsize": "1"}
        for sym, tok in fallback.items()
    }
    logger.warning(f"[INSTRUMENTS] Using fallback with {len(fallback)} instruments")


def get_token(symbol: str) -> Optional[str]:
    """Resolve symbol name → Angel One numeric token. e.g. RELIANCE → 2881"""
    if not _loaded:
        load_instruments()
    s = symbol.upper().replace("-EQ", "").strip()
    token = _symbol_to_token.get(s)
    if not token:
        logger.warning(f"[INSTRUMENTS] Token not found for symbol: {s}")
    return token


def get_symbol(token: str) -> Optional[str]:
    """Resolve Angel One token → symbol name. e.g. 2881 → RELIANCE"""
    if not _loaded:
        load_instruments()
    return _token_to_symbol.get(str(token))


def get_tradingsymbol(symbol: str) -> str:
    """Return NSE trading symbol. e.g. RELIANCE → RELIANCE-EQ"""
    if not _loaded:
        load_instruments()
    s = symbol.upper().replace("-EQ", "").strip()
    info = _symbol_to_info.get(s)
    if info:
        return info["tradingsymbol"]
    return f"{s}-EQ"


def search_symbols(query: str, limit: int = 20) -> list[dict]:
    """
    Search instruments by symbol or name with relevance ranking.
    Scoring: exact match (100) > prefix (80/60) > substring (40/20).
    Returns top `limit` results sorted by relevance.
    """
    if not _loaded:
        load_instruments()
    if not query:
        # Return first N symbols alphabetically
        sorted_syms = sorted(_symbol_to_info.keys())[:limit]
        return [_symbol_to_info[s] for s in sorted_syms]

    q = query.upper().strip()
    scored: list[tuple[int, str, dict]] = []

    for sym, info in _symbol_to_info.items():
        name_upper = info.get("name", "").upper()
        score = 0

        # Exact symbol match
        if sym == q:
            score = 100
        # Symbol starts with query
        elif sym.startswith(q):
            score = 80
        # Company name starts with query
        elif name_upper.startswith(q):
            score = 60
        # Symbol contains query
        elif q in sym:
            score = 40
        # Company name contains query
        elif q in name_upper:
            score = 20

        if score > 0:
            scored.append((score, sym, info))

    # Sort by score descending, then symbol alphabetically
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [item[2] for item in scored[:limit]]


def get_all_symbols() -> list[str]:
    """Return all loaded symbol names."""
    if not _loaded:
        load_instruments()
    return list(_symbol_to_token.keys())


def get_instrument_count() -> int:
    """Return count of loaded instruments."""
    return len(_symbol_to_token)
