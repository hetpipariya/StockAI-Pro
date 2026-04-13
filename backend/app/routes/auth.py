"""Authentication routes for the canonical /api/v1/auth API contract."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app import config
from app.services.db import UserModel, get_async_session
from app.utils.auth_utils import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
_optional_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

_DUMMY_PASSWORD_HASH = "$2b$12$LJ3m4ys.ehaGPCWQB4z2/.FpFqjKJzMVhasO/5l.VoxTrSSCVIwmW"

_USER_LOOKUP_COLUMNS = (
    UserModel.id,
    UserModel.username,
    UserModel.email,
    UserModel.is_active,
    UserModel.is_verified,
    UserModel.trading_mode,
    UserModel.starting_capital,
    UserModel.refresh_token_hash,
    UserModel.created_at,
    UserModel.last_login,
)

_LOGIN_LOOKUP_COLUMNS = _USER_LOOKUP_COLUMNS + (UserModel.password_hash,)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = Field(None, max_length=255)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username must contain only letters, numbers, and underscores")
        return v.lower().strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.lower().strip() if v else None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: AsyncSession = Depends(get_async_session),
) -> UserModel:
    payload = decode_access_token(token)

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await session.execute(
        select(UserModel)
        .options(load_only(*_USER_LOOKUP_COLUMNS))
        .where(UserModel.id == user_id)
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )
    return user


async def get_optional_user(
    token: Optional[str] = Depends(_optional_oauth2),
    session: AsyncSession = Depends(get_async_session),
) -> Optional[UserModel]:
    if not token:
        return None
    try:
        return await get_current_user(token, session)
    except HTTPException:
        return None


async def _issue_tokens_for_user(user: UserModel, session: AsyncSession) -> dict:
    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id)

    user.refresh_token_hash = hash_refresh_token(refresh_token)
    user.last_login = datetime.utcnow()
    await session.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "trading_mode": user.trading_mode,
            "starting_capital": user.starting_capital,
        },
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    session: AsyncSession = Depends(get_async_session),
):
    existing = await session.execute(
        select(UserModel).where(UserModel.username == data.username)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken. Please choose a different one.",
        )

    if data.email:
        existing_email = await session.execute(
            select(UserModel).where(UserModel.email == data.email)
        )
        if existing_email.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered.",
            )

    new_user = UserModel(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        is_active=True,
        is_verified=False,
        starting_capital=config.STARTING_CAPITAL,
        trading_mode=config.TRADING_MODE,
    )
    session.add(new_user)

    try:
        await session.commit()
        await session.refresh(new_user)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration failed due to conflict. Please try again.",
        ) from exc

    tokens = await _issue_tokens_for_user(new_user, session)
    logger.info("[AUTH] New user registered id=%s username=%s", new_user.id, new_user.username)

    return {
        "status": "ok",
        "message": "Account created successfully",
        "data": tokens,
    }


@router.post("/signup", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def signup_alias(
    data: RegisterRequest,
    session: AsyncSession = Depends(get_async_session),
):
    return await register(data, session)


@router.post("/login")
async def login(
    data: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
):
    username = data.username.lower().strip()

    result = await session.execute(
        select(UserModel)
        .options(load_only(*_LOGIN_LOOKUP_COLUMNS))
        .where(UserModel.username == username)
    )
    user = result.scalars().first()

    if not user:
        verify_password(data.password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )

    tokens = await _issue_tokens_for_user(user, session)
    logger.info("[AUTH] Login success user_id=%s username=%s", user.id, user.username)

    return {
        "status": "ok",
        "message": "Login successful",
        "data": tokens,
    }


@router.get("/login")
async def login_help():
    return {
        "status": "error",
        "message": "Use POST /api/v1/auth/login with JSON {username, password}.",
        "hint": "For UI login, open /login on the frontend app.",
    }


@router.post("/token")
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_async_session),
):
    login_req = LoginRequest(username=form_data.username, password=form_data.password)
    return await login(login_req, session)


@router.get("/me")
async def get_me(current_user: UserModel = Depends(get_current_user)):
    return {
        "status": "ok",
        "message": "User profile",
        "data": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "is_active": current_user.is_active,
            "is_verified": current_user.is_verified,
            "trading_mode": current_user.trading_mode,
            "starting_capital": current_user.starting_capital,
            "created_at": (
                current_user.created_at.isoformat() if current_user.created_at else None
            ),
            "last_login": (
                current_user.last_login.isoformat() if current_user.last_login else None
            ),
        },
    }


@router.post("/refresh")
async def refresh_token(
    data: RefreshRequest,
    session: AsyncSession = Depends(get_async_session),
):
    payload = decode_refresh_token(data.refresh_token)

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        ) from exc

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    expected_hash = hash_refresh_token(data.refresh_token)
    if user.refresh_token_hash != expected_hash:
        user.refresh_token_hash = None
        await session.commit()
        logger.warning(
            "[AUTH] Refresh token mismatch for user_id=%s; forcing re-login",
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been used or is invalid. Please login again.",
        )

    new_access = create_access_token(user.id, user.username)
    new_refresh = create_refresh_token(user.id)

    user.refresh_token_hash = hash_refresh_token(new_refresh)
    await session.commit()

    return {
        "status": "ok",
        "message": "Tokens refreshed",
        "data": {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        },
    }


@router.post("/logout")
async def logout(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    current_user.refresh_token_hash = None
    await session.commit()

    from app.trading.user_state import trading_manager

    await trading_manager.remove_state(current_user.id)

    logger.info("[AUTH] Logout user_id=%s", current_user.id)
    return {
        "status": "ok",
        "message": "Logged out successfully",
        "data": None,
    }


@router.get("/broker-status")
async def get_broker_status(current_user: UserModel = Depends(get_current_user)):
    """Get the status of the broker (Angel Broking/SmartAPI) connection.

    Returns information about whether the broker session is active and its age.
    If broker session is old, the user may need to re-login.
    """
    try:
        from app.connectors.smartapi_connector import SmartAPIConnector
        connector = SmartAPIConnector()

        is_logged_in = connector.is_logged_in
        session_age_minutes = connector.session_age_minutes

        # Session is considered stale if > 55 minutes (SmartAPI auth token expires in ~55min)
        is_stale = session_age_minutes > 55

        status_msg = "connected"
        if not is_logged_in:
            status_msg = "disconnected"
        elif is_stale:
            status_msg = "stale"

        return {
            "status": "ok",
            "data": {
                "broker": "angel_broking",
                "connection_status": status_msg,
                "is_logged_in": is_logged_in,
                "session_age_minutes": round(session_age_minutes, 1) if session_age_minutes != float("inf") else None,
                "is_stale": is_stale,
                "message": (
                    "Broker session is stale. Please initiate a new session to continue trading."
                    if is_stale else
                    "Broker connection is healthy"
                    if is_logged_in else
                    "Not connected to broker. Login required."
                ),
            },
        }
    except Exception as e:
        logger.error("[AUTH] Broker status check failed: %s", e)
        return {
            "status": "error",
            "data": {
                "broker": "angel_broking",
                "connection_status": "error",
                "message": f"Could not check broker status: {str(e)[:100]}"
            },
        }
