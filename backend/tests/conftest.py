"""Test config: skip integration tests if Neo4j/ES are not reachable.

Assumes fixtures are already loaded (see backend/README.md). The `loaded` fixture
loads them once per session so tests are self-contained when containers are up.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def _neo4j_up() -> bool:
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        d.verify_connectivity()
        d.close()
        return True
    except Exception:
        return False


NEO4J_AVAILABLE = _neo4j_up()

requires_neo4j = pytest.mark.skipif(
    not NEO4J_AVAILABLE, reason="Neo4j not reachable (start docker compose)")


@pytest.fixture(scope="session")
def loaded():
    """Ensure the fixture graph is present in Neo4j (additive MERGE) for the graph/Cypher
    scenarios, WITHOUT touching Elasticsearch.

    Historically this also recreated the ES index from fixtures. That is deliberately no
    longer done: the retrieval/RBAC/subscription integration tests now run against the
    REAL corpus (the deployed ES index), which — unlike the fixture stub — carries the
    per-space chunk vectors, the concepts registry, and the document metadata (section,
    sensitivity, ingested_at) those tests need. Wiping ES to fixtures would both destroy
    the live corpus and, with the query-embedding offline, gate every fixture query to an
    empty answer. The fixture NODES are still MERGE-loaded into Neo4j (harmless to the
    real graph; retrieval filters the d0009xx namespace out of citations by design).
    """
    if not NEO4J_AVAILABLE:
        pytest.skip("Neo4j not reachable")
    import subprocess
    subprocess.run([sys.executable, "fixtures/build_fixtures.py"], cwd=BACKEND, check=True)
    import loader
    loader.load(BACKEND / "fixtures" / "nodes.jsonl", BACKEND / "fixtures" / "edges.jsonl")
    return True
