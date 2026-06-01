from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from stockai_shared.connectors import get_market_data_connector
from stockai_shared.services.instrument_service import (get_token_by_symbol,
                                             get_tradingsymbol,
                                             normalize_symbol_input,
                                             resolve_symbol_input)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstrumentBinding:
    symbol: str
    token: str
    exchange: str
    tradingsymbol: str


class LiveMarketDataService:
    """Resolve instruments locally and use SmartAPI only for live data calls."""

    def __init__(
        self,
        connector_provider: Callable[[], Any],
        exchange: str = "NSE",
    ) -> None:
        self._connector_provider = connector_provider
        self._exchange = str(exchange or "NSE").strip() or "NSE"

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return normalize_symbol_input(symbol)

    def resolve_instrument(self, symbol: str) -> InstrumentBinding:
        resolved_exchange, normalized = resolve_symbol_input(symbol, exchange=self._exchange)
        token = get_token_by_symbol(normalized, exchange=resolved_exchange)
        tradingsymbol = get_tradingsymbol(normalized, exchange=resolved_exchange)
        binding = InstrumentBinding(
            symbol=normalized,
            token=token,
            exchange=resolved_exchange,
            tradingsymbol=tradingsymbol,
        )
        logger.info(
            "[PIPELINE] token_resolved symbol=%s exchange=%s token=%s",
            binding.symbol,
            binding.exchange,
            binding.token,
        )
        return binding

    async def fetch_snapshot(self, symbol: str) -> dict[str, Any]:
        binding = self.resolve_instrument(symbol)
        connector = await asyncio.to_thread(self._connector_provider)

        fetch_method = getattr(connector, "fetch_latest", None) or getattr(connector, "get_ltp", None)
        if not callable(fetch_method):
            raise RuntimeError("Connector does not expose a snapshot fetch method")

        payload = await asyncio.to_thread(fetch_method, binding.token, binding.exchange, binding.tradingsymbol)
        if not payload:
            raise ValueError(f"LTP not available for {binding.symbol}")

        return {
            "symbol": binding.symbol,
            "ltp": float(payload.get("ltp", 0.0)),
            "open": float(payload.get("open", 0.0)),
            "high": float(payload.get("high", 0.0)),
            "low": float(payload.get("low", 0.0)),
            "close": float(payload.get("close", payload.get("ltp", 0.0))),
            "volume": int(payload.get("volume", 0) or 0),
        }

    async def fetch_history_rows(
        self,
        symbol: str,
        interval: str,
        from_date: Optional[datetime],
        to_date: Optional[datetime],
        limit: int,
    ) -> list[Any]:
        binding = self.resolve_instrument(symbol)
        connector = await asyncio.to_thread(self._connector_provider)

        rows = await asyncio.to_thread(
            connector.fetch_history,
            binding.token,
            binding.exchange,
            interval,
            from_date,
            to_date,
            limit,
        )
        return rows or []


def get_default_live_market_data_service() -> LiveMarketDataService:
    return LiveMarketDataService(connector_provider=get_market_data_connector)
