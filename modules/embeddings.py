"""Embedding model and helpers for semantic search.

Uses sentence-transformers (all-MiniLM-L6-v2) to encode text into
normalized 384-dimensional vectors, stored as BLOBs in SQLite.
Similarity is computed in Python via dot product (valid for unit vectors).
"""

import struct

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(text: str) -> list[float]:
    """Encode text into a normalized embedding vector (384 dims)."""
    return _get_model().encode(text, normalize_embeddings=True).tolist()


def to_blob(vec: list[float]) -> bytes:
    """Serialize a float list to a binary blob for SQLite storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def from_blob(blob: bytes) -> list[float]:
    """Deserialize a binary blob back to a float list."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def rank(
    query_vec: list[float],
    candidates: list[tuple[str, list[float]]],
) -> list[tuple[str, float]]:
    """Return (key, score) pairs sorted by descending cosine similarity.

    Since both query and candidate vectors are L2-normalised, the dot
    product equals the cosine similarity — values range from -1 to 1.
    """
    if not candidates:
        return []
    keys = [c[0] for c in candidates]
    matrix = np.array([c[1] for c in candidates])
    q = np.array(query_vec)
    scores: list[float] = (matrix @ q).tolist()
    return sorted(zip(keys, scores), key=lambda x: x[1], reverse=True)
