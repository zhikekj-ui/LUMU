"""Unified embedding interface — zero-config local semantic embedding.

Uses fastembed (ONNX-based BAAI/bge-small-zh-v1.5, 512d) for local semantic embedding.
No configuration required — works out of the box.
Falls back to hash-bucket (384d) if fastembed is not installed.
Supports optional API-based embedding (OpenAI-compatible) for higher quality.
"""
import json
import hashlib
import math
import urllib.request

_DIM = 384  # hash-bucket fallback dimension
_model = None  # cached fastembed model


def get_embedding_config():
    """Get embedding API config from user_config.json (optional override)."""
    try:
        from core.user_config import load_config
        cfg = load_config()
        return {
            "api_key": cfg.get("embedding_api_key", ""),
            "base_url": cfg.get("embedding_base_url", ""),
            "model": cfg.get("embedding_model", ""),
        }
    except Exception:
        return {"api_key": "", "base_url": "", "model": ""}


def is_api_configured():
    """Check if an embedding API override is configured."""
    cfg = get_embedding_config()
    return bool(cfg["api_key"] and cfg["base_url"] and cfg["model"])


def api_embed(text: str) -> list[float]:
    """Get embedding from configured API (OpenAI-compatible /embeddings endpoint)."""
    cfg = get_embedding_config()
    url = cfg["base_url"].rstrip("/") + "/embeddings"
    payload = json.dumps({"model": cfg["model"], "input": text[:8000]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["data"][0]["embedding"]


def _get_local_model():
    """Lazy-init and cache fastembed model (BAAI/bge-small-zh-v1.5)."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name="BAAI/bge-small-zh-v1.5")
    return _model


def local_embed(text: str) -> list[float]:
    """Local semantic embedding using fastembed (BAAI/bge-small-zh-v1.5, 512d).

    Zero-config: no API key needed, runs on CPU via ONNX runtime.
    Falls back to hash-bucket (384d) if fastembed unavailable.
    """
    try:
        model = _get_local_model()
        embeddings = list(model.embed([text]))
        return list(embeddings[0])
    except Exception:
        return _hash_bucket_embed(text)


def _hash_bucket_embed(text: str) -> list[float]:
    """Hash-bucket embedding — last-resort zero-dependency fallback (384d)."""
    vec = [0.0] * _DIM
    for n in (2, 3, 4):
        for i in range(len(text) - n + 1):
            gram = text[i:i + n]
            h = int(hashlib.md5(gram.encode()).hexdigest(), 16)
            idx = h % _DIM
            val = ((h >> 32) % 1000 - 500) / 500.0
            vec[idx] += val
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def get_embedding_fn():
    """Return the best available embedding function (with API→local fallback)."""
    return get_embedding


def get_embedding(text: str) -> list[float]:
    """Get embedding — API if configured, else local semantic model.

    This is the main entry point. Automatically uses the best available method:
    1. API embedding (if user has configured an external API)
    2. Local fastembed model (BAAI/bge-small-zh-v1.5, zero-config)
    3. Hash-bucket fallback (if fastembed not installed)
    """
    if is_api_configured():
        try:
            return api_embed(text)
        except Exception:
            pass  # fall through to local
    return local_embed(text)


def get_embedding_info() -> dict:
    """Return info about the current embedding configuration."""
    cfg = get_embedding_config()
    if is_api_configured():
        return {
            "mode": "api",
            "api_configured": True,
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "dimension": "varies",
        }
    # Check if fastembed is available
    try:
        import fastembed  # noqa: F401
        return {
            "mode": "local",
            "api_configured": False,
            "model": "BAAI/bge-small-zh-v1.5 (ONNX)",
            "base_url": None,
            "dimension": 512,
        }
    except ImportError:
        return {
            "mode": "local",
            "api_configured": False,
            "model": "hash-bucket (384d)",
            "base_url": None,
            "dimension": _DIM,
        }
