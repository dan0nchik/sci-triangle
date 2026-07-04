"""Neo4j loader for the knowledge graph (contract PLAN.md §4.2).

Loads graph/nodes.jsonl + graph/edges.jsonl (or any pair of files) into Neo4j
in idempotent MERGE batches, and creates the required indexes:

  * uniqueness constraint on :Entity(id)
  * btree indexes on type, year, geography, domain
  * vector indexes (256-dim, cosine) for chunk & entity embeddings

Every node is stored with a generic :Entity label plus a second label equal to
its `type` (Material, Process, Assertion, ...). Edge type becomes the Cypher
relationship type. Node `props` and edge `props` are flattened onto the element.

Usage:
    python loader.py --nodes graph/nodes.jsonl --edges graph/edges.jsonl
    python loader.py --fixtures        # loads backend/fixtures/{nodes,edges}.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List

from neo4j import GraphDatabase

from config import (
    FIXTURES_DIR,
    GRAPH_DIR,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)

BATCH = 500

# Relationship types are injected into Cypher, so restrict to a known safe set.
ALLOWED_REL_TYPES = {
    "uses_material", "produces_output", "operates_at_condition", "uses_equipment",
    "measured", "described_in", "authored_by", "works_at", "expert_in",
    "validated_by", "contradicts", "supersedes", "located_in", "about", "related",
}


def _driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _safe_label(t: str) -> str:
    """Sanitize a node type into a valid Cypher label."""
    return "".join(ch for ch in (t or "Entity") if ch.isalnum() or ch == "_") or "Entity"


def create_schema(session) -> None:
    stmts = [
        "CREATE CONSTRAINT entity_id IF NOT EXISTS "
        "FOR (n:Entity) REQUIRE n.id IS UNIQUE",
        "CREATE INDEX entity_type IF NOT EXISTS FOR (n:Entity) ON (n.type)",
        "CREATE INDEX entity_year IF NOT EXISTS FOR (n:Entity) ON (n.year)",
        "CREATE INDEX entity_geo IF NOT EXISTS FOR (n:Entity) ON (n.geography)",
        "CREATE INDEX entity_domain IF NOT EXISTS FOR (n:Entity) ON (n.domain)",
        # Full-text over names/aliases/statement for lexical fallback search.
        "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS "
        "FOR (n:Entity) ON EACH [n.name, n.name_en, n.aliases_text, n.statement]",
    ]
    for s in stmts:
        session.run(s)

    # Vector indexes (Neo4j 5 syntax). 256-dim cosine.
    for name, label in (("chunk_embeddings", "Chunk"), ("entity_embeddings", "Entity")):
        session.run(
            f"CREATE VECTOR INDEX {name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: 256, "
            "`vector.similarity_function`: 'cosine'}}"
        )


def _prepare_node(n: dict) -> dict:
    props = dict(n.get("props") or {})
    aliases = n.get("aliases") or []
    row = {
        "id": n["id"],
        "type": n.get("type", "Entity"),
        "label": _safe_label(n.get("type")),
        "name": n.get("name"),
        "name_en": n.get("name_en"),
        "aliases": aliases,
        "aliases_text": " ".join(aliases),
        "concept_id": n.get("concept_id"),
        "confidence": n.get("confidence"),
        "source_docs": n.get("source_docs") or [],
        "embedding": n.get("embedding"),
        # promoted well-known facets for indexing/filtering
        "year": props.get("year"),
        "geography": props.get("geography"),
        "domain": props.get("domain"),
        "props": json.dumps(props, ensure_ascii=False),
        # keep a few frequently-read scalar props at top level for convenience
        "statement": props.get("statement"),
        "review_status": props.get("review_status"),
    }
    return row


def load_nodes(session, nodes: Iterable[dict]) -> int:
    rows = [_prepare_node(n) for n in nodes]
    # Group by label because label cannot be parameterized.
    by_label: Dict[str, List[dict]] = {}
    for r in rows:
        by_label.setdefault(r["label"], []).append(r)
    total = 0
    for label, group in by_label.items():
        for i in range(0, len(group), BATCH):
            batch = group[i : i + BATCH]
            session.run(
                f"""
                UNWIND $rows AS row
                MERGE (n:Entity {{id: row.id}})
                SET n += {{
                    type: row.type, name: row.name, name_en: row.name_en,
                    aliases: row.aliases, aliases_text: row.aliases_text,
                    concept_id: row.concept_id, confidence: row.confidence,
                    source_docs: row.source_docs, props_json: row.props,
                    year: row.year, geography: row.geography, domain: row.domain,
                    statement: row.statement, review_status: row.review_status
                }}
                SET n:{label}
                WITH n, row
                FOREACH (_ IN CASE WHEN row.embedding IS NULL THEN [] ELSE [1] END |
                    SET n.embedding = row.embedding)
                """,
                rows=batch,
            )
            total += len(batch)
    return total


def load_edges(session, edges: Iterable[dict]) -> int:
    by_type: Dict[str, List[dict]] = {}
    skipped = 0
    for e in edges:
        etype = e.get("type", "related")
        if etype not in ALLOWED_REL_TYPES:
            etype = "related"
        row = {
            "src": e["src"],
            "dst": e["dst"],
            "props": json.dumps(e.get("props") or {}, ensure_ascii=False),
            "source_doc": e.get("source_doc"),
            "chunk_id": e.get("chunk_id"),
            "confidence": e.get("confidence"),
            "method": e.get("method"),
            "extracted_at": e.get("extracted_at"),
            "created_by": e.get("created_by"),
            # promote numeric-condition props for convenient reads
            "param": (e.get("props") or {}).get("param"),
            "op": (e.get("props") or {}).get("op"),
            "value": (e.get("props") or {}).get("value"),
            "value2": (e.get("props") or {}).get("value2"),
            "unit": (e.get("props") or {}).get("unit"),
            "edge_id": e.get("id") or f"{e['src']}|{etype}|{e['dst']}",
        }
        by_type.setdefault(etype, []).append(row)

    total = 0
    for etype, group in by_type.items():
        for i in range(0, len(group), BATCH):
            batch = group[i : i + BATCH]
            session.run(
                f"""
                UNWIND $rows AS row
                MATCH (a:Entity {{id: row.src}})
                MATCH (b:Entity {{id: row.dst}})
                MERGE (a)-[r:{etype} {{edge_id: row.edge_id}}]->(b)
                SET r += {{
                    props_json: row.props, source_doc: row.source_doc,
                    chunk_id: row.chunk_id, confidence: row.confidence,
                    method: row.method, extracted_at: row.extracted_at,
                    created_by: row.created_by, param: row.param, op: row.op,
                    value: row.value, value2: row.value2, unit: row.unit, type: '{etype}'
                }}
                """,
                rows=batch,
            )
            total += len(batch)
    return total, skipped


def load(nodes_path: Path, edges_path: Path) -> dict:
    nodes = read_jsonl(nodes_path)
    edges = read_jsonl(edges_path)
    with _driver() as driver:
        with driver.session() as session:
            create_schema(session)
            n = load_nodes(session, nodes)
            e, skipped = load_edges(session, edges)
    return {"nodes": n, "edges": e, "skipped": skipped}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=Path)
    ap.add_argument("--edges", type=Path)
    ap.add_argument("--fixtures", action="store_true",
                    help="load backend/fixtures/{nodes,edges}.jsonl")
    args = ap.parse_args()

    if args.fixtures:
        nodes_path = FIXTURES_DIR / "nodes.jsonl"
        edges_path = FIXTURES_DIR / "edges.jsonl"
    else:
        nodes_path = args.nodes or (GRAPH_DIR / "nodes.jsonl")
        edges_path = args.edges or (GRAPH_DIR / "edges.jsonl")

    print(f"Loading nodes={nodes_path} edges={edges_path}")
    result = load(nodes_path, edges_path)
    print(f"Loaded: {result}")


if __name__ == "__main__":
    main()
