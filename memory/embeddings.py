"""Shared dense embedding for memory & retrieval — real semantics via fastembed.

This module is the SINGLE source of embeddings for the agent's own memory
(semantic.py / intelligent_memory.py) and for RAG. It wraps
``knowledge.embedding.get_embedding`` so that *everything* in the framework
shares one vector space (the same BAAI/bge-small-zh-v1.5 model the knowledge
base uses). Previous hashing / TF-IDF based "embeddings" are replaced by real
semantic vectors, so the agent can finally recall its own past by *meaning*,
not just by keyword overlap.

Embeddings are L2-normalized so that cosine(a, b) == dot(a, b).
"""
import math

# bge-small-zh-v1.5 produces 512-d vectors (local mode). This is the fixed
# storage dimension for all persisted memory vectors.
DIM = 512


def dimension() -> int:
    """Return the fixed storage dimension of embedded vectors."""
    return DIM


def embed(text: str) -> list[float]:
    """Return a normalized 512-d dense vector for ``text``.

    Uses the unified ``knowledge.embedding`` entry point, which picks the best
    available backend (configured API -> local fastembed -> hash fallback).
    The result is L2-normalized.
    """
    from knowledge.embedding import get_embedding

    vec = list(get_embedding(text or ""))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two (normalized) dense vectors.

    Zips to the shorter length so a dimension mismatch (e.g. a not-yet-migrated
    legacy vector) degrades gracefully instead of crashing.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(n))
