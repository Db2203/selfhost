"""Deleting assets: derived files go, library originals stay, tombstones
keep re-indexed copies from coming back."""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.indexer import index_library
from app.models import User
from app.queue import get_job_queue
from app.security import hash_password
from app.storage.local import LocalFilesystemStorage
from tests.test_assets import populated  # noqa: F401  (fixture)
from tests.test_auth import auth_header, login
from tests.test_upload import RecordingQueue, jpeg_bytes, upload


def _first_asset(client, tokens):
    return client.get("/assets", headers=auth_header(tokens)).json()["items"][0]


def test_delete_removes_asset_and_derived_files(populated, test_user, tmp_path):  # noqa: F811
    tokens = login(populated, test_user)
    item = _first_asset(populated, tokens)

    # Thumbnails exist on disk before, gone after.
    media_root = tmp_path / "media"
    thumbs_before = list(media_root.rglob("*.webp"))
    assert thumbs_before

    response = populated.delete(f"/assets/{item['id']}", headers=auth_header(tokens))
    assert response.status_code == 204

    assert populated.get(f"/assets/{item['id']}", headers=auth_header(tokens)).status_code == 404
    page = populated.get("/assets", headers=auth_header(tokens)).json()
    assert page["total"] == 1
    assert len(list(media_root.rglob("*.webp"))) < len(thumbs_before)

    # The library original is on a read-only mount and must survive.
    assert list((tmp_path / "library").rglob("*.jpg"))


def test_reindex_does_not_resurrect_deleted_assets(populated, test_user, tmp_path):  # noqa: F811
    tokens = login(populated, test_user)
    item = _first_asset(populated, tokens)
    populated.delete(f"/assets/{item['id']}", headers=auth_header(tokens))

    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    username, _ = test_user

    async def go():
        from sqlalchemy import select

        async with factory() as session:
            user_id = (
                await session.execute(select(User.id).where(User.username == username))
            ).scalar_one()
            return await index_library(
                session, LocalFilesystemStorage(tmp_path / "library"), user_id
            )

    report = asyncio.run(go())
    assert report.added == 0
    assert report.skipped_deleted == 1

    assert populated.get("/assets", headers=auth_header(tokens)).json()["total"] == 1


def test_deleted_upload_loses_its_original_bytes(populated, test_user, tmp_path):  # noqa: F811
    populated.app.dependency_overrides[get_job_queue] = lambda: RecordingQueue()
    tokens = login(populated, test_user)
    created = upload(populated, tokens, jpeg_bytes("olive")).json()

    uploads_dir = tmp_path / "media" / "uploads"
    assert list(uploads_dir.rglob("*.jpg"))

    populated.delete(f"/assets/{created['id']}", headers=auth_header(tokens))
    assert list(uploads_dir.rglob("*.jpg")) == []


def test_reupload_after_delete_resurrects(populated, test_user):  # noqa: F811
    populated.app.dependency_overrides[get_job_queue] = lambda: RecordingQueue()
    tokens = login(populated, test_user)

    first = upload(populated, tokens, jpeg_bytes("navy")).json()
    populated.delete(f"/assets/{first['id']}", headers=auth_header(tokens))

    again = upload(populated, tokens, jpeg_bytes("navy")).json()
    assert again["duplicate"] is False  # a fresh asset, not the old id
    assert again["id"] != first["id"]


def test_delete_requires_ownership(populated, test_user):  # noqa: F811
    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other = f"del-{uuid.uuid4().hex[:6]}"

    async def go():
        async with factory() as session:
            session.add(User(username=other, password_hash=hash_password("pw123456")))
            await session.commit()

    asyncio.run(go())
    owner_tokens = login(populated, test_user)
    item = _first_asset(populated, owner_tokens)

    intruder = login(populated, (other, "pw123456"))
    assert (
        populated.delete(f"/assets/{item['id']}", headers=auth_header(intruder)).status_code
        == 404
    )
    # Still there for the owner.
    assert populated.get("/assets", headers=auth_header(owner_tokens)).json()["total"] == 2
