"""FastAPI application exposing the full C→D REST contract (PLAN.md §4.3).

C-store + C-query provide search / graph / documents / experts / stats.
C-platform (C13–C18) adds on top, without touching the retrieval core beyond an
RBAC filter hook:
  * C13 RBAC/ABAC  — JWT roles, ABAC document filtering at retrieval level
  * C14 Audit      — sqlite audit log of searches / views / exports / edits
  * C15 Subscriptions — saved queries + incremental "what's new" feed
  * C16 Export     — md / jsonld (schema.org+PROV-O) / pdf / xlsx
  * C17 Analytics  — coverage, Material×Process gaps, contradictions, expert map
  * C18 Observability — structlog JSON logs, request-id + timing, extended health
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
REPO_ROOT = BACKEND.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import (analytics, answer_cache, auth, db, exporters, observability,
                 search as search_mod, store, upload as upload_mod)
from app.models import (
    AuditLogResponse, CompareResponse, CompareRow, DocumentResponse,
    EdgePatch, EdgePatchResponse, ExpertRef, ExportRequest, ExportResponse,
    NodeNeighborsResponse, ReviewRequest, ReviewResponse, SearchRequest,
    SearchResponse, StatsResponse, SubscriptionListResponse, SubscriptionRequest,
    SubscriptionResponse, SubscriptionUpdates, TokenRequest, TokenResponse,
)

observability.configure_logging()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    store.init()
    upload_mod.init()
    yield


app = FastAPI(title="sci-tangle C-store API", version="0.2.0",
              lifespan=_lifespan,
              description="Knowledge graph + search API for R&D mining/metallurgy corpus")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    expose_headers=["x-request-id", "x-took-ms"],
)
app.add_middleware(observability.RequestContextMiddleware)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_search_role(authorization: Optional[str], body_role: Optional[str]) -> str:
    """JWT role wins; otherwise the demo body `role_ctx`; otherwise researcher."""
    if authorization and authorization.lower().startswith("bearer "):
        return auth.decode_role(authorization)
    return body_role or auth.DEFAULT_ROLE


# ------------------------------------------------------------------ health (C18)
@app.get("/api/health")
def health():
    h = observability.health()
    h["time"] = _now()
    return h


# ------------------------------------------------------------------ auth (C13)
@app.post("/api/auth/token", response_model=TokenResponse)
def api_token(req: TokenRequest):
    token = auth.issue_token(req.role)
    store.audit_log(req.role, "/api/auth/token", "auth_token", {"role": req.role})
    return {"access_token": token, "token_type": "bearer", "role": req.role}


@app.get("/api/auth/me")
def api_me(role: str = Depends(auth.current_role)):
    return {"role": role,
            "capabilities": sorted(c for c in auth.CAPABILITIES if auth.can(role, c))}


# ------------------------------------------------------------------ search
@app.post("/api/search", response_model=SearchResponse)
def api_search(req: SearchRequest, authorization: Optional[str] = Header(None),
               skip_cache: bool = Query(False)):
    role = _resolve_search_role(authorization, req.role_ctx)
    filters = req.filters.model_dump(exclude_none=True) if req.filters else {}
    # UI sends geography='all' / empty strings meaning «без фильтра» — drop them,
    # otherwise ES would filter on the literal term and return nothing.
    filters = {k: v for k, v in filters.items() if v not in ("", "all")}
    result = search_mod.search(req.query, filters=filters, role_ctx=role,
                               skip_cache=skip_cache)
    store.cache_search(result["search_id"], req.query, role, result)
    store.audit_log(role, "/api/search", "search",
                    params={"query": req.query, "filters": filters},
                    took_ms=result.get("took_ms"),
                    result_counts={
                        "citations": len(result.get("citations") or []),
                        "experts": len(result.get("experts") or []),
                        "contradictions": len(result.get("contradictions") or []),
                        "gaps": len(result.get("gaps") or []),
                    })
    return result


# ------------------------------------------------------------------ upload (ingest pipeline)
@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...),
                     role: str = Depends(auth.current_role)):
    """Загрузка одного документа (pdf/docx/pptx/xlsx/…). Возвращает job_id;
    прогресс стадий — GET /api/upload/{job_id}. Дедуп по sha256."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        res = upload_mod.submit(data, file.filename or "upload.bin")
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))
    store.audit_log(role, "/api/upload", "upload",
                    params={"filename": file.filename, "doc_id": res["doc_id"],
                            "cached": res["cached"]})
    return res


@app.get("/api/upload/{job_id}")
def api_upload_status(job_id: str):
    job = upload_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


# ------------------------------------------------------------------ graph
@app.get("/api/graph/node/{node_id:path}", response_model=NodeNeighborsResponse)
def api_node(node_id: str, depth: int = Query(2, ge=1, le=4)):
    node = db.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"node {node_id} not found")
    neighbors = db.get_neighbors(node_id, depth=depth)
    return {"node": node, "neighbors": neighbors}


@app.get("/api/graph/overview")
def api_overview(limit: int = Query(300, ge=1, le=2000)):
    return db.overview(limit=limit)


# ------------------------------------------------------------------ concepts (Compare page)
@app.get("/api/concepts")
def api_concepts(type: Optional[str] = Query(None),
                 q: Optional[str] = Query(None),
                 comparable: bool = Query(False),
                 limit: int = Query(20, ge=1, le=200)):
    """Graph-wide concept lookup for the «Сравнение» dropdown. Returns both a bare
    array and a {concepts:[...]} envelope (frontend adapter accepts either)."""
    concepts = db.search_concepts(type=type, q=q, comparable=comparable, limit=limit)
    return {"concepts": concepts}


# ------------------------------------------------------------------ documents
@app.get("/api/documents/{doc_id}", response_model=DocumentResponse)
def api_document(doc_id: str, role: str = Depends(auth.current_role)):
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"document {doc_id} not found")
    # ABAC: external partners may not open internal documents directly.
    if not auth.doc_visible(role, doc.get("section"), doc.get("sensitivity")):
        store.audit_log(role, f"/api/documents/{doc_id}", "document_view_denied",
                        params={"doc_id": doc_id})
        raise HTTPException(status_code=403, detail="document not visible for this role")
    store.audit_log(role, f"/api/documents/{doc_id}", "document_view",
                    params={"doc_id": doc_id})
    # contract §4.1 / types.ts DocumentMeta expects `geography_hint`
    doc["geography_hint"] = doc.get("geography_hint") or doc.get("geography")
    return doc


# ------------------------------------------------------------------ experts (C17)
@app.get("/api/experts", response_model=List[ExpertRef])
def api_experts(topic: Optional[str] = None, role: str = Depends(auth.current_role)):
    # contract §4.3 / types.ts: /api/experts returns a bare array of ExpertSummary
    experts = analytics.expert_map(topic=topic)
    store.audit_log(role, "/api/experts", "experts", params={"topic": topic},
                    result_counts={"experts": len(experts)})
    return experts


# ------------------------------------------------------------------ stats (C17)
_DOMAIN_LABELS = {
    "hydro": "Гидрометаллургия", "pyro": "Пирометаллургия",
    "обогащение": "Обогащение", "экология": "Экология",
    "горное дело": "Горное дело", "водоочистка": "Водоочистка",
}


def _buckets(d: dict, labels: Optional[dict] = None) -> List[dict]:
    labels = labels or {}
    if isinstance(d, list):
        return d
    return [{"key": k, "label": labels.get(k, k),
             "n_docs": v if isinstance(v, int) else (v or {}).get("n_docs", 0),
             "n_assertions": 0 if isinstance(v, int) else (v or {}).get("n_assertions", 0)}
            for k, v in (d or {}).items()]


def _corpus_total() -> Optional[int]:
    try:
        p = REPO_ROOT / "corpus" / "documents.jsonl"
        if p.exists():
            return sum(1 for line in p.read_text(encoding="utf-8").splitlines()
                       if line.strip())
    except Exception:
        pass
    return None


@app.get("/api/stats", response_model=StatsResponse)
def api_stats():
    s = db.graph_stats()
    raw_gaps = _global_gaps()
    try:
        import summaries
        domain_summaries = summaries.load_summaries()
    except Exception:
        domain_summaries = {}
    # C17 analytics extras (frontend ignores; kept for other consumers)
    try:
        coverage = analytics.corpus_coverage()
    except Exception:
        coverage = {}
    try:
        material_process_gaps = analytics.material_process_gaps()
    except Exception:
        material_process_gaps = []
    try:
        top_contradictions = analytics.top_contradictions()
    except Exception:
        top_contradictions = []
    try:
        experts = analytics.expert_map(limit=15)
    except Exception:
        experts = []
    try:
        cache_stats = answer_cache.stats()
    except Exception:
        cache_stats = {}

    node_types = s.get("node_types") or {}
    by_year = [{"year": int(y), "n_docs": n}
               for y, n in sorted((s.get("by_year") or {}).items())]
    top_gaps = [{"id": f"g{i}",
                 "title": g if len(g) <= 70 else g[:67] + "…",
                 "description": g, "severity": "medium"}
                for i, g in enumerate(raw_gaps)]
    return {
        "n_nodes": s.get("n_nodes", 0),
        "n_edges": s.get("n_edges", 0),
        "n_documents": s.get("n_documents", 0),
        "n_assertions": node_types.get("Assertion", 0),
        "n_contradictions": s.get("contradictions", 0),
        "node_types": node_types,
        "by_domain": _buckets(s.get("by_domain"), _DOMAIN_LABELS),
        "by_section": _buckets(s.get("by_section")),
        "by_year": by_year,
        "top_gaps": top_gaps,
        "domain_summaries": domain_summaries,
        "n_corpus_total": _corpus_total(),
        "coverage": coverage,
        "material_process_gaps": material_process_gaps,
        "top_contradictions": top_contradictions,
        "experts": experts,
        "cache": cache_stats,
    }


# ------------------------------------------------------------------ answer-cache (Answer-Cache agent)
@app.delete("/api/cache")
def api_clear_cache():
    """Очистить кэш ответов /api/search (для демо/защиты; RBAC отменён)."""
    n = answer_cache.clear()
    store.audit_log("anonymous", "/api/cache", "cache_clear",
                    result_counts={"cleared": n})
    return {"cleared": n}


def _global_gaps() -> List[str]:
    """Simple gap heuristic on the graph: processes without any numeric condition."""
    q = """
    MATCH (p:Process)
    WHERE NOT (p)-[:operates_at_condition]->(:Condition)
    RETURN p.name AS name LIMIT 20
    """
    gaps = []
    try:
        with db.driver().session() as sess:
            for r in sess.run(q):
                gaps.append(f"Процесс без числовых условий: {r['name']}")
    except Exception:
        pass
    return gaps


# ------------------------------------------------------------------ compare
@app.get("/api/compare", response_model=CompareResponse)
def api_compare(tech_a: str, tech_b: str, params: Optional[str] = None):
    param_list = [p.strip() for p in (params or "").split(",") if p.strip()] or \
        ["домен", "условия", "источники"]
    rows: List[CompareRow] = []

    def _describe(tid: str, param: str) -> Optional[str]:
        node = db.get_node(tid)
        if not node:
            return None
        if param == "домен":
            return (node["props"] or {}).get("domain")
        if param in ("условия", "источники"):
            sub = db.get_neighbors(tid, depth=1)
            if param == "условия":
                conds = [n["name"] for n in sub["nodes"] if n.get("type") == "Condition"]
                return "; ".join(conds) or None
            pubs = [n["name"] for n in sub["nodes"] if n.get("type") == "Publication"]
            return "; ".join(pubs) or None
        return None

    for p in param_list:
        rows.append(CompareRow(param=p, tech_a=_describe(tech_a, p),
                               tech_b=_describe(tech_b, p)))
    return {"tech_a": tech_a, "tech_b": tech_b, "rows": rows}


# ------------------------------------------------------------------ subscriptions (C15)
@app.post("/api/subscriptions", response_model=SubscriptionResponse)
def api_subscribe(req: SubscriptionRequest, role: str = Depends(auth.require("subscribe"))):
    sid = "sub_" + uuid.uuid4().hex[:10]
    filters = req.filters.model_dump(exclude_none=True) if req.filters else {}
    filters = {k: v for k, v in filters.items() if v not in ("", "all")}
    rec = store.add_subscription(sid, req.query, filters, role, req.email)
    # start the cursor at epoch so the first update feed surfaces current relevant docs
    store.touch_subscription(sid, "1970-01-01T00:00:00+00:00")
    rec["last_checked"] = "1970-01-01T00:00:00+00:00"
    store.audit_log(role, "/api/subscriptions", "subscribe",
                    params={"query": req.query, "filters": filters})
    return rec


@app.get("/api/subscriptions", response_model=SubscriptionListResponse)
def api_list_subscriptions(role: str = Depends(auth.require("subscribe"))):
    return {"subscriptions": store.list_subscriptions()}


@app.delete("/api/subscriptions/{sub_id}")
def api_delete_subscription(sub_id: str, role: str = Depends(auth.require("subscribe"))):
    if not store.delete_subscription(sub_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    store.audit_log(role, f"/api/subscriptions/{sub_id}", "unsubscribe",
                    params={"id": sub_id})
    return {"id": sub_id, "deleted": True}


@app.get("/api/subscriptions/{sub_id}/updates", response_model=SubscriptionUpdates)
def api_sub_updates(sub_id: str, role: str = Depends(auth.require("subscribe"))):
    sub = store.get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")
    updates = _subscription_updates(sub, advance=False)
    return {"id": sub_id, "query": sub["query"], "last_checked": sub["last_checked"],
            "n_new": len(updates), "updates": updates}


@app.post("/api/subscriptions/check_all")
def api_check_all(role: str = Depends(auth.require("subscribe"))):
    out = []
    for sub in store.list_subscriptions():
        updates = _subscription_updates(sub, advance=True)
        out.append({"id": sub["id"], "query": sub["query"], "n_new": len(updates),
                    "updates": updates})
    store.audit_log(role, "/api/subscriptions/check_all", "check_all",
                    result_counts={"subscriptions": len(out),
                                   "new_total": sum(o["n_new"] for o in out)})
    return {"checked": len(out), "results": out}


def _subscription_updates(sub: dict, advance: bool) -> List[dict]:
    """Re-run the saved query and return cited docs newer than last_checked."""
    since = sub.get("last_checked") or "1970-01-01T00:00:00+00:00"
    role = sub.get("role") or auth.DEFAULT_ROLE
    result = search_mod.search(sub["query"], filters=sub.get("filters") or {},
                               role_ctx=role)
    citations = result.get("citations") or []
    doc_ids = [c["doc_id"] for c in citations if c.get("doc_id")]
    meta = db.doc_titles(doc_ids)
    new_docs = []
    seen = set()
    for c in citations:
        did = c.get("doc_id")
        if not did or did in seen:
            continue
        seen.add(did)
        m = meta.get(did) or {}
        ing = m.get("ingested_at")
        if ing and str(ing) > str(since):
            new_docs.append({"doc_id": did, "title": m.get("title") or c.get("title"),
                             "year": m.get("year"), "ingested_at": ing,
                             "quote": c.get("quote")})
    if advance:
        store.touch_subscription(sub["id"])
    return new_docs


# ------------------------------------------------------------------ graph edit (C13: review)
@app.patch("/api/graph/edge/{edge_id:path}", response_model=EdgePatchResponse)
def api_patch_edge(edge_id: str, patch: EdgePatch,
                   role: str = Depends(auth.require("review"))):
    ts = _now()
    ok = db.patch_edge(edge_id, patch.author, patch.comment, patch.props, ts)
    if not ok:
        raise HTTPException(status_code=404, detail=f"edge {edge_id} not found")
    store.audit_log(role, f"/api/graph/edge/{edge_id}", "patch_edge",
                    params={"edge_id": edge_id, "author": patch.author,
                            "comment": patch.comment})
    return {"id": edge_id, "updated": True, "author": patch.author,
            "comment": patch.comment, "timestamp": ts, "version": 2}


@app.post("/api/assertions/{assert_id:path}/review", response_model=ReviewResponse)
def api_review(assert_id: str, req: ReviewRequest,
               role: str = Depends(auth.require("review"))):
    if req.status not in {"confirmed", "disputed", "rejected"}:
        raise HTTPException(status_code=400, detail="invalid status")
    ts = _now()
    ok = db.review_assertion(assert_id, req.status, req.author, ts)
    if not ok:
        raise HTTPException(status_code=404, detail=f"assertion {assert_id} not found")
    store.audit_log(role, f"/api/assertions/{assert_id}/review", "review",
                    params={"assert_id": assert_id, "status": req.status,
                            "author": req.author})
    return {"id": assert_id, "review_status": req.status, "author": req.author,
            "timestamp": ts}


# ------------------------------------------------------------------ export (C16)
@app.post("/api/export", response_model=ExportResponse)
def api_export(req: ExportRequest, role: str = Depends(auth.require("export"))):
    fmt = (req.format or "md").lower()

    # A compare-table can be exported to xlsx directly (no search result needed).
    compare = req.compare or (req.payload or {}).get("compare")
    if fmt == "xlsx" and compare:
        out = exporters.export("xlsx", "compare", {}, compare=compare)
        store.audit_log(role, "/api/export", "export", params={"format": "xlsx"})
        return {"search_id": req.search_id, **out}

    # All four formats (md / jsonld / pdf / xlsx) also work off a search result.
    if req.payload:
        query = req.payload.get("query", "")
        result = req.payload.get("result") or req.payload
    elif req.search_id:
        cached = store.get_cached_search(req.search_id)
        if not cached:
            raise HTTPException(status_code=404, detail="search_id not found")
        query, result = cached["query"], cached["result"]
    else:
        raise HTTPException(status_code=400,
                            detail="provide search_id, payload or a compare table")

    try:
        out = exporters.export(fmt, query, result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store.audit_log(role, "/api/export", "export",
                    params={"search_id": req.search_id, "format": fmt},
                    result_counts={"citations": len(result.get("citations") or [])})
    return {"search_id": req.search_id, **out}


# ------------------------------------------------------------------ audit (C14)
@app.get("/api/audit/log", response_model=AuditLogResponse)
def api_audit(action: Optional[str] = None,
              limit: int = Query(100, ge=1, le=1000),
              offset: int = Query(0, ge=0),
              role: str = Depends(auth.require("audit"))):
    return store.audit_query(action=action, limit=limit, offset=offset)
