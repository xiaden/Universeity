"""Deterministic local embedder (P2-S3 exact fallback).

Produces a fixed-dimension, normalized vector from text with no external provider, so
the ``VectorIndex`` exact fallback is ACTIVE by default and byte-deterministic (a given
text always embeds identically — replay-stable). The real pgvector HNSW path is a
separate, GATED backend (see :mod:`umd.projections.vector`); this embedder belongs to the
exact in-process fallback only.
"""

from __future__ import annotations

import hashlib
import math
import re

#: Fixed embedding dimension for the exact fallback.
DIM = 64


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


def embed_text(text: str, dim: int = DIM) -> list[float]:
    """A deterministic bag-of-token feature vector (normalized to unit L2)."""
    vec = [0.0] * dim
    for tok in _tokens(text):
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if (digest[4] & 1) else -1.0
        vec[idx] += sign
    # Normalize (a zero vector stays zero).
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity (1.0 == identical direction). Both vectors must be normalized."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return float(dot)


def l2_distance(a: list[float], b: list[float]) -> float:
    """Euclidean distance (0.0 == identical)."""
    return float(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False))))


__all__ = ["embed_text", "cosine", "l2_distance", "DIM"]
