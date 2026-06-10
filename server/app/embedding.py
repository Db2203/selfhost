"""Image/text embedding for natural-language search.

The real CLIP model is heavy, so it loads lazily and only ever in the worker
process — the API delegates text embedding to the worker via the job queue.
"""

import io
import math
from typing import Protocol

from app.models import EMBEDDING_DIM

CLIP_MODEL = "ViT-B-32"
CLIP_PRETRAINED = "laion2b_s34b_b79k"


class Embedder(Protocol):
    def embed_image(self, data: bytes) -> list[float]: ...

    def embed_text(self, text: str) -> list[float]: ...


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))  # both pre-normalized


class ClipEmbedder:
    """OpenCLIP ViT-B/32. Instantiating downloads weights on first use."""

    def __init__(self) -> None:
        import open_clip
        import torch

        self._torch = torch
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED
        )
        self._model.eval()
        self._tokenizer = open_clip.get_tokenizer(CLIP_MODEL)

    def embed_image(self, data: bytes) -> list[float]:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            tensor = self._preprocess(img.convert("RGB")).unsqueeze(0)
        with self._torch.no_grad():
            features = self._model.encode_image(tensor)[0]
        return normalize([float(x) for x in features])

    def embed_text(self, text: str) -> list[float]:
        tokens = self._tokenizer([text])
        with self._torch.no_grad():
            features = self._model.encode_text(tokens)[0]
        return normalize([float(x) for x in features])


class FakeEmbedder:
    """Deterministic test embedder: images map to their average color and
    texts map to named colors, so "blue" finds blue pictures. First three
    dimensions are RGB; the rest are zero."""

    _colors = {
        "red": (255, 0, 0),
        "green": (0, 128, 0),
        "blue": (0, 0, 255),
        "white": (255, 255, 255),
        "black": (1, 1, 1),
    }

    def embed_image(self, data: bytes) -> list[float]:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            small = img.convert("RGB").resize((8, 8))
            pixels = list(small.getdata())
        n = len(pixels)
        rgb = [sum(p[i] for p in pixels) / n for i in range(3)]
        return normalize(rgb + [0.0] * (EMBEDDING_DIM - 3))

    def embed_text(self, text: str) -> list[float]:
        for name, rgb in self._colors.items():
            if name in text.lower():
                return normalize(list(map(float, rgb)) + [0.0] * (EMBEDDING_DIM - 3))
        return normalize([1.0] * EMBEDDING_DIM)


_embedder: Embedder | None = None


def get_worker_embedder() -> Embedder:
    """Process-wide singleton for the worker; loads CLIP on first call."""
    global _embedder
    if _embedder is None:
        _embedder = ClipEmbedder()
    return _embedder
