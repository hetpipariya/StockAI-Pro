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

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, create_engine, event,
                        text)
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import (Mapped, declarative_base, mapped_column,
                            relationship, sessionmaker)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config import APP_ENV
from app.config import DATABASE_URL as CONFIG_DATABASE_URL
from app.config import (DB_COMMAND_TIMEOUT_SECONDS, DB_LOCK_TIMEOUT_MS,
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
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
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

    def __repr__(self):
        return f"<User id={self.id} username={self.username}>"


class CandleModel(Base):
    """OHLCV candle storage with composite unique on (symbol, timeframe, timestamp)."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),
        Index("ix_candle_lookup", "symbol", "timeframe", "timestamp"),
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
        Index("ix_instruments_exchange_symbol", "exchange", "symbol"),
        Index("ix_instruments_exchange_token", "exchange", "token"),
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


def _register_slow_query_logging(target_engine, label: str) -> None:
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
        if elapsed_ms >= DB_SLOW_QUERY_MS:
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


if DB_LOG_SLOW_QUERIES:
    _register_slow_query_logging(engine.sync_engine, "async")
    _register_slow_query_logging(sync_engine, "sync")

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
