import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_auth
from app.models import Device
from app.schemas import DeviceOut

router = APIRouter(prefix="/devices", tags=["devices"])


def _to_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        name=device.name,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked=device.revoked_at is not None,
    )


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DeviceOut]:
    result = await session.execute(
        select(Device).where(Device.user_id == auth.user.id).order_by(Device.created_at)
    )
    return [_to_out(d) for d in result.scalars()]


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    result = await session.execute(
        select(Device).where(Device.id == device_id, Device.user_id == auth.user.id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown device")

    device.revoked_at = datetime.now(timezone.utc)
    device.refresh_token_hash = None
    await session.commit()
