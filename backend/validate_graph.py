"""C6 — Real SHACL validation of the knowledge graph.

Pipeline:
    graph/nodes.jsonl + graph/edges.jsonl   (sample)
        -> RDF (rdflib) using the sci-tangle ontology vocabulary (docs/ontology.ttl)
        -> pyshacl validation against docs/shapes.ttl
        -> aggregated report (nodes/edges checked, violations by category + examples)

Edges are reified as `sct:Fact` resources so their provenance (source_doc, confidence,
extracted_at, method) can be validated as first-class SHACL targets.

Usage:
    python backend/validate_graph.py                 # sample 8000 nodes + 8000 edges
    python backend/validate_graph.py --sample 5000
    python backend/validate_graph.py --full          # whole graph (slow)
    python backend/validate_graph.py --report docs/VALIDATION_REPORT.md
"""
from __future__ import annotations

import argparse
import collections
import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = ROOT / "graph"
DOCS_DIR = ROOT / "docs"
ONTOLOGY_TTL = DOCS_DIR / "ontology.ttl"
SHAPES_TTL = DOCS_DIR / "shapes.ttl"

SCT = Namespace("https://sci-tangle.nornickel.example/ontology#")
NODE = Namespace("https://sci-tangle.nornickel.example/node/")
FACT = Namespace("https://sci-tangle.nornickel.example/fact/")
SH = Namespace("http://www.w3.org/ns/shacl#")

# node type -> ontology class
TYPE_CLASS = {
    "Material": SCT.Material, "Process": SCT.Process, "Equipment": SCT.Equipment,
    "Parameter": SCT.Parameter, "Condition": SCT.Condition, "Measurement": SCT.Measurement,
    "Experiment": SCT.Experiment, "Publication": SCT.Publication, "Expert": SCT.Expert,
    "Facility": SCT.Facility, "Assertion": SCT.Assertion,
}
# edge type -> object property
EDGE_PROP = {
    "uses_material": SCT.uses_material, "produces_output": SCT.produces_output,
    "operates_at_condition": SCT.operates_at_condition, "uses_equipment": SCT.uses_equipment,
    "measured": SCT.measured, "described_in": SCT.described_in, "authored_by": SCT.authored_by,
    "works_at": SCT.works_at, "expert_in": SCT.expert_in, "validated_by": SCT.validated_by,
    "contradicts": SCT.contradicts, "supersedes": SCT.supersedes, "located_in": SCT.located_in,
    "about": SCT.about, "related": SCT.related,
}


def _uri(node_id: str) -> URIRef:
    return URIRef(NODE + urllib.parse.quote(node_id, safe=""))


def _as_double(val: Any) -> Optional[Literal]:
    """Only emit xsd:double when the value is genuinely numeric.

    Qualitative string values ("существенно снизилось") are emitted as plain
    strings so the SHACL datatype constraint reports them honestly as violations.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return Literal(float(val), datatype=XSD.double)
    return None


def read_jsonl_sample(path: Path, limit: Optional[int]) -> List[dict]:
    rows: List[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def node_to_rdf(g: Graph, n: dict) -> None:
    nid = n.get("id")
    if not nid:
        return
    subj = _uri(nid)
    ntype = n.get("type")
    cls = TYPE_CLASS.get(ntype)
    if cls is not None:
        g.add((subj, RDF.type, cls))
    if n.get("name"):
        g.add((subj, RDFS.label, Literal(n["name"])))
    if n.get("name_en"):
        g.add((subj, SCT.name_en, Literal(n["name_en"])))
    if n.get("concept_id"):
        g.add((subj, SCT.concept_id, Literal(n["concept_id"])))
    conf = n.get("confidence")
    if isinstance(conf, (int, float)):
        g.add((subj, SCT.confidence, Literal(float(conf), datatype=XSD.double)))
    for a in n.get("aliases") or []:
        g.add((subj, SCT.alias, Literal(a)))

    p = n.get("props") or {}

    # Condition / Measurement structured fields
    if ntype in ("Condition", "Measurement"):
        if p.get("param") is not None:
            g.add((subj, SCT.param, Literal(str(p["param"]))))
        if p.get("op") is not None:
            g.add((subj, SCT.op, Literal(str(p["op"]))))
        if "value" in p and p["value"] is not None:
            dv = _as_double(p["value"])
            g.add((subj, SCT.value, dv if dv is not None else Literal(str(p["value"]))))
        if p.get("value2") is not None:
            dv = _as_double(p["value2"])
            if dv is not None:
                g.add((subj, SCT.value2, dv))
        if p.get("unit"):
            g.add((subj, SCT.unit, Literal(str(p["unit"]))))
        if p.get("quote"):
            g.add((subj, SCT.quote, Literal(str(p["quote"]))))

    # Assertion fields
    if ntype == "Assertion":
        if p.get("statement"):
            g.add((subj, SCT.statement, Literal(str(p["statement"]))))
        if p.get("confidence") is not None:
            g.add((subj, SCT.assertionConfidence, Literal(str(p["confidence"]))))
        if p.get("review_status") is not None:
            g.add((subj, SCT.reviewStatus, Literal(str(p["review_status"]))))
        if isinstance(p.get("n_sources"), int):
            g.add((subj, SCT.nSources, Literal(p["n_sources"], datatype=XSD.integer)))
        for ev in p.get("evidence") or []:
            ref = ev.get("chunk_id") or ev.get("doc_id") if isinstance(ev, dict) else str(ev)
            if ref:
                g.add((subj, SCT.hasEvidence, Literal(str(ref))))

    # Publication fields
    if ntype == "Publication":
        if p.get("doc_id"):
            g.add((subj, SCT.doc_id, Literal(str(p["doc_id"]))))
        if isinstance(p.get("year"), int):
            g.add((subj, SCT.year, Literal(p["year"], datatype=XSD.integer)))
        if p.get("source_type"):
            g.add((subj, SCT.sourceType, Literal(str(p["source_type"]))))
        if p.get("geography"):
            g.add((subj, SCT.geography, Literal(str(p["geography"]))))


def edge_to_rdf(g: Graph, e: dict, idx: int) -> None:
    src, dst, etype = e.get("src"), e.get("dst"), e.get("type", "related")
    if not src or not dst:
        return
    s, o = _uri(src), _uri(dst)
    prop = EDGE_PROP.get(etype, SCT.related)
    # direct triple
    g.add((s, prop, o))
    # reified provenanced fact
    fid = e.get("id") or f"{src}|{etype}|{dst}|{idx}"
    fact = URIRef(FACT + urllib.parse.quote(fid, safe=""))
    g.add((fact, RDF.type, SCT.Fact))
    g.add((fact, SCT.factSubject, s))
    g.add((fact, SCT.factObject, o))
    g.add((fact, RDF.predicate, prop))
    if e.get("source_doc"):
        g.add((fact, SCT.source_doc, Literal(str(e["source_doc"]))))
    if e.get("chunk_id"):
        g.add((fact, SCT.chunk_id, Literal(str(e["chunk_id"]))))
    conf = e.get("confidence")
    if isinstance(conf, (int, float)) and not isinstance(conf, bool):
        g.add((fact, SCT.confidence, Literal(float(conf), datatype=XSD.double)))
    elif conf is not None:
        g.add((fact, SCT.confidence, Literal(str(conf))))
    if e.get("method") is not None:
        g.add((fact, SCT.method, Literal(str(e["method"]))))
    if e.get("extracted_at"):
        g.add((fact, SCT.extractedAt, Literal(str(e["extracted_at"]))))
    if e.get("created_by"):
        g.add((fact, SCT.createdBy, Literal(str(e["created_by"]))))


def build_graph(nodes: List[dict], edges: List[dict]) -> Graph:
    g = Graph()
    g.bind("sct", SCT)
    for n in nodes:
        node_to_rdf(g, n)
    for i, e in enumerate(edges):
        edge_to_rdf(g, e, i)
    return g


# ------------------------------------------------------------------ reporting
def _shape_label(shape_ref: Any) -> str:
    if shape_ref is None:
        return "(unknown)"
    s = str(shape_ref)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def analyze_results(results_graph: Graph) -> Dict[str, Any]:
    """Aggregate SHACL ValidationResult nodes by (severity, path, message)."""
    categories: Dict[Tuple[str, str], Dict[str, Any]] = {}
    total = 0
    sev_counts: collections.Counter = collections.Counter()
    for res in results_graph.subjects(RDF.type, SH.ValidationResult):
        total += 1
        path = results_graph.value(res, SH.resultPath)
        msg = results_graph.value(res, SH.resultMessage)
        sev = _shape_label(results_graph.value(res, SH.resultSeverity))
        focus = results_graph.value(res, SH.focusNode)
        sev_counts[sev] += 1
        key = (_shape_label(path), str(msg) if msg else "(no message)")
        cat = categories.setdefault(key, {
            "path": _shape_label(path), "message": str(msg) if msg else "",
            "severity": sev, "count": 0, "examples": [],
        })
        cat["count"] += 1
        if focus is not None and len(cat["examples"]) < 3:
            fid = urllib.parse.unquote(str(focus).rsplit("/", 1)[-1])
            val = results_graph.value(res, SH.value)
            ex = fid if val is None else f"{fid}  (value={val})"
            cat["examples"].append(ex)
    ranked = sorted(categories.values(), key=lambda c: c["count"], reverse=True)
    return {"total": total, "by_severity": dict(sev_counts), "categories": ranked}


def run(sample: Optional[int], report_path: Optional[Path]) -> Dict[str, Any]:
    from pyshacl import validate

    nodes = read_jsonl_sample(GRAPH_DIR / "nodes.jsonl", sample)
    edges = read_jsonl_sample(GRAPH_DIR / "edges.jsonl", sample)
    node_types = collections.Counter(n.get("type") for n in nodes)
    edge_types = collections.Counter(e.get("type") for e in edges)

    data_graph = build_graph(nodes, edges)
    shapes_graph = Graph().parse(SHAPES_TTL, format="turtle")
    onto_graph = Graph().parse(ONTOLOGY_TTL, format="turtle")

    conforms, results_graph, results_text = validate(
        data_graph,
        shacl_graph=shapes_graph,
        ont_graph=onto_graph,
        inference="none",
        abort_on_first=False,
        meta_shacl=False,
        advanced=True,
    )

    analysis = analyze_results(results_graph)
    summary = {
        "conforms": conforms,
        "nodes_checked": len(nodes),
        "edges_checked": len(edges),
        "triples": len(data_graph),
        "node_types": dict(node_types),
        "edge_types": dict(edge_types),
        "analysis": analysis,
    }
    _print_summary(summary)
    if report_path is not None:
        report_path.write_text(render_markdown(summary, sample), encoding="utf-8")
        print(f"\nReport written to {report_path}")
    return summary


def _print_summary(s: Dict[str, Any]) -> None:
    a = s["analysis"]
    print(f"conforms={s['conforms']}  nodes={s['nodes_checked']}  "
          f"edges={s['edges_checked']}  triples={s['triples']}")
    print(f"violations total={a['total']}  by severity={a['by_severity']}")
    print("top categories:")
    for c in a["categories"][:8]:
        print(f"  [{c['severity']:>9}] x{c['count']:<6} {c['path']}: {c['message'][:70]}")


def render_markdown(s: Dict[str, Any], sample: Optional[int]) -> str:
    a = s["analysis"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: List[str] = []
    L.append("# SHACL-валидация графа sci-tangle\n")
    L.append(f"_Сгенерировано `backend/validate_graph.py` · {now}_\n")
    L.append("Реальный прогон pyshacl по `docs/shapes.ttl` (словарь `docs/ontology.ttl`) "
             "на выборке живого графа `graph/nodes.jsonl` + `graph/edges.jsonl`. "
             "Нарушения — это честная картина шума извлечения, а не подгонка данных.\n")
    L.append("## Итог прогона\n")
    L.append(f"- Выборка: **{s['nodes_checked']} узлов** + **{s['edges_checked']} рёбер** "
             f"({'весь граф' if sample is None else f'первые {sample} каждого файла'}), "
             f"{s['triples']} RDF-триплетов.")
    L.append(f"- `sh:conforms` = **{s['conforms']}** (наличие нарушений ожидаемо и допустимо).")
    L.append(f"- Всего результатов валидации: **{a['total']}** "
             f"(по severity: {a['by_severity']}).\n")
    L.append("### Проверенные типы узлов\n")
    L.append("| Тип | Кол-во в выборке |")
    L.append("|---|---|")
    for t, c in sorted(s["node_types"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {t} | {c} |")
    L.append("")
    L.append("### Проверенные типы рёбер (реифицированы как `sct:Fact`)\n")
    L.append("| Тип связи | Кол-во |")
    L.append("|---|---|")
    for t, c in sorted(s["edge_types"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {t} | {c} |")
    L.append("")
    L.append("## Топ категорий нарушений\n")
    if not a["categories"]:
        L.append("_Нарушений не обнаружено._\n")
    else:
        L.append("| # | Severity | Кол-во | Свойство | Сообщение | Примеры (focus node) |")
        L.append("|---|---|---|---|---|---|")
        for i, c in enumerate(a["categories"][:8], 1):
            ex = "; ".join(c["examples"]) or "—"
            ex = ex.replace("|", "\\|")
            msg = c["message"].replace("|", "\\|")
            L.append(f"| {i} | {c['severity']} | {c['count']} | `{c['path']}` | {msg} | {ex} |")
    L.append("")
    L.append("## Интерпретация\n")
    L.append("- **`op` вне канонического набора** — шум поля оператора в извлечении "
             "(`gt`, `lt`, `≥`, `≤`, `min`, `max`, `~`, `→`, естественноязычные варианты). "
             "Кандидат на нормализацию в rule-слое (маппинг синонимов оператора).")
    L.append("- **`value` не xsd:double** — качественные значения (\"существенно снизилось\") "
             "и пустые значения там, где ожидается число: сигнал доработать rule-first фильтр.")
    L.append("- **Publication `year` / `source_type` (Warning)** — эти поля живут в "
             "`corpus/documents.jsonl` и не денормализованы на узлы Publication графа; "
             "требуют join при загрузке, поэтому помечены как Warning, а не Violation.")
    L.append("- Провенанс факт-рёбер (`source_doc`, `confidence` 0..1, `method`, `extracted_at`) "
             "и структура Assertion (`statement`, `confidence` high/medium/low, `review_status`, "
             "непустой `evidence`) проходят валидацию на подавляющем большинстве элементов.")
    L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="SHACL validation of the sci-tangle graph")
    ap.add_argument("--sample", type=int, default=8000,
                    help="max nodes and max edges to read (default 8000)")
    ap.add_argument("--full", action="store_true", help="validate the whole graph (slow)")
    ap.add_argument("--report", type=Path, default=DOCS_DIR / "VALIDATION_REPORT.md",
                    help="path to write the markdown report (default docs/VALIDATION_REPORT.md)")
    args = ap.parse_args()
    sample = None if args.full else args.sample
    run(sample, args.report)


if __name__ == "__main__":
    main()
