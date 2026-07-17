import hashlib
import logging
import mimetypes
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.deps import AuthContext, get_auth
from app.indexer import IMAGE_EXTENSIONS, extract_metadata
from app.models import AlbumAsset, Asset, DeletedAsset, Face, Thumbnail
from app.queue import JobQueue, get_job_queue
from app.schemas import AssetOut, AssetPage, AssetUpdate, AssetUrls, UploadResult
from app.signing import sign_asset_url, verify_asset_signature
from app.storage import Storage, get_library_storage, get_media_storage
from app.video import VIDEO_EXTENSIONS, FfprobeError, probe_video

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])

VARIANTS = {"grid", "preview", "original", "playback"}
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
        favorite=asset.favorite,
        urls=AssetUrls(
            grid=sign_asset_url(asset.id, "grid") if "grid" in kinds else None,
            preview=sign_asset_url(asset.id, "preview") if "preview" in kinds else None,
            original=sign_asset_url(asset.id, "original"),
            playback=sign_asset_url(asset.id, "playback")
            if asset.media_type == "video"
            else None,
        ),
    )


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single 'bytes=start-end' Range header against a known size.

    Returns None to serve the whole file (no/unsupported header), raises 416
    for a syntactically valid but unsatisfiable range. Multi-range requests
    are legal to ignore — we answer with the full body.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    start_s, _, end_s = header[len("bytes=") :].partition("-")
    try:
        if start_s == "":
            # Suffix form: the last N bytes.
            suffix = int(end_s)
            if suffix <= 0:
                return None
            return max(0, size - suffix), size - 1
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    end = min(end, size - 1)
    if start >= size or start > end:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, end


async def _stream_file(
    storage: Storage, path: str, content_type: str, request: Request
) -> StreamingResponse:
    """Serve a (potentially large) stored file with HTTP range support, so
    browsers can seek around videos without downloading the whole thing."""
    size = await storage.size(path)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}

    byte_range = _parse_range(request.headers.get("range"), size)
    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(storage.stream(path), media_type=content_type, headers=headers)

    start, end = byte_range
    headers["Content-Length"] = str(end - start + 1)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        storage.stream(path, offset=start, length=end - start + 1),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=content_type,
        headers=headers,
    )


@router.get("", response_model=AssetPage)
async def list_assets(
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    favorite: bool | None = None,
) -> AssetPage:
    filters = [Asset.owner_id == auth.user.id]
    if favorite is not None:
        filters.append(Asset.favorite == favorite)
    total = await session.scalar(select(func.count()).select_from(Asset).where(*filters))
    result = await session.execute(
        select(Asset)
        .where(*filters)
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
    """Receive a photo or video from a client (phone backup). Dedup is by
    content hash, so re-uploading or uploading a file the indexer already
    has is a cheap no-op."""
    extension = PurePosixPath(file.filename or "upload.jpg").suffix.lower() or ".jpg"
    if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
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

    # Re-uploading previously deleted content is an explicit request to
    # bring it back: clear the tombstone.
    await session.execute(
        delete(DeletedAsset).where(
            DeletedAsset.owner_id == auth.user.id, DeletedAsset.content_hash == content_hash
        )
    )

    duration = None
    if extension in VIDEO_EXTENSIONS:
        # ffprobe wants a seekable file, not bytes.
        tmp = tempfile.NamedTemporaryFile(suffix=extension, delete=False)
        try:
            tmp.write(data)
            tmp.close()
            info = await probe_video(tmp.name)
        except FfprobeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Not a readable video"
            ) from None
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        media_type = "video"
        width, height = info.width, info.height
        taken_at, duration = info.taken_at, info.duration_seconds
    else:
        try:
            width, height, taken_at = extract_metadata(data)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Not a readable image"
            ) from None
        media_type = "image"

    path = f"uploads/{content_hash[:2]}/{content_hash}{extension}"
    await media.write(path, data)
    asset = Asset(
        owner_id=auth.user.id,
        storage_path=path,
        store="uploads",
        content_hash=content_hash,
        media_type=media_type,
        size_bytes=len(data),
        width=width,
        height=height,
        taken_at=taken_at,
        duration_seconds=duration,
    )
    session.add(asset)
    await session.commit()

    # Kick the (idempotent, backlog-style) processing jobs. We deliberately do
    # NOT pass a fixed job id: arq dedups a fixed id against both queued AND
    # completed-result keys, so a fixed id would silently drop the enqueue once
    # an earlier backlog job's result is still cached — leaving this upload
    # unprocessed. Redundant runs are cheap (they no-op when nothing is due).
    await queue.enqueue("thumbnail_backlog_job")
    await queue.enqueue("transcode_backlog_job")
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


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(get_auth)],
    session: Annotated[AsyncSession, Depends(get_session)],
    media: Annotated[Storage, Depends(get_media_storage)],
) -> None:
    """Remove an asset and everything derived from it.

    Library originals are on a read-only mount and stay put — a tombstone
    stops the next re-index from bringing the asset back. Uploaded
    originals are ours, so their bytes are removed too.
    """
    result = await session.execute(
        select(Asset)
        .where(Asset.id == asset_id, Asset.owner_id == auth.user.id)
        .options(selectinload(Asset.thumbnails))
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown asset")

    doomed = [t.storage_path for t in asset.thumbnails]
    if asset.playback_path:
        doomed.append(asset.playback_path)
    if asset.store == "uploads":
        doomed.append(asset.storage_path)

    session.add(DeletedAsset(owner_id=auth.user.id, content_hash=asset.content_hash))
    await session.execute(delete(AlbumAsset).where(AlbumAsset.asset_id == asset.id))
    await session.execute(delete(Face).where(Face.asset_id == asset.id))
    await session.execute(delete(Thumbnail).where(Thumbnail.asset_id == asset.id))
    await session.execute(delete(Asset).where(Asset.id == asset.id))
    await session.commit()

    # Best effort, after the commit: the DB is authoritative and an
    # orphaned file is harmless, but a 500 here would be a lie.
    for path in doomed:
        try:
            await media.delete(path)
        except Exception:
            logger.warning("could not delete %s from media storage", path)


@router.patch("/{asset_id}", response_model=AssetOut)
async def update_asset(
    asset_id: uuid.UUID,
    body: AssetUpdate,
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

    asset.favorite = body.favorite
    await session.commit()
    return asset_to_out(asset)


@router.get("/{asset_id}/file/{variant}")
async def get_asset_file(
    asset_id: uuid.UUID,
    variant: str,
    exp: int,
    sig: str,
    request: Request,
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

    if variant == "playback" and asset.playback_path is not None:
        # The transcoded H.264 rendition (originals browsers can't play).
        return await _stream_file(media, asset.playback_path, "video/mp4", request)

    if variant in ("original", "playback"):
        # playback without a rendition means the original is already
        # web-safe. Indexed originals live in the read-only library;
        # uploads in media.
        storage = library if asset.store == "library" else media
        path = asset.storage_path
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return await _stream_file(storage, path, content_type, request)

    result = await session.execute(
        select(Thumbnail).where(Thumbnail.asset_id == asset_id, Thumbnail.kind == variant)
    )
    thumb = result.scalar_one_or_none()
    if thumb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No thumbnail")

    return StreamingResponse(
        media.stream(thumb.storage_path),
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=3600"},
    )
