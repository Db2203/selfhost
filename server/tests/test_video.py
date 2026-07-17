"""Video indexing tests. Need ffmpeg/ffprobe on PATH (present in CI and the
Docker image); skipped otherwise, like the S3 tests without MinIO."""

import asyncio
import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.indexer import index_library
from app.models import Asset, User
from app.security import hash_password
from app.storage.local import LocalFilesystemStorage
from app.thumbnailer import thumbnail_backlog
from app.video import probe_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg not installed",
)


def make_mp4(path, seconds=1.0, size="64x48", metadata=None):
    """Render a tiny H.264 clip with ffmpeg's synthetic test source."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    ]
    for key, value in (metadata or {}).items():
        cmd += ["-metadata", f"{key}={value}"]
    subprocess.run(cmd + [str(path)], check=True)


@pytest.fixture
def session_and_user(client):
    engine = client.app.state.test_engine
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def go():
        async with factory() as session:
            user = User(username=f"vid-{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
            session.add(user)
            await session.commit()
            return user.id

    return factory, asyncio.run(go())


def test_probe_video_reads_metadata(tmp_path):
    make_mp4(
        tmp_path / "clip.mp4",
        seconds=2.0,
        metadata={"creation_time": "2024-06-15T14:30:21.000000Z"},
    )

    info = asyncio.run(probe_video(tmp_path / "clip.mp4"))

    assert (info.width, info.height) == (64, 48)
    assert info.duration_seconds == pytest.approx(2.0, abs=0.3)
    assert info.video_codec == "h264"
    assert info.is_web_safe
    assert info.taken_at is not None and info.taken_at.year == 2024


def test_index_library_adds_video_assets(tmp_path, session_and_user):
    factory, user_id = session_and_user
    root = tmp_path / "library"
    make_mp4(root / "2024/holiday.mp4", seconds=1.0)
    # Same bytes twice: the copy must dedup, exactly like photos.
    (root / "copy.mp4").write_bytes((root / "2024/holiday.mp4").read_bytes())

    async def go():
        async with factory() as session:
            report = await index_library(session, LocalFilesystemStorage(root), user_id)
            result = await session.execute(select(Asset).where(Asset.owner_id == user_id))
            return report, list(result.scalars())

    report, assets = asyncio.run(go())

    assert report.scanned == 2
    assert report.added == 1
    assert report.skipped_duplicates == 1
    assert report.errors == []

    video = assets[0]
    assert video.media_type == "video"
    assert video.storage_path == "2024/holiday.mp4"
    assert (video.width, video.height) == (64, 48)
    assert video.duration_seconds == pytest.approx(1.0, abs=0.3)
    assert video.transcoded_at is None  # transcode decision hasn't run yet


def test_broken_video_is_reported_not_fatal(tmp_path, session_and_user):
    factory, user_id = session_and_user
    root = tmp_path / "library"
    root.mkdir()
    (root / "broken.mp4").write_bytes(b"not really a video")
    make_mp4(root / "fine.mp4")

    async def go():
        async with factory() as session:
            return await index_library(session, LocalFilesystemStorage(root), user_id)

    report = asyncio.run(go())
    assert report.added == 1
    assert len(report.errors) == 1
    assert "broken.mp4" in report.errors[0]


def test_thumbnail_backlog_leaves_videos_alone(tmp_path, session_and_user):
    """Until poster frames land, video rows must not error the image backlog."""
    factory, user_id = session_and_user
    root = tmp_path / "library"
    make_mp4(root / "clip.mp4")
    media = LocalFilesystemStorage(tmp_path / "media")

    async def go():
        async with factory() as session:
            await index_library(session, LocalFilesystemStorage(root), user_id)
            return await thumbnail_backlog(session, LocalFilesystemStorage(root), media)

    report = asyncio.run(go())
    assert report.errors == []
    assert report.generated == 0
