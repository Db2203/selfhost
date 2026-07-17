"""Album CRUD, membership, and ownership isolation."""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import User
from app.security import hash_password
from tests.test_assets import populated  # noqa: F401  (fixture)
from tests.test_auth import auth_header, login


def _asset_ids(client, tokens):
    return [a["id"] for a in client.get("/assets", headers=auth_header(tokens)).json()["items"]]


def make_album(client, tokens, name="Trip"):
    response = client.post("/albums", json={"name": name}, headers=auth_header(tokens))
    assert response.status_code == 201
    return response.json()


def test_albums_require_auth(client):
    assert client.get("/albums").status_code == 401


def test_album_lifecycle(populated, test_user):  # noqa: F811
    tokens = login(populated, test_user)
    ids = _asset_ids(populated, tokens)

    album = make_album(populated, tokens, "Summer 2025")
    assert album["asset_count"] == 0
    assert album["cover"] is None

    add = populated.post(
        f"/albums/{album['id']}/assets", json={"asset_ids": ids}, headers=auth_header(tokens)
    )
    assert add.status_code == 204
    # Adding again is a no-op, not an error or a duplicate membership.
    populated.post(
        f"/albums/{album['id']}/assets", json={"asset_ids": ids}, headers=auth_header(tokens)
    )

    listed = populated.get("/albums", headers=auth_header(tokens)).json()
    assert len(listed) == 1
    assert listed[0]["asset_count"] == 2
    assert listed[0]["cover"] is not None

    members = populated.get(f"/albums/{album['id']}/assets", headers=auth_header(tokens)).json()
    assert {m["id"] for m in members} == set(ids)

    renamed = populated.patch(
        f"/albums/{album['id']}", json={"name": "Summer '25"}, headers=auth_header(tokens)
    )
    assert renamed.json()["name"] == "Summer '25"

    removed = populated.delete(
        f"/albums/{album['id']}/assets/{ids[0]}", headers=auth_header(tokens)
    )
    assert removed.status_code == 204
    members = populated.get(f"/albums/{album['id']}/assets", headers=auth_header(tokens)).json()
    assert [m["id"] for m in members] == [ids[1]]


def test_deleting_album_keeps_assets(populated, test_user):  # noqa: F811
    tokens = login(populated, test_user)
    ids = _asset_ids(populated, tokens)
    album = make_album(populated, tokens)
    populated.post(
        f"/albums/{album['id']}/assets", json={"asset_ids": ids}, headers=auth_header(tokens)
    )

    assert (
        populated.delete(f"/albums/{album['id']}", headers=auth_header(tokens)).status_code == 204
    )
    assert populated.get("/albums", headers=auth_header(tokens)).json() == []
    # The photos themselves are untouched.
    assert populated.get("/assets", headers=auth_header(tokens)).json()["total"] == 2


def test_deleting_asset_removes_it_from_albums(populated, test_user):  # noqa: F811
    tokens = login(populated, test_user)
    ids = _asset_ids(populated, tokens)
    album = make_album(populated, tokens)
    populated.post(
        f"/albums/{album['id']}/assets", json={"asset_ids": ids}, headers=auth_header(tokens)
    )

    populated.delete(f"/assets/{ids[0]}", headers=auth_header(tokens))

    members = populated.get(f"/albums/{album['id']}/assets", headers=auth_header(tokens)).json()
    assert [m["id"] for m in members] == [ids[1]]
    assert populated.get("/albums", headers=auth_header(tokens)).json()[0]["asset_count"] == 1


def test_albums_are_owner_scoped(populated, test_user):  # noqa: F811
    engine = populated.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)
    other = f"alb-{uuid.uuid4().hex[:6]}"

    async def go():
        async with factory() as session:
            session.add(User(username=other, password_hash=hash_password("pw123456")))
            await session.commit()

    asyncio.run(go())
    owner_tokens = login(populated, test_user)
    album = make_album(populated, owner_tokens)
    owner_assets = _asset_ids(populated, owner_tokens)

    intruder = login(populated, (other, "pw123456"))
    assert populated.get("/albums", headers=auth_header(intruder)).json() == []
    assert (
        populated.get(f"/albums/{album['id']}/assets", headers=auth_header(intruder)).status_code
        == 404
    )

    # An intruder's album can't be stuffed with someone else's photos.
    own_album = make_album(populated, intruder, "sneaky")
    response = populated.post(
        f"/albums/{own_album['id']}/assets",
        json={"asset_ids": owner_assets},
        headers=auth_header(intruder),
    )
    assert response.status_code == 404
