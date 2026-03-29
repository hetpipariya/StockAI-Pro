"""
Tick Aggregator — converts raw SmartAPI ticks into 1-minute OHLCV candles.
Thread-safe accumulator per symbol.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class _CandleAccumulator:
    """Accumulates ticks for a single symbol into a 1m candle."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.minute_key: Optional[str] = None  # "2026-02-26 10:15"
        self.open: float = 0
        self.high: float = 0
        self.low: float = 0
        self.close: float = 0
        self.volume: int = 0
        self.tick_count: int = 0

    def add_tick(self, ltp: float, volume: int = 0) -> Optional[dict]:
        """
        Add a tick. Returns a completed candle dict if the minute rolled over.
        """
        now = datetime.now()
        current_minute = now.strftime("%Y-%m-%d %H:%M")

        completed_candle = None

        if self.minute_key and current_minute != self.minute_key:
            # Minute rolled over — emit completed candle
            completed_candle = {
                "time": f"{self.minute_key}:00",
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "volume": self.volume,
            }
            # Reset for new minute
            self.minute_key = current_minute
            self.open = ltp
            self.high = ltp
            self.low = ltp
            self.close = ltp
            self.volume = volume
            self.tick_count = 1
        elif not self.minute_key:
            # First tick ever
            self.minute_key = current_minute
            self.open = ltp
            self.high = ltp
            self.low = ltp
            self.close = ltp
            self.volume = volume
            self.tick_count = 1
        else:
            # Same minute — update
            self.high = max(self.high, ltp)
            self.low = min(self.low, ltp)
            self.close = ltp
            self.volume += volume
            self.tick_count += 1

        return completed_candle

    def get_current(self) -> Optional[dict]:
        """Get the in-progress candle (not yet completed)."""
        if not self.minute_key:
            return None
        return {
            "time": f"{self.minute_key}:00",
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class TickAggregator:
    """
    Aggregates ticks into 1m candles for all symbols.
    Thread-safe. Calls on_candle callback when a candle completes.
    """

    def __init__(self):
        self._accumulators: dict[str, _CandleAccumulator] = {}
        self._lock = threading.Lock()
        self._on_candle: Optional[Callable] = None

    def set_candle_callback(self, callback: Callable):
        """Set callback for completed candles: callback(symbol, candle_dict)"""
        self._on_candle = callback

    def process_tick(self, symbol: str, ltp: float, volume: int = 0) -> Optional[dict]:
        """
        Process a raw tick. Returns completed candle if minute rolled over.
        Also triggers the on_candle callback.
        """
        with self._lock:
            if symbol not in self._accumulators:
                self._accumulators[symbol] = _CandleAccumulator(symbol)

            completed = self._accumulators[symbol].add_tick(ltp, volume)

        if completed:
            logger.info(f"[TICK] 1m candle completed: {symbol} O={completed['open']:.2f} H={completed['high']:.2f} L={completed['low']:.2f} C={completed['close']:.2f} V={completed['volume']}")

            # Trigger callback
            if self._on_candle:
                try:
                    self._on_candle(symbol, completed)
                except Exception as e:
                    logger.error(f"[TICK] Candle callback error: {e}")

        return completed

    def get_current_candle(self, symbol: str) -> Optional[dict]:
        """Get the in-progress candle for a symbol."""
        with self._lock:
            acc = self._accumulators.get(symbol)
            return acc.get_current() if acc else None

    def get_stats(self) -> dict:
        """Return aggregator stats."""
        with self._lock:
            return {
                "symbols": len(self._accumulators),
                "ticks": {sym: acc.tick_count for sym, acc in self._accumulators.items()},
            }


# Global singleton
tick_aggregator = TickAggregator()
