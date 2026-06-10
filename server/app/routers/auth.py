from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Device, User
from app.schemas import LoginRequest, RefreshRequest, TokenPair
from app.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_bad_credentials = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
)

# An argon2 hash of a throwaway value; see login() below.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> TokenPair:
    result = await session.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    # Verify against a dummy hash when the user is unknown, so the response
    # time doesn't reveal which usernames exist.
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise _bad_credentials
    if not verify_password(body.password, user.password_hash):
        raise _bad_credentials

    refresh_token = new_refresh_token()
    device = Device(
        user_id=user.id,
        name=body.device_name,
        refresh_token_hash=hash_refresh_token(refresh_token),
    )
    session.add(device)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(user.id, device.id),
        refresh_token=refresh_token,
        device_id=device.id,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> TokenPair:
    result = await session.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if (
        device is None
        or device.revoked_at is not None
        or device.refresh_token_hash is None
        or device.refresh_token_hash != hash_refresh_token(body.refresh_token)
    ):
        raise _bad_credentials

    # Rotate: each refresh token is single-use, so a stolen old token is dead.
    next_token = new_refresh_token()
    device.refresh_token_hash = hash_refresh_token(next_token)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(device.user_id, device.id),
        refresh_token=next_token,
        device_id=device.id,
    )
