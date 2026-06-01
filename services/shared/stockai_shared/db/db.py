"""
Database models and engine configuration.
PostgreSQL primary, SQLite dev-only fallback.
All trading tables enforce user_id isolation via foreign keys.
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, create_engine,
                        event, text)
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import (Mapped, declarative_base, mapped_column,
                            relationship, sessionmaker)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from stockai_shared.config.config import APP_ENV
from stockai_shared.config.config import DATABASE_URL as CONFIG_DATABASE_URL
from stockai_shared.config.config import (DB_COMMAND_TIMEOUT_SECONDS, DB_LOCK_TIMEOUT_MS,
                        DB_LOG_SLOW_QUERIES, DB_MAX_OVERFLOW,
                        DB_POOL_RECYCLE_SECONDS, DB_POOL_SIZE,
                        DB_POOL_TIMEOUT_SECONDS, DB_SLOW_QUERY_MS,
                        DB_STATEMENT_TIMEOUT_MS, REQUIRE_POSTGRES,
                        RESET_SQLITE_ON_START, SQLALCHEMY_ECHO)

logger = logging.getLogger(__name__)

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════


class UserModel(Base):
    """User account with auth, trading config, and relationships."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Account state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Trading config (per-user, loaded into UserTradingState)
    starting_capital: Mapped[float] = mapped_column(
        Float, default=100_000.0, nullable=False
    )
    trading_mode: Mapped[str] = mapped_column(
        String(10), default="PAPER", nullable=False
    )

    # Refresh token storage (for token rotation)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    last_login: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    orders = relationship(
        "OrderModel", back_populates="user", cascade="all, delete-orphan"
    )
    positions = relationship(
        "PositionModel", back_populates="user", cascade="all, delete-orphan"
    )
    trade_logs = relationship(
        "TradeLogModel", back_populates="user", cascade="all, delete-orphan"
    )
    predictions = relationship(
        "PredictionModel", back_populates="user", cascade="all, delete-orphan"
    )
    trading_state = relationship(
        "UserTradingStateModel",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User id={self.id} email={self.email}>"


class UserTradingStateModel(Base):
    """Persisted per-user runtime trading state."""

    __tablename__ = "user_trading_state"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_trading_state_user_id"),
        Index("ix_user_trading_state_last_updated", "last_updated"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    balance: Mapped[float] = mapped_column(Float, nullable=False, default=100_000.0)
    positions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    orders: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user = relationship("UserModel", back_populates="trading_state")


class CandleModel(Base):
    """OHLCV candle storage with composite unique on (symbol, timeframe, timestamp)."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),
        Index("ix_candle_timeframe", "timeframe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)


class InstrumentModel(Base):
    """Instrument token master for symbol/token resolution across exchanges."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_instruments_exchange_symbol"),
        UniqueConstraint("exchange", "token", name="uq_instruments_exchange_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    token: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange: Mapped[str] = mapped_column(String(12), nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    expiry: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    strike: Mapped[float] = mapped_column(Float, nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tick_size: Mapped[float] = mapped_column(Float, nullable=True)
    isin: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class OrderModel(Base):
    """Orders with user isolation and composite indexes."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_symbol", "user_id", "symbol"),
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_user_timestamp", "user_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    mode: Mapped[str] = mapped_column(String(10), default="paper")
    confidence: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship("UserModel", back_populates="orders")


class PositionModel(Base):
    """Open positions — one per user per symbol (enforced by unique constraint)."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_position_user_symbol"),
        Index("ix_positions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=False,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="paper")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship("UserModel", back_populates="positions")


class TradeLogModel(Base):
    """Immutable audit trail for every trade action."""

    __tablename__ = "trade_logs"
    __table_args__ = (
        Index("ix_trade_logs_user_id", "user_id"),
        Index("ix_trade_logs_user_symbol", "user_id", "symbol"),
        Index("ix_trade_logs_user_timestamp", "user_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    order_id: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    price: Mapped[float] = mapped_column(Float, nullable=True, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, nullable=True, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(25), nullable=True)
    pnl: Mapped[float] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    extra: Mapped[str] = mapped_column(Text, nullable=True)

    user = relationship("UserModel", back_populates="trade_logs")


class PredictionModel(Base):
    """ML predictions — nullable user_id for system-generated predictions."""

    __tablename__ = "predictions"
    __table_args__ = (Index("ix_predictions_symbol_timestamp", "symbol", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    horizon: Mapped[str] = mapped_column(String(10), nullable=True)
    predicted_price: Mapped[float] = mapped_column(Float, nullable=True)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)

    user = relationship("UserModel", back_populates="predictions")


class TradeModel(Base):
    """Simple trade table for API examples and production smoke checks."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )


class OrderStateLog(Base):
    """Order state transitions for debugging."""

    __tablename__ = "order_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    state: Mapped[str] = mapped_column(String(25))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailyRiskState(Base):
    """Global daily risk snapshot (legacy — user-level risk is in TradingManager)."""

    __tablename__ = "daily_risk_state"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    starting_capital: Mapped[float] = mapped_column(Float)
    current_capital: Mapped[float] = mapped_column(Float)
    trades_today: Mapped[int] = mapped_column(Integer, default=0)
    halted: Mapped[bool] = mapped_column(Boolean, default=False)


# ═══════════════════════════════════════════════════════════════════
# DATABASE ENGINE SETUP
# ═══════════════════════════════════════════════════════════════════

_db_url = CONFIG_DATABASE_URL.strip()
_env = APP_ENV

if not _db_url:
    raise RuntimeError(
        "DATABASE_URL resolution failed: empty value received from app.config"
    )

DATABASE_URL = _db_url
_is_postgres = "postgresql" in _db_url or "postgres" in _db_url
_is_sqlite = _db_url.startswith("sqlite")
_pool_size = max(5, DB_POOL_SIZE)
_max_overflow = max(0, DB_MAX_OVERFLOW)
_pool_timeout = max(5.0, DB_POOL_TIMEOUT_SECONDS)
_pool_recycle = max(60, DB_POOL_RECYCLE_SECONDS)

if _env == "production" and _is_sqlite:
    raise RuntimeError(
        "FATAL: SQLite is not allowed in production. Configure PostgreSQL."
    )

if REQUIRE_POSTGRES and not _is_postgres:
    raise RuntimeError(
        "FATAL: REQUIRE_POSTGRES=true but non-PostgreSQL DB is active. "
        "Set DATABASE_URL to PostgreSQL or disable REQUIRE_POSTGRES explicitly for SQLite-only development."
    )

_engine_kwargs = {
    "echo": SQLALCHEMY_ECHO,
    "hide_parameters": True,
    "future": True,
}
if _is_postgres:
    _command_timeout = max(5.0, DB_COMMAND_TIMEOUT_SECONDS)
    _engine_kwargs.update(
        {
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": _pool_size,
            "max_overflow": _max_overflow,
            "pool_pre_ping": True,
            "pool_recycle": _pool_recycle,
            "pool_timeout": _pool_timeout,
            "pool_use_lifo": True,
            "connect_args": {
                "timeout": _command_timeout,
                "command_timeout": _command_timeout,
                "server_settings": {
                    "application_name": "stockai-backend",
                    "statement_timeout": str(max(1000, DB_STATEMENT_TIMEOUT_MS)),
                    "lock_timeout": str(max(500, DB_LOCK_TIMEOUT_MS)),
                },
            },
        }
    )

engine = create_async_engine(_db_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# ═══════════════════════════════════════════════════════════════════
# READ REPLICA ENGINE SETUP
# ═══════════════════════════════════════════════════════════════════

import os

_replica_db_url = os.getenv("REPLICA_DATABASE_URL", "").strip()
if _replica_db_url:
    logger.info("[DB] Initializing read-replica engine with: %s", _replica_db_url)
    replica_engine = create_async_engine(_replica_db_url, **_engine_kwargs)
    AsyncReplicaSessionLocal = async_sessionmaker(
        bind=replica_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
else:
    logger.info("[DB] No REPLICA_DATABASE_URL configured. Read queries will route to primary engine.")
    replica_engine = engine
    AsyncReplicaSessionLocal = AsyncSessionLocal

# Backward-compatible async session factory alias used by existing modules.
async_session = AsyncSessionLocal
SessionLocal = AsyncSessionLocal

# Sync engine for background workers and sync-only code paths.
if _is_sqlite:
    _sync_url = _db_url.replace("+aiosqlite", "")
    sync_engine = create_engine(
        _sync_url,
        echo=False,
        hide_parameters=True,
        future=True,
    )
else:
    _sync_url = (
        _db_url.replace("+asyncpg", "+psycopg2")
        if "+asyncpg" in _db_url
        else _db_url.replace("postgresql://", "postgresql+psycopg2://")
    )
    _sync_pool_size = max(5, min(_pool_size, 24))
    _sync_max_overflow = max(5, min(_max_overflow, 48))
    sync_engine = create_engine(
        _sync_url,
        echo=False,
        hide_parameters=True,
        future=True,
        pool_size=_sync_pool_size,
        max_overflow=_sync_max_overflow,
        pool_pre_ping=True,
        pool_recycle=_pool_recycle,
        pool_timeout=_pool_timeout,
        pool_use_lifo=True,
        connect_args={
            "options": (
                f"-c statement_timeout={max(1000, DB_STATEMENT_TIMEOUT_MS)} "
                f"-c lock_timeout={max(500, DB_LOCK_TIMEOUT_MS)}"
            )
        },
    )

sync_session_factory = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)


_max_slowest_query_ms = 0.0

def _register_query_instrumentation(target_engine, label: str) -> None:
    @event.listens_for(target_engine, "before_cursor_execute")
    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        conn.info.setdefault("_query_start_time", []).append(time.perf_counter())

    @event.listens_for(target_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start_stack = conn.info.get("_query_start_time")
        if not start_stack:
            return
        started_at = start_stack.pop(-1)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        
        # Determine statement type/operation
        first_word = "UNKNOWN"
        if statement:
            parts = statement.strip().split()
            if parts:
                first_word = "".join(c for c in parts[0] if c.isalnum()).upper()
        
        try:
            from stockai_shared.metrics.metrics import DB_QUERY_LATENCY
            DB_QUERY_LATENCY.labels(operation=first_word).observe(elapsed_ms / 1000.0)
        except Exception:
            pass

        if elapsed_ms >= DB_SLOW_QUERY_MS:
            global _max_slowest_query_ms
            try:
                from stockai_shared.metrics.metrics import DB_SLOW_QUERIES_TOTAL, DB_SLOWEST_QUERY_MS
                DB_SLOW_QUERIES_TOTAL.inc()
                if elapsed_ms > _max_slowest_query_ms:
                    _max_slowest_query_ms = elapsed_ms
                    DB_SLOWEST_QUERY_MS.set(elapsed_ms)
            except Exception:
                pass

            if DB_LOG_SLOW_QUERIES:
                compact_sql = " ".join((statement or "").split())
                upper_sql = compact_sql.upper()

                # Instrument master bootstrap reads/writes are expected and can flood logs.
                if any(
                    marker in upper_sql
                    for marker in (
                        "INSERT INTO INSTRUMENTS",
                        "DELETE FROM INSTRUMENTS",
                        "UPDATE INSTRUMENTS",
                        "FROM INSTRUMENTS",
                    )
                ):
                    return

                if len(compact_sql) > 240:
                    compact_sql = compact_sql[:240] + "..."
                logger.warning(
                    "[DB][SLOW][%s] %.1fms | %s",
                    label,
                    elapsed_ms,
                    compact_sql,
                )


_register_query_instrumentation(engine.sync_engine, "async")
_register_query_instrumentation(sync_engine, "sync")
if _replica_db_url and replica_engine is not engine:
    _register_query_instrumentation(replica_engine.sync_engine, "replica")

# Monkeypatch QueuePool._do_get connection checkout to track connection waiting in real-time
try:
    from sqlalchemy.pool import QueuePool
    _orig_do_get = QueuePool._do_get

    def _instrumented_do_get(self, *args, **kwargs):
        try:
            from stockai_shared.metrics.metrics import DB_POOL_WAITING
            DB_POOL_WAITING.inc()
        except Exception:
            pass
        try:
            return _orig_do_get(self, *args, **kwargs)
        finally:
            try:
                from stockai_shared.metrics.metrics import DB_POOL_WAITING
                DB_POOL_WAITING.dec()
            except Exception:
                pass

    QueuePool._do_get = _instrumented_do_get
except Exception as e:
    logger.warning("[DB] Failed to monkeypatch QueuePool._do_get: %s", e)

logger.info("[DB] Engine initialized (%s)", "PostgreSQL" if _is_postgres else "SQLite")

_TRANSIENT_DB_ERROR_MARKERS = (
    "deadlock detected",
    "could not serialize access",
    "lock timeout",
    "connection refused",
    "connection reset",
    "server closed the connection",
    "too many clients",
    "the database system is starting up",
)


def is_transient_db_error(exc: Exception) -> bool:
    if isinstance(exc, (OperationalError, DBAPIError)):
        if getattr(exc, "connection_invalidated", False):
            return True
        lowered = str(exc).lower()
        return any(marker in lowered for marker in _TRANSIENT_DB_ERROR_MARKERS)
    return False


async def run_db_transaction_with_retry(
    action_func,
    *args,
    max_retries: int = 3,
    base_delay: float = 0.1,
    timeout_seconds: float = 5.0,
    **kwargs
):
    """
    Executes an async database operation with automatic retries on transient errors,
    exponential backoff, and a strict timeout guard.
    """
    from stockai_shared.metrics.metrics import DB_TRANSIENT_RETRIES, DB_QUERY_LATENCY
    
    start_time = time.perf_counter()
    op_name = getattr(action_func, "__name__", "db_op")
    
    for attempt in range(1, max_retries + 1):
        try:
            result = await asyncio.wait_for(
                action_func(*args, **kwargs),
                timeout=timeout_seconds
            )
            elapsed = time.perf_counter() - start_time
            DB_QUERY_LATENCY.labels(operation=op_name).observe(elapsed)
            return result
        except Exception as exc:
            transient = is_transient_db_error(exc)
            if transient and attempt < max_retries:
                try:
                    DB_TRANSIENT_RETRIES.labels().inc()
                except Exception:
                    pass
                wait_time = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[DB] Transient transaction error in '%s' (attempt %d/%d): %s. Retrying in %.2fs",
                    op_name,
                    attempt,
                    max_retries,
                    exc,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
                continue
            raise



def _resolve_sqlite_file_path() -> Optional[Path]:
    if not _is_sqlite:
        return None

    try:
        parsed = make_url(_db_url)
        raw_path = str(parsed.database or "").strip()
    except Exception as exc:
        logger.warning("[DB] Could not parse SQLite DB URL for reset: %s", exc)
        return None

    if not raw_path or raw_path == ":memory:":
        return None

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (Path.cwd() / db_path).resolve()
    return db_path


async def _reset_sqlite_db_file_if_needed() -> None:
    if not (_is_sqlite and RESET_SQLITE_ON_START):
        return

    db_path = _resolve_sqlite_file_path()
    if db_path is None:
        logger.info("[DB] SQLite reset skipped (in-memory or unresolved DB path)")
        return

    # Dispose first to release file handles before unlinking on Windows.
    await engine.dispose()
    sync_engine.dispose()

    candidates = [
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
        Path(str(db_path) + "-journal"),
    ]

    removed = 0
    for candidate in candidates:
        for attempt in range(1, 4):
            try:
                if candidate.exists():
                    candidate.unlink()
                    removed += 1
                break
            except FileNotFoundError:
                break
            except PermissionError as exc:
                if attempt == 3:
                    logger.warning(
                        "[DB] Could not remove locked SQLite file %s: %s",
                        candidate,
                        exc,
                    )
                else:
                    await asyncio.sleep(0.2 * attempt)
            except Exception as exc:
                logger.warning("[DB] Failed removing SQLite file %s: %s", candidate, exc)
                break

    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[DB] SQLite reset complete; removed %d file(s) for %s", removed, db_path)


# ═══════════════════════════════════════════════════════════════════
# SESSION DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════


async def init_db():
    """Create all tables from metadata (used at startup)."""
    try:
        await _reset_sqlite_db_file_if_needed()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[DB] ✓ Tables initialized")

        # Enable TimescaleDB hypertables conditionally if using PostgreSQL
        if _is_postgres:
            try:
                async with engine.begin() as conn:
                    # 1. Create extension conditionally
                    try:
                        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                        logger.info("[DB] TimescaleDB extension verified/installed.")
                    except Exception as ext_err:
                        logger.warning("[DB] TimescaleDB extension not available: %s. Falling back to standard Postgres.", ext_err)
                        return

                    # 2. Check if candles is already a hypertable
                    result = await conn.execute(text(
                        "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'candles';"
                    ))
                    is_hypertable = result.first() is not None

                    if not is_hypertable:
                        # Drop existing primary key on 'id' and 'uq_candle' constraint
                        # Find the PK constraint name dynamically
                        pk_res = await conn.execute(text(
                            "SELECT conname FROM pg_constraint WHERE conrelid = 'candles'::regclass AND contype = 'p';"
                        ))
                        pk_row = pk_res.first()
                        if pk_row:
                            await conn.execute(text(f"ALTER TABLE candles DROP CONSTRAINT {pk_row[0]};"))

                        await conn.execute(text("ALTER TABLE candles DROP CONSTRAINT IF EXISTS uq_candle;"))

                        # Add composite primary key including timestamp
                        await conn.execute(text(
                            "ALTER TABLE candles ADD PRIMARY KEY (timestamp, symbol, timeframe);"
                        ))

                        # Convert candles table to a TimescaleDB hypertable (7-day partitions)
                        await conn.execute(text(
                            "SELECT create_hypertable('candles', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);"
                        ))
                        logger.info("[DB] ✓ Candles table converted to TimescaleDB hypertable (7-day chunks)")

                        # Enable compression policy
                        await conn.execute(text(
                            "ALTER TABLE candles SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol, timeframe');"
                        ))
                        await conn.execute(text(
                            "SELECT add_compression_policy('candles', INTERVAL '14 days', if_not_exists => TRUE);"
                        ))
                        logger.info("[DB] ✓ TimescaleDB compression policy added (14-day segment retention)")

                    # 3. Check if market_data table exists and convert it
                    md_exists_res = await conn.execute(text(
                        "SELECT 1 FROM information_schema.tables WHERE table_name = 'market_data';"
                    ))
                    if md_exists_res.first() is not None:
                        result = await conn.execute(text(
                            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_data';"
                        ))
                        is_md_hyper = result.first() is not None
                        if not is_md_hyper:
                            await conn.execute(text(
                                "SELECT create_hypertable('market_data', 'time', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);"
                            ))
                            await conn.execute(text(
                                "ALTER TABLE market_data SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol, timeframe');"
                            ))
                            await conn.execute(text(
                                "SELECT add_compression_policy('market_data', INTERVAL '7 days', if_not_exists => TRUE);"
                            ))
                            await conn.execute(text(
                                "SELECT add_retention_policy('market_data', INTERVAL '180 days', if_not_exists => TRUE);"
                            ))
                            logger.info("[DB] ✓ market_data table converted to TimescaleDB hypertable")

                    # 4. Check if market_ticks table exists and convert it
                    mt_exists_res = await conn.execute(text(
                        "SELECT 1 FROM information_schema.tables WHERE table_name = 'market_ticks';"
                    ))
                    if mt_exists_res.first() is not None:
                        result = await conn.execute(text(
                            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_ticks';"
                        ))
                        is_mt_hyper = result.first() is not None
                        if not is_mt_hyper:
                            await conn.execute(text("ALTER TABLE market_ticks DROP CONSTRAINT IF EXISTS market_ticks_pkey;"))
                            await conn.execute(text("ALTER TABLE market_ticks ADD PRIMARY KEY (time, id);"))
                            await conn.execute(text(
                                "SELECT create_hypertable('market_ticks', 'time', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);"
                            ))
                            await conn.execute(text(
                                "ALTER TABLE market_ticks SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol');"
                            ))
                            await conn.execute(text(
                                "SELECT add_compression_policy('market_ticks', INTERVAL '7 days', if_not_exists => TRUE);"
                            ))
                            await conn.execute(text(
                                "SELECT add_retention_policy('market_ticks', INTERVAL '30 days', if_not_exists => TRUE);"
                            ))
                            logger.info("[DB] ✓ market_ticks table converted to TimescaleDB hypertable")
            except Exception as exc:
                logger.error("[DB] Failed to convert candles/market tables to TimescaleDB hypertable: %s. Continuing with standard Postgres schema.", exc)
    except Exception as e:
        logger.error("[DB] Initialization failed: %s", e)
        raise


async def check_db_connection(retries: int = 3, delay: float = 2.0) -> bool:
    """Verify the database is reachable with exponential backoff."""
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.debug("[DB] Connection verified (attempt %d/%d)", attempt, retries)
            return True
        except Exception as exc:
            wait = delay * (2 ** (attempt - 1))
            if attempt < retries:
                logger.warning(
                    "[DB] Connection check failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    retries,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "[DB] Connection check failed after %d attempts: %s", retries, exc
                )
    return False


async def get_async_session():
    """FastAPI dependency for async DB sessions.

    Usage in routes:
        session: AsyncSession = Depends(get_async_session)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        else:
            # Avoid unnecessary commits for pure reads; close the transaction explicitly.
            if session.in_transaction():
                if session.new or session.dirty or session.deleted:
                    await session.commit()
                else:
                    await session.rollback()


async def get_async_replica_session():
    """FastAPI dependency for async DB sessions routed to the read-replica.

    Usage in read-only routes:
        session: AsyncSession = Depends(get_async_replica_session)
    """
    async with AsyncReplicaSessionLocal() as session:
        try:
            yield session
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        else:
            if session.in_transaction():
                await session.rollback()


async def get_db_session():
    """Legacy dependency — yields session or None."""
    if AsyncSessionLocal:
        async with AsyncSessionLocal() as session:
            yield session
    else:
        yield None


async def get_db():
    """FastAPI dependency alias for route handlers."""
    async for session in get_db_session():
        yield session


def get_sync_db_session():
    """Generator for synchronous DB sessions (background threads)."""
    if sync_session_factory:
        session = sync_session_factory()
        try:
            yield session
        finally:
            session.close()
    else:
        yield None
