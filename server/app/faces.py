"""Face detection: find faces in assets and store per-face embeddings.

Detection runs in the worker only (InsightFace/ArcFace via ONNX). Each
detected face becomes a `faces` row with a 512-dim embedding; clustering
into named people happens separately (app/people.py).
"""

import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding import normalize
from app.models import Asset, Face, Thumbnail
from app.storage.base import Storage

logger = logging.getLogger(__name__)

MIN_DETECTION_SCORE = 0.55


@dataclass
class DetectedFace:
    bbox: tuple[int, int, int, int]  # x, y, w, h
    score: float
    embedding: list[float]


class FaceDetector(Protocol):
    def detect(self, data: bytes) -> list[DetectedFace]: ...


class InsightFaceDetector:
    """InsightFace buffalo_l pack (detection + ArcFace embeddings), CPU."""

    def __init__(self) -> None:
        import os

        from insightface.app import FaceAnalysis

        root = os.path.expanduser("~/.cache/insightface")
        self._app = FaceAnalysis(name="buffalo_l", root=root)
        self._app.prepare(ctx_id=-1)  # CPU

    def detect(self, data: bytes) -> list[DetectedFace]:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            rgb = np.array(img.convert("RGB"))
        results = self._app.get(rgb[:, :, ::-1])  # insightface expects BGR

        detected = []
        for face in results:
            if face.det_score < MIN_DETECTION_SCORE:
                continue
            x1, y1, x2, y2 = (int(v) for v in face.bbox)
            detected.append(
                DetectedFace(
                    bbox=(x1, y1, max(1, x2 - x1), max(1, y2 - y1)),
                    score=float(face.det_score),
                    embedding=normalize([float(v) for v in face.normed_embedding]),
                )
            )
        return detected


class FakeFaceDetector:
    """Deterministic test detector: a solid-color image is "one face of the
    person with that color"; same color ⇒ same embedding ⇒ same cluster.
    Near-black images contain no face."""

    def detect(self, data: bytes) -> list[DetectedFace]:
        from PIL import Image

        from app.models import EMBEDDING_DIM

        with Image.open(io.BytesIO(data)) as img:
            small = img.convert("RGB").resize((8, 8))
            pixels = list(small.getdata())
            width, height = img.size
        n = len(pixels)
        rgb = [sum(p[i] for p in pixels) / n for i in range(3)]
        if sum(rgb) < 30:  # "no face here"
            return []
        embedding = normalize(rgb + [0.0] * (EMBEDDING_DIM - 3))
        return [DetectedFace(bbox=(0, 0, width, height), score=0.99, embedding=embedding)]


@dataclass
class FaceScanReport:
    scanned: int = 0
    faces_found: int = 0
    errors: list[str] = field(default_factory=list)


async def detect_faces_backlog(
    session: AsyncSession, detector: FaceDetector, library: Storage, media: Storage
) -> FaceScanReport:
    """Detect faces for every asset not scanned yet.

    Uses the preview thumbnail when available (big enough for small faces,
    orientation already baked in); falls back to the original.
    """
    report = FaceScanReport()
    result = await session.execute(select(Asset).where(Asset.faces_scanned_at.is_(None)))
    for asset in result.scalars():
        try:
            thumb = (
                await session.execute(
                    select(Thumbnail).where(
                        Thumbnail.asset_id == asset.id, Thumbnail.kind == "preview"
                    )
                )
            ).scalar_one_or_none()
            data = (
                await media.read(thumb.storage_path)
                if thumb is not None
                else await library.read(asset.storage_path)
            )
            for found in detector.detect(data):
                x, y, w, h = found.bbox
                session.add(
                    Face(
                        asset_id=asset.id,
                        embedding=found.embedding,
                        bbox_x=x,
                        bbox_y=y,
                        bbox_w=w,
                        bbox_h=h,
                        score=found.score,
                    )
                )
                report.faces_found += 1
            asset.faces_scanned_at = datetime.now(timezone.utc)
            await session.commit()
            report.scanned += 1
        except Exception as exc:  # one bad file must not kill the backlog
            await session.rollback()
            logger.exception("face detection failed for %s", asset.storage_path)
            report.errors.append(f"{asset.storage_path}: {exc}")
    return report


_detector: FaceDetector | None = None


def get_worker_detector() -> FaceDetector:
    """Process-wide singleton for the worker; loads models on first call."""
    global _detector
    if _detector is None:
        _detector = InsightFaceDetector()
    return _detector
