"""Search orchestration (C-query): planner -> retrieval+gating -> graph expansion
-> LLM evidence-packet synthesis.

Pipeline:
  1. C7  planner.plan(query)          -> structured intent (cached, LLM + fallback)
  2. C8  retrieval.retrieve(...)      -> filter-first + RRF + score-gating
  3. C9  graph expansion              -> assertions/measurements/conditions/experts
  4. C10 synthesis.synthesize(...)    -> YandexGPT Pro evidence packet (grounded)

`search()` and `parse_intent()` keep their day-1 signatures for API/test compat;
`intent["numbers"]` stays deterministic (regex) as the integration tests rely on it.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import answer_cache, auth, db, planner, retrieval, synthesis  # noqa: E402


def parse_intent(query: str) -> Dict[str, Any]:
    """Back-compat shim: structured intent via the planner (regex numbers preserved)."""
    return planner.plan(query)


def _dedupe_by_id(items: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for it in items:
        i = it.get("id")
        if i and i not in seen:
            seen.add(i)
            out.append(it)
    return out


def search(query: str, filters: Optional[Dict] = None,
           role_ctx: str = "researcher", skip_cache: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    filters = filters or {}

    # 0) answer-cache lookup (Answer-Cache agent). A repeated identical question is
    # served straight from sqlite — no LLM, no retrieval. `data_version` folded into the
    # key means a grown corpus/graph/embedding matrix self-invalidates the entry.
    # skip_cache=true (demo "live" mode / QA harness) bypasses both read and write.
    dv = None
    if not skip_cache:
        dv = answer_cache.data_version()
        hit = answer_cache.lookup(query, filters, role_ctx, dv=dv)
        if hit is not None:
            hit["took_ms"] = int((time.time() - t0) * 1000)  # real lookup latency
            return hit

    # 1) plan
    intent = planner.plan(query)

    # 2) retrieval + score-gating
    ret = retrieval.retrieve(query, intent, filters=filters, role_ctx=role_ctx)
    citations = ret["citations"]

    # 2b) honesty backstop for out-of-domain queries whose incidental corpus overlap
    # (aluminium-energy tables, Czochralski method, ...) passes lexical+semantic retrieval
    # (neither BM25 nor doc-doc cosine nor the graph separates it — see backend/README).
    # Deterministic foreign-material rejection (in retrieve) already handles aluminium;
    # this catches material-less foreign topics (cattle/wine/LLM). Skipped for in-domain
    # queries so the flaky LLM judge never falsely rejects обессоливание/шахтные воды.
    # (a strong filename match — gate.namedoc — proves the corpus HAS a document about
    # the query's subject, so the judge is skipped there too: f15 НДТ class)
    if (citations and not (ret.get("gate") or {}).get("namedoc")
            and not retrieval.query_in_domain(query, intent)):
        if not synthesis.judge_relevance(query, citations):
            ret = retrieval._empty_result(ret.get("concept_entities"), None, gated=True)
            citations = ret["citations"]

    # 3) graph expansion around surviving anchors (depth 1; capped for answer packet)
    anchors = ret["anchor_ids"]
    sub = db.subgraph_for(anchors, depth=1) if anchors else {"nodes": [], "edges": []}
    if role_ctx == "external_partner":
        sub = _rbac_filter_subgraph(sub)
    sub = _cap_subgraph(sub, anchors, max_nodes=60)
    sub_ids = [n["id"] for n in sub["nodes"]]

    experts = db.experts_for_nodes(sub_ids) if sub_ids else []
    contradictions = db.contradictions_for_nodes(sub_ids) if sub_ids else []

    sub_assertions = [n for n in sub["nodes"] if n.get("type") == "Assertion"]
    assertions = _dedupe_by_id((ret.get("assertions") or []) + sub_assertions)
    measurements = [n for n in sub["nodes"] if n.get("type") == "Measurement"]
    conditions = [n for n in sub["nodes"] if n.get("type") == "Condition"]

    # only keep assertions/conditions actually grounded in surviving evidence docs
    if citations:
        kept_docs = set(ret["kept_docs"])
        assertions = [a for a in assertions
                      if _touches_docs(a, kept_docs) or not _has_evidence(a)] or assertions

    # 4) synthesis (evidence packet); review queries get the domain summary as context
    domain_summary = None
    if intent.get("query_type") == "review":
        domain_summary = _dominant_domain_summary(sub["nodes"])
    syn = synthesis.synthesize(
        query, intent, citations, assertions, measurements, conditions,
        contradictions, experts, adjacent=ret.get("adjacent"),
        domain_summary=domain_summary,
    )

    gaps = list(syn.get("gaps") or [])
    gaps += detect_gaps(intent, assertions, citations)

    result = {
        "answer_md": syn["answer_md"],
        "intent": _contract_intent(intent),
        "citations": citations,
        "subgraph": sub,
        "experts": experts,
        "contradictions": contradictions,
        "gaps": _contract_gaps(gaps),
        "confidence_summary": _contract_confidence(syn["confidence_summary"], assertions),
        "retrieval_trace": _build_retrieval_trace(intent, ret, citations),
        "took_ms": int((time.time() - t0) * 1000),
        "search_id": "s_" + uuid.uuid4().hex[:12],
        "cached": False,
    }

    # store into the answer-cache (skips fallback-template answers; short TTL for
    # honest "not found"). `dv` reused from the lookup so read/write share a version.
    if not skip_cache:
        answer_cache.store(query, filters, role_ctx, result,
                           synth=syn.get("synth"), dv=dv)

    return result


# --------------------------------------------------------------------- retrieval trace
# Explainability panel data (UX-Explainability agent, docs/CONTRACT_TRACE.md). Built here
# from what retrieval.retrieve() already returns — retrieval.py (embedding-agent-owned) is
# NOT modified. The core exposes per-citation signals (lex/sem/concept) + aggregate gate
# counts, so per-branch stats are computed over the SURVIVING (post-gate) citations; the
# pre-gate candidate pool is reported only as the aggregate `docs_considered`.
def _build_retrieval_trace(intent: Dict[str, Any], ret: Dict[str, Any],
                           citations: List[Dict]) -> Dict[str, Any]:
    gate = ret.get("gate") or {}
    n_candidates = int(gate.get("n_candidates") or 0)
    n_kept = int(gate.get("n_kept") or 0)
    namedoc = bool(gate.get("namedoc"))
    gated = bool(gate.get("gated"))

    # per-branch survivors, derived from each citation's live signals
    branch_defs = [
        ("lexical", "lex", "BM25 (Elasticsearch)"),
        ("semantic", "sem", "cosine query↔chunk (precompute)"),
        ("graph", "concept", "концепт-якорь графа / термин в тексте"),
        ("doc-name", "namedoc", "совпадение имени/заголовка документа"),
    ]
    branches: List[Dict[str, Any]] = []
    for name, sig, desc in branch_defs:
        if sig == "namedoc":
            # only a GLOBAL flag is exposed (which docs matched by name is not per-citation),
            # so report activation, not a per-citation survivor count.
            branches.append({
                "name": name, "method": desc, "n_candidates": None,
                "active": namedoc,
                # per-citation attribution isn't exposed; `active` says the branch fired.
                "n_passed_gate": None if namedoc else 0,
                "top_signals": [],
            })
            continue
        hits = []
        for c in citations:
            s = c.get("_signals") or {}
            if s.get(sig):
                title = c.get("title") or c.get("doc_id")
                metric = (f"cos={c.get('_cosine')}" if sig == "sem"
                          else f"rrf={c.get('_score')}" if sig == "lex"
                          else c.get("doc_id"))
                hits.append({"doc_id": c.get("doc_id"), "title": title, "signal": metric})
        branches.append({
            "name": name,
            "method": desc,
            # pre-gate per-branch candidate counts are not exposed by the retrieval core
            # (owned by the embedding agent); null = unknown, not zero.
            "n_candidates": None,
            "n_passed_gate": len(hits),
            "top_signals": hits[:3],
        })

    concepts_matched: List[Dict[str, Any]] = []
    seen_c: set = set()
    for e in (ret.get("concept_entities") or []):
        cid = e.get("id")
        nm = e.get("name")
        if nm and cid not in seen_c:
            seen_c.add(cid)
            concepts_matched.append({"concept_id": cid, "name": nm,
                                     "matched_from": "запрос"})
    if not concepts_matched:
        for c in (intent.get("concepts") or []):
            nm = c.get("name") if isinstance(c, dict) else c
            if nm and nm not in seen_c:
                seen_c.add(nm)
                concepts_matched.append({"concept_id": None, "name": str(nm),
                                         "matched_from": "запрос"})

    passed = bool(citations)
    if passed:
        reason = (f"{n_kept} чанков прошли скор-гейт (≥2 сигналов или сильный семантический)"
                  + (" ; сильное совпадение имени документа" if namedoc else ""))
    elif gated:
        reason = ("скор-гейт: доказательств недостаточно "
                  "(<2 сигналов и нет сильного семантического совпадения)")
    else:
        reason = "кандидатов не найдено"

    return {
        "branches": branches,
        "concepts_matched": concepts_matched,
        "gate": {"passed": passed, "reason": reason,
                 "n_candidates": n_candidates, "n_kept": n_kept, "namedoc": namedoc},
        "docs_considered": n_candidates,
    }


# --------------------------------------------------------------------- contract shaping
# The internal planner/synthesis use richer/looser shapes; the REST contract (§4.3,
# frontend types.ts) expects: intent.type + string concepts, confidence_summary as an
# object, gaps as objects. We normalize here so the frontend adapters become no-ops.
def _contract_intent(intent: Dict[str, Any]) -> Dict[str, Any]:
    concepts = []
    for c in intent.get("concepts") or []:
        name = c.get("name") if isinstance(c, dict) else c
        if name:
            concepts.append(str(name))
    # numeric constraints as human-readable strings
    numeric: List[str] = []
    for n in intent.get("numbers") or []:
        if not isinstance(n, dict):
            continue
        val, unit = n.get("value"), n.get("unit") or ""
        if val is not None:
            v = int(val) if float(val).is_integer() else val
            numeric.append(f"{v} {unit}".strip())
    for cond in intent.get("conditions") or []:
        if isinstance(cond, dict):
            parts = [cond.get("param"), cond.get("op"), cond.get("value"), cond.get("unit")]
            s = " ".join(str(p) for p in parts if p not in (None, ""))
        else:
            s = str(cond).strip()
        if s:
            numeric.append(s)
    out: Dict[str, Any] = {
        "type": intent.get("query_type") or "lookup",
        "concepts": concepts,
        "geography": _norm_geography(intent.get("geography")),
    }
    if numeric:
        out["numeric_constraints"] = numeric
    yf, yt = intent.get("year_from"), intent.get("year_to")
    if yf is not None or yt is not None:
        out["years"] = [yf if yf is not None else yt, yt if yt is not None else yf]
    return out


def _norm_geography(g: Any) -> str:
    """Coerce planner geography (may be a list or free-form string) to the contract
    enum expected by the frontend: RU | foreign | global | all."""
    if isinstance(g, (list, tuple)):
        # e.g. ['Россия', 'зарубежье'] -> both present -> global
        return "global" if g else "all"
    if not g:
        return "all"
    s = str(g).strip().lower()
    if s in {"ru", "foreign", "global", "all"}:
        return s
    if any(w in s for w in ("росс", "рф", "отечеств")):
        return "RU"
    if any(w in s for w in ("зарубеж", "миров", "world", "global", "foreign")):
        return "foreign"
    return "all"


def _contract_confidence(overall: Any, assertions: List[Dict]) -> Dict[str, Any]:
    if isinstance(overall, dict):
        return overall
    n_high = n_medium = n_low = 0
    for a in assertions:
        lvl = (a.get("props") or {}).get("confidence")
        if lvl == "high":
            n_high += 1
        elif lvl == "medium":
            n_medium += 1
        elif lvl == "low":
            n_low += 1
    return {"overall": overall or "medium",
            "n_high": n_high, "n_medium": n_medium, "n_low": n_low}


def _contract_gaps(gaps: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for i, g in enumerate(gaps):
        if isinstance(g, dict):
            out.append(g)
            continue
        text = str(g)
        title = text if len(text) <= 60 else text[:57] + "…"
        out.append({"id": f"gap_{i}", "title": title, "description": text,
                    "severity": "medium"})
    return out


def _cap_subgraph(sub: Dict[str, Any], anchors: List[str],
                  max_nodes: int = 60) -> Dict[str, Any]:
    """Bound the answer-packet subgraph (prior incident: 2036 nodes). Keep anchor
    nodes first, then fill by connectivity (edge degree), then prune dangling edges."""
    nodes = sub.get("nodes", [])
    if len(nodes) <= max_nodes:
        return sub
    anchor_set = set(anchors or [])
    edges = sub.get("edges", [])
    deg: Dict[str, int] = {}
    for e in edges:
        deg[e.get("src")] = deg.get(e.get("src"), 0) + 1
        deg[e.get("dst")] = deg.get(e.get("dst"), 0) + 1
    ranked = sorted(nodes, key=lambda n: (n.get("id") not in anchor_set,
                                          -deg.get(n.get("id"), 0)))
    keep = ranked[:max_nodes]
    keep_ids = {n.get("id") for n in keep}
    kept_edges = [e for e in edges
                  if e.get("src") in keep_ids and e.get("dst") in keep_ids]
    return {"nodes": keep, "edges": kept_edges}


def _rbac_filter_subgraph(sub: Dict[str, Any]) -> Dict[str, Any]:
    """Drop Publication nodes (and their edges) not visible to external_partner."""
    blocked = set()
    kept_nodes = []
    for n in sub.get("nodes", []):
        if n.get("type") == "Publication":
            p = n.get("props") or {}
            if not auth.doc_visible("external_partner", p.get("section"),
                                    p.get("sensitivity")):
                blocked.add(n["id"])
                continue
        kept_nodes.append(n)
    if not blocked:
        return sub
    kept_edges = [e for e in sub.get("edges", [])
                  if e.get("src") not in blocked and e.get("dst") not in blocked]
    return {"nodes": kept_nodes, "edges": kept_edges}


def _dominant_domain_summary(nodes: List[Dict]) -> Optional[str]:
    """Pick the most frequent process domain among expansion nodes; return its summary."""
    try:
        import summaries
    except Exception:
        return None
    counts: Dict[str, int] = {}
    for n in nodes:
        if n.get("type") == "Process":
            d = (n.get("props") or {}).get("domain")
            if d:
                counts[d] = counts.get(d, 0) + 1
    if not counts:
        return None
    top = max(counts, key=counts.get)
    return summaries.summary_for_domain(top)


def _has_evidence(a: Dict) -> bool:
    return bool((a.get("props") or {}).get("evidence"))


def _touches_docs(a: Dict, docs: set) -> bool:
    for ev in (a.get("props") or {}).get("evidence", []) or []:
        if ev.get("doc_id") in docs:
            return True
    return False


def detect_gaps(intent: Dict, assertions: List[Dict], citations: List[Dict]) -> List[str]:
    gaps: List[str] = []
    if not citations:
        return gaps  # empty case already handled by synthesis
    if intent.get("numbers") and not any(
        (a.get("props") or {}).get("evidence") for a in assertions
    ):
        gaps.append("Числовые ограничения указаны, но структурированных утверждений "
                    "с этими значениями не найдено.")
    return gaps


# kept for backwards compatibility (older imports)
def synthesize_answer(query, intent, assertions, measurements, conditions,
                      citations, contradictions) -> str:
    return synthesis._template(query, intent.get("query_type", "lookup"), citations,
                               assertions, measurements, conditions, contradictions)
