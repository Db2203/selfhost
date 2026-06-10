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
