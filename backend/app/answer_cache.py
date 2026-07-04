"""Answer-Cache — full caching of /api/search responses (Answer-Cache agent).

A repeated identical question must NOT re-run the LLM planner/synthesis or the
retrieval pipeline. The whole SearchResponse is cached in a standalone sqlite file
(`backend/answer_cache.sqlite`) keyed by a hash that folds in a live *data_version*,
so the cache self-invalidates whenever the corpus/graph/embeddings grow (extraction,
sync, checkpoint precompute) — a stale answer is more dangerous than a cache miss.

Key = sha256(
    normalized_query        # lower + collapsed whitespace + ё→е
  ⨝ canonical_filters       # empty/'all' dropped, JSON with sorted keys
  ⨝ role
  ⨝ data_version            # ES doc+chunk counts, Neo4j node+edge counts,
)                           #   active embedding-matrix mtime

Value = full SearchResponse JSON + created_at + hit_count + expires_at.

TTL policy:
  * normal answer (LLM-grounded)          -> DEFAULT_TTL (24h)
  * honest empty "не найдено" (0 citations) -> EMPTY_TTL (15 min): data grows, the
    topic may appear soon, so we keep such answers short-lived.
  * fallback template (LLM unavailable) / errors -> NOT cached at all.

Connections are opened per call (check_same_thread=False), mirroring app/store.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DB_PATH = BACKEND / "answer_cache.sqlite"

DEFAULT_TTL = 24 * 60 * 60      # 24h for grounded answers
EMPTY_TTL = 15 * 60            # 15 min for honest "not found" answers
_DV_TTL = 15.0                # in-memory data_version cache window (seconds)

_lock = threading.Lock()
_initialized = False

# in-memory data_version cache (avoids hitting ES/Neo4j on every request)
_dv_cache: Dict[str, Any] = {"v": None, "at": 0.0}
_dv_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        with _conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS answers (
                    k             TEXT PRIMARY KEY,
                    data_version  TEXT,
                    response      TEXT,
                    created_at    TEXT,
                    expires_at    REAL,
                    hit_count     INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_answers_exp ON answers(expires_at);

                CREATE TABLE IF NOT EXISTS meta (
                    name  TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0
                );
                """
            )
        _initialized = True


def _bump(c: sqlite3.Connection, name: str, delta: int = 1) -> None:
    c.execute(
        "INSERT INTO meta(name, value) VALUES(?, ?) "
        "ON CONFLICT(name) DO UPDATE SET value = value + ?",
        (name, delta, delta),
    )


# ------------------------------------------------------------------ data_version
def _components() -> Dict[str, Any]:
    """Live signals whose change must invalidate the cache. Each is best-effort:
    a failing backend yields 0 (which still produces a deterministic, if pessimistic,
    version — flapping only causes extra misses, never stale hits)."""
    from app import chunk_vectors, db
    from config import ES_CHUNKS, ES_DOCUMENTS

    es_docs = es_chunks = neo_nodes = neo_edges = 0
    emb_mtime = 0.0
    try:
        es_docs = int(db.es().count(index=ES_DOCUMENTS)["count"])
    except Exception:
        pass
    try:
        es_chunks = int(db.es().count(index=ES_CHUNKS)["count"])
    except Exception:
        pass
    try:
        with db.driver().session() as s:
            neo_nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            neo_edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    except Exception:
        pass
    try:
        npy, _ = chunk_vectors._resolve_paths()
        if npy.exists():
            emb_mtime = npy.stat().st_mtime
    except Exception:
        pass
    return {"es_docs": es_docs, "es_chunks": es_chunks,
            "neo_nodes": neo_nodes, "neo_edges": neo_edges,
            "emb_mtime": round(emb_mtime, 3)}


def data_version(force: bool = False) -> str:
    now = time.time()
    with _dv_lock:
        if not force and _dv_cache["v"] and (now - _dv_cache["at"]) < _DV_TTL:
            return _dv_cache["v"]
    comp = _components()
    v = ("d{es_docs}-c{es_chunks}-n{neo_nodes}-e{neo_edges}-m{emb_mtime}"
         .format(**comp))
    with _dv_lock:
        _dv_cache["v"] = v
        _dv_cache["at"] = now
    return v


def reset_data_version() -> None:
    """Force the next data_version() to recompute (used by tests / after a known sync)."""
    with _dv_lock:
        _dv_cache["v"] = None
        _dv_cache["at"] = 0.0


# ------------------------------------------------------------------ key
def _normalize_query(q: str) -> str:
    q = (q or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", q).strip()


def _canon_filters(filters: Optional[Dict[str, Any]]) -> str:
    f = {k: v for k, v in (filters or {}).items() if v not in (None, "", "all")}
    return json.dumps(f, sort_keys=True, ensure_ascii=False)


def make_key(query: str, filters: Optional[Dict[str, Any]], role: Optional[str],
             dv: Optional[str] = None) -> str:
    dv = dv if dv is not None else data_version()
    raw = "\x1f".join([
        _normalize_query(query),
        _canon_filters(filters),
        (role or "researcher"),
        dv,
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ lookup / store
def lookup(query: str, filters: Optional[Dict[str, Any]],
           role: Optional[str], dv: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the cached SearchResponse dict on a live hit (and bump hit_count),
    else None. Counters (lookups/hits) are updated for /api/stats."""
    init()
    key = make_key(query, filters, role, dv=dv)
    now = time.time()
    try:
        with _conn() as c:
            _bump(c, "lookups", 1)
            row = c.execute(
                "SELECT response, expires_at, hit_count FROM answers WHERE k = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] is not None and row["expires_at"] < now:
                # expired — drop it so the table stays clean; counts as a miss
                c.execute("DELETE FROM answers WHERE k = ?", (key,))
                return None
            c.execute("UPDATE answers SET hit_count = hit_count + 1 WHERE k = ?", (key,))
            _bump(c, "hits", 1)
            result = json.loads(row["response"])
    except Exception:
        return None
    result["cached"] = True
    return result


def store(query: str, filters: Optional[Dict[str, Any]], role: Optional[str],
          result: Dict[str, Any], synth: Optional[str] = None,
          dv: Optional[str] = None) -> bool:
    """Persist a successful SearchResponse. Returns True if cached.

    Not cached: fallback-template answers (synth=='template', LLM was down) — a
    degraded answer must never masquerade as the real one. Empty "not found"
    answers get the short TTL; everything else the 24h TTL.
    """
    if synth == "template":
        return False
    init()
    ttl = EMPTY_TTL if synth == "empty" else DEFAULT_TTL
    dv = dv if dv is not None else data_version()
    key = make_key(query, filters, role, dv=dv)
    payload = dict(result)
    payload["cached"] = False
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO answers"
                "(k, data_version, response, created_at, expires_at, hit_count) "
                "VALUES (?,?,?,?,?,COALESCE("
                "(SELECT hit_count FROM answers WHERE k = ?), 0))",
                (key, dv, json.dumps(payload, ensure_ascii=False),
                 _now_iso(), time.time() + ttl, key),
            )
    except Exception:
        return False
    return True


# ------------------------------------------------------------------ admin / stats
def clear() -> int:
    """Delete all cached answers (DELETE /api/cache). Counters are kept."""
    init()
    with _conn() as c:
        n = c.execute("SELECT count(*) AS c FROM answers").fetchone()["c"]
        c.execute("DELETE FROM answers")
    return int(n)


def stats() -> Dict[str, Any]:
    """{entries, hits, hit_rate, size_mb} for /api/stats."""
    init()
    entries = hits = lookups = 0
    try:
        with _conn() as c:
            entries = c.execute("SELECT count(*) AS c FROM answers").fetchone()["c"]
            m = {r["name"]: r["value"]
                 for r in c.execute("SELECT name, value FROM meta")}
        hits = int(m.get("hits", 0))
        lookups = int(m.get("lookups", 0))
    except Exception:
        pass
    hit_rate = round(hits / lookups, 3) if lookups else 0.0
    size_mb = 0.0
    try:
        if DB_PATH.exists():
            size_mb = round(DB_PATH.stat().st_size / (1024 * 1024), 3)
    except Exception:
        pass
    return {"entries": int(entries), "hits": hits, "hit_rate": hit_rate,
            "size_mb": size_mb}
