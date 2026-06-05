"""Compatibility shim for legacy imports.

This module now delegates to the dynamic instrument service and no longer
reads any local static JSON file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from stockai_shared.config.config import SMARTAPI_EXCHANGE
from stockai_shared.services.instrument_service import (
    get_all_symbols as _get_all_symbols,
    get_instrument_count as _get_instrument_count,
    get_symbol_by_token as _get_symbol_by_token,
    get_token_by_symbol as _get_token_by_symbol,
    get_tradingsymbol as _get_tradingsymbol,
    refresh_instruments_daily,
    search_symbols as _search_symbols,
)


def get_instrument_cache_path() -> Path:
    return Path("<dynamic-cache>")


def instrument_cache_exists() -> bool:
    return _get_instrument_count() > 0


def load_instruments(force: bool = False) -> int:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(refresh_instruments_daily(force=force))

    # If called from an already-running event loop, schedule background refresh
    # and return current in-memory count immediately.
    asyncio.create_task(refresh_instruments_daily(force=force))
    return _get_instrument_count()


def get_token_by_symbol(symbol: str, exchange: str = SMARTAPI_EXCHANGE) -> str:
    return _get_token_by_symbol(symbol=symbol, exchange=exchange)


def get_symbol_by_token(token: str, exchange: str | None = None) -> str:
    return _get_symbol_by_token(token=token, exchange=exchange)


def get_token(symbol: str) -> str:
    return get_token_by_symbol(symbol)


def get_symbol(token: str) -> str:
    return get_symbol_by_token(token)


def get_tradingsymbol(symbol: str, exchange: str = SMARTAPI_EXCHANGE) -> str:
    return _get_tradingsymbol(symbol=symbol, exchange=exchange)


def search_symbols(query: str, limit: int = 20, exchange: str = SMARTAPI_EXCHANGE) -> list[dict[str, Any]]:
    return _search_symbols(query=query, limit=limit, exchange=exchange)


def get_all_symbols(exchange: str = SMARTAPI_EXCHANGE) -> list[str]:
    return _get_all_symbols(exchange=exchange)


def get_instrument_count() -> int:
    return _get_instrument_count()
