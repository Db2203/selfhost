"""Embedding backlog job + vector similarity search."""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.embedding import Embedder, cosine_similarity
from app.models import Asset, Thumbnail
from app.storage.base import Storage

logger = logging.getLogger(__name__)


@dataclass
class EmbedReport:
    embedded: int = 0
    errors: list[str] = field(default_factory=list)


async def embed_backlog(
    session: AsyncSession, embedder: Embedder, library: Storage, media: Storage
) -> EmbedReport:
    """Embed every asset that doesn't have an embedding yet.

    Prefers the grid thumbnail as input (small, already orientation-baked);
    falls back to the original for assets without one.
    """
    report = EmbedReport()
    result = await session.execute(select(Asset).where(Asset.embedding.is_(None)))
    for asset in result.scalars():
        try:
            thumb = (
                await session.execute(
                    select(Thumbnail).where(
                        Thumbnail.asset_id == asset.id, Thumbnail.kind == "grid"
                    )
                )
            ).scalar_one_or_none()
            if thumb is not None:
                data = await media.read(thumb.storage_path)
            else:
                # Library assets vs phone uploads (which live in media storage).
                source = library if asset.store == "library" else media
                data = await source.read(asset.storage_path)
            asset.embedding = embedder.embed_image(data)
            await session.commit()
            report.embedded += 1
        except Exception as exc:  # one bad file must not kill the backlog
            await session.rollback()
            logger.exception("failed to embed %s", asset.storage_path)
            report.errors.append(f"{asset.storage_path}: {exc}")
    return report


async def search_assets(
    session: AsyncSession, owner_id: uuid.UUID, query_vector: list[float], limit: int
) -> list[Asset]:
    """Rank the owner's embedded assets by cosine similarity to the query."""
    base = (
        select(Asset)
        .where(Asset.owner_id == owner_id, Asset.embedding.is_not(None))
        .options(selectinload(Asset.thumbnails))
    )

    if session.bind.dialect.name == "postgresql":
        # "<=>" is pgvector's cosine-distance operator; the HNSW index serves it.
        qvec = "[" + ",".join(f"{x:g}" for x in query_vector) + "]"
        result = await session.execute(
            base.order_by(text("embedding <=> CAST(:qvec AS vector)"))
            .limit(limit)
            .params(qvec=qvec)
        )
        return list(result.scalars())

    # SQLite (local tests): rank in Python.
    result = await session.execute(base)
    assets = list(result.scalars())
    assets.sort(key=lambda a: -cosine_similarity(a.embedding, query_vector))
    return assets[:limit]
