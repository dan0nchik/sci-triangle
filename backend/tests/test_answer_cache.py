"""Unit tests for the answer-cache (Answer-Cache agent).

These run WITHOUT Neo4j/ES: `data_version` is passed explicitly (or its component
collector is monkeypatched), and a throwaway sqlite file is used per test. They cover
hit/miss, data_version invalidation, TTL policy, normalization, skip-of-fallback and
the stats/clear admin surface.
"""
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import answer_cache  # noqa: E402


def _result(answer="ответ", cid="d1"):
    return {
        "answer_md": answer,
        "citations": [{"doc_id": cid, "quote": "q"}],
        "took_ms": 4200,
        "search_id": "s_orig",
        "cached": False,
    }


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    """Point the cache at an isolated sqlite file and reset module state."""
    monkeypatch.setattr(answer_cache, "DB_PATH", tmp_path / "ac.sqlite")
    monkeypatch.setattr(answer_cache, "_initialized", False)
    answer_cache.reset_data_version()
    answer_cache.init()
    return answer_cache


# --------------------------------------------------------------------- hit / miss
def test_hit_and_miss(cache):
    q, f, role, dv = "как очистить воду", {}, "researcher", "v1"
    assert cache.lookup(q, f, role, dv=dv) is None            # cold miss

    assert cache.store(q, f, role, _result(), synth="llm", dv=dv) is True
    hit = cache.lookup(q, f, role, dv=dv)
    assert hit is not None
    assert hit["cached"] is True
    assert hit["answer_md"] == "ответ"

    # a different query is a miss
    assert cache.lookup("совсем другой запрос", f, role, dv=dv) is None


def test_hit_count_increments(cache):
    dv = "v1"
    cache.store("q", {}, "r", _result(), synth="llm", dv=dv)
    for _ in range(3):
        cache.lookup("q", {}, "r", dv=dv)
    s = cache.stats()
    assert s["entries"] == 1
    assert s["hits"] == 3


# ----------------------------------------------------------- data_version invalidation
def test_data_version_invalidation(cache):
    cache.store("q", {}, "r", _result(), synth="llm", dv="v1")
    # same query, NEW data_version -> stale entry must not be served
    assert cache.lookup("q", {}, "r", dv="v2") is None
    # original version still hits
    assert cache.lookup("q", {}, "r", dv="v1") is not None


def test_data_version_from_components(cache, monkeypatch):
    comp = {"es_docs": 10, "es_chunks": 100, "neo_nodes": 5,
            "neo_edges": 7, "emb_mtime": 1.0}
    monkeypatch.setattr(cache, "_components", lambda: dict(comp))
    cache.reset_data_version()
    v1 = cache.data_version(force=True)
    cache.store("q", {}, "r", _result())          # uses v1
    assert cache.lookup("q", {}, "r") is not None

    # simulate data growth (extraction) -> version changes -> miss
    comp["es_docs"] = 11
    cache.reset_data_version()
    v2 = cache.data_version(force=True)
    assert v1 != v2
    assert cache.lookup("q", {}, "r") is None


# --------------------------------------------------------------------- normalization
def test_query_normalization(cache):
    cache.store("Циркуляция  КАТОЛИТА", {}, "r", _result(), synth="llm", dv="v1")
    # lower + collapsed whitespace + ё→е all fold to the same key
    assert cache.lookup("циркуляция католита", {}, "r", dv="v1") is not None


def test_filters_and_role_partition(cache):
    cache.store("q", {"domain": "hydro"}, "r", _result(), synth="llm", dv="v1")
    assert cache.lookup("q", {"domain": "pyro"}, "r", dv="v1") is None   # diff filter
    assert cache.lookup("q", {"domain": "hydro"}, "other", dv="v1") is None  # diff role
    assert cache.lookup("q", {"domain": "hydro"}, "r", dv="v1") is not None


# --------------------------------------------------------------------- TTL policy
def test_empty_answer_short_ttl(cache, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    cache.store("q", {}, "r", _result(), synth="empty", dv="v1")
    assert cache.lookup("q", {}, "r", dv="v1") is not None       # fresh
    now[0] += cache.EMPTY_TTL + 1                                # 15 min later
    assert cache.lookup("q", {}, "r", dv="v1") is None           # expired


def test_normal_answer_survives_short_window(cache, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    cache.store("q", {}, "r", _result(), synth="llm", dv="v1")
    now[0] += cache.EMPTY_TTL + 1                                # 15 min: empty would die
    assert cache.lookup("q", {}, "r", dv="v1") is not None       # 24h answer still alive


# --------------------------------------------------------------------- fallback skip
def test_template_fallback_not_cached(cache):
    assert cache.store("q", {}, "r", _result(), synth="template", dv="v1") is False
    assert cache.lookup("q", {}, "r", dv="v1") is None


# --------------------------------------------------------------------- admin
def test_clear_and_stats(cache):
    cache.store("a", {}, "r", _result(), synth="llm", dv="v1")
    cache.store("b", {}, "r", _result(), synth="llm", dv="v1")
    assert cache.stats()["entries"] == 2
    assert cache.clear() == 2
    assert cache.stats()["entries"] == 0
