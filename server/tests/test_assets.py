import asyncio
import uuid

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.indexer import index_library
from app.models import User
from app.security import hash_password
from app.storage import get_library_storage, get_media_storage
from app.storage.local import LocalFilesystemStorage
from app.thumbnailer import thumbnail_backlog
from tests.test_auth import auth_header, login


def make_jpeg(path, color, size=(64, 48), exif_taken=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    kwargs = {}
    if exif_taken:
        exif = Image.Exif()
        exif[36867] = exif_taken
        kwargs["exif"] = exif
    img.save(path, "JPEG", **kwargs)


@pytest.fixture
def populated(client, test_user, tmp_path):
    """Index + thumbnail a small library for test_user; override storages."""
    library_root = tmp_path / "library"
    make_jpeg(library_root / "new.jpg", "blue", exif_taken="2025:01:02 10:00:00")
    make_jpeg(library_root / "old.jpg", "red", exif_taken="2020:05:05 09:00:00")
    media_root = tmp_path / "media"
    media_root.mkdir()
    library = LocalFilesystemStorage(library_root)
    media = LocalFilesystemStorage(media_root)

    client.app.dependency_overrides[get_library_storage] = lambda: library
    client.app.dependency_overrides[get_media_storage] = lambda: media

    engine = client.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    username, _ = test_user

    async def go():
        from sqlalchemy import select

        async with factory() as session:
            user_id = (
                await session.execute(select(User.id).where(User.username == username))
            ).scalar_one()
            await index_library(session, library, user_id)
            await thumbnail_backlog(session, library, media)

    asyncio.run(go())
    return client


def test_list_assets_requires_auth(client):
    assert client.get("/assets").status_code == 401


def test_list_assets_newest_first_with_urls(populated, test_user):
    tokens = login(populated, test_user)
    response = populated.get("/assets", headers=auth_header(tokens))
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert len(page["items"]) == 2
    # 2025 photo before 2020 photo.
    assert page["items"][0]["taken_at"] > page["items"][1]["taken_at"]
    first = page["items"][0]
    assert first["urls"]["grid"] and first["urls"]["preview"] and first["urls"]["original"]


def test_pagination(populated, test_user):
    tokens = login(populated, test_user)
    page = populated.get("/assets?limit=1&offset=1", headers=auth_header(tokens)).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_other_users_assets_are_invisible(populated):
    # A different account sees an empty library and 404 on detail fetches.
    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other = f"other-{uuid.uuid4().hex[:6]}"

    async def go():
        async with factory() as session:
            session.add(User(username=other, password_hash=hash_password("pw123456")))
            await session.commit()

    asyncio.run(go())
    tokens = login(populated, (other, "pw123456"))
    assert populated.get("/assets", headers=auth_header(tokens)).json()["total"] == 0


def test_signed_url_serves_bytes_without_auth_header(populated, test_user):
    tokens = login(populated, test_user)
    item = populated.get("/assets", headers=auth_header(tokens)).json()["items"][0]

    grid = populated.get(item["urls"]["grid"])  # no Authorization header
    assert grid.status_code == 200
    assert grid.headers["content-type"] == "image/webp"
    assert len(grid.content) > 0

    original = populated.get(item["urls"]["original"])
    assert original.status_code == 200
    assert original.headers["content-type"] == "image/jpeg"


def test_tampered_or_expired_signature_is_rejected(populated, test_user):
    tokens = login(populated, test_user)
    item = populated.get("/assets", headers=auth_header(tokens)).json()["items"][0]
    url = item["urls"]["grid"]

    tampered = url.replace("sig=", "sig=00")
    assert populated.get(tampered).status_code == 403

    expired = url.replace("exp=", "exp=1")  # epoch second 1 → long past
    assert populated.get(expired).status_code == 403

    # A signature for one variant must not unlock another.
    swapped = url.replace("/file/grid", "/file/original")
    assert populated.get(swapped).status_code == 403


def test_favorite_toggle_and_filter(populated, test_user):
    tokens = login(populated, test_user)
    items = populated.get("/assets", headers=auth_header(tokens)).json()["items"]
    assert all(item["favorite"] is False for item in items)

    marked = populated.patch(
        f"/assets/{items[0]['id']}",
        json={"favorite": True},
        headers=auth_header(tokens),
    )
    assert marked.status_code == 200
    assert marked.json()["favorite"] is True

    favorites = populated.get("/assets?favorite=true", headers=auth_header(tokens)).json()
    assert favorites["total"] == 1
    assert favorites["items"][0]["id"] == items[0]["id"]

    # Un-favorite puts the filter back to empty.
    populated.patch(
        f"/assets/{items[0]['id']}", json={"favorite": False}, headers=auth_header(tokens)
    )
    assert populated.get("/assets?favorite=true", headers=auth_header(tokens)).json()["total"] == 0


def test_favorite_requires_ownership(populated, test_user):
    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other = f"fav-{uuid.uuid4().hex[:6]}"

    async def go():
        async with factory() as session:
            session.add(User(username=other, password_hash=hash_password("pw123456")))
            await session.commit()

    asyncio.run(go())
    owner_tokens = login(populated, test_user)
    item = populated.get("/assets", headers=auth_header(owner_tokens)).json()["items"][0]

    intruder = login(populated, (other, "pw123456"))
    response = populated.patch(
        f"/assets/{item['id']}", json={"favorite": True}, headers=auth_header(intruder)
    )
    assert response.status_code == 404


def test_range_requests_serve_partial_content(populated, test_user):
    tokens = login(populated, test_user)
    item = populated.get("/assets", headers=auth_header(tokens)).json()["items"][0]
    url = item["urls"]["original"]

    whole = populated.get(url)
    assert whole.status_code == 200
    assert whole.headers["accept-ranges"] == "bytes"
    total = len(whole.content)

    part = populated.get(url, headers={"Range": "bytes=10-49"})
    assert part.status_code == 206
    assert part.content == whole.content[10:50]
    assert part.headers["content-range"] == f"bytes 10-49/{total}"
    assert part.headers["content-length"] == "40"

    # Suffix and open-ended forms.
    tail = populated.get(url, headers={"Range": "bytes=-5"})
    assert tail.status_code == 206
    assert tail.content == whole.content[-5:]
    open_ended = populated.get(url, headers={"Range": f"bytes={total - 3}-"})
    assert open_ended.content == whole.content[-3:]

    # Past the end of the file: unsatisfiable.
    bad = populated.get(url, headers={"Range": f"bytes={total + 10}-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == f"bytes */{total}"


def test_bare_file_url_without_signature_is_rejected(populated, test_user):
    tokens = login(populated, test_user)
    item = populated.get("/assets", headers=auth_header(tokens)).json()["items"][0]
    response = populated.get(f"/assets/{item['id']}/file/grid")
    assert response.status_code in (403, 422)  # missing exp/sig params
