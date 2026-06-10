"""Rate limiting for the auth endpoints (slows credential brute-forcing)."""

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool:
        """Record a hit for key; return False when over the limit."""
        ...


class RedisRateLimiter:
    """Fixed-window counter in Redis (shared across API replicas).

    Fails open: if Redis is unreachable the login path stays available and
    the failure is logged — for a personal server, availability wins.
    """

    def __init__(self, redis_url: str, max_attempts: int, window_seconds: int):
        self._url = redis_url
        self._max = max_attempts
        self._window = window_seconds
        self._client = None

    async def allow(self, key: str) -> bool:
        try:
            if self._client is None:
                from redis.asyncio import Redis

                self._client = Redis.from_url(self._url)
            redis_key = f"ratelimit:{key}:{int(time.time() // self._window)}"
            count = await self._client.incr(redis_key)
            if count == 1:
                await self._client.expire(redis_key, self._window)
            return count <= self._max
        except Exception:
            logger.exception("rate limiter unavailable; allowing request")
            return True


class InMemoryRateLimiter:
    """Single-process fixed window; for tests and redis-less dev runs."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, tuple[int, int]] = {}

    async def allow(self, key: str) -> bool:
        window = int(time.time() // self._window)
        count, seen_window = self._hits.get(key, (0, window))
        if seen_window != window:
            count = 0
        count += 1
        self._hits[key] = (count, window)
        return count <= self._max
