import asyncio

from app.ratelimit import InMemoryRateLimiter
from app.routers.auth import get_rate_limiter


def test_in_memory_limiter_blocks_after_max():
    limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=3600)

    async def go():
        assert await limiter.allow("k") is True
        assert await limiter.allow("k") is True
        assert await limiter.allow("k") is False
        assert await limiter.allow("other") is True  # independent keys

    asyncio.run(go())


def test_login_returns_429_after_repeated_attempts(client, test_user):
    limiter = InMemoryRateLimiter(3, 3600)
    client.app.dependency_overrides[get_rate_limiter] = lambda: limiter
    username, password = test_user

    def attempt(pw):
        return client.post(
            "/auth/login",
            json={"username": username, "password": pw, "device_name": "x"},
        )

    for _ in range(3):
        assert attempt("wrong-password").status_code == 401

    # Limit reached: even the CORRECT password is refused now.
    assert attempt(password).status_code == 429


def test_limit_is_per_username(client, test_user):
    limiter = InMemoryRateLimiter(3, 3600)
    client.app.dependency_overrides[get_rate_limiter] = lambda: limiter
    username, password = test_user

    for _ in range(4):
        client.post(
            "/auth/login",
            json={"username": "someone-else", "password": "x", "device_name": "x"},
        )

    # A different username from the same IP is unaffected.
    fine = client.post(
        "/auth/login",
        json={"username": username, "password": password, "device_name": "x"},
    )
    assert fine.status_code == 200
