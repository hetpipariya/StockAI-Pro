"""
Connectors package — exposes broker-compatible market data connectors.
"""

from __future__ import annotations

from app.services.instrument_service import (get_symbol_by_token,
                                             get_token_by_symbol,
                                             get_tradingsymbol, search_symbols)

from .broker_router import BrokerRouter
from .smartapi_connector import SmartAPIConnector
from .upstox_connector import UpstoxConnector

_market_connector: BrokerRouter | None = None


def get_symbol_token(symbol: str, exchange: str = "NSE") -> str:
    """Resolve symbol -> Angel One token via dynamic instrument cache."""
    return get_token_by_symbol(symbol, exchange=exchange)


def get_symbol_from_token(token: str, exchange: str | None = None) -> str:
    """Resolve Angel One token -> symbol via dynamic instrument cache."""
    return get_symbol_by_token(token, exchange=exchange)


def get_market_data_connector() -> BrokerRouter:
    """Return a singleton broker router for historical/live market data."""
    global _market_connector
    if _market_connector is None:
        _market_connector = BrokerRouter()
    return _market_connector


__all__ = [
    "SmartAPIConnector",
    "UpstoxConnector",
    "BrokerRouter",
    "get_market_data_connector",
    "get_symbol_token",
    "get_symbol_from_token",
    "get_tradingsymbol",
    "search_symbols",
]
