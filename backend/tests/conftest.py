"""Shared test fixtures for StockAI Pro backend tests."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.middleware import _api_requests, _login_attempts
from app.server import app
from app.services.db import Base, get_async_session
from app.trading.user_state import trading_manager


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def reset_process_local_state():
    """Prevent test leakage from in-memory middleware and trading singletons."""
    _api_requests.clear()
    _login_attempts.clear()
    trading_manager._states.clear()


@pytest.fixture
async def test_engine():
    for table in Base.metadata.tables.values():
        seen_names = set()
        duplicate_indexes = []
        for index in list(table.indexes):
            if index.name in seen_names:
                duplicate_indexes.append(index)
            else:
                seen_names.add(index.name)
        for index in duplicate_indexes:
            table.indexes.discard(index)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def app_with_overrides(session_factory):
    async def _override_get_async_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_async_session] = _override_get_async_session
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_async_session, None)


@pytest.fixture
async def client(app_with_overrides):
    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def make_user_payload():
    def _make_user_payload(prefix: str = "user") -> dict:
        token = uuid4().hex[:10]
        return {
            "username": f"{prefix}_{token}",
            "password": "SecurePass123",
            "email": f"{prefix}_{token}@example.com",
        }

    return _make_user_payload


@pytest.fixture
async def signup_user(client, make_user_payload):
    async def _signup_user(prefix: str = "user") -> dict:
        payload = make_user_payload(prefix)
        response = await client.post("/api/v1/auth/signup", json=payload)
        assert response.status_code == 201, response.text
        body = response.json()
        return {
            "request": payload,
            "response": body,
            "tokens": body["data"],
            "user": body["data"]["user"],
        }

    return _signup_user


@pytest.fixture
async def auth_headers(signup_user):
    created = await signup_user("auth")
    return {"Authorization": f"Bearer {created['tokens']['access_token']}"}


@pytest.fixture
def run_async():
    def _run_async(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    return _run_async


@pytest.fixture
def mock_ohlcv_df():
    """Generate a realistic 100-row OHLCV DataFrame for testing."""
    np.random.seed(42)
    n = 100
    base_price = 2500.0
    prices = [base_price]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0, 0.005)))

    df = pd.DataFrame(
        {
            "open": [p * (1 - np.random.uniform(0, 0.003)) for p in prices],
            "high": [p * (1 + np.random.uniform(0.001, 0.005)) for p in prices],
            "low": [p * (1 - np.random.uniform(0.001, 0.005)) for p in prices],
            "close": prices,
            "volume": np.random.randint(50000, 500000, n),
        }
    )
    return df


@pytest.fixture
def mock_ohlcv_list(mock_ohlcv_df):
    """Convert OHLCV DataFrame to list of dicts (API format)."""
    records = []
    for i, row in mock_ohlcv_df.iterrows():
        records.append(
            {
                "time": f"2026-03-19T10:{i:02d}:00Z",
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            }
        )
    return records


@pytest.fixture
def short_ohlcv_df():
    """10-row DataFrame — too short for meaningful features."""
    np.random.seed(99)
    n = 10
    prices = [100 + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 0.3 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [1000] * n,
        }
    )


@pytest.fixture
def bullish_ohlcv_df():
    """50-row strongly uptrending DataFrame."""
    np.random.seed(7)
    n = 50
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] + np.random.uniform(0.1, 0.6))

    return pd.DataFrame(
        {
            "open": [p - 0.2 for p in prices],
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [50000 + i * 500 for i in range(n)],
        }
    )


@pytest.fixture
def bearish_ohlcv_df():
    """50-row strongly downtrending DataFrame."""
    np.random.seed(13)
    n = 50
    prices = [200.0]
    for _ in range(n - 1):
        prices.append(prices[-1] - np.random.uniform(0.1, 0.6))

    return pd.DataFrame(
        {
            "open": [p + 0.2 for p in prices],
            "high": [p + 0.3 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices,
            "volume": [50000 + i * 500 for i in range(n)],
        }
    )
