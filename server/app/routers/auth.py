from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import Device, User
from app.ratelimit import RateLimiter, RedisRateLimiter
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

_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = RedisRateLimiter(
            settings.redis_url,
            max_attempts=settings.login_rate_limit_attempts,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    return _limiter


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> TokenPair:
    client_ip = request.client.host if request.client else "unknown"
    if not await limiter.allow(f"login:{body.username.lower()}:{client_ip}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; try again later",
        )

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
    presented_hash = hash_refresh_token(body.refresh_token)
    next_token = new_refresh_token()

    # Rotate atomically: the UPDATE only succeeds if the presented token is
    # still the current one. Two concurrent refreshes with the same token race
    # on this single row write — exactly one updates a row, the other matches
    # nothing and is rejected. (A plain read-check-write would let both win.)
    result = await session.execute(
        update(Device)
        .where(
            Device.id == body.device_id,
            Device.revoked_at.is_(None),
            Device.refresh_token_hash == presented_hash,
        )
        .values(refresh_token_hash=hash_refresh_token(next_token))
        .returning(Device.user_id)
    )
    row = result.first()
    if row is None:
        await session.rollback()
        raise _bad_credentials
    await session.commit()

    return TokenPair(
        access_token=create_access_token(row.user_id, body.device_id),
        refresh_token=next_token,
        device_id=body.device_id,
    )
