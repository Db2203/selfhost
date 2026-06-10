import mimetypes
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.deps import AuthContext, get_auth
from app.models import Asset, Thumbnail
from app.schemas import AssetOut, AssetPage, AssetUrls
from app.signing import sign_asset_url, verify_asset_signature
from app.storage import Storage, get_library_storage, get_media_storage

router = APIRouter(prefix="/assets", tags=["assets"])

VARIANTS = {"grid", "preview", "original"}


def asset_to_out(asset: Asset) -> AssetOut:
    kinds = {t.kind for t in asset.thumbnails}
    return AssetOut(
        id=asset.id,
        media_type=asset.media_type,
        width=asset.width,
        height=asset.height,
        size_bytes=asset.size_bytes,
        taken_at=asset.taken_at,
        created_at=asset.created_at,
        urls=AssetUrls(
            grid=sign_asset_url(asset.id, "grid") if "grid" in kinds else None,
            preview=sign_asset_url(asset.id, "preview") if "preview" in kinds else None,
            original=sign_asset_url(asset.id, "original"),
        ),
    )


@router.get("", response_model=AssetPage)
async def list_assets(
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AssetPage:
    owner_filter = Asset.owner_id == auth.user.id
    total = await session.scalar(select(func.count()).select_from(Asset).where(owner_filter))
    result = await session.execute(
        select(Asset)
        .where(owner_filter)
        .options(selectinload(Asset.thumbnails))
        # Newest first; assets with no EXIF date sort by when they were indexed.
        .order_by(Asset.taken_at.desc().nulls_last(), Asset.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [asset_to_out(a) for a in result.scalars()]
    return AssetPage(items=items, total=total or 0, offset=offset, limit=limit)


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(
    asset_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetOut:
    result = await session.execute(
        select(Asset)
        .where(Asset.id == asset_id, Asset.owner_id == auth.user.id)
        .options(selectinload(Asset.thumbnails))
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown asset")
    return asset_to_out(asset)


@router.get("/{asset_id}/file/{variant}")
async def get_asset_file(
    asset_id: uuid.UUID,
    variant: str,
    exp: int,
    sig: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    library: Annotated[Storage, Depends(get_library_storage)],
    media: Annotated[Storage, Depends(get_media_storage)],
) -> StreamingResponse:
    # The signature is the credential here (img tags can't send headers);
    # it expires and covers exactly one asset + variant.
    if variant not in VARIANTS or not verify_asset_signature(asset_id, variant, exp, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown asset")

    if variant == "original":
        storage, path = library, asset.storage_path
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    else:
        result = await session.execute(
            select(Thumbnail).where(Thumbnail.asset_id == asset_id, Thumbnail.kind == variant)
        )
        thumb = result.scalar_one_or_none()
        if thumb is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No thumbnail")
        storage, path = media, thumb.storage_path
        content_type = "image/webp"

    return StreamingResponse(
        storage.stream(path),
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
