from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import SMARTAPI_EXCHANGE
from app.connectors import get_market_data_connector, get_symbol_token
from .nifty_cache import canonical_path, ensure_nifty_dirs
from .nifty_validator import validate_nifty_history

logger = logging.getLogger(__name__)


INTERVAL_MAP: dict[str, str] = {
    "daily": "1d",
    "1h": "1h",
    "5m": "5m",
}

DEFAULT_HISTORICAL_DAYS: dict[str, int] = {
    "daily": 2000,
    "1h": 730,
    "5m": 120,
}

MAX_WINDOW_DAYS: dict[str, int] = {
    "daily": 2000,
    "1h": 730,
    "5m": 60,
}

IST = ZoneInfo("Asia/Kolkata")


class NiftyDataLoader:
    def __init__(
        self,
        symbol: str = "NIFTY 50",
        exchange: str = SMARTAPI_EXCHANGE,
        symbol_token: str | None = None,
        connector: Any | None = None,
    ) -> None:
        self.symbol = symbol
        self.exchange = exchange
        self.symbol_token = symbol_token
        self.connector = connector or get_market_data_connector()

    def resolve_symbol_token(self) -> str:
        if self.symbol_token:
            return str(self.symbol_token)
        try:
            token = get_symbol_token(self.symbol, exchange=self.exchange)
            return str(token)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to resolve token for {self.symbol} on {self.exchange}: {exc}"
            )

    def _normalize_smartapi_history(self, raw_data: list[Any]) -> pd.DataFrame:
        if not raw_data:
            return pd.DataFrame()

        if isinstance(raw_data[0], (list, tuple)):
            df = pd.DataFrame(raw_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        elif isinstance(raw_data[0], dict):
            df = pd.DataFrame(raw_data)
        else:
            df = pd.DataFrame(raw_data)

        if df.empty:
            return pd.DataFrame()

        if "timestamp" not in df.columns and "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        else:
            raise ValueError("SmartAPI history response did not include a timestamp column")

        for column in ["open", "high", "low", "close", "volume"]:
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")

        df = df.replace([pd.NA, None], pd.NA)
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        return df

    def _resolve_yfinance_symbol(self) -> str:
        normalized = str(self.symbol or "").strip().upper()
        if normalized in {"NIFTY", "NIFTY 50", "NIFTY50"}:
            return "^NSEI"
        return normalized or "^NSEI"

    def _fetch_history_yfinance(
        self,
        granularity: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
        except Exception as exc:
            logger.warning("[NIFTY] yfinance fallback unavailable: %s", exc)
            return pd.DataFrame()

        interval = INTERVAL_MAP[granularity]
        yf_symbol = self._resolve_yfinance_symbol()
        logger.info(
            "[NIFTY] Falling back to yfinance for %s (%s → %s, interval=%s)",
            yf_symbol,
            from_date.isoformat(),
            to_date.isoformat(),
            interval,
        )

        try:
            frame = yf.download(
                yf_symbol,
                start=from_date,
                end=to_date,
                interval=interval if interval != "1h" else "60m",
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception as exc:
            logger.warning("[NIFTY] yfinance download failed: %s", exc)
            return pd.DataFrame()

        if frame is None or frame.empty:
            return pd.DataFrame()

        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = ["_".join([str(part) for part in col if part]) for col in frame.columns]

        frame = frame.reset_index()
        timestamp_col = next((col for col in frame.columns if str(col).lower() in {"date", "datetime", "timestamp"}), None)
        if timestamp_col and timestamp_col != "timestamp":
            frame = frame.rename(columns={timestamp_col: "timestamp"})

        rename_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
        frame = frame.rename(columns=rename_map)
        if "timestamp" not in frame.columns:
            return pd.DataFrame()

        for column in ["open", "high", "low", "close", "volume"]:
            if column not in frame.columns:
                frame[column] = pd.NA

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        return frame[["timestamp", "open", "high", "low", "close", "volume"]]

    def _segment_date_ranges(self, start: datetime, end: datetime, max_days: int) -> list[tuple[datetime, datetime]]:
        ranges: list[tuple[datetime, datetime]] = []
        current_start = start
        while current_start < end:
            current_end = min(current_start + timedelta(days=max_days), end)
            ranges.append((current_start, current_end))
            current_start = current_end + timedelta(seconds=1)
        return ranges

    @staticmethod
    def _as_aware_ist(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=IST)
        return value.astimezone(IST)

    def _clamp_window(self, from_date: datetime, to_date: datetime) -> tuple[datetime, datetime]:
        now_ist = datetime.now(tz=IST)
        start = self._as_aware_ist(from_date)
        end = self._as_aware_ist(to_date)
        if end > now_ist:
            end = now_ist
        if start > end:
            start = end - timedelta(days=1)
        return start, end

    def fetch_history(
        self,
        granularity: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        interval = INTERVAL_MAP[granularity]
        from_date, to_date = self._clamp_window(from_date, to_date)
        token = None
        try:
            token = self.resolve_symbol_token()
        except Exception as exc:
            logger.warning("[NIFTY] Token resolution failed; using fallback data source if needed: %s", exc)
        logger.info(
            "[NIFTY] Fetching history %s %s → %s (interval=%s)",
            granularity,
            from_date.isoformat(),
            to_date.isoformat(),
            interval,
        )
        try:
            raw_data = self.connector.fetch_history(
                symbol_token=str(token or self.symbol),
                exchange=self.exchange,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
                limit=2000,
            )
            frame = self._normalize_smartapi_history(raw_data)
            if not frame.empty:
                return frame
        except Exception as exc:
            logger.warning("[NIFTY] Broker history fetch failed; falling back to yfinance: %s", exc)

        return self._fetch_history_yfinance(granularity, from_date, to_date)

    def fetch_range(
        self,
        granularity: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        from_date, to_date = self._clamp_window(from_date, to_date)
        max_days = MAX_WINDOW_DAYS[granularity]
        frames: list[pd.DataFrame] = []
        for start, end in self._segment_date_ranges(from_date, to_date, max_days):
            frame = self.fetch_history(granularity, start, end)
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        return combined

    def load_existing_canonical(self, granularity: str) -> pd.DataFrame:
        ensure_nifty_dirs()
        path = canonical_path(granularity)
        if not path.exists():
            return pd.DataFrame()
        frame = pd.read_csv(path)
        if "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        return frame
