import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

SERVER_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_url(tmp_path):
    # SQLite locally; CI sets TEST_DATABASE_URL to a real Postgres service.
    return os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")


@pytest.fixture
def alembic_config(db_url):
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def _table_names(engine) -> set[str]:
    async def go():
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

    return asyncio.run(go())


def test_upgrade_creates_schema_and_downgrade_removes_it(alembic_config, db_url):
    command.upgrade(alembic_config, "head")
    engine = create_async_engine(db_url)
    try:
        tables = _table_names(engine)
        assert {"users", "devices", "assets", "thumbnails"} <= tables

        command.downgrade(alembic_config, "base")
        assert not ({"users", "devices", "assets", "thumbnails"} & _table_names(engine))
    finally:
        asyncio.run(engine.dispose())


def test_duplicate_asset_hash_per_owner_is_rejected(alembic_config, db_url):
    command.upgrade(alembic_config, "head")
    engine = create_async_engine(db_url)

    def make_id():
        return str(uuid.uuid4()) if "sqlite" in db_url else uuid.uuid4()

    insert_asset = text(
        "INSERT INTO assets"
        " (id, owner_id, storage_path, content_hash, media_type, size_bytes)"
        " VALUES (:id, :owner, :path, :hash, 'image', 1)"
    )

    async def go():
        owner = make_id()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, password_hash)"
                    " VALUES (:id, :username, 'x')"
                ),
                {"id": owner, "username": f"u-{owner}"[:60]},
            )
            await conn.execute(
                insert_asset,
                {"id": make_id(), "owner": owner, "path": "a/one.jpg", "hash": "same-hash"},
            )

        # Postgres aborts the whole transaction on a constraint violation, so
        # the duplicate insert gets its own transaction (rolled back on error).
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    insert_asset,
                    {
                        "id": make_id(),
                        "owner": owner,
                        "path": "b/copy-of-one.jpg",
                        "hash": "same-hash",
                    },
                )

    try:
        asyncio.run(go())
    finally:
        asyncio.run(engine.dispose())
        command.downgrade(alembic_config, "base")
