"""
Live Candle Builder — aggregates raw LTP ticks into OHLCV candles.
Supports multiple timeframes (5m, 15m) for live intraday trading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LiveCandle:
    """Single OHLCV candle being built from ticks."""

    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: int = 0
    tick_count: int = 0
    start_time: Optional[datetime] = None

    def update(self, price: float, vol: int = 0):
        if self.tick_count == 0:
            self.open = price
            self.high = price
            self.low = price
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        self.close = price
        self.volume += vol
        self.tick_count += 1

    def to_dict(self) -> dict:
        return {
            "time": (
                self.start_time.strftime("%Y-%m-%d %H:%M:%S") if self.start_time else ""
            ),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @property
    def is_empty(self) -> bool:
        return self.tick_count == 0


class CandleBuilder:
    """
    Accumulates ticks per symbol into timeframe-based OHLCV candles.
    When the timeframe boundary is crossed, the completed candle is returned.
    Also maintains a rolling history of completed candles per symbol.
    """

    def __init__(self, timeframe_minutes: int, history_limit: int = 200):
        if timeframe_minutes <= 0:
            raise ValueError("timeframe_minutes must be > 0")

        self._timeframe_minutes = timeframe_minutes
        self._timeframe_label = f"{timeframe_minutes}m"
        self._active: Dict[str, LiveCandle] = {}
        self._history: Dict[str, List[dict]] = {}
        self._history_limit = history_limit

    def _candle_start(self, dt: datetime) -> datetime:
        """Round down to the nearest timeframe boundary."""
        minute = (dt.minute // self._timeframe_minutes) * self._timeframe_minutes
        return dt.replace(minute=minute, second=0, microsecond=0)

    def process_tick(
        self, symbol: str, price: float, volume: int = 0
    ) -> Optional[dict]:
        """
        Feed a tick. Returns a completed candle dict if a boundary was crossed,
        otherwise returns None.
        """
        now = datetime.now()
        boundary = self._candle_start(now)

        candle = self._active.get(symbol)
        completed = None

        # If we have an active candle that belongs to an older timeframe window, finalize it
        if candle and candle.start_time and candle.start_time < boundary:
            if not candle.is_empty:
                completed = candle.to_dict()
                completed["timeframe"] = self._timeframe_label
                # Store in history
                if symbol not in self._history:
                    self._history[symbol] = []
                self._history[symbol].append(completed)
                if len(self._history[symbol]) > self._history_limit:
                    self._history[symbol] = self._history[symbol][
                        -self._history_limit:
                    ]
                logger.info(
                    "[CANDLE-%s] Completed candle for %s: O=%.2f H=%.2f L=%.2f C=%.2f",
                    self._timeframe_label,
                    symbol,
                    completed["open"],
                    completed["high"],
                    completed["low"],
                    completed["close"],
                )
            # Start fresh candle
            candle = None

        # Create new candle if needed
        if candle is None:
            candle = LiveCandle(start_time=boundary)
            self._active[symbol] = candle

        candle.update(price, volume)
        return completed

    def get_history(self, symbol: str, limit: int = 100) -> List[dict]:
        """Get completed candle history for a symbol."""
        history = self._history.get(symbol, [])
        return history[-limit:]

    def get_current_candle(self, symbol: str) -> Optional[dict]:
        """Get the in-progress candle for a symbol."""
        candle = self._active.get(symbol)
        if candle and not candle.is_empty:
            current = candle.to_dict()
            current["timeframe"] = self._timeframe_label
            return current
        return None

    def active_symbols(self) -> list:
        return list(self._active.keys())


class CandleBuilder15m(CandleBuilder):
    def __init__(self, history_limit: int = 200):
        super().__init__(timeframe_minutes=15, history_limit=history_limit)


class CandleBuilder5m(CandleBuilder):
    def __init__(self, history_limit: int = 240):
        super().__init__(timeframe_minutes=5, history_limit=history_limit)


# Singleton instances
candle_builder_15m = CandleBuilder15m()
candle_builder_5m = CandleBuilder5m()
