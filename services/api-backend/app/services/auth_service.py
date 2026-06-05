from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stockai_shared.schemas.auth_signup import SignupRequest
from stockai_shared.db.db import UserModel
from stockai_shared.utils.auth_utils import hash_password


class DuplicateEmailError(Exception):
    pass


def _is_duplicate_email_integrity_error(exc: IntegrityError) -> bool:
    message = str(exc).lower()
    return "email" in message and (
        "duplicate key" in message or "unique constraint" in message
    )


async def signup_user(session: AsyncSession, payload: SignupRequest) -> UserModel:
    existing = await session.scalar(
        select(UserModel.id).where(UserModel.email == payload.email).limit(1)
    )
    if existing is not None:
        raise DuplicateEmailError("Email already registered")

    user = UserModel(
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_verified=False,
    )

    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _is_duplicate_email_integrity_error(exc):
            raise DuplicateEmailError("Email already registered") from exc
        raise

    await session.refresh(user)
    return user
