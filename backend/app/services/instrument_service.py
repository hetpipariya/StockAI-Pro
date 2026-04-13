from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

import httpx
from sqlalchemy import delete, insert, select

from app import config
from app.services.db import AsyncSessionLocal, InstrumentModel, sync_session_factory
from app.services.redis_client import get_cache_sync, set_cache

logger = logging.getLogger(__name__)

_REDIS_SNAPSHOT_KEY = "instruments:snapshot:v1"
_REDIS_EXCHANGE_KEY_PREFIX = "instruments:exchange:v1"


@dataclass(frozen=True)
class InstrumentRecord:
    symbol: str
    token: str
    exchange: str
    tradingsymbol: str
    name: str
    instrument_type: str
    expiry: str
    strike: Optional[float]
    lot_size: int
    tick_size: Optional[float]
    isin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "token": self.token,
            "exchange": self.exchange,
            "tradingsymbol": self.tradingsymbol,
            "name": self.name,
            "instrument_type": self.instrument_type,
            "expiry": self.expiry,
            "strike": self.strike,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
            "isin": self.isin,
        }


class InstrumentService:
    """Dynamic instrument token service backed by OpenAPI + Redis + DB."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._refresh_lock = asyncio.Lock()

        self._loaded = False
        self._last_refresh_at: Optional[str] = None

        self._records: list[InstrumentRecord] = []
        self._symbol_to_token: dict[str, str] = {}
        self._symbol_to_info: dict[str, dict[str, Any]] = {}
        self._token_to_symbol: dict[str, str] = {}
        self._token_to_symbol_any: dict[str, str] = {}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_exchange(exchange: str) -> str:
        normalized = str(exchange or "NSE").strip().upper()
        return normalized or "NSE"

    @staticmethod
    def _normalize_token(token: Any) -> str:
        return str(token or "").strip()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = str(symbol or "").strip().upper()
        if normalized.endswith("-EQ"):
            normalized = normalized[:-3]
        return normalized

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _symbol_key(cls, exchange: str, symbol: str) -> str:
        return f"{cls._normalize_exchange(exchange)}:{cls._normalize_symbol(symbol)}"

    @classmethod
    def _token_key(cls, exchange: str, token: str) -> str:
        return f"{cls._normalize_exchange(exchange)}:{cls._normalize_token(token)}"

    @staticmethod
    def _priority(record: InstrumentRecord) -> int:
        score = 0
        if record.tradingsymbol.endswith("-EQ"):
            score += 120
        if record.instrument_type in {"", "EQ", "EQUITY"}:
            score += 80
        if record.exchange in {"NSE", "BSE"}:
            score += 20
        if record.symbol in {"NIFTY 50", "BANKNIFTY"}:
            score += 10
        return score

    def _parse_payload(self, payload: list[dict[str, Any]]) -> list[InstrumentRecord]:
        records: list[InstrumentRecord] = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            exchange = self._normalize_exchange(
                item.get("exch_seg")
                or item.get("exchange")
                or item.get("exchange_segment")
                or ""
            )
            raw_symbol = str(
                item.get("symbol")
                or item.get("tradingsymbol")
                or item.get("trading_symbol")
                or ""
            ).strip()
            token = self._normalize_token(
                item.get("token") or item.get("symboltoken") or item.get("instrument_token")
            )

            if not exchange or not raw_symbol or not token:
                continue

            tradingsymbol = raw_symbol.upper()
            symbol = self._normalize_symbol(raw_symbol)
            if not symbol:
                continue

            name = str(item.get("name") or symbol).strip() or symbol
            instrument_type = str(
                item.get("instrumenttype") or item.get("instrument_type") or ""
            ).strip().upper()

            record = InstrumentRecord(
                symbol=symbol,
                token=token,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                name=name,
                instrument_type=instrument_type,
                expiry=str(item.get("expiry") or "").strip(),
                strike=self._safe_float(item.get("strike")),
                lot_size=max(1, self._safe_int(item.get("lotsize") or item.get("lot_size"), 1)),
                tick_size=self._safe_float(item.get("tick_size") or item.get("ticksize")),
                isin=str(item.get("isin") or "").strip(),
            )
            records.append(record)

        return records

    def _dedupe_records(self, records: list[InstrumentRecord]) -> list[InstrumentRecord]:
        """Keep a deterministic, best-ranked set unique by symbol and token."""
        if not records:
            return []

        prioritized = sorted(
            records,
            key=lambda record: (
                -self._priority(record),
                record.exchange,
                record.symbol,
                record.token,
            ),
        )

        seen_symbol_keys: set[str] = set()
        seen_token_keys: set[str] = set()
        deduped: list[InstrumentRecord] = []

        for record in prioritized:
            s_key = self._symbol_key(record.exchange, record.symbol)
            t_key = self._token_key(record.exchange, record.token)
            if s_key in seen_symbol_keys or t_key in seen_token_keys:
                continue

            seen_symbol_keys.add(s_key)
            seen_token_keys.add(t_key)
            deduped.append(record)

        return deduped

    def _apply_records(self, records: list[InstrumentRecord], source: str) -> int:
        symbol_to_token: dict[str, str] = {}
        symbol_to_info: dict[str, dict[str, Any]] = {}
        symbol_ranks: dict[str, int] = {}

        token_to_symbol: dict[str, str] = {}
        token_to_symbol_ranks: dict[str, int] = {}
        token_to_symbol_any: dict[str, str] = {}
        token_any_ranks: dict[str, int] = {}

        for record in records:
            rank = self._priority(record)

            s_key = self._symbol_key(record.exchange, record.symbol)
            if rank >= symbol_ranks.get(s_key, -1):
                symbol_ranks[s_key] = rank
                symbol_to_token[s_key] = record.token
                symbol_to_info[s_key] = record.to_dict()

            alias = self._normalize_symbol(record.tradingsymbol)
            if alias and alias != record.symbol:
                alias_key = self._symbol_key(record.exchange, alias)
                alias_rank = rank - 1
                if alias_rank >= symbol_ranks.get(alias_key, -1):
                    alias_info = dict(record.to_dict())
                    alias_info["symbol"] = alias
                    symbol_ranks[alias_key] = alias_rank
                    symbol_to_token[alias_key] = record.token
                    symbol_to_info[alias_key] = alias_info

            t_key = self._token_key(record.exchange, record.token)
            if rank >= token_to_symbol_ranks.get(t_key, -1):
                token_to_symbol_ranks[t_key] = rank
                token_to_symbol[t_key] = record.symbol

            if rank >= token_any_ranks.get(record.token, -1):
                token_any_ranks[record.token] = rank
                token_to_symbol_any[record.token] = record.symbol

        self._inject_index_aliases(symbol_to_token, symbol_to_info)

        with self._lock:
            self._records = records
            self._symbol_to_token = symbol_to_token
            self._symbol_to_info = symbol_to_info
            self._token_to_symbol = token_to_symbol
            self._token_to_symbol_any = token_to_symbol_any
            self._loaded = bool(symbol_to_token)
            self._last_refresh_at = self._now_iso()
            count = len(symbol_to_token)

        logger.info(
            "[INSTRUMENTS] Applied %d mapped symbols from %s source",
            count,
            source,
        )
        return count

    def _inject_index_aliases(
        self,
        symbol_to_token: dict[str, str],
        symbol_to_info: dict[str, dict[str, Any]],
    ) -> None:
        alias_pairs = (
            ("NSE:NIFTY", "NSE:NIFTY 50"),
            ("NSE:NIFTY 50", "NSE:NIFTY"),
            ("NSE:NIFTY BANK", "NSE:BANKNIFTY"),
            ("NSE:BANKNIFTY", "NSE:NIFTY BANK"),
        )
        for target_key, source_key in alias_pairs:
            if target_key in symbol_to_token:
                continue
            token = symbol_to_token.get(source_key)
            info = symbol_to_info.get(source_key)
            if not token or not info:
                continue
            cloned = dict(info)
            cloned["symbol"] = target_key.split(":", 1)[1]
            symbol_to_token[target_key] = token
            symbol_to_info[target_key] = cloned

    async def fetch_all_instruments_from_api(self) -> list[dict[str, Any]]:
        """Fetch full instrument master from Angel One OpenAPI endpoint."""
        retries = max(1, int(config.INSTRUMENT_FETCH_RETRIES))
        timeout_seconds = max(5.0, float(config.INSTRUMENT_FETCH_TIMEOUT_SECONDS))

        headers = {
            "Accept": "application/json",
            "User-Agent": "stockai-pro-instrument-service/1.0",
        }

        # Keep credentials server-side only (never exposed to frontend).
        if config.SMARTAPI_API_KEY:
            headers["X-PrivateKey"] = config.SMARTAPI_API_KEY
        if config.SMARTAPI_CLIENT_ID:
            headers["X-ClientCode"] = config.SMARTAPI_CLIENT_ID

        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.get(config.INSTRUMENT_MASTER_URL, headers=headers)
                    response.raise_for_status()
                    payload = response.json()

                if not isinstance(payload, list):
                    raise ValueError("Instrument API payload must be a JSON array")

                logger.info(
                    "[INSTRUMENTS] Fetched %d rows from Angel OpenAPI (attempt %d/%d)",
                    len(payload),
                    attempt,
                    retries,
                )
                return payload
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "[INSTRUMENTS] Fetch attempt %d/%d failed: %s",
                    attempt,
                    retries,
                    exc,
                )
                if attempt < retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 8))

        raise RuntimeError(
            "Failed to fetch instrument master from Angel One OpenAPI"
        ) from last_error

    async def _persist_to_redis(self, records: list[InstrumentRecord]) -> None:
        try:
            ttl = max(60, int(config.INSTRUMENT_REDIS_TTL_SECONDS))
            snapshot_payload = {
                "updated_at": self._now_iso(),
                "records": [record.to_dict() for record in records],
            }
            await set_cache(_REDIS_SNAPSHOT_KEY, snapshot_payload, ttl=ttl)

            exchange_payload: dict[str, dict[str, Any]] = {}
            with self._lock:
                for key, token in self._symbol_to_token.items():
                    exchange, symbol = key.split(":", 1)
                    bucket = exchange_payload.setdefault(
                        exchange,
                        {
                            "symbol_to_token": {},
                            "token_to_symbol": {},
                            "symbol_to_info": {},
                        },
                    )
                    bucket["symbol_to_token"][symbol] = token

                for key, symbol in self._token_to_symbol.items():
                    exchange, token = key.split(":", 1)
                    bucket = exchange_payload.setdefault(
                        exchange,
                        {
                            "symbol_to_token": {},
                            "token_to_symbol": {},
                            "symbol_to_info": {},
                        },
                    )
                    bucket["token_to_symbol"][token] = symbol

                for key, info in self._symbol_to_info.items():
                    exchange, symbol = key.split(":", 1)
                    bucket = exchange_payload.setdefault(
                        exchange,
                        {
                            "symbol_to_token": {},
                            "token_to_symbol": {},
                            "symbol_to_info": {},
                        },
                    )
                    bucket["symbol_to_info"][symbol] = info

            for exchange, payload in exchange_payload.items():
                await set_cache(f"{_REDIS_EXCHANGE_KEY_PREFIX}:{exchange}", payload, ttl=ttl)

            logger.info("[INSTRUMENTS] Redis cache updated (ttl=%ss)", ttl)
        except Exception as exc:
            logger.warning("[INSTRUMENTS] Redis persistence failed: %s", exc)

    async def _persist_to_db(self, records: list[InstrumentRecord]) -> None:
        if AsyncSessionLocal is None:
            return

        rows = [
            {
                "symbol": record.symbol,
                "token": record.token,
                "exchange": record.exchange,
                "tradingsymbol": record.tradingsymbol,
                "name": record.name,
                "instrument_type": record.instrument_type,
                "expiry": record.expiry,
                "strike": record.strike,
                "lot_size": record.lot_size,
                "tick_size": record.tick_size,
                "isin": record.isin,
            }
            for record in records
        ]

        if not rows:
            return

        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await session.execute(delete(InstrumentModel))
                    for start in range(0, len(rows), 4000):
                        chunk = rows[start : start + 4000]
                        await session.execute(insert(InstrumentModel), chunk)
            logger.info("[INSTRUMENTS] Persisted %d rows to database", len(rows))
        except Exception as exc:
            logger.warning("[INSTRUMENTS] Database persistence failed: %s", exc)

    @staticmethod
    def _records_from_snapshot(snapshot: Any) -> list[InstrumentRecord]:
        if not isinstance(snapshot, dict):
            return []
        rows = snapshot.get("records")
        if not isinstance(rows, list):
            return []

        records: list[InstrumentRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            token = str(row.get("token") or "").strip()
            exchange = str(row.get("exchange") or "").strip().upper()
            tradingsymbol = str(row.get("tradingsymbol") or symbol).strip().upper()
            if not symbol or not token or not exchange:
                continue
            records.append(
                InstrumentRecord(
                    symbol=symbol,
                    token=token,
                    exchange=exchange,
                    tradingsymbol=tradingsymbol,
                    name=str(row.get("name") or symbol).strip() or symbol,
                    instrument_type=str(row.get("instrument_type") or "").strip().upper(),
                    expiry=str(row.get("expiry") or "").strip(),
                    strike=InstrumentService._safe_float(row.get("strike")),
                    lot_size=max(1, InstrumentService._safe_int(row.get("lot_size"), 1)),
                    tick_size=InstrumentService._safe_float(row.get("tick_size")),
                    isin=str(row.get("isin") or "").strip(),
                )
            )
        return records

    def _load_from_redis_sync(self) -> int:
        try:
            snapshot = get_cache_sync(_REDIS_SNAPSHOT_KEY)
            records = self._records_from_snapshot(snapshot)
            if not records:
                return 0
            return self._apply_records(records, source="redis")
        except Exception as exc:
            logger.warning("[INSTRUMENTS] Redis load failed: %s", exc)
            return 0

    def _load_from_db_sync(self) -> int:
        if sync_session_factory is None:
            return 0

        try:
            session = sync_session_factory()
            try:
                rows = session.query(InstrumentModel).all()
            finally:
                session.close()

            records = [
                InstrumentRecord(
                    symbol=str(row.symbol or "").strip().upper(),
                    token=str(row.token or "").strip(),
                    exchange=str(row.exchange or "").strip().upper(),
                    tradingsymbol=str(row.tradingsymbol or row.symbol or "").strip().upper(),
                    name=str(row.name or row.symbol or "").strip(),
                    instrument_type=str(row.instrument_type or "").strip().upper(),
                    expiry=str(row.expiry or "").strip(),
                    strike=row.strike,
                    lot_size=max(1, int(row.lot_size or 1)),
                    tick_size=row.tick_size,
                    isin=str(row.isin or "").strip(),
                )
                for row in rows
                if row.symbol and row.token and row.exchange
            ]
            if not records:
                return 0

            return self._apply_records(records, source="database")
        except Exception as exc:
            logger.warning("[INSTRUMENTS] Database load failed: %s", exc)
            return 0

    async def _load_from_db_async(self) -> int:
        if AsyncSessionLocal is None:
            return 0

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(InstrumentModel))
                rows = result.scalars().all()

            records = [
                InstrumentRecord(
                    symbol=str(row.symbol or "").strip().upper(),
                    token=str(row.token or "").strip(),
                    exchange=str(row.exchange or "").strip().upper(),
                    tradingsymbol=str(row.tradingsymbol or row.symbol or "").strip().upper(),
                    name=str(row.name or row.symbol or "").strip(),
                    instrument_type=str(row.instrument_type or "").strip().upper(),
                    expiry=str(row.expiry or "").strip(),
                    strike=row.strike,
                    lot_size=max(1, int(row.lot_size or 1)),
                    tick_size=row.tick_size,
                    isin=str(row.isin or "").strip(),
                )
                for row in rows
                if row.symbol and row.token and row.exchange
            ]
            if not records:
                return 0

            count = self._apply_records(records, source="database")
            await self._persist_to_redis(records)
            return count
        except Exception as exc:
            logger.warning("[INSTRUMENTS] Async database load failed: %s", exc)
            return 0

    def _ensure_loaded_sync(self) -> None:
        with self._lock:
            if self._loaded and self._symbol_to_token:
                return

        if self._load_from_redis_sync() > 0:
            return
        if self._load_from_db_sync() > 0:
            return

        # Cold-start fallback: attempt one direct refresh when no event loop is active,
        # otherwise schedule async refresh in background.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self.refresh_instruments_daily(force=False))
            except Exception as exc:
                logger.warning("[INSTRUMENTS] Cold-start refresh failed: %s", exc)
            return

        try:
            loop.create_task(self.refresh_instruments_daily(force=False))
        except Exception as exc:
            logger.warning("[INSTRUMENTS] Background refresh schedule failed: %s", exc)

    async def store_instruments(self, payload: list[dict[str, Any]]) -> int:
        records = self._parse_payload(payload)
        if not records:
            raise ValueError("No valid instrument records parsed from API payload")

        deduped_records = self._dedupe_records(records)
        if not deduped_records:
            raise ValueError("No unique instrument records available after deduplication")

        if len(deduped_records) != len(records):
            logger.info(
                "[INSTRUMENTS] Deduplicated API rows: %d -> %d",
                len(records),
                len(deduped_records),
            )

        count = self._apply_records(deduped_records, source="openapi")
        await asyncio.gather(
            self._persist_to_redis(deduped_records),
            self._persist_to_db(deduped_records),
            return_exceptions=True,
        )
        return count

    async def refresh_instruments_daily(self, force: bool = False) -> int:
        """Refresh instrument set with API-first strategy and cache/DB fallback."""
        with self._lock:
            if self._loaded and not force:
                return len(self._symbol_to_token)

        async with self._refresh_lock:
            with self._lock:
                if self._loaded and not force:
                    return len(self._symbol_to_token)

            if not force:
                if self._load_from_redis_sync() > 0:
                    with self._lock:
                        return len(self._symbol_to_token)

                db_count = await self._load_from_db_async()
                if db_count > 0:
                    return db_count

            try:
                payload = await self.fetch_all_instruments_from_api()
                return await self.store_instruments(payload)
            except Exception as exc:
                logger.error("[INSTRUMENTS] API refresh failed: %s", exc)

                with self._lock:
                    if self._loaded and self._symbol_to_token:
                        logger.warning(
                            "[INSTRUMENTS] Using in-memory fallback (%d symbols)",
                            len(self._symbol_to_token),
                        )
                        return len(self._symbol_to_token)

                if self._load_from_redis_sync() > 0:
                    with self._lock:
                        return len(self._symbol_to_token)

                db_count = await self._load_from_db_async()
                if db_count > 0:
                    return db_count

                raise

    def get_token_by_symbol(self, symbol: str, exchange: str = "NSE") -> str:
        self._ensure_loaded_sync()
        s_key = self._symbol_key(exchange, symbol)

        with self._lock:
            token = self._symbol_to_token.get(s_key)
            if token:
                return token

        normalized_symbol = self._normalize_symbol(symbol)
        normalized_exchange = self._normalize_exchange(exchange)
        cached_exchange = get_cache_sync(f"{_REDIS_EXCHANGE_KEY_PREFIX}:{normalized_exchange}")
        if isinstance(cached_exchange, dict):
            token_map = cached_exchange.get("symbol_to_token") or {}
            token = token_map.get(normalized_symbol)
            if token:
                return str(token)

        raise KeyError(
            f"Instrument token not found for symbol: {normalized_exchange}:{normalized_symbol}"
        )

    def get_symbol_by_token(self, token: str, exchange: Optional[str] = None) -> str:
        self._ensure_loaded_sync()
        normalized_token = self._normalize_token(token)
        if not normalized_token:
            raise KeyError("Instrument symbol not found for empty token")

        with self._lock:
            if exchange:
                symbol = self._token_to_symbol.get(self._token_key(exchange, normalized_token))
                if symbol:
                    return symbol
            symbol_any = self._token_to_symbol_any.get(normalized_token)
            if symbol_any:
                return symbol_any

        if exchange:
            cached_exchange = get_cache_sync(
                f"{_REDIS_EXCHANGE_KEY_PREFIX}:{self._normalize_exchange(exchange)}"
            )
            if isinstance(cached_exchange, dict):
                reverse_map = cached_exchange.get("token_to_symbol") or {}
                symbol = reverse_map.get(normalized_token)
                if symbol:
                    return str(symbol)

        raise KeyError(f"Instrument symbol not found for token: {normalized_token}")

    def get_tradingsymbol(self, symbol: str, exchange: str = "NSE") -> str:
        self._ensure_loaded_sync()
        s_key = self._symbol_key(exchange, symbol)
        with self._lock:
            info = self._symbol_to_info.get(s_key)
            if info and info.get("tradingsymbol"):
                return str(info["tradingsymbol"])

        normalized = self._normalize_symbol(symbol)
        return f"{normalized}-EQ" if " " not in normalized else normalized

    def search_symbols(
        self,
        query: str,
        limit: int = 20,
        exchange: Optional[str] = "NSE",
    ) -> list[dict[str, Any]]:
        self._ensure_loaded_sync()
        capped_limit = max(1, min(int(limit), 100))
        lookup = str(query or "").strip().upper()

        with self._lock:
            items = list(self._symbol_to_info.items())

        if exchange:
            exchange_prefix = f"{self._normalize_exchange(exchange)}:"
            items = [(k, v) for k, v in items if k.startswith(exchange_prefix)]

        if not lookup:
            items.sort(key=lambda row: row[1].get("symbol", ""))
            return [dict(row[1]) for row in items[:capped_limit]]

        ranked: list[tuple[float, dict[str, Any]]] = []
        for _, info in items:
            symbol = str(info.get("symbol") or "").upper()
            name = str(info.get("name") or "").upper()
            tradingsymbol = str(info.get("tradingsymbol") or "").upper()

            score = 0.0
            if symbol == lookup:
                score = 140.0
            elif tradingsymbol == lookup:
                score = 130.0
            elif symbol.startswith(lookup):
                score = 110.0
            elif tradingsymbol.startswith(lookup):
                score = 105.0
            elif name.startswith(lookup):
                score = 95.0
            elif lookup in symbol:
                score = 80.0
            elif lookup in name:
                score = 70.0

            fuzzy = max(
                SequenceMatcher(None, lookup, symbol).ratio(),
                SequenceMatcher(None, lookup, tradingsymbol).ratio(),
                SequenceMatcher(None, lookup, name).ratio(),
            )
            if fuzzy >= 0.58:
                score = max(score, 40.0 + fuzzy * 60.0)

            if score > 0:
                ranked.append((score, info))

        ranked.sort(key=lambda row: (-row[0], row[1].get("symbol", "")))
        return [dict(row[1]) for row in ranked[:capped_limit]]

    def suggest_symbols(
        self,
        prefix: str,
        limit: int = 10,
        exchange: Optional[str] = "NSE",
    ) -> list[str]:
        matches = self.search_symbols(prefix, limit=limit, exchange=exchange)
        return [str(item.get("symbol") or "") for item in matches if item.get("symbol")]

    def get_all_symbols(self, exchange: Optional[str] = "NSE") -> list[str]:
        self._ensure_loaded_sync()
        with self._lock:
            keys = list(self._symbol_to_token.keys())
        if exchange:
            prefix = f"{self._normalize_exchange(exchange)}:"
            keys = [key for key in keys if key.startswith(prefix)]
        symbols = [key.split(":", 1)[1] for key in keys]
        symbols.sort()
        return symbols

    def get_instrument_count(self) -> int:
        with self._lock:
            return len(self._symbol_to_token)

    def get_last_refresh_at(self) -> Optional[str]:
        with self._lock:
            return self._last_refresh_at

    def get_bootstrap_counts(self) -> dict[str, int]:
        with self._lock:
            records = list(self._records)

        nse_eq = sum(
            1
            for record in records
            if record.exchange == "NSE"
            and (
                record.tradingsymbol.endswith("-EQ")
                or record.instrument_type in {"EQ", "EQUITY"}
            )
        )
        return {
            "total": len(records),
            "nse_eq": nse_eq,
        }


_service = InstrumentService()


async def fetch_all_instruments_from_api() -> list[dict[str, Any]]:
    return await _service.fetch_all_instruments_from_api()


async def store_instruments(payload: list[dict[str, Any]]) -> int:
    return await _service.store_instruments(payload)


async def refresh_instruments_daily(force: bool = False) -> int:
    return await _service.refresh_instruments_daily(force=force)


def get_token_by_symbol(symbol: str, exchange: str = "NSE") -> str:
    return _service.get_token_by_symbol(symbol=symbol, exchange=exchange)


def get_symbol_by_token(token: str, exchange: Optional[str] = None) -> str:
    return _service.get_symbol_by_token(token=token, exchange=exchange)


def get_tradingsymbol(symbol: str, exchange: str = "NSE") -> str:
    return _service.get_tradingsymbol(symbol=symbol, exchange=exchange)


def search_symbols(
    query: str,
    limit: int = 20,
    exchange: Optional[str] = "NSE",
) -> list[dict[str, Any]]:
    return _service.search_symbols(query=query, limit=limit, exchange=exchange)


def suggest_symbols(
    prefix: str,
    limit: int = 10,
    exchange: Optional[str] = "NSE",
) -> list[str]:
    return _service.suggest_symbols(prefix=prefix, limit=limit, exchange=exchange)


def get_all_symbols(exchange: Optional[str] = "NSE") -> list[str]:
    return _service.get_all_symbols(exchange=exchange)


def get_instrument_count() -> int:
    return _service.get_instrument_count()


def get_last_refresh_at() -> Optional[str]:
    return _service.get_last_refresh_at()


def get_bootstrap_counts() -> dict[str, int]:
    return _service.get_bootstrap_counts()
