"""arq worker entrypoint.

Heavy jobs (indexing, thumbnailing, embeddings) run here, never in the API
request path.
"""

import dataclasses
import uuid

from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionFactory
from app.indexer import index_library
from app.storage import get_library_storage


async def ping(ctx: dict) -> str:
    return "pong"


async def index_library_job(ctx: dict, user_id: str) -> dict:
    async with SessionFactory() as session:
        report = await index_library(session, get_library_storage(), uuid.UUID(user_id))
    return dataclasses.asdict(report)


class WorkerSettings:
    functions = [ping, index_library_job]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
