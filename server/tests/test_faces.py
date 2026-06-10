import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.faces import FakeFaceDetector, detect_faces_backlog
from app.indexer import index_library
from app.models import Face, Person, User
from app.people import cluster_faces
from app.storage import get_library_storage, get_media_storage
from app.storage.local import LocalFilesystemStorage
from app.thumbnailer import thumbnail_backlog
from tests.test_assets import make_jpeg
from tests.test_auth import auth_header, login

detector = FakeFaceDetector()

THRESHOLD = 0.45


@pytest.fixture
def family_album(client, test_user, tmp_path):
    """3 'photos of Alice' (blue), 2 'of Bob' (red), 1 empty scene (black).

    The fake detector treats a solid color as one face of one person.
    """
    library_root = tmp_path / "library"
    make_jpeg(library_root / "alice1.jpg", "blue")
    make_jpeg(library_root / "alice2.jpg", (0, 10, 245))  # nearly the same blue
    make_jpeg(library_root / "alice3.jpg", (10, 0, 250))
    make_jpeg(library_root / "bob1.jpg", "red")
    make_jpeg(library_root / "bob2.jpg", (250, 10, 0))
    make_jpeg(library_root / "scene.jpg", "black")  # no face
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
        async with factory() as session:
            user_id = (
                await session.execute(select(User.id).where(User.username == username))
            ).scalar_one()
            await index_library(session, library, user_id)
            await thumbnail_backlog(session, library, media)
            scan = await detect_faces_backlog(session, detector, library, media)
            return user_id, scan

    user_id, scan = asyncio.run(go())
    return client, factory, user_id, scan


def run_clustering(factory, user_id, min_cluster_size=2):
    async def go():
        async with factory() as session:
            return await cluster_faces(
                session, user_id, threshold=THRESHOLD, min_cluster_size=min_cluster_size
            )

    return asyncio.run(go())


def test_detection_finds_faces_and_marks_scanned(family_album):
    _, factory, _, scan = family_album
    assert scan.scanned == 6
    assert scan.faces_found == 5  # the black scene has none
    assert scan.errors == []

    async def go():
        async with factory() as session:
            faces = list((await session.execute(select(Face))).scalars())
            return faces

    faces = asyncio.run(go())
    assert len(faces) == 5
    assert all(f.embedding is not None and f.score > 0.5 for f in faces)


def test_detection_is_idempotent(family_album):
    _, factory, _, _ = family_album

    async def go():
        async with factory() as session:
            library = LocalFilesystemStorage("/nonexistent")  # must not be read
            return await detect_faces_backlog(session, detector, library, library)

    rerun = asyncio.run(go())
    assert rerun.scanned == 0
    assert rerun.faces_found == 0


def test_clustering_groups_same_person(family_album):
    _, factory, user_id, _ = family_album
    report = run_clustering(factory, user_id)
    assert report.new_people == 2  # Alice and Bob
    assert report.assigned_to_existing == 0

    async def go():
        async with factory() as session:
            people = list((await session.execute(select(Person))).scalars())
            counts = {}
            for person in people:
                counts[person.id] = len(
                    list(
                        (
                            await session.execute(
                                select(Face).where(Face.person_id == person.id)
                            )
                        ).scalars()
                    )
                )
            return sorted(counts.values())

    assert asyncio.run(go()) == [2, 3]


def test_new_photo_joins_existing_named_person(family_album, tmp_path):
    """The killer property: re-clustering must not destroy a user's naming."""
    client, factory, user_id, _ = family_album
    run_clustering(factory, user_id)

    async def name_alice():
        async with factory() as session:
            people = list((await session.execute(select(Person))).scalars())
            # Alice is the 3-face cluster.
            for person in people:
                faces = list(
                    (
                        await session.execute(select(Face).where(Face.person_id == person.id))
                    ).scalars()
                )
                if len(faces) == 3:
                    person.name = "Alice"
            await session.commit()

    asyncio.run(name_alice())

    # A new blue photo arrives and gets scanned.
    library = client.app.dependency_overrides[get_library_storage]()
    media = client.app.dependency_overrides[get_media_storage]()
    make_jpeg(tmp_path / "library" / "alice4.jpg", (5, 5, 252))

    async def rescan():
        async with factory() as session:
            await index_library(session, library, user_id)
            await thumbnail_backlog(session, library, media)
            await detect_faces_backlog(session, detector, library, media)

    asyncio.run(rescan())
    report = run_clustering(factory, user_id)
    assert report.assigned_to_existing == 1
    assert report.new_people == 0

    async def check():
        async with factory() as session:
            alice = (
                await session.execute(select(Person).where(Person.name == "Alice"))
            ).scalar_one()
            faces = list(
                (await session.execute(select(Face).where(Face.person_id == alice.id))).scalars()
            )
            return len(faces)

    assert asyncio.run(check()) == 4


def test_people_endpoints(family_album, test_user):
    client, factory, user_id, _ = family_album
    run_clustering(factory, user_id)
    tokens = login(client, test_user)

    assert client.get("/people").status_code == 401  # anonymous

    people = client.get("/people", headers=auth_header(tokens)).json()
    assert len(people) == 2
    assert people[0]["face_count"] >= people[1]["face_count"]
    assert people[0]["cover"]  # signed url present

    # Rename.
    person_id = people[0]["id"]
    renamed = client.patch(
        f"/people/{person_id}", json={"name": "Alice"}, headers=auth_header(tokens)
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Alice"

    # Person's assets are listed and owner-scoped.
    assets = client.get(f"/people/{person_id}/assets", headers=auth_header(tokens))
    assert assets.status_code == 200
    assert len(assets.json()) == 3

    # Merge Bob into Alice.
    other_id = people[1]["id"]
    merged = client.post(
        f"/people/{person_id}/merge",
        json={"other_id": other_id},
        headers=auth_header(tokens),
    )
    assert merged.status_code == 204
    remaining = client.get("/people", headers=auth_header(tokens)).json()
    assert len(remaining) == 1
    assert remaining[0]["face_count"] == 5

    # Self-merge is rejected.
    assert (
        client.post(
            f"/people/{person_id}/merge",
            json={"other_id": person_id},
            headers=auth_header(tokens),
        ).status_code
        == 400
    )
