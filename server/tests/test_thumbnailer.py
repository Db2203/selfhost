import asyncio
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.indexer import index_library
from app.models import Asset, Thumbnail, User
from app.security import hash_password
from app.storage.local import LocalFilesystemStorage
from app.thumbnailer import THUMBNAIL_KINDS, render_thumbnail, thumbnail_backlog


def make_jpeg(path, color, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")


@pytest.fixture
def stores(tmp_path):
    library_root = tmp_path / "library"
    make_jpeg(library_root / "big.jpg", "blue", (3000, 2000))
    make_jpeg(library_root / "small.jpg", "red", (120, 90))
    media_root = tmp_path / "media"
    media_root.mkdir()
    return LocalFilesystemStorage(library_root), LocalFilesystemStorage(media_root), media_root


@pytest.fixture
def session_and_user(client):
    engine = client.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def go():
        async with factory() as session:
            user = User(username=f"th-{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
            session.add(user)
            await session.commit()
            return user.id

    return factory, asyncio.run(go())


def test_backlog_generates_all_kinds_and_is_idempotent(stores, session_and_user):
    library, media, media_root = stores
    factory, user_id = session_and_user

    async def go():
        async with factory() as session:
            await index_library(session, library, user_id)
            first = await thumbnail_backlog(session, library, media)
            second = await thumbnail_backlog(session, library, media)
            result = await session.execute(select(Thumbnail))
            return first, second, list(result.scalars())

    first, second, thumbs = asyncio.run(go())

    assert first.generated == 2 * len(THUMBNAIL_KINDS)  # 2 assets x kinds
    assert first.errors == []
    assert second.generated == 0
    assert second.skipped == 2

    for thumb in thumbs:
        file = media_root / thumb.storage_path
        assert file.is_file()
        with Image.open(file) as img:
            assert img.format == "WEBP"
            assert (img.width, img.height) == (thumb.width, thumb.height)
            assert max(img.size) <= THUMBNAIL_KINDS[thumb.kind]


def test_uploaded_assets_thumbnail_from_media_storage(stores, session_and_user):
    """Phone uploads live in media storage, not the library — the backlog
    must read them from the right place instead of erroring out."""
    library, media, media_root = stores
    factory, user_id = session_and_user
    make_jpeg(media_root / "uploads/ab/abcd.jpg", "purple", (800, 600))

    async def go():
        async with factory() as session:
            session.add(
                Asset(
                    owner_id=user_id,
                    storage_path="uploads/ab/abcd.jpg",
                    store="uploads",
                    content_hash="abcd",
                    media_type="image",
                    size_bytes=1,
                    width=800,
                    height=600,
                )
            )
            await session.commit()
            return await thumbnail_backlog(session, library, media)

    report = asyncio.run(go())
    assert report.errors == []
    assert report.generated == len(THUMBNAIL_KINDS)


def test_small_images_are_never_upscaled():
    src = io.BytesIO()
    Image.new("RGB", (120, 90), "green").save(src, "JPEG")
    rendered, width, height = render_thumbnail(src.getvalue(), max_side=256)
    assert (width, height) == (120, 90)


def test_exif_orientation_is_applied():
    src = io.BytesIO()
    img = Image.new("RGB", (200, 100), "blue")
    exif = Image.Exif()
    exif[274] = 6  # rotate 90° CW
    img.save(src, "JPEG", exif=exif)
    rendered, width, height = render_thumbnail(src.getvalue(), max_side=256)
    assert (width, height) == (100, 200)
