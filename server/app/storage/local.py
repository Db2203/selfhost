import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from app.storage.base import Storage, StoragePathError


class LocalFilesystemStorage(Storage):
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        # Symlinks and ".." segments must not let a key escape the root.
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root):
            raise StoragePathError(f"path escapes storage root: {path!r}")
        return candidate

    async def read(self, path: str) -> bytes:
        return await asyncio.to_thread(self._resolve(path).read_bytes)

    async def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write to a sibling temp file then rename, so a crash mid-write
            # never leaves a half-written object at the final key.
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)

        await asyncio.to_thread(_write)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._resolve(path).is_file)

    async def delete(self, path: str) -> None:
        await asyncio.to_thread(self._resolve(path).unlink)

    async def size(self, path: str) -> int:
        stat = await asyncio.to_thread(self._resolve(path).stat)
        return stat.st_size

    async def stream(
        self,
        path: str,
        chunk_size: int = 1024 * 1024,
        offset: int = 0,
        length: int | None = None,
    ) -> AsyncIterator[bytes]:
        target = self._resolve(path)
        file = await asyncio.to_thread(target.open, "rb")
        try:
            if offset:
                await asyncio.to_thread(file.seek, offset)
            remaining = length
            while True:
                step = chunk_size if remaining is None else min(chunk_size, remaining)
                if step <= 0:
                    break
                chunk = await asyncio.to_thread(file.read, step)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(file.close)

    async def list_files(self, prefix: str = "") -> AsyncIterator[str]:
        base = self._resolve(prefix) if prefix else self.root

        def _walk() -> list[str]:
            if not base.is_dir():
                return []
            # as_posix(): keys are stored in the DB and must use "/" even
            # when the host filesystem is Windows.
            return sorted(
                p.relative_to(self.root).as_posix()
                for p in base.rglob("*")
                if p.is_file()
            )

        for rel_path in await asyncio.to_thread(_walk):
            yield rel_path
