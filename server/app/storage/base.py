from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class StoragePathError(ValueError):
    """The requested path is invalid (e.g. escapes the storage root)."""


class Storage(ABC):
    """Backend-agnostic access to stored files.

    All paths are relative keys (e.g. "originals/ab/cd/abcd123.jpg"); the
    backend decides where they physically live. Business logic must never
    touch the filesystem or an object store directly — always through this.
    """

    @abstractmethod
    async def read(self, path: str) -> bytes: ...

    @abstractmethod
    async def write(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...

    @abstractmethod
    async def size(self, path: str) -> int: ...

    @abstractmethod
    def stream(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]: ...

    @abstractmethod
    def list_files(self, prefix: str = "") -> AsyncIterator[str]:
        """Yield relative paths of all files under prefix (recursively)."""
        ...
