"""Job-queue access for the API process (enqueue only; workers execute)."""

from typing import Protocol

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings


class JobQueue(Protocol):
    async def enqueue(self, job_name: str, *args, job_id: str | None = None) -> None: ...

    async def enqueue_and_wait(self, job_name: str, *args, timeout: int = 30): ...


class ArqJobQueue:
    def __init__(self) -> None:
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        return self._pool

    async def enqueue(self, job_name: str, *args, job_id: str | None = None) -> None:
        pool = await self._get_pool()
        # A fixed job_id coalesces repeat enqueues while one is still queued.
        await pool.enqueue_job(job_name, *args, _job_id=job_id)

    async def enqueue_and_wait(self, job_name: str, *args, timeout: int = 30):
        pool = await self._get_pool()
        job = await pool.enqueue_job(job_name, *args)
        return await job.result(timeout=timeout)


_queue = ArqJobQueue()


def get_job_queue() -> JobQueue:
    return _queue
