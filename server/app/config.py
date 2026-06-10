from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "photonest"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://photonest:photonest@postgres:5432/photonest"
    redis_url: str = "redis://redis:6379/0"

    # Read-write storage for derived/uploaded files (thumbnails, phone
    # uploads): "local" filesystem or any "s3"-compatible store (MinIO, NAS).
    storage_backend: str = "local"
    storage_root: str = "/srv/storage"
    s3_bucket: str = ""
    s3_endpoint: str = ""  # e.g. http://minio:9000; empty = real AWS
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    # The existing photo folder, mounted read-only; the indexer records files
    # here but never modifies or copies them.
    library_root: str = "/srv/library"

    # Must be overridden in production; the default is only usable in dev.
    secret_key: str = "dev-only-change-me"

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    signed_url_ttl_minutes: int = 60

    # Face clustering: cosine similarity needed to call two faces the same
    # person, and the minimum cluster size that becomes a Person.
    face_match_threshold: float = 0.45
    face_cluster_min_size: int = 2

    # Login attempts allowed per username+IP within the window.
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
