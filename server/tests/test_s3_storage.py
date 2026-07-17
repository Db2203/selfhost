"""S3 backend tests — run against a real MinIO service in CI.

Locally they skip unless TEST_S3_ENDPOINT is set (e.g. a MinIO container).
"""

import asyncio
import os
import uuid

import pytest

from app.storage.base import StoragePathError
from app.storage.s3 import S3Storage

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_S3_ENDPOINT"),
    reason="TEST_S3_ENDPOINT not set (MinIO runs in CI)",
)


@pytest.fixture
def storage():
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    store = S3Storage(
        bucket=bucket,
        endpoint_url=os.environ["TEST_S3_ENDPOINT"],
        access_key=os.environ.get("TEST_S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("TEST_S3_SECRET_KEY", "minioadmin"),
    )

    async def make_bucket():
        async with store._client() as client:
            await client.create_bucket(Bucket=bucket)

    asyncio.run(make_bucket())
    return store


def test_write_read_roundtrip(storage):
    async def go():
        await storage.write("originals/ab/photo.jpg", b"jpeg-bytes")
        assert await storage.exists("originals/ab/photo.jpg")
        assert await storage.read("originals/ab/photo.jpg") == b"jpeg-bytes"
        assert await storage.size("originals/ab/photo.jpg") == len(b"jpeg-bytes")

    asyncio.run(go())


def test_missing_object_does_not_exist(storage):
    async def go():
        assert not await storage.exists("nope/missing.jpg")

    asyncio.run(go())


def test_delete_stream_and_list(storage):
    async def go():
        data = b"0123456789" * 500
        await storage.write("a/big.bin", data)
        await storage.write("a/small.bin", b"x")

        chunks = [c async for c in storage.stream("a/big.bin", chunk_size=1024)]
        assert b"".join(chunks) == data
        assert len(chunks) > 1

        listed = [p async for p in storage.list_files("a/")]
        assert sorted(listed) == ["a/big.bin", "a/small.bin"]

        await storage.delete("a/small.bin")
        assert not await storage.exists("a/small.bin")

    asyncio.run(go())


def test_stream_range_yields_exact_slice(storage):
    async def go():
        data = bytes(range(256)) * 40
        await storage.write("clip.mp4", data)
        chunks = [
            c async for c in storage.stream("clip.mp4", chunk_size=100, offset=250, length=500)
        ]
        assert b"".join(chunks) == data[250:750]
        tail = [c async for c in storage.stream("clip.mp4", offset=len(data) - 10)]
        assert b"".join(tail) == data[-10:]

    asyncio.run(go())


def test_traversal_keys_are_rejected(storage):
    async def go():
        with pytest.raises(StoragePathError):
            await storage.read("../escape")

    asyncio.run(go())
