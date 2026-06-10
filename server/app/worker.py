"""arq worker entrypoint.

Real jobs (indexing, thumbnailing, embeddings) arrive in later stages; the
ping task exists so the worker container has a verifiable job from day one.
"""

from arq.connections import RedisSettings

from app.config import get_settings


async def ping(ctx: dict) -> str:
    return "pong"


class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
