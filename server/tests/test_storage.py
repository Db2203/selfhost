import asyncio

import pytest

from app.storage.base import StoragePathError
from app.storage.local import LocalFilesystemStorage


@pytest.fixture
def storage(tmp_path):
    return LocalFilesystemStorage(tmp_path)


def test_write_read_roundtrip(storage):
    async def go():
        await storage.write("originals/ab/photo.jpg", b"jpeg-bytes")
        assert await storage.exists("originals/ab/photo.jpg")
        assert await storage.read("originals/ab/photo.jpg") == b"jpeg-bytes"
        assert await storage.size("originals/ab/photo.jpg") == len(b"jpeg-bytes")

    asyncio.run(go())


def test_delete_removes_file(storage):
    async def go():
        await storage.write("a.txt", b"x")
        await storage.delete("a.txt")
        assert not await storage.exists("a.txt")

    asyncio.run(go())


def test_stream_yields_all_content_in_chunks(storage):
    async def go():
        data = b"0123456789" * 1000
        await storage.write("big.bin", data)
        chunks = [c async for c in storage.stream("big.bin", chunk_size=1024)]
        assert b"".join(chunks) == data
        assert len(chunks) > 1

    asyncio.run(go())


def test_stream_range_yields_exact_slice(storage):
    async def go():
        data = bytes(range(256)) * 40
        await storage.write("clip.mp4", data)
        # Middle slice, spanning chunk boundaries.
        chunks = [
            c async for c in storage.stream("clip.mp4", chunk_size=100, offset=250, length=500)
        ]
        assert b"".join(chunks) == data[250:750]
        # Open-ended tail.
        tail = [c async for c in storage.stream("clip.mp4", offset=len(data) - 10)]
        assert b"".join(tail) == data[-10:]

    asyncio.run(go())


def test_path_escaping_root_is_rejected(storage):
    async def go():
        with pytest.raises(StoragePathError):
            await storage.read("../../etc/passwd")
        with pytest.raises(StoragePathError):
            await storage.write("a/../../outside.txt", b"x")

    asyncio.run(go())


def test_write_is_atomic_no_tmp_left_behind(storage, tmp_path):
    async def go():
        await storage.write("photo.jpg", b"data")
        leftovers = [p for p in tmp_path.rglob("*.tmp")]
        assert leftovers == []

    asyncio.run(go())
