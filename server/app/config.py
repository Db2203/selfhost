from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "photonest"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://photonest:photonest@postgres:5432/photonest"
    redis_url: str = "redis://redis:6379/0"

    # Must be overridden in production; the default is only usable in dev.
    secret_key: str = "dev-only-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
