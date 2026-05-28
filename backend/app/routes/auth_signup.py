from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.auth_signup import SignupRequest, SignupResponse
from app.services.auth_service import DuplicateEmailError, signup_user
from app.services.db import get_async_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SignupResponse:
    try:
        user = await signup_user(session=session, payload=payload)
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    return SignupResponse(id=user.id, email=user.email)
