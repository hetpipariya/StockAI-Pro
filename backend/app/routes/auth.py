"""
Authentication routes — signup, login, me, refresh, logout.
All passwords hashed with bcrypt (12 rounds). All tokens are JWT HS256.

Token system:
  - Access token  → 24h, used for API authentication
  - Refresh token → 7 days, used only at /auth/refresh for token rotation
"""
from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.db import get_async_session, UserModel
from app.utils.auth_utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_access_token, decode_refresh_token,
    hash_refresh_token,
)
from app import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
compat_router = APIRouter(prefix="/api/v1", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Pydantic Schemas ──────────────────────────────────────────────────

class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = Field(None, max_length=255)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username must contain only letters, numbers, and underscores"
            )
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
    """JSON login body — kept for backward compatibility with frontend."""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Dependency: Get Current User ──────────────────────────────────────

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: AsyncSession = Depends(get_async_session),
) -> UserModel:
    """
    Dependency injection function.
    Use as: Depends(get_current_user) on any protected route.
    Validates JWT, fetches user from DB, returns UserModel.
    """
    payload = decode_access_token(token)
    user_id = int(payload["sub"])

    result = await session.execute(
        select(UserModel).where(UserModel.id == user_id)
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


# ── Optional Auth (for endpoints that benefit from user context) ──────

_optional_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)


async def get_optional_user(
    token: Optional[str] = Depends(_optional_oauth2),
    session: AsyncSession = Depends(get_async_session),
) -> Optional[UserModel]:
    """Returns user if valid token present, None if no token."""
    if not token:
        return None
    try:
        return await get_current_user(token, session)
    except HTTPException:
        return None


# ── POST /api/v1/auth/signup ──────────────────────────────────────────

@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    data: SignupRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Register a new user.
    - Validates username/email uniqueness
    - Hashes password with bcrypt (12 rounds)
    - Returns access + refresh token pair immediately
    """
    # Check username uniqueness
    existing = await session.execute(
        select(UserModel).where(UserModel.username == data.username)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken. Please choose a different one.",
        )

    # Check email uniqueness (if provided)
    if data.email:
        existing_email = await session.execute(
            select(UserModel).where(UserModel.email == data.email)
        )
        if existing_email.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered.",
            )

    # Create user with hashed password
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
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration failed due to conflict. Please try again.",
        )

    # Generate token pair
    access_token = create_access_token(new_user.id, new_user.username)
    refresh_token = create_refresh_token(new_user.id)

    # Store hashed refresh token
    new_user.refresh_token_hash = hash_refresh_token(refresh_token)
    new_user.last_login = datetime.utcnow()
    await session.commit()

    logger.info(f"[Auth] New user registered: id={new_user.id} username={new_user.username}")

    return {
        "status": "ok",
        "message": "Account created successfully",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": new_user.id,
                "username": new_user.username,
                "email": new_user.email,
            },
        },
    }


# ── POST /api/v1/auth/login ──────────────────────────────────────────

@router.post("/login")
async def login(
    data: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Authenticate user with username + password (JSON body).
    Returns access + refresh token pair.
    Always uses constant-time comparison (no timing attacks).
    """
    username = data.username.lower().strip()

    result = await session.execute(
        select(UserModel).where(UserModel.username == username)
    )
    user = result.scalars().first()

    # IMPORTANT: always verify password even if user not found
    # This prevents timing-based user enumeration attacks
    dummy_hash = "$2b$12$LJ3m4ys.ehaGPCWQB4z2/.FpFqjKJzMVhasO/5l.VoxTrSSCVIwmW"
    if not user:
        verify_password(data.password, dummy_hash)  # Constant-time
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

    # Generate fresh token pair
    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id)

    # Store hashed refresh token (invalidates previous refresh token)
    user.refresh_token_hash = hash_refresh_token(refresh_token)
    user.last_login = datetime.utcnow()
    await session.commit()

    logger.info(f"[Auth] Login: user_id={user.id} username={user.username}")

    return {
        "status": "ok",
        "message": "Login successful",
        "data": {
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
        },
    }


@router.get("/login")
async def login_help():
    """Human-friendly response when the login API route is opened in a browser."""
    return {
        "status": "error",
        "message": "Use POST /api/v1/auth/login with JSON {username, password}.",
        "hint": "For UI login, open /login on the frontend app (e.g. https://stockai-pro.in/login).",
    }


@compat_router.post("/signup", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def signup_compat(
    data: SignupRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Compatibility alias for clients using /api/v1/signup."""
    return await signup(data, session)


@compat_router.post("/login", include_in_schema=False)
async def login_compat(
    data: LoginRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Compatibility alias for clients using /api/v1/login."""
    return await login(data, session)


@compat_router.get("/login", include_in_schema=False)
async def login_help_compat():
    """Compatibility alias for browser visits to /api/v1/login."""
    return await login_help()


# ── POST /api/v1/auth/login (OAuth2 form-data — for Swagger UI) ──────

@router.post("/token")
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_async_session),
):
    """
    OAuth2-compatible login using form-data (username + password fields).
    Powers the Swagger UI 'Authorize' button. Returns same format as /login.
    """
    # Reuse the JSON login logic
    login_req = LoginRequest(username=form_data.username, password=form_data.password)
    return await login(login_req, session)


# ── GET /api/v1/auth/me ───────────────────────────────────────────────

@router.get("/me")
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """Return current authenticated user's profile."""
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
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
        },
    }


# ── POST /api/v1/auth/refresh ─────────────────────────────────────────

@router.post("/refresh")
async def refresh_token(
    data: RefreshRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Exchange a refresh token for a new access + refresh token pair.
    Implements token rotation — old refresh token is invalidated.
    """
    payload = decode_refresh_token(data.refresh_token)
    user_id = int(payload["sub"])

    result = await session.execute(
        select(UserModel).where(UserModel.id == user_id)
    )
    user = result.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # Validate refresh token matches what's stored (prevents token reuse)
    expected_hash = hash_refresh_token(data.refresh_token)
    if user.refresh_token_hash != expected_hash:
        # Possible token theft — invalidate all tokens
        user.refresh_token_hash = None
        await session.commit()
        logger.warning(
            f"[Auth] Refresh token mismatch for user_id={user.id} — "
            "possible token theft. All tokens invalidated."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been used or is invalid. "
                   "Please login again.",
        )

    # Issue fresh token pair (rotation)
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


# ── POST /api/v1/auth/logout ──────────────────────────────────────────

@router.post("/logout")
async def logout(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Logout user by invalidating their refresh token.
    The access token will naturally expire (JWTs can't be server-side revoked).
    """
    current_user.refresh_token_hash = None
    await session.commit()

    # Remove user's trading state from memory
    from app.trading.user_state import trading_manager
    await trading_manager.remove_state(current_user.id)

    logger.info(f"[Auth] Logout: user_id={current_user.id}")
    return {"status": "ok", "message": "Logged out successfully", "data": None}
