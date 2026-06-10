import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    device_name: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    device_id: uuid.UUID
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    device_id: uuid.UUID
    refresh_token: str


class DeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked: bool

    model_config = {"from_attributes": False}


class AssetUrls(BaseModel):
    grid: str | None
    preview: str | None
    original: str


class AssetOut(BaseModel):
    id: uuid.UUID
    media_type: str
    width: int | None
    height: int | None
    size_bytes: int
    taken_at: datetime | None
    created_at: datetime
    urls: AssetUrls


class AssetPage(BaseModel):
    items: list[AssetOut]
    total: int
    offset: int
    limit: int


class SearchResults(BaseModel):
    query: str
    items: list[AssetOut]
