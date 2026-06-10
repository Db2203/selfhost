import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Device, User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

_unauthorized = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass
class AuthContext:
    user: User
    device: Device


async def get_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    """Authenticate the request: valid JWT AND a live (non-revoked) device.

    The device row is checked on every request so that revoking a device cuts
    off its access immediately rather than at token expiry.
    """
    if credentials is None:
        raise _unauthorized

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise _unauthorized

    try:
        user_id = uuid.UUID(payload["sub"])
        device_id = uuid.UUID(payload["dev"])
    except (KeyError, ValueError):
        raise _unauthorized from None

    device = await session.get(Device, device_id)
    if device is None or device.user_id != user_id or device.revoked_at is not None:
        raise _unauthorized
    user = await session.get(User, user_id)
    if user is None:
        raise _unauthorized

    device.last_seen_at = datetime.now(timezone.utc)
    await session.commit()
    return AuthContext(user=user, device=device)


async def get_user_device(
    session: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID
) -> Device | None:
    result = await session.execute(
        select(Device).where(Device.id == device_id, Device.user_id == user_id)
    )
    return result.scalar_one_or_none()
