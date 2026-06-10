"""arq worker entrypoint.

Heavy jobs (indexing, thumbnailing, embeddings) run here, never in the API
request path.
"""

import dataclasses
import uuid

from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionFactory
from app.embedding import get_worker_embedder
from app.faces import detect_faces_backlog, get_worker_detector
from app.indexer import index_library
from app.people import cluster_faces
from app.search import embed_backlog
from app.storage import get_library_storage, get_media_storage
from app.thumbnailer import thumbnail_backlog


async def ping(ctx: dict) -> str:
    return "pong"


async def index_library_job(ctx: dict, user_id: str) -> dict:
    async with SessionFactory() as session:
        report = await index_library(session, get_library_storage(), uuid.UUID(user_id))
    return dataclasses.asdict(report)


async def thumbnail_backlog_job(ctx: dict) -> dict:
    async with SessionFactory() as session:
        report = await thumbnail_backlog(session, get_library_storage(), get_media_storage())
    return dataclasses.asdict(report)


async def embed_backlog_job(ctx: dict) -> dict:
    async with SessionFactory() as session:
        report = await embed_backlog(
            session, get_worker_embedder(), get_library_storage(), get_media_storage()
        )
    return dataclasses.asdict(report)


async def embed_text_job(ctx: dict, query: str) -> list[float]:
    """Embed a search query for the API (the model only lives here)."""
    return get_worker_embedder().embed_text(query)


async def detect_faces_job(ctx: dict) -> dict:
    async with SessionFactory() as session:
        report = await detect_faces_backlog(
            session, get_worker_detector(), get_library_storage(), get_media_storage()
        )
    return dataclasses.asdict(report)


async def cluster_faces_job(ctx: dict, user_id: str) -> dict:
    settings = get_settings()
    async with SessionFactory() as session:
        report = await cluster_faces(
            session,
            uuid.UUID(user_id),
            threshold=settings.face_match_threshold,
            min_cluster_size=settings.face_cluster_min_size,
        )
    return dataclasses.asdict(report)


class WorkerSettings:
    functions = [
        ping,
        index_library_job,
        thumbnail_backlog_job,
        embed_backlog_job,
        embed_text_job,
        detect_faces_job,
        cluster_faces_job,
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Backlog jobs process the whole library in one run and, on first use, also
    # download model weights — far longer than arq's 300s default. Without this
    # they'd be killed mid-run and retried indefinitely. Jobs are idempotent
    # and resumable, but they should be allowed to simply finish.
    job_timeout = 7200
    # Keep results long enough for the CLI to collect them.
    keep_result = 7200
    max_tries = 3
