"""
15-Minute Candle Builder — aggregates raw LTP ticks into OHLCV candles.
Designed for live intraday trading signal generation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, field

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
            "time": self.start_time.strftime("%Y-%m-%d %H:%M:%S") if self.start_time else "",
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @property
    def is_empty(self) -> bool:
        return self.tick_count == 0


class CandleBuilder15m:
    """
    Accumulates ticks per symbol into 15-minute OHLCV candles.
    When a 15m boundary is crossed, the completed candle is returned.
    Also maintains a rolling history of completed candles per symbol.
    """

    def __init__(self, history_limit: int = 200):
        self._active: Dict[str, LiveCandle] = {}
        self._history: Dict[str, List[dict]] = {}
        self._history_limit = history_limit

    @staticmethod
    def _candle_start(dt: datetime) -> datetime:
        """Round down to the nearest 15-minute boundary."""
        minute = (dt.minute // 15) * 15
        return dt.replace(minute=minute, second=0, microsecond=0)

    def process_tick(self, symbol: str, price: float, volume: int = 0) -> Optional[dict]:
        """
        Feed a tick. Returns a completed 15m candle dict if a boundary was crossed,
        otherwise returns None.
        """
        now = datetime.now()
        boundary = self._candle_start(now)

        candle = self._active.get(symbol)
        completed = None

        # If we have an active candle that belongs to an older 15m window, finalize it
        if candle and candle.start_time and candle.start_time < boundary:
            if not candle.is_empty:
                completed = candle.to_dict()
                # Store in history
                if symbol not in self._history:
                    self._history[symbol] = []
                self._history[symbol].append(completed)
                if len(self._history[symbol]) > self._history_limit:
                    self._history[symbol] = self._history[symbol][-self._history_limit:]
                logger.info(f"[CANDLE-15m] Completed candle for {symbol}: O={completed['open']:.2f} H={completed['high']:.2f} L={completed['low']:.2f} C={completed['close']:.2f}")
            # Start fresh candle
            candle = None

        # Create new candle if needed
        if candle is None:
            candle = LiveCandle(start_time=boundary)
            self._active[symbol] = candle

        candle.update(price, volume)
        return completed

    def get_history(self, symbol: str, limit: int = 100) -> List[dict]:
        """Get completed 15m candle history for a symbol."""
        history = self._history.get(symbol, [])
        return history[-limit:]

    def get_current_candle(self, symbol: str) -> Optional[dict]:
        """Get the in-progress candle for a symbol."""
        candle = self._active.get(symbol)
        if candle and not candle.is_empty:
            return candle.to_dict()
        return None

    def active_symbols(self) -> list:
        return list(self._active.keys())


# Singleton instance
candle_builder_15m = CandleBuilder15m()
