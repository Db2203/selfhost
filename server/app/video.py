"""Video handling: ffprobe metadata, poster frames, web-safe renditions.

ffmpeg/ffprobe are system binaries (in the Docker image; installed locally
for dev), driven over subprocess — no heavy Python video bindings. Probing
needs a real file with seek support (MOV metadata often sits at the end of
the file), so storage objects are spooled to a temp file first.
"""

import asyncio
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset
from app.storage.base import Storage

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}

# What browsers play natively from an MP4 container. Anything else (HEVC
# from iPhones, mostly) gets a transcoded rendition.
WEB_SAFE_VIDEO_CODECS = {"h264"}
WEB_SAFE_AUDIO_CODECS = {"aac", "mp3"}


class FfprobeError(RuntimeError):
    """ffprobe failed or returned something unusable."""


class FfmpegError(RuntimeError):
    """ffmpeg failed (frame extraction, transcode)."""


@dataclass
class VideoInfo:
    width: int | None
    height: int | None
    duration_seconds: float | None
    video_codec: str | None
    audio_codec: str | None
    taken_at: datetime | None

    @property
    def is_web_safe(self) -> bool:
        return self.video_codec in WEB_SAFE_VIDEO_CODECS and (
            self.audio_codec is None or self.audio_codec in WEB_SAFE_AUDIO_CODECS
        )


def _parse_creation_time(value: str) -> datetime | None:
    # Container tag, ISO 8601, e.g. "2024-06-15T14:30:21.000000Z".
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def probe_video(local_path: str | Path) -> VideoInfo:
    """Run ffprobe on a local file and pull out what the indexer records."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(local_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FfprobeError(stderr.decode(errors="replace").strip() or "ffprobe failed")

    data = json.loads(stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise FfprobeError("no video stream")
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    fmt = data.get("format", {})
    duration = fmt.get("duration")
    raw_created = fmt.get("tags", {}).get("creation_time")

    return VideoInfo(
        width=video.get("width"),
        height=video.get("height"),
        duration_seconds=float(duration) if duration else None,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        taken_at=_parse_creation_time(raw_created) if raw_created else None,
    )


async def extract_poster_frame(local_path: str | Path, at_seconds: float = 1.0) -> bytes:
    """Grab a single frame as JPEG bytes (thumbnail/embedding input).

    Seeks to ~1s so the poster isn't a black fade-in frame; clips shorter
    than that fall back to the first frame.
    """
    for seek in (at_seconds, 0.0):
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-v", "error",
            "-ss", f"{seek:g}",
            "-i", str(local_path),
            "-frames:v", "1",
            "-f", "image2pipe", "-c:v", "mjpeg", "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and stdout:
            return stdout
    raise FfmpegError(stderr.decode(errors="replace").strip() or "no frame extracted")


def playback_path(content_hash: str) -> str:
    return f"playback/{content_hash[:2]}/{content_hash}.mp4"


async def transcode_to_web_safe(local_in: Path, local_out: Path) -> None:
    """Re-encode to H.264/AAC MP4 — the rendition browsers can always play.

    faststart puts the index at the front of the file so playback starts
    before the whole thing is downloaded. The scale filter rounds odd
    dimensions down: yuv420p H.264 requires them even.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v", "error", "-y",
        "-i", str(local_in),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(local_out),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise FfmpegError(stderr.decode(errors="replace").strip() or "transcode failed")


@dataclass
class TranscodeReport:
    transcoded: int = 0
    already_web_safe: int = 0
    errors: list[str] = field(default_factory=list)


async def transcode_backlog(
    session: AsyncSession, library: Storage, media: Storage
) -> TranscodeReport:
    """Decide playback for every video that hasn't been considered yet.

    Web-safe originals are just marked (playback_path stays NULL and the
    file endpoint serves the original); everything else gets an H.264
    rendition written to media storage. Keyed on content hash, so re-runs
    and interrupted runs only fill in what's missing.
    """
    report = TranscodeReport()
    result = await session.execute(
        select(Asset).where(Asset.media_type == "video", Asset.transcoded_at.is_(None))
    )
    for asset in result.scalars():
        try:
            source = library if asset.store == "library" else media
            async with spooled_local_copy(source, asset.storage_path) as (local, _):
                info = await probe_video(local)
                if info.is_web_safe:
                    report.already_web_safe += 1
                else:
                    rendition = local.with_suffix(".playback.mp4")
                    try:
                        await transcode_to_web_safe(local, rendition)
                        target = playback_path(asset.content_hash)
                        await media.write(target, rendition.read_bytes())
                        asset.playback_path = target
                    finally:
                        rendition.unlink(missing_ok=True)
                    report.transcoded += 1
            asset.transcoded_at = datetime.now(timezone.utc)
            await session.commit()
        except Exception as exc:  # one bad file must not kill the backlog
            await session.rollback()
            logger.exception("transcode failed for %s", asset.storage_path)
            report.errors.append(f"{asset.storage_path}: {exc}")
    return report


@asynccontextmanager
async def spooled_local_copy(storage: Storage, path: str):
    """Stream a storage object into a temp file and yield its local path.

    Also yields the file's sha256 alongside, computed during the copy so the
    (possibly large) object is only pulled from storage once.
    """
    import hashlib

    digest = hashlib.sha256()
    tmp = tempfile.NamedTemporaryFile(suffix=Path(path).suffix, delete=False)
    try:
        try:
            async for chunk in storage.stream(path):
                digest.update(chunk)
                tmp.write(chunk)
        finally:
            tmp.close()
        yield Path(tmp.name), digest.hexdigest()
    finally:
        await asyncio.to_thread(Path(tmp.name).unlink)
