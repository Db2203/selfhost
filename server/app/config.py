from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "photonest"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://photonest:photonest@postgres:5432/photonest"
    redis_url: str = "redis://redis:6379/0"

    # Read-write root for derived/uploaded files (thumbnails, phone uploads);
    # swapping to a NAS path or an S3 bucket is a config change, not code.
    storage_root: str = "/srv/storage"
    # The existing photo folder, mounted read-only; the indexer records files
    # here but never modifies or copies them.
    library_root: str = "/srv/library"

    # Must be overridden in production; the default is only usable in dev.
    secret_key: str = "dev-only-change-me"

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
