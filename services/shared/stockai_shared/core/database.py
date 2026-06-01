from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from stockai_shared.db import db as db_service


def get_database_backend() -> str:
    return "postgresql" if "postgres" in db_service.DATABASE_URL else "sqlite"


def is_postgres() -> bool:
    return get_database_backend() == "postgresql"


def is_sqlite() -> bool:
    return get_database_backend() == "sqlite"


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in db_service.get_async_session():
        yield session


async def healthcheck(retries: int = 1, delay: float = 0.0) -> bool:
    return await db_service.check_db_connection(retries=retries, delay=delay)
