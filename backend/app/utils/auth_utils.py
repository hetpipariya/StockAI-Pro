"""
Auth utility functions — password hashing and JWT operations.
Single source of truth for all auth logic.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status

from app import config

logger = logging.getLogger(__name__)

# ── Password Hashing ──────────────────────────────────────────────────
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # 12 rounds ≈ 250ms on modern hardware (good balance)
)


def hash_password(plain_password: str) -> str:
    """Hash a password using bcrypt with 12 rounds."""
    if not plain_password or len(plain_password.strip()) < 6:
        raise ValueError("Password must be at least 6 characters.")
    # bcrypt has a 72-byte limit; truncate safely
    truncated = plain_password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    return _pwd_context.hash(truncated)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time bcrypt comparison. Returns False (never raises) on mismatch."""
    try:
        truncated = plain_password.encode("utf-8")[:72].decode("utf-8", errors="ignore")
        return _pwd_context.verify(truncated, hashed_password)
    except Exception:
        return False


# ── JWT Token Generation ──────────────────────────────────────────────
_ALGORITHM = config.JWT_ALGORITHM          # "HS256"
_SECRET = config.JWT_SECRET
_ACCESS_EXPIRE = config.ACCESS_TOKEN_EXPIRE_MINUTES   # 1440 = 24h
_REFRESH_EXPIRE = config.REFRESH_TOKEN_EXPIRE_DAYS    # 7 days


def create_access_token(user_id: int, username: str,
                        extra_claims: Optional[dict] = None) -> str:
    """
    Create a short-lived access token (24 hours default).
    Contains: user_id, username, token type, expiry.
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=_ACCESS_EXPIRE),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    """
    Create a long-lived refresh token (7 days default).
    Used only at /auth/refresh — never for API calls.
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=_REFRESH_EXPIRE),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate an access token.
    Raises HTTPException 401 on any failure.
    """
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_refresh_token(token: str) -> dict:
    """
    Decode and validate a refresh token.
    Raises HTTPException 401 on any failure.
    """
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type — expected refresh token",
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please login again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for safe DB storage (SHA-256)."""
    return hashlib.sha256(token.encode()).hexdigest()
