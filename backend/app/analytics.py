"""C17 — Analytics for /api/stats, gaps, contradictions, expert map.

Coverage is drawn from BOTH corpus/documents.jsonl (full corpus facets) and the
Neo4j graph (node/edge counts). Gaps and contradictions are Cypher over the graph.
Degrades gracefully: any unavailable source contributes an empty slice.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from app import db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_DOCS = REPO_ROOT / "corpus" / "documents.jsonl"


# ------------------------------------------------------- corpus coverage
def corpus_coverage() -> Dict[str, Any]:
    """Section / domain-ish (source_type) / year coverage from the full corpus manifest."""
    by_section: Counter = Counter()
    by_source_type: Counter = Counter()
    by_year: Counter = Counter()
    by_geography: Counter = Counter()
    n = 0
    if CORPUS_DOCS.exists():
        for line in CORPUS_DOCS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            if d.get("section"):
                by_section[d["section"]] += 1
            if d.get("source_type"):
                by_source_type[d["source_type"]] += 1
            if d.get("year"):
                by_year[str(d["year"])] += 1
            geo = d.get("geography_hint") or d.get("geography")
            if geo:
                by_geography[geo] += 1
    return {
        "n_corpus_documents": n,
        "corpus_by_section": dict(by_section.most_common()),
        "corpus_by_source_type": dict(by_source_type.most_common()),
        "corpus_by_year": dict(sorted(by_year.items())),
        "corpus_by_geography": dict(by_geography.most_common()),
    }


# ------------------------------------------------------- gaps (Material×Process)
def material_process_gaps(limit: int = 30) -> List[Dict[str, Any]]:
    """Material×Process combinations that have NO linked Publication and NO Experiment
    within 2 hops — i.e. structurally under-evidenced (C17 gap analysis)."""
    q = """
    MATCH (p:Process)-[:uses_material|produces_output]-(m:Material)
    WITH DISTINCT p, m
    WHERE NOT (p)-[*1..2]-(:Publication)
      AND NOT (p)-[*1..2]-(:Experiment)
    RETURN p.name AS process, p.id AS process_id,
           m.name AS material, m.id AS material_id
    LIMIT $lim
    """
    out: List[Dict[str, Any]] = []
    try:
        with db.driver().session() as s:
            for r in s.run(q, lim=limit):
                out.append({"process": r["process"], "process_id": r["process_id"],
                            "material": r["material"], "material_id": r["material_id"]})
    except Exception:
        pass
    return out


# ------------------------------------------------------- top contradictions
def top_contradictions(limit: int = 10) -> List[Dict[str, Any]]:
    q = """
    MATCH (a:Assertion)-[:contradicts]-(b:Assertion)
    RETURN a, b LIMIT $lim
    """
    seen = set()
    out: List[Dict[str, Any]] = []
    try:
        with db.driver().session() as s:
            for rec in s.run(q, lim=limit * 2):
                a = db._node_dict(dict(rec["a"]))
                b = db._node_dict(dict(rec["b"]))
                key = tuple(sorted([a["id"], b["id"]]))
                if key in seen:
                    continue
                seen.add(key)
                pa, pb = a["props"] or {}, b["props"] or {}
                out.append({
                    "a": a["id"], "b": b["id"],
                    "a_statement": pa.get("statement") or a["name"],
                    "b_statement": pb.get("statement") or b["name"],
                    "a_evidence": pa.get("evidence") or [],
                    "b_evidence": pb.get("evidence") or [],
                    "a_confidence": pa.get("confidence"),
                    "b_confidence": pb.get("confidence"),
                })
                if len(out) >= limit:
                    break
    except Exception:
        pass
    return out


# ------------------------------------------------------- expert map
def expert_map(topic: str = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Experts for a topic, ranked by number of works (expert_in / authored_by walk)."""
    experts = db.find_experts(topic=topic, limit=limit * 2)
    experts.sort(key=lambda e: e.get("n_works", 0), reverse=True)
    return experts[:limit]
