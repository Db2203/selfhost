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
    """Read-write storage for derived/uploaded files (thumbnails, uploads)."""
    settings = get_settings()
    if settings.storage_backend == "s3":
        from app.storage.s3 import S3Storage

        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        )
    return LocalFilesystemStorage(settings.storage_root)


def get_library_storage() -> Storage:
    """The user's existing photo library, treated as read-only."""
    return LocalFilesystemStorage(get_settings().library_root)
