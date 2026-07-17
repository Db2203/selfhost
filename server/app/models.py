import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 512  # CLIP ViT-B/32


class EmbeddingVector(TypeDecorator):
    """pgvector on Postgres; JSON on SQLite (used only by local tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        # none_as_null: a missing embedding must be SQL NULL (so the backlog
        # query's IS NULL matches), not the JSON string 'null'.
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    devices: Mapped[list["Device"]] = relationship(back_populates="user")
    assets: Mapped[list["Asset"]] = relationship(back_populates="owner")


class Device(Base):
    """A registered client (phone, PC, browser) with its own revocable session."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    # Hash of the device's current refresh token; null until first login.
    refresh_token_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="devices")


class Asset(Base):
    __tablename__ = "assets"
    # The same photo may exist on the laptop and the phone; the content hash
    # makes the second copy a no-op instead of a duplicate.
    __table_args__ = (UniqueConstraint("owner_id", "content_hash", name="uq_asset_owner_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Path relative to the storage root, so moving the library is config, not a migration.
    storage_path: Mapped[str] = mapped_column(String(1024))
    # Which backend holds the original: "library" (read-only photo folder)
    # or "uploads" (read-write media storage, e.g. phone backups).
    store: Mapped[str] = mapped_column(String(16), default="library", server_default="library")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    media_type: Mapped[str] = mapped_column(String(32))  # "image" | "video"
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Video-only: clip length in seconds (from ffprobe).
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    # Video-only: media-storage path of the web-safe (H.264) rendition, or
    # NULL when the original already plays in browsers. transcoded_at marks
    # that the decision ran at all (same not-scanned/no-result split as
    # faces_scanned_at below).
    playback_path: Mapped[str | None] = mapped_column(String(1024))
    transcoded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector, nullable=True)
    # Set once face detection has run (distinguishes "not scanned" from "no faces").
    faces_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(back_populates="assets")
    thumbnails: Mapped[list["Thumbnail"]] = relationship(back_populates="asset")
    faces: Mapped[list["Face"]] = relationship(back_populates="asset")


class Person(Base):
    """A cluster of similar faces; named by the user."""

    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    faces: Mapped[list["Face"]] = relationship(back_populates="person")


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL")
    )
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector, nullable=True)
    # Bounding box in source-image pixels.
    bbox_x: Mapped[int] = mapped_column(Integer)
    bbox_y: Mapped[int] = mapped_column(Integer)
    bbox_w: Mapped[int] = mapped_column(Integer)
    bbox_h: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    asset: Mapped[Asset] = relationship(back_populates="faces")
    person: Mapped[Person | None] = relationship(back_populates="faces")


class Thumbnail(Base):
    __tablename__ = "thumbnails"
    __table_args__ = (UniqueConstraint("asset_id", "kind", name="uq_thumbnail_asset_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # "grid" | "preview"
    storage_path: Mapped[str] = mapped_column(String(1024))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    asset: Mapped[Asset] = relationship(back_populates="thumbnails")
