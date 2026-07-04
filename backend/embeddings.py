"""Minimal, self-contained query-embedding helper.

Day 1: we must NOT depend on shared/yandex_client.py (owned by agent B, not ready).
This module provides a small local function that calls the Yandex REST embeddings
endpoint for search *queries* (emb://{folder}/text-search-query/latest, 256-dim).

If the API key is missing or the call fails (e.g. offline / no proxy), we fall back
to a deterministic hashing-based pseudo-embedding so that vector code paths stay
testable without network. The fallback is clearly not semantically meaningful but
keeps the pipeline runnable for fixture-level development.
"""
from __future__ import annotations

import hashlib
import math
from typing import List

import httpx

from config import EMBED_DIM, YANDEX_API_KEY, YANDEX_FOLDER_ID

_YANDEX_EMBED_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"


def _fallback_embedding(text: str, dim: int = EMBED_DIM) -> List[float]:
    """Deterministic hash-based unit vector. Not semantic, but stable & offline."""
    vec = [0.0] * dim
    if not text:
        return vec
    for token in text.lower().split():
        h = hashlib.sha256(token.encode("utf-8")).digest()
        for i in range(dim):
            vec[i] += (h[i % len(h)] - 128) / 128.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_query(text: str, timeout: float = 10.0) -> List[float]:
    """Return a 256-dim embedding for a search query.

    Uses Yandex text-search-query when a key is configured; otherwise (or on any
    error) returns the deterministic fallback so callers never crash.
    """
    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        return _fallback_embedding(text)
    model_uri = f"emb://{YANDEX_FOLDER_ID}/text-search-query/latest"
    try:
        resp = httpx.post(
            _YANDEX_EMBED_URL,
            headers={
                "Authorization": f"Api-Key {YANDEX_API_KEY}",
                "x-folder-id": YANDEX_FOLDER_ID,
            },
            json={"modelUri": model_uri, "text": text},
            timeout=timeout,
        )
        resp.raise_for_status()
        emb = resp.json().get("embedding")
        if emb and len(emb) == EMBED_DIM:
            return [float(x) for x in emb]
    except Exception:
        pass
    return _fallback_embedding(text)


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
