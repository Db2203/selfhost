from app.config import get_settings
from app.storage.base import Storage, StoragePathError
from app.storage.local import LocalFilesystemStorage

__all__ = ["Storage", "StoragePathError", "LocalFilesystemStorage", "get_storage"]


def get_storage() -> Storage:
    """Build the configured storage backend.

    Only the local filesystem exists today; an S3/MinIO backend slots in here
    later without touching any caller.
    """
    settings = get_settings()
    return LocalFilesystemStorage(settings.storage_root)
