import asyncio
import shutil
import uuid

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.indexer import index_library
from app.models import Asset, User
from app.security import hash_password
from app.storage.local import LocalFilesystemStorage

EXIF_DATETIME_ORIGINAL = 36867


def make_jpeg(path, color, size=(64, 48), taken="2024:06:15 14:30:21"):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[EXIF_DATETIME_ORIGINAL] = taken
    img.save(path, "JPEG", exif=exif)


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    make_jpeg(root / "2024/beach.jpg", "blue")
    make_jpeg(root / "2024/sunset.jpg", "red", size=(100, 80))
    (root / "notes.txt").write_text("not an image")
    # The same photo copied into a second folder must not become a second asset.
    shutil.copy(root / "2024/beach.jpg", root / "backup-beach.jpg")
    return LocalFilesystemStorage(root)


@pytest.fixture
def session_and_user(client):
    """A session factory and a persisted user, riding on the migrated test db."""
    engine = client.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def go():
        async with factory() as session:
            user = User(username=f"idx-{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
            session.add(user)
            await session.commit()
            return user.id

    user_id = asyncio.run(go())
    return factory, user_id


def test_index_library_end_to_end(library, session_and_user):
    factory, user_id = session_and_user

    async def go():
        async with factory() as session:
            report = await index_library(session, library, user_id)
            result = await session.execute(select(Asset).where(Asset.owner_id == user_id))
            return report, list(result.scalars())

    report, assets = asyncio.run(go())

    # 3 image files scanned, but beach.jpg and its copy share a hash.
    assert report.scanned == 3
    assert report.added == 2
    assert report.skipped_duplicates == 1
    assert report.errors == []

    by_name = {a.storage_path: a for a in assets}
    assert len(assets) == 2
    sunset = by_name["2024/sunset.jpg"]
    assert (sunset.width, sunset.height) == (100, 80)
    assert sunset.taken_at is not None
    assert sunset.taken_at.year == 2024
    assert sunset.media_type == "image"
    assert len(sunset.content_hash) == 64


def test_reindex_is_idempotent(library, session_and_user):
    factory, user_id = session_and_user

    async def go():
        async with factory() as session:
            first = await index_library(session, library, user_id)
            second = await index_library(session, library, user_id)
            return first, second

    first, second = asyncio.run(go())
    assert first.added == 2
    assert second.added == 0
    assert second.skipped_duplicates == 3


def test_corrupt_image_is_reported_not_fatal(tmp_path, session_and_user):
    factory, user_id = session_and_user
    root = tmp_path / "bad-library"
    root.mkdir()
    (root / "broken.jpg").write_bytes(b"this is not a jpeg")
    make_jpeg(root / "fine.jpg", "green")

    async def go():
        async with factory() as session:
            return await index_library(session, LocalFilesystemStorage(root), user_id)

    report = asyncio.run(go())
    assert report.added == 1
    assert len(report.errors) == 1
    assert "broken.jpg" in report.errors[0]
