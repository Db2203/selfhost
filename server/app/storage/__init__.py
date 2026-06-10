from app.config import get_settings
from app.storage.base import Storage, StoragePathError
from app.storage.local import LocalFilesystemStorage

__all__ = [
    "Storage",
    "StoragePathError",
    "LocalFilesystemStorage",
    "get_media_storage",
    "get_library_storage",
]


def get_media_storage() -> Storage:
    """Read-write storage for derived/uploaded files (thumbnails, uploads).

    Only the local filesystem exists today; an S3/MinIO backend slots in here
    later without touching any caller.
    """
    return LocalFilesystemStorage(get_settings().storage_root)


def get_library_storage() -> Storage:
    """The user's existing photo library, treated as read-only."""
    return LocalFilesystemStorage(get_settings().library_root)
