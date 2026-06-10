import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.embedding import FakeEmbedder
from app.models import EMBEDDING_DIM, Asset, User
from app.routers.search import get_query_embedder
from app.search import embed_backlog
from app.storage import get_library_storage, get_media_storage
from app.storage.local import LocalFilesystemStorage
from tests.test_assets import make_jpeg
from tests.test_auth import auth_header, login

fake = FakeEmbedder()


@pytest.fixture
def populated_with_colors(client, test_user, tmp_path):
    """A library with one blue and one red photo, indexed + thumbnailed +
    embedded with the fake embedder; query embedding is also faked."""
    from app.indexer import index_library
    from app.thumbnailer import thumbnail_backlog

    library_root = tmp_path / "library"
    make_jpeg(library_root / "ocean.jpg", "blue")
    make_jpeg(library_root / "barn.jpg", "red")
    media_root = tmp_path / "media"
    media_root.mkdir()
    library = LocalFilesystemStorage(library_root)
    media = LocalFilesystemStorage(media_root)

    client.app.dependency_overrides[get_library_storage] = lambda: library
    client.app.dependency_overrides[get_media_storage] = lambda: media

    async def fake_query_embedder():
        async def embed(text: str) -> list[float]:
            return fake.embed_text(text)

        return embed

    client.app.dependency_overrides[get_query_embedder] = fake_query_embedder

    engine = client.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    username, _ = test_user

    async def go():
        async with factory() as session:
            user_id = (
                await session.execute(select(User.id).where(User.username == username))
            ).scalar_one()
            await index_library(session, library, user_id)
            await thumbnail_backlog(session, library, media)
            report = await embed_backlog(session, fake, library, media)
            return report

    report = asyncio.run(go())
    return client, report


def test_embed_backlog_fills_embeddings(populated_with_colors, client):
    _, report = populated_with_colors
    assert report.embedded == 2
    assert report.errors == []

    engine = client.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def go():
        async with factory() as session:
            result = await session.execute(select(Asset))
            return [a.embedding for a in result.scalars()]

    embeddings = asyncio.run(go())
    assert all(e is not None and len(e) == EMBEDDING_DIM for e in embeddings)


def test_embed_backlog_is_idempotent(populated_with_colors, client, test_user):
    populated, _ = populated_with_colors
    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)

    library = populated.app.dependency_overrides[get_library_storage]()
    media = populated.app.dependency_overrides[get_media_storage]()

    async def go():
        async with factory() as session:
            return await embed_backlog(session, fake, library, media)

    assert asyncio.run(go()).embedded == 0


def test_search_requires_auth(client):
    assert client.get("/search?q=beach").status_code == 401


def test_search_ranks_by_meaning(populated_with_colors, test_user):
    populated, _ = populated_with_colors
    tokens = login(populated, test_user)

    blue = populated.get("/search?q=blue ocean", headers=auth_header(tokens))
    assert blue.status_code == 200
    items = blue.json()["items"]
    assert len(items) == 2
    blue_first = items[0]

    red = populated.get("/search?q=red barn", headers=auth_header(tokens)).json()["items"]
    red_first = red[0]

    # Different queries surface different photos first.
    assert blue_first["id"] != red_first["id"]
    # And the result includes usable signed urls.
    assert blue_first["urls"]["grid"]


def test_search_does_not_leak_other_users_photos(populated_with_colors):
    populated, _ = populated_with_colors
    import uuid as uuid_mod

    from app.security import hash_password

    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other = f"search-other-{uuid_mod.uuid4().hex[:6]}"

    async def go():
        async with factory() as session:
            session.add(User(username=other, password_hash=hash_password("pw123456")))
            await session.commit()

    asyncio.run(go())
    tokens = login(populated, (other, "pw123456"))
    results = populated.get("/search?q=blue", headers=auth_header(tokens)).json()
    assert results["items"] == []
