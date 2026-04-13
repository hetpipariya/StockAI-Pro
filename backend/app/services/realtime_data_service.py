from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from app.connectors.smartapi_connector import SmartAPIConnector
from app.services.instrument_service import get_token_by_symbol, get_tradingsymbol


@dataclass(frozen=True)
class InstrumentBinding:
    symbol: str
    token: str
    tradingsymbol: str


class LiveMarketDataService:
    """Resolve instruments locally and use SmartAPI only for live data calls."""

    def __init__(
        self,
        connector_provider: Callable[[], SmartAPIConnector],
        exchange: str = "NSE",
    ) -> None:
        self._connector_provider = connector_provider
        self._exchange = str(exchange or "NSE").strip() or "NSE"

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return str(symbol or "").strip().upper()

    def resolve_instrument(self, symbol: str) -> InstrumentBinding:
        normalized = self.normalize_symbol(symbol)
        token = get_token_by_symbol(normalized, exchange=self._exchange)
        tradingsymbol = get_tradingsymbol(normalized, exchange=self._exchange)
        return InstrumentBinding(
            symbol=normalized,
            token=token,
            tradingsymbol=tradingsymbol,
        )

    async def fetch_snapshot(self, symbol: str) -> dict[str, Any]:
        binding = self.resolve_instrument(symbol)
        connector = await asyncio.to_thread(self._connector_provider)

        payload = await asyncio.to_thread(
            connector.get_ltp,
            binding.token,
            self._exchange,
            binding.tradingsymbol,
        )
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
            self._exchange,
            interval,
            from_date,
            to_date,
            limit,
        )
        return rows or []
