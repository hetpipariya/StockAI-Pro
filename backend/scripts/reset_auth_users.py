from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.services.db import AsyncSessionLocal, engine, UserModel  # noqa: E402
from app.utils.auth_utils import hash_password  # noqa: E402


def _resolve_target_credentials() -> tuple[str, str]:
    email = os.getenv("RESET_AUTH_EMAIL", "").strip()
    password = os.getenv("RESET_AUTH_PASSWORD", "")

    if not email or not password:
        raise RuntimeError("Set RESET_AUTH_EMAIL and RESET_AUTH_PASSWORD before running this script")

    return email, password


async def reset_users(target_email: str, target_password: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))

    async with AsyncSessionLocal() as session:
        user = UserModel(
            email=target_email,
            password_hash=hash_password(target_password),
            is_active=True,
            is_verified=True,
            starting_capital=config.STARTING_CAPITAL,
            trading_mode=config.TRADING_MODE,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    print(f"Reset users table and seeded {target_email} with id=1")


if __name__ == "__main__":
    email, password = _resolve_target_credentials()
    asyncio.run(reset_users(email, password))