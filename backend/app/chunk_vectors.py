"""Precomputed chunk-embedding store (agent R, task 1).

Loads graph/embeddings/chunk_embeddings.npy ([N,256] float32, text-search-doc space)
+ chunk_ids.json ([{chunk_id, doc_id}] in row order) into memory once, L2-normalizes
rows, and serves:

  * get(chunk_id)      -> normalized vector (list[float]) or None
  * search(qvec, k)    -> top-k [(chunk_id, doc_id, cosine)] over the WHOLE corpus

This is the "vector branch by PRECOMPUTE": cosine scoring uses precomputed doc-space
vectors, never an in-process embedding of candidate chunk texts (the old p95-killer).
Chosen over a Neo4j :Chunk vector index / ES dense_vector because an in-memory matmul
over ~29k x 256 is <10 ms and needs no re-index (documented in backend/README.md).

The file is reloaded automatically when its mtime changes, so a running backend picks
up a growing precompute (checkpoint tests) without a restart.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

_REPO = Path(__file__).resolve().parent.parent.parent
_NPY = _REPO / "graph" / "embeddings" / "chunk_embeddings.npy"
_IDS = _REPO / "graph" / "embeddings" / "chunk_ids.json"

_lock = threading.Lock()
_mat: Optional[np.ndarray] = None          # [N,256] L2-normalized float32
_ids: List[dict] = []                       # row -> {chunk_id, doc_id}
_index: dict = {}                           # chunk_id -> row
_mtime: float = 0.0


def _load(force: bool = False) -> None:
    global _mat, _ids, _index, _mtime
    if not _NPY.exists() or not _IDS.exists():
        return
    mt = _NPY.stat().st_mtime
    if not force and _mat is not None and mt == _mtime:
        return
    with _lock:
        mt = _NPY.stat().st_mtime
        if not force and _mat is not None and mt == _mtime:
            return
        arr = np.load(_NPY).astype(np.float32)
        ids = json.load(open(_IDS, encoding="utf-8"))
        n = min(len(arr), len(ids))
        arr = arr[:n]
        ids = ids[:n]
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        _mat = arr / norms
        _ids = ids
        _index = {d["chunk_id"]: i for i, d in enumerate(ids)}
        _mtime = mt


def ready() -> bool:
    _load()
    return _mat is not None and len(_ids) > 0


def n_vectors() -> int:
    _load()
    return 0 if _mat is None else int(_mat.shape[0])


def get(chunk_id: str) -> Optional[List[float]]:
    _load()
    i = _index.get(chunk_id)
    if i is None or _mat is None:
        return None
    return _mat[i].tolist()


def has(chunk_id: str) -> bool:
    _load()
    return chunk_id in _index


def search(qvec: List[float], k: int = 20) -> List[Tuple[str, str, float]]:
    """Top-k chunks by cosine(qvec, chunk) over the whole precomputed corpus."""
    _load()
    if _mat is None or not qvec:
        return []
    q = np.asarray(qvec, dtype=np.float32)
    nq = np.linalg.norm(q)
    if nq == 0:
        return []
    q = q / nq
    sims = _mat @ q                                  # cosine (rows normalized)
    k = min(k, sims.shape[0])
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    out = []
    for i in idx:
        d = _ids[int(i)]
        out.append((d["chunk_id"], d["doc_id"], float(sims[int(i)])))
    return out


def cosine_to(qvec: List[float], chunk_id: str) -> Optional[float]:
    v = get(chunk_id)
    if v is None or not qvec:
        return None
    q = np.asarray(qvec, dtype=np.float32)
    nq = np.linalg.norm(q)
    if nq == 0:
        return None
    return float(np.dot(np.asarray(v, dtype=np.float32), q / nq))
