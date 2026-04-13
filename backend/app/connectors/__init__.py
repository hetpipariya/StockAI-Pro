"""
Connectors package — exposes SmartAPIConnector and instrument master functions.
"""

from __future__ import annotations

from app.services.instrument_service import (get_symbol_by_token,
                                             get_token_by_symbol,
                                             get_tradingsymbol, search_symbols)

from .smartapi_connector import SmartAPIConnector


def get_symbol_token(symbol: str, exchange: str = "NSE") -> str:
    """Resolve symbol -> Angel One token via dynamic instrument cache."""
    return get_token_by_symbol(symbol, exchange=exchange)


def get_symbol_from_token(token: str, exchange: str | None = None) -> str:
    """Resolve Angel One token -> symbol via dynamic instrument cache."""
    return get_symbol_by_token(token, exchange=exchange)


__all__ = [
    "SmartAPIConnector",
    "get_symbol_token",
    "get_symbol_from_token",
    "get_tradingsymbol",
    "search_symbols",
]
