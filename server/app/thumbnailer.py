"""Generate WebP thumbnails for assets that don't have them yet.

Two kinds: a small "grid" image for the timeline and a larger "preview" for
the lightbox. Output is keyed on the asset's content hash, so the job is
idempotent and survives interruption — re-running only fills in what's
missing.
"""

import io
import logging
from dataclasses import dataclass, field

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Thumbnail
from app.storage.base import Storage
from app.video import extract_poster_frame, spooled_local_copy

logger = logging.getLogger(__name__)

register_heif_opener()

# kind -> longest-side pixel cap
THUMBNAIL_KINDS = {"grid": 256, "preview": 1440}
WEBP_QUALITY = 80


@dataclass
class ThumbnailReport:
    generated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def thumbnail_path(content_hash: str, kind: str) -> str:
    return f"thumbs/{content_hash[:2]}/{content_hash}-{kind}.webp"


def render_thumbnail(data: bytes, max_side: int) -> tuple[bytes, int, int]:
    """Resize to fit max_side (never upscaling) and encode as WebP."""
    with Image.open(io.BytesIO(data)) as img:
        # Phone photos store rotation in EXIF; bake it in or grids look sideways.
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        scale = min(1.0, max_side / max(img.size))
        if scale < 1.0:
            img = img.resize(
                (round(img.width * scale), round(img.height * scale)), Image.LANCZOS
            )
        out = io.BytesIO()
        img.save(out, "WEBP", quality=WEBP_QUALITY)
        return out.getvalue(), img.width, img.height


async def _thumbnail_source(library: Storage, media: Storage, asset: Asset) -> bytes:
    """Image bytes to thumbnail from: the original for photos, an extracted
    poster frame for videos."""
    # Indexed originals live in the read-only library; phone uploads
    # in media storage (the same split the file endpoint makes).
    source = library if asset.store == "library" else media
    if asset.media_type == "image":
        return await source.read(asset.storage_path)
    async with spooled_local_copy(source, asset.storage_path) as (local, _):
        return await extract_poster_frame(local)


async def thumbnail_asset(
    session: AsyncSession, library: Storage, media: Storage, asset: Asset
) -> int:
    """Generate any missing thumbnail kinds for one asset; returns count made."""
    existing_kinds = {
        kind
        for (kind,) in (
            await session.execute(select(Thumbnail.kind).where(Thumbnail.asset_id == asset.id))
        )
    }

    made = 0
    data: bytes | None = None
    for kind, max_side in THUMBNAIL_KINDS.items():
        if kind in existing_kinds:
            continue
        if data is None:
            data = await _thumbnail_source(library, media, asset)
        rendered, width, height = render_thumbnail(data, max_side)
        path = thumbnail_path(asset.content_hash, kind)
        await media.write(path, rendered)
        session.add(
            Thumbnail(asset_id=asset.id, kind=kind, storage_path=path, width=width, height=height)
        )
        made += 1
    if made:
        await session.commit()
    return made


async def thumbnail_backlog(
    session: AsyncSession, library: Storage, media: Storage
) -> ThumbnailReport:
    """Generate thumbnails for every asset that is missing any kind."""
    report = ThumbnailReport()
    result = await session.execute(select(Asset))
    for asset in result.scalars():
        try:
            made = await thumbnail_asset(session, library, media, asset)
            if made:
                report.generated += made
            else:
                report.skipped += 1
        except Exception as exc:  # a bad source file must not kill the backlog
            await session.rollback()
            logger.exception("failed to thumbnail %s", asset.storage_path)
            report.errors.append(f"{asset.storage_path}: {exc}")
    return report
