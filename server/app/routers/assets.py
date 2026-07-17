import hashlib
import mimetypes
import uuid
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.deps import AuthContext, get_auth
from app.indexer import IMAGE_EXTENSIONS, extract_metadata
from app.models import Asset, Thumbnail
from app.queue import JobQueue, get_job_queue
from app.schemas import AssetOut, AssetPage, AssetUrls, UploadResult
from app.signing import sign_asset_url, verify_asset_signature
from app.storage import Storage, get_library_storage, get_media_storage

router = APIRouter(prefix="/assets", tags=["assets"])

VARIANTS = {"grid", "preview", "original"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


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
        duration_seconds=asset.duration_seconds,
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


@router.post("/upload", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    file: UploadFile,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    media: Annotated[Storage, Depends(get_media_storage)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> UploadResult:
    """Receive a photo from a client (phone backup). Dedup is by content
    hash, so re-uploading or uploading a photo the indexer already has is a
    cheap no-op."""
    extension = PurePosixPath(file.filename or "upload.jpg").suffix.lower() or ".jpg"
    if extension not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type"
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File too large"
        )

    content_hash = hashlib.sha256(data).hexdigest()
    existing = (
        await session.execute(
            select(Asset.id).where(
                Asset.owner_id == auth.user.id, Asset.content_hash == content_hash
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return UploadResult(id=existing, duplicate=True)

    try:
        width, height, taken_at = extract_metadata(data)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a readable image"
        ) from None

    path = f"uploads/{content_hash[:2]}/{content_hash}{extension}"
    await media.write(path, data)
    asset = Asset(
        owner_id=auth.user.id,
        storage_path=path,
        store="uploads",
        content_hash=content_hash,
        media_type="image",
        size_bytes=len(data),
        width=width,
        height=height,
        taken_at=taken_at,
    )
    session.add(asset)
    await session.commit()

    # Kick the (idempotent, backlog-style) processing jobs. We deliberately do
    # NOT pass a fixed job id: arq dedups a fixed id against both queued AND
    # completed-result keys, so a fixed id would silently drop the enqueue once
    # an earlier backlog job's result is still cached — leaving this upload
    # unprocessed. Redundant runs are cheap (they no-op when nothing is due).
    await queue.enqueue("thumbnail_backlog_job")
    await queue.enqueue("embed_backlog_job")
    await queue.enqueue("detect_faces_job")
    await queue.enqueue("cluster_faces_job", str(auth.user.id))

    return UploadResult(id=asset.id, duplicate=False)


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
        # Indexed originals live in the read-only library; uploads in media.
        storage = library if asset.store == "library" else media
        path = asset.storage_path
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
