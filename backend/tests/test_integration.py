"""Integration tests for the C-store: fixture load, 3 Cypher scenarios, API calls.

Run:  ../.venv-c/bin/python -m pytest tests -v   (from backend/)
Requires Neo4j (and preferably ES) from docker-compose to be up.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.conftest import requires_neo4j  # noqa: E402


# --------------------------------------------------------------- fixture load
@requires_neo4j
def test_fixture_loaded(loaded):
    from app import db
    stats = db.graph_stats()
    assert stats["n_nodes"] >= 40
    assert stats["n_edges"] >= 55
    assert stats["node_types"].get("Assertion", 0) >= 4
    assert stats["contradictions"] >= 1


# --------------------------------------------------------------- Cypher scenario 1
@requires_neo4j
def test_cypher_three_level_traversal(loaded):
    """3-level traversal from a process reaches its measurement."""
    from app import db
    with db.driver().session() as s:
        rows = s.run(
            """
            MATCH (p:Entity {id:$id})-[*1..3]-(m:Measurement)
            RETURN DISTINCT m.id AS id
            """,
            id="proc:electrowinning_ni",
        ).data()
    ids = {r["id"] for r in rows}
    assert "meas:ni_recovery_925" in ids


# --------------------------------------------------------------- Cypher scenario 2
@requires_neo4j
def test_cypher_numeric_condition_filter(loaded):
    """Filter operates_at_condition edges by numeric value (<=300 sulfates)."""
    from app import db
    with db.driver().session() as s:
        rows = s.run(
            """
            MATCH (p)-[r:operates_at_condition]->(c:Condition)
            WHERE r.param CONTAINS 'сульфат' AND r.op = '<=' AND r.value <= 300
            RETURN DISTINCT p.id AS pid, r.value AS value
            """
        ).data()
    assert rows, "expected at least one sulfate<=300 condition edge"
    assert all(r["value"] <= 300 for r in rows)
    assert "proc:reverse_osmosis" in {r["pid"] for r in rows}


# --------------------------------------------------------------- Cypher scenario 3
@requires_neo4j
def test_cypher_contradiction_and_supersedes(loaded):
    """Contradiction pair + supersedes version chain exist."""
    from app import db
    with db.driver().session() as s:
        contra = s.run(
            "MATCH (a:Assertion)-[:contradicts]-(b:Assertion) "
            "RETURN a.id AS a, b.id AS b"
        ).data()
        sup = s.run(
            "MATCH (a:Assertion)-[:supersedes]->(b:Assertion) "
            "RETURN a.id AS a, b.id AS b"
        ).data()
    assert contra
    assert any(r["a"] == "assert:catholyte_flow_v2" and
               r["b"] == "assert:catholyte_flow_v1" for r in sup)


# --------------------------------------------------------------- API tests
@pytest.fixture(scope="module")
def client(loaded):
    from app.main import app
    return TestClient(app)


@requires_neo4j
def test_api_search_golden(client):
    """Retrieval surfaces topically-relevant evidence for a lexically-strong query.

    Runs against the loaded graph. Asserts on deterministic behaviour only — the
    intent parse (rule-based) and that at least one citation is genuinely about the
    query subject (water treatment), grounded in the cited chunk text. Does NOT depend
    on a specific doc_id, nor on LLM synthesis (offline in CI / dead-key envs), so it
    stays green regardless of which corpus document is the strongest lexical match.
    """
    r = client.post("/api/search",
                    json={"query": "очистка шахтных вод сульфаты 300 мг/л"})
    assert r.status_code == 200
    data = r.json()
    # contract §4.3: intent.type + numeric_constraints (strings), not raw {numbers}
    assert data["intent"]["type"] == "lookup"
    assert "300 мг/л" in (data["intent"].get("numeric_constraints") or [])
    # retrieval must surface evidence via the lex+concept gate (embeddings not required)
    cits = data["citations"]
    assert cits, "expected citations for an in-corpus water-treatment query"
    # at least one citation is on-topic: its chunk text / title carries a water term
    water_terms = ("вод", "сульфат", "осмос", "умягч", "обессолив", "шахтн", "очист")
    evidence = " ".join(((c.get("quote") or "") + " " + (c.get("title") or ""))
                        for c in cits).lower()
    assert any(t in evidence for t in water_terms), \
        f"no water-treatment evidence in citations: {evidence[:200]!r}"
    # graph expansion produced a subgraph anchored on the retrieved docs
    assert data["subgraph"]["nodes"]


@requires_neo4j
def test_api_node(client):
    r = client.get("/api/graph/node/proc:electrowinning_ni", params={"depth": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["node"]["id"] == "proc:electrowinning_ni"
    assert len(data["neighbors"]["nodes"]) > 3


@requires_neo4j
def test_api_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["n_nodes"] >= 40


@requires_neo4j
def test_api_experts(client):
    r = client.get("/api/experts", params={"topic": "никел"})
    assert r.status_code == 200
    # contract §4.3: /api/experts returns a bare array of ExpertSummary
    names = [e["name"] for e in r.json()]
    assert any("Коржаков" in n for n in names)


@requires_neo4j
def test_api_export_roundtrip(client):
    sr = client.post("/api/search", json={"query": "электроэкстракция никеля католит"})
    sid = sr.json()["search_id"]
    er = client.post("/api/export", json={"search_id": sid, "format": "md"})
    assert er.status_code == 200
    assert er.json()["content"]
