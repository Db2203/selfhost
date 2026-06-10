import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import get_session
from app.main import create_app
from app.models import User
from app.ratelimit import InMemoryRateLimiter
from app.routers.auth import get_rate_limiter
from app.security import hash_password

SERVER_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_url(tmp_path):
    return os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")


@pytest.fixture
def migrated_db(db_url):
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(config, "head")
    yield db_url
    command.downgrade(config, "base")


@pytest.fixture
def client(migrated_db):
    # NullPool: no connection may outlive one event loop (asyncpg requirement).
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    # Permissive limiter so login-heavy tests don't trip it; the rate-limit
    # tests install a strict one themselves.
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter(10_000, 60)
    app.state.test_engine = engine

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_user(client):
    """Create a user directly in the DB; returns (username, password)."""
    username = f"user-{uuid.uuid4().hex[:8]}"
    password = "correct horse battery staple"

    engine = client.app.state.test_engine

    async def go():
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(User(username=username, password_hash=hash_password(password)))
            await session.commit()

    asyncio.run(go())
    return username, password
