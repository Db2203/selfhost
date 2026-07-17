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
    duration_seconds: float | None = None  # videos only
    urls: AssetUrls


class AssetPage(BaseModel):
    items: list[AssetOut]
    total: int
    offset: int
    limit: int


class SearchResults(BaseModel):
    query: str
    items: list[AssetOut]


class PersonOut(BaseModel):
    id: uuid.UUID
    name: str | None
    face_count: int
    # Signed grid-thumbnail URL of a photo containing this person.
    cover: str | None


class PersonRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class PersonMerge(BaseModel):
    other_id: uuid.UUID


class UploadResult(BaseModel):
    id: uuid.UUID
    duplicate: bool
