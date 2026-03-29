"""
Connectors package — exposes SmartAPIConnector and instrument master functions.
"""
from .smartapi_connector import SmartAPIConnector
from app.services.instrument_master import get_token, get_symbol, get_tradingsymbol, search_symbols


def get_symbol_token(symbol: str) -> str:
    """Resolve symbol → AngelOne numeric token via instrument master."""
    token = get_token(symbol)
    return token if token else symbol  # Fallback: return symbol as-is


__all__ = [
    "SmartAPIConnector",
    "get_symbol_token",
    "get_symbol",
    "get_tradingsymbol",
    "search_symbols",
]
