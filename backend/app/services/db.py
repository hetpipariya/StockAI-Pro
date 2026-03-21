import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, sessionmaker
from sqlalchemy import String, Float, Integer, DateTime, UniqueConstraint, Index, Boolean
from datetime import datetime
from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

Base = declarative_base()


class CandleModel(Base):
    """OHLCV candle storage with composite unique on (symbol, timeframe, timestamp)."""
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),
        Index("ix_candle_lookup", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)


class PredictionModel(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    horizon: Mapped[str] = mapped_column(String(10))
    predicted_price: Mapped[float] = mapped_column(Float)
    signal: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[int] = mapped_column(Integer)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    explanation: Mapped[str] = mapped_column(String(255), nullable=True)


class OrderModel(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    transaction_type: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(25), default="PENDING_CONFIRMATION")
    mode: Mapped[str] = mapped_column(String(10))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    error: Mapped[str] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)

class PositionModel(Base):
    __tablename__ = "positions"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    direction: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class OrderStateLog(Base):
    __tablename__ = "order_states"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(50), index=True)
    state: Mapped[str] = mapped_column(String(25))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class DailyRiskState(Base):
    __tablename__ = "daily_risk_state"
    date: Mapped[str] = mapped_column(String(10), primary_key=True) # "YYYY-MM-DD"
    starting_capital: Mapped[float] = mapped_column(Float)
    current_capital: Mapped[float] = mapped_column(Float)
    trades_today: Mapped[int] = mapped_column(Integer, default=0)
    halted: Mapped[bool] = mapped_column(Boolean, default=False)


class UserModel(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime] = mapped_column(DateTime, nullable=True)

class TradeLogModel(Base):
    """Immutable audit trail for every trade action."""
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    order_id: Mapped[str] = mapped_column(String(50), index=True)
    event: Mapped[str] = mapped_column(String(30))  # SIGNAL, PLACED, CONFIRMED, FILLED, FAILED, EXIT
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=True)
    target: Mapped[float] = mapped_column(Float, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(500), nullable=True)
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(25), nullable=True)
    pnl: Mapped[float] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(String(255), nullable=True)
    extra: Mapped[str] = mapped_column(String(1000), nullable=True)  # JSON metadata blob

# Database Engine Setup
try:
    is_sqlite = DATABASE_URL.startswith("sqlite")
    
    if is_sqlite:
        engine = create_async_engine(DATABASE_URL, echo=False)
    else:
        # PostgreSQL optimizations
        engine = create_async_engine(
            DATABASE_URL, 
            echo=False, 
            pool_size=10, 
            max_overflow=20, 
            pool_recycle=1800
        )
        
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    # Create synchronous engine for background threads (OrderRouter/Executor)
    # Convert asyncpg to psycopg2 for sync engine
    if is_sqlite:
        SYNC_DATABASE_URL = DATABASE_URL.replace("+aiosqlite", "")
        sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)
    else:
        # Handle postgresql+asyncpg -> postgresql+psycopg2
        SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg2") if "+asyncpg" in DATABASE_URL else DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
        sync_engine = create_engine(
            SYNC_DATABASE_URL, 
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800
        )
        
    sync_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
except Exception as e:
    logger.error("[DB] Failed to create engine: %s", e)
    engine = None
    async_session = None
    sync_engine = None
    sync_session_factory = None


async def init_db():
    if engine is None:
        logger.error("[DB] Engine is not initialized; skipping table creation")
        return

    _retries = 5
    _delay = 2.0
    for attempt in range(1, _retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("[DB] ✓ Tables initialized (candles, predictions, orders)")
            return
        except Exception as e:
            if attempt < _retries:
                logger.warning(
                    "[DB] Initialization attempt %d/%d failed: %s — retrying in %.0fs",
                    attempt, _retries, e, _delay,
                )
                await asyncio.sleep(_delay)
                _delay *= 2
            else:
                logger.error("[DB] Initialization failed after %d attempts: %s", _retries, e)


async def check_db_connection() -> bool:
    """Return True if the database is reachable, False otherwise."""
    if engine is None:
        return False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("[DB] Health check failed: %s", e)
        return False


async def get_db_session():
    if async_session:
        async with async_session() as session:
            yield session
    else:
        yield None

def get_sync_db_session():
    """Generator for synchronous DB sessions."""
    if sync_session_factory:
        session = sync_session_factory()
        try:
            yield session
        finally:
            session.close()
    else:
        yield None
