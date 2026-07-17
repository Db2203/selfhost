"""Scan the (read-only) photo library and upsert asset rows.

Originals are never modified or copied; an asset records the file's relative
path, content hash, dimensions, and capture time. Hashing makes re-runs and
duplicate files (same photo in two folders, or on laptop and phone) no-ops.
"""

import hashlib
import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset
from app.storage.base import Storage
from app.video import VIDEO_EXTENSIONS, FfprobeError, probe_video, spooled_local_copy

logger = logging.getLogger(__name__)

register_heif_opener()

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic", ".heif"
}

# EXIF tag ids (no names needed at runtime).
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306


@dataclass
class IndexReport:
    scanned: int = 0
    added: int = 0
    skipped_duplicates: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_exif_datetime(value: str) -> datetime | None:
    try:
        # EXIF format: "2024:06:15 14:30:21" (naive, local time of the camera).
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, AttributeError):
        return None


def extract_metadata(data: bytes) -> tuple[int, int, datetime | None]:
    """Return (width, height, taken_at) for an image, raising on non-images."""
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size
        exif = img.getexif()
        raw = exif.get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME)
        if raw is None:
            # DateTimeOriginal usually lives in the Exif sub-IFD.
            sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
            raw = sub.get(_EXIF_DATETIME_ORIGINAL)
    taken_at = _parse_exif_datetime(raw) if isinstance(raw, str) else None
    return width, height, taken_at


async def hash_file(storage: Storage, path: str) -> str:
    digest = hashlib.sha256()
    async for chunk in storage.stream(path):
        digest.update(chunk)
    return digest.hexdigest()


async def _is_duplicate(session: AsyncSession, owner_id: uuid.UUID, content_hash: str) -> bool:
    existing = await session.execute(
        select(Asset.id).where(Asset.owner_id == owner_id, Asset.content_hash == content_hash)
    )
    return existing.scalar_one_or_none() is not None


async def _image_asset(
    session: AsyncSession, library: Storage, owner_id: uuid.UUID, path: str, report: IndexReport
) -> Asset | None:
    content_hash = await hash_file(library, path)
    if await _is_duplicate(session, owner_id, content_hash):
        report.skipped_duplicates += 1
        return None

    data = await library.read(path)
    try:
        width, height, taken_at = extract_metadata(data)
    except UnidentifiedImageError:
        report.errors.append(f"{path}: not a readable image")
        return None

    return Asset(
        owner_id=owner_id,
        storage_path=path,
        content_hash=content_hash,
        media_type="image",
        size_bytes=len(data),
        width=width,
        height=height,
        taken_at=taken_at,
    )


async def _video_asset(
    session: AsyncSession, library: Storage, owner_id: uuid.UUID, path: str, report: IndexReport
) -> Asset | None:
    # Spool to a temp file (ffprobe needs seekable input) and hash in the
    # same pass, so a large video is only pulled from storage once.
    async with spooled_local_copy(library, path) as (local, content_hash):
        if await _is_duplicate(session, owner_id, content_hash):
            report.skipped_duplicates += 1
            return None

        try:
            info = await probe_video(local)
        except FfprobeError as exc:
            report.errors.append(f"{path}: {exc}")
            return None

        return Asset(
            owner_id=owner_id,
            storage_path=path,
            content_hash=content_hash,
            media_type="video",
            size_bytes=local.stat().st_size,
            width=info.width,
            height=info.height,
            taken_at=info.taken_at,
            duration_seconds=info.duration_seconds,
        )


async def index_library(
    session: AsyncSession, library: Storage, owner_id: uuid.UUID
) -> IndexReport:
    report = IndexReport()

    async for path in library.list_files():
        extension = "." + path.rsplit(".", 1)[-1].lower()
        if extension in IMAGE_EXTENSIONS:
            build = _image_asset
        elif extension in VIDEO_EXTENSIONS:
            build = _video_asset
        else:
            continue
        report.scanned += 1
        try:
            asset = await build(session, library, owner_id, path, report)
            if asset is None:
                continue
            session.add(asset)
            await session.commit()
            report.added += 1
        except Exception as exc:  # one bad file must not kill the whole scan
            await session.rollback()
            logger.exception("failed to index %s", path)
            report.errors.append(f"{path}: {exc}")

    return report
