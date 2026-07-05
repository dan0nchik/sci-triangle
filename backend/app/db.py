"""Data-access helpers over Neo4j + Elasticsearch for the API layer."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from neo4j import GraphDatabase  # noqa: E402
from elasticsearch import Elasticsearch  # noqa: E402

from config import (  # noqa: E402
    ES_CHUNKS, ES_CONDITIONS, ES_DOCUMENTS, ES_URL,
    NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER,
)

_driver = None
_es = None


def driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver


def es() -> Elasticsearch:
    global _es
    if _es is None:
        _es = Elasticsearch(ES_URL, request_timeout=30)
    return _es


def es_available() -> bool:
    try:
        return bool(es().ping())
    except Exception:
        return False


# ---------------------------------------------------------------- node helpers
def _node_dict(props: Dict[str, Any]) -> Dict[str, Any]:
    """Convert stored Neo4j node props into API GraphNode-shaped dict."""
    raw_props = {}
    if props.get("props_json"):
        try:
            raw_props = json.loads(props["props_json"])
        except Exception:
            raw_props = {}
    return {
        "id": props.get("id"),
        "type": props.get("type"),
        "name": props.get("name"),
        "name_en": props.get("name_en"),
        "confidence": props.get("confidence"),
        "props": raw_props,
    }


def get_node(node_id: str) -> Optional[Dict[str, Any]]:
    with driver().session() as s:
        rec = s.run("MATCH (n:Entity {id:$id}) RETURN n", id=node_id).single()
        if not rec:
            return None
        return _node_dict(dict(rec["n"]))


def get_neighbors(node_id: str, depth: int = 2, limit: int = 200) -> Dict[str, Any]:
    depth = max(1, min(depth, 4))
    q = f"""
    MATCH path=(n:Entity {{id:$id}})-[*1..{depth}]-(m:Entity)
    WITH nodes(path) AS ns, relationships(path) AS rs
    UNWIND ns AS nd
    WITH collect(DISTINCT nd) AS nodes0, collect(rs) AS rss
    RETURN nodes0 AS nodes,
           reduce(acc=[], rs IN rss | acc + rs) AS rels
    """
    nodes: Dict[str, Dict] = {}
    edges: Dict[str, Dict] = {}
    with driver().session() as s:
        rec = s.run(q, id=node_id).single()
        if not rec:
            return {"nodes": [], "edges": []}
        for nd in rec["nodes"]:
            d = _node_dict(dict(nd))
            nodes[d["id"]] = d
        for r in rec["rels"]:
            edge = _rel_dict(r)
            edges[edge["id"]] = edge
    return {"nodes": list(nodes.values())[:limit], "edges": list(edges.values())}


def _rel_dict(r) -> Dict[str, Any]:
    props = dict(r)
    raw = {}
    if props.get("props_json"):
        try:
            raw = json.loads(props["props_json"])
        except Exception:
            raw = {}
    return {
        "id": props.get("edge_id") or f"{r.start_node['id']}|{r.type}|{r.end_node['id']}",
        "src": r.start_node["id"],
        "dst": r.end_node["id"],
        "type": props.get("type") or r.type,
        "confidence": props.get("confidence"),
        "props": raw,
    }


# Обзор и статистика считаются по всему графу (после ночной пересборки —
# 44k+ узлов): под параллельными заходами жюри каждый вызов degree-скана
# складывался в минутные очереди и вешал api. Результат меняется только при
# перезаливке графа, поэтому короткий in-memory TTL-кэш безопасен.
_OVERVIEW_TTL_S = 600
_overview_cache: Dict[int, tuple] = {}  # limit -> (monotonic_ts, payload)


def overview(limit: int = 300) -> Dict[str, Any]:
    cached = _overview_cache.get(limit)
    if cached and (time.monotonic() - cached[0]) < _OVERVIEW_TTL_S:
        return cached[1]
    result = _overview_uncached(limit)
    _overview_cache[limit] = (time.monotonic(), result)
    return result


def _overview_uncached(limit: int = 300) -> Dict[str, Any]:
    # Якоря обзора — самые связные концептные узлы. Листовые Measurement/
    # Condition исключены: после массовой экстракции их большинство в порядке
    # хранения, и «первые N рёбер» вытесняли Process/Material из выборки
    # (ломался и обзорный граф, и автокомплит сравнения технологий).
    q = """
    MATCH (a:Entity)
    WHERE a.type IS NULL OR NOT a.type IN ['Measurement', 'Condition']
    WITH a, COUNT { (a)--() } AS deg
    ORDER BY deg DESC LIMIT $lim
    WITH collect(a) AS anchors
    UNWIND anchors AS a
    MATCH (a)-[r]->(b:Entity)
    WHERE b IN anchors
    RETURN a, r, b
    """
    nodes: Dict[str, Dict] = {}
    edges: Dict[str, Dict] = {}
    with driver().session() as s:
        for rec in s.run(q, lim=limit):
            for key in ("a", "b"):
                d = _node_dict(dict(rec[key]))
                nodes[d["id"]] = d
            edge = _rel_dict(rec["r"])
            edges[edge["id"]] = edge
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def subgraph_for(node_ids: List[str], depth: int = 1) -> Dict[str, Any]:
    nodes: Dict[str, Dict] = {}
    edges: Dict[str, Dict] = {}
    for nid in node_ids:
        sub = get_neighbors(nid, depth=depth)
        for nd in sub["nodes"]:
            nodes[nd["id"]] = nd
        for ed in sub["edges"]:
            edges[ed["id"]] = ed
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


# ---------------------------------------------------------------- vector search
def vector_search_entities(embedding: List[float], k: int = 8) -> List[Dict[str, Any]]:
    q = """
    CALL db.index.vector.queryNodes('entity_embeddings', $k, $emb)
    YIELD node, score
    RETURN node, score
    """
    out = []
    with driver().session() as s:
        for rec in s.run(q, k=k, emb=embedding):
            d = _node_dict(dict(rec["node"]))
            d["score"] = rec["score"]
            out.append(d)
    return out


# ---------------------------------------------------------------- ES search
def _number_variants(n: Dict[str, Any]) -> List[str]:
    """Textual variants of an intent number for ES boosting: comma/dot decimal forms,
    with and without the unit ('1,2' / '1.2' / '1,2 м/с')."""
    val, unit = n.get("value"), (n.get("unit") or "").strip()
    if val is None:
        return []
    try:
        f = float(val)
        base = str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        base = str(val)
    variants = {base, base.replace(".", ",")}
    if unit:
        variants |= {f"{v} {unit}" for v in list(variants)}
    return [v for v in variants if v]


def es_search_chunks(query: str, filters: Optional[Dict] = None, size: int = 8,
                     numbers: Optional[List[Dict]] = None) -> List[Dict]:
    if not es_available():
        return []
    must = [{
        "multi_match": {
            "query": query,
            "fields": ["text^2", "text.en", "section_title"],
            "type": "most_fields",
        }
    }]
    # Number boost (agent R, task: number accuracy): chunks containing the query's
    # numeric constraints ("1,2"/"1.2", "300 мг/л") rank higher so the numeric evidence
    # chunk reaches the citation top. should-clauses affect scoring only, never filter.
    should = []
    for n in numbers or []:
        if not isinstance(n, dict):
            continue
        for v in _number_variants(n):
            should.append({"match_phrase": {"text": {"query": v, "boost": 3.0}}})
    filt = []
    filters = filters or {}
    if filters.get("year_from") or filters.get("year_to"):
        rng = {}
        if filters.get("year_from"):
            rng["gte"] = filters["year_from"]
        if filters.get("year_to"):
            rng["lte"] = filters["year_to"]
        filt.append({"range": {"year": rng}})
    if filters.get("geography"):
        filt.append({"term": {"geography": filters["geography"]}})
    if filters.get("section"):
        filt.append({"term": {"section": filters["section"]}})
    if filters.get("doc_id"):
        filt.append({"term": {"doc_id": filters["doc_id"]}})
    body = {"query": {"bool": {"must": must, "filter": filt, "should": should}},
            "size": size}
    try:
        res = es().search(index=ES_CHUNKS, **body)
    except Exception:
        return []
    return [{**h["_source"], "_score": h["_score"]} for h in res["hits"]["hits"]]


def es_search_conditions(param_substr: Optional[str] = None,
                         value_lte: Optional[float] = None,
                         value_gte: Optional[float] = None, size: int = 10) -> List[Dict]:
    if not es_available():
        return []
    must, filt = [], []
    if param_substr:
        must.append({"match": {"param_text": param_substr}})
    if value_lte is not None:
        filt.append({"range": {"value": {"lte": value_lte}}})
    if value_gte is not None:
        filt.append({"range": {"value": {"gte": value_gte}}})
    body = {"query": {"bool": {"must": must or [{"match_all": {}}], "filter": filt}},
            "size": size}
    try:
        res = es().search(index=ES_CONDITIONS, **body)
    except Exception:
        return []
    return [h["_source"] for h in res["hits"]["hits"]]


def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    if not es_available():
        return None
    try:
        doc = es().get(index=ES_DOCUMENTS, id=doc_id)["_source"]
    except Exception:
        return None
    chunks = []
    try:
        res = es().search(index=ES_CHUNKS, query={"term": {"doc_id": doc_id}},
                          size=100, sort=[{"seq": "asc"}])
        chunks = [h["_source"] for h in res["hits"]["hits"]]
    except Exception:
        pass
    doc["chunks"] = chunks
    return doc


# ---------------------------------------------------------------- analytics
_stats_cache: Dict[str, tuple] = {}  # "stats" -> (monotonic_ts, payload)


def graph_stats() -> Dict[str, Any]:
    cached = _stats_cache.get("stats")
    if cached and (time.monotonic() - cached[0]) < _OVERVIEW_TTL_S:
        return cached[1]
    result = _graph_stats_uncached()
    _stats_cache["stats"] = (time.monotonic(), result)
    return result


def _graph_stats_uncached() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    with driver().session() as s:
        out["n_nodes"] = s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
        out["n_edges"] = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        out["node_types"] = {r["t"]: r["c"] for r in s.run(
            "MATCH (n:Entity) RETURN n.type AS t, count(*) AS c ORDER BY c DESC")}
        out["by_domain"] = {r["d"]: r["c"] for r in s.run(
            "MATCH (n:Entity) WHERE n.domain IS NOT NULL "
            "RETURN n.domain AS d, count(*) AS c")}
        out["by_section"] = {r["s"]: r["c"] for r in s.run(
            "MATCH (n:Publication) WHERE n.props_json IS NOT NULL "
            "RETURN coalesce(n.props_json,'') AS raw, 1 AS one") if False}
        # sections/years derived from Publication nodes
        secs, years = {}, {}
        for rec in s.run("MATCH (n:Publication) RETURN n"):
            p = _node_dict(dict(rec["n"]))["props"]
            sec = p.get("section")
            yr = p.get("year")
            if sec:
                secs[sec] = secs.get(sec, 0) + 1
            if yr:
                years[str(yr)] = years.get(str(yr), 0) + 1
        out["by_section"] = secs
        out["by_year"] = years
        out["contradictions"] = s.run(
            "MATCH (:Assertion)-[r:contradicts]->(:Assertion) "
            "RETURN count(r) AS c").single()["c"]
        out["n_documents"] = out["node_types"].get("Publication", 0)
    return out


def find_experts(topic: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    if topic:
        q = """
        MATCH (e:Expert)
        OPTIONAL MATCH (e)-[:expert_in]->(t:Entity)
        WITH e, collect(t) AS topics
        WHERE any(t IN topics WHERE toLower(t.name) CONTAINS toLower($topic))
           OR toLower(coalesce(e.name,'')) CONTAINS toLower($topic)
        OPTIONAL MATCH (pub:Publication)-[:authored_by]->(e)
        RETURN e, count(DISTINCT pub) AS n_works
        LIMIT $lim
        """
        params = {"topic": topic, "lim": limit}
    else:
        q = """
        MATCH (e:Expert)
        OPTIONAL MATCH (pub:Publication)-[:authored_by]->(e)
        RETURN e, count(DISTINCT pub) AS n_works
        LIMIT $lim
        """
        params = {"lim": limit}
    out = []
    with driver().session() as s:
        for rec in s.run(q, **params):
            e = _node_dict(dict(rec["e"]))
            out.append({
                "id": e["id"], "name": e["name"],
                "affiliation": (e["props"] or {}).get("affiliation"),
                "n_works": rec["n_works"],
            })
    return out


def experts_for_nodes(node_ids: List[str]) -> List[Dict[str, Any]]:
    if not node_ids:
        return []
    q = """
    MATCH (e:Expert)-[:expert_in|authored_by]-(x:Entity)
    WHERE x.id IN $ids
    OPTIONAL MATCH (pub:Publication)-[:authored_by]->(e)
    RETURN DISTINCT e, count(DISTINCT pub) AS n_works
    """
    out = []
    with driver().session() as s:
        for rec in s.run(q, ids=node_ids):
            e = _node_dict(dict(rec["e"]))
            out.append({
                "id": e["id"], "name": e["name"],
                "affiliation": (e["props"] or {}).get("affiliation"),
                "n_works": rec["n_works"],
            })
    return out


def contradictions_for_nodes(node_ids: List[str]) -> List[Dict[str, Any]]:
    q = """
    MATCH (a:Assertion)-[:contradicts]-(b:Assertion)
    WHERE a.id IN $ids OR b.id IN $ids
    RETURN DISTINCT a, b
    """
    seen = set()
    out = []
    with driver().session() as s:
        for rec in s.run(q, ids=node_ids):
            a = _node_dict(dict(rec["a"]))
            b = _node_dict(dict(rec["b"]))
            key = tuple(sorted([a["id"], b["id"]]))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "a": a["id"], "b": b["id"],
                "a_statement": (a["props"] or {}).get("statement") or a["name"],
                "b_statement": (b["props"] or {}).get("statement") or b["name"],
            })
    return out


# ---------------------------------------------------------------- C-query helpers
def entities_by_terms(terms: List[str], limit: int = 40) -> List[Dict[str, Any]]:
    """Find graph entities whose name/name_en/aliases match any surface form.

    Exact (case-insensitive) match on name/name_en/alias, plus CONTAINS for terms
    of length >= 4. Matching by surface form (not concept_id) because the fixture
    uses a different concept_id scheme than shared/concepts.yaml.
    """
    forms = sorted({(t or "").strip().lower() for t in terms if t and t.strip()})
    if not forms:
        return []
    long_forms = [f for f in forms if len(f) >= 4]
    q = """
    MATCH (n:Entity)
    WHERE any(t IN $forms WHERE
              toLower(n.name) = t
              OR toLower(coalesce(n.name_en,'')) = t
              OR t IN [a IN coalesce(n.aliases,[]) | toLower(a)])
       OR any(t IN $long WHERE
              toLower(n.name) CONTAINS t
              OR toLower(coalesce(n.name_en,'')) CONTAINS t)
    RETURN DISTINCT n LIMIT $lim
    """
    out = []
    with driver().session() as s:
        for rec in s.run(q, forms=forms, long=long_forms, lim=limit):
            out.append(_node_dict(dict(rec["n"])))
    return out


def docs_linked_to_entities(entity_ids: List[str], depth: int = 2) -> Dict[str, List[str]]:
    """For each entity id -> list of doc_ids it is connected to (Publications within
    `depth` hops, plus its own source_docs). Used for the 'concept' relevance signal."""
    if not entity_ids:
        return {}
    depth = max(1, min(depth, 3))
    q = f"""
    MATCH (n:Entity) WHERE n.id IN $ids
    OPTIONAL MATCH (n)-[*1..{depth}]-(p:Publication)
    RETURN n.id AS eid, n.source_docs AS sdocs,
           collect(DISTINCT p.id) AS pubids
    """
    out: Dict[str, List[str]] = {}
    with driver().session() as s:
        for rec in s.run(q, ids=entity_ids):
            docs = set(rec["sdocs"] or [])
            for pid in rec["pubids"] or []:
                if pid and pid.startswith("pub:"):
                    docs.add(pid.split("pub:", 1)[1])
            out[rec["eid"]] = sorted(docs)
    return out


def assertions_for_entities(entity_ids: List[str], limit: int = 12) -> List[Dict[str, Any]]:
    """Assertions connected (<=2 hops) to the given entities, with evidence quotes."""
    if not entity_ids:
        return []
    q = """
    MATCH (n:Entity) WHERE n.id IN $ids
    MATCH (a:Assertion)-[*1..2]-(n)
    RETURN DISTINCT a LIMIT $lim
    """
    out = []
    seen = set()
    with driver().session() as s:
        for rec in s.run(q, ids=entity_ids, lim=limit):
            a = _node_dict(dict(rec["a"]))
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            out.append(a)
    return out


def chunks_for_docs(doc_ids: List[str], per_doc: int = 3) -> List[Dict[str, Any]]:
    """Representative chunks for docs (for citation recovery on semantic hits)."""
    if not doc_ids or not es_available():
        return []
    out = []
    for did in doc_ids:
        try:
            res = es().search(index=ES_CHUNKS, query={"term": {"doc_id": did}},
                              size=per_doc, sort=[{"seq": "asc"}])
            out.extend(h["_source"] for h in res["hits"]["hits"])
        except Exception:
            continue
    return out


def es_search_docs_by_name(query: str, size: int = 5) -> List[Dict[str, Any]]:
    """Doc-level lexical branch: match query against document FILENAME (often the true
    title in the real corpus, while `title` is OCR junk) and title.
    Returns [{doc_id, _score, filename}] sorted by score."""
    if not es_available():
        return []
    body = {
        "query": {"multi_match": {"query": query,
                                  "fields": ["filename^2", "filename.en",
                                             "title", "title.en"]}},
        "size": size,
    }
    try:
        res = es().search(index=ES_DOCUMENTS, **body)
    except Exception:
        return []
    return [{"doc_id": h["_id"], "_score": h["_score"],
             "filename": (h["_source"] or {}).get("filename")}
            for h in res["hits"]["hits"]]


def chunk_texts(chunk_ids: List[str]) -> Dict[str, str]:
    """chunk_id -> text (from ES chunks), for vector-branch candidates."""
    ids = [c for c in dict.fromkeys(chunk_ids) if c]
    if not ids or not es_available():
        return {}
    out: Dict[str, str] = {}
    try:
        res = es().mget(index=ES_CHUNKS, ids=ids, _source=["text", "doc_id"])
        for d in res["docs"]:
            if d.get("found"):
                out[d["_id"]] = (d["_source"] or {}).get("text") or ""
    except Exception:
        pass
    return out


def doc_titles(doc_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """doc_id -> {title, year, section, geography, sensitivity, ingested_at} from ES
    documents; Publication node fallback if ES is unavailable."""
    meta: Dict[str, Dict[str, Any]] = {}
    ids = [d for d in set(doc_ids) if d]
    if not ids:
        return meta
    if es_available():
        try:
            res = es().mget(index=ES_DOCUMENTS, ids=ids)
            for d in res["docs"]:
                if d.get("found"):
                    src = d["_source"]
                    meta[d["_id"]] = {
                        "title": src.get("title"), "year": src.get("year"),
                        "section": src.get("section"),
                        "geography": src.get("geography") or src.get("geography_hint"),
                        "sensitivity": src.get("sensitivity"),
                        "ingested_at": src.get("ingested_at"),
                    }
        except Exception:
            pass
    missing = [d for d in ids if d not in meta]
    if missing:
        with driver().session() as s:
            for did in missing:
                rec = s.run("MATCH (p:Publication {id:$pid}) RETURN p",
                            pid=f"pub:{did}").single()
                if rec:
                    nd = _node_dict(dict(rec["p"]))
                    p = nd["props"] or {}
                    meta[did] = {"title": nd["name"], "year": p.get("year"),
                                 "section": p.get("section"),
                                 "geography": p.get("geography"),
                                 "sensitivity": p.get("sensitivity"),
                                 "ingested_at": p.get("ingested_at")}
    return meta


def domain_processes() -> Dict[str, List[Dict[str, Any]]]:
    """Group Process nodes by domain (for C11 domain summaries)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    with driver().session() as s:
        for rec in s.run("MATCH (p:Process) RETURN p, p.domain AS d"):
            nd = _node_dict(dict(rec["p"]))
            d = rec["d"] or (nd["props"] or {}).get("domain") or "прочее"
            out.setdefault(d, []).append(nd)
    return out


def patch_edge(edge_id: str, author: str, comment: Optional[str],
               props: Optional[Dict], timestamp: str) -> bool:
    """Apply a manual edit to an edge.

    Edges are addressed by a stable id: either an explicit `edge_id` property, or a
    composite `src|type|dst` (the form returned by `_rel_dict` when `edge_id` is
    absent — e.g. fixture edges). We match on whichever form is provided.
    """
    sets = ("SET r.created_by = $author, r.edit_comment = $comment, "
            "r.edited_at = $ts, r.method = 'manual', "
            "r.version = coalesce(r.version, 1) + 1")
    parts = edge_id.split("|")
    if len(parts) == 3:
        src, etype, dst = parts
        match = ("MATCH (a:Entity {id:$src})-[r]->(b:Entity {id:$dst}) "
                 "WHERE coalesce(r.type, type(r)) = $etype ")
        params = {"src": src, "dst": dst, "etype": etype,
                  "author": author, "comment": comment, "ts": timestamp}
    else:
        match = "MATCH ()-[r {edge_id:$eid}]->() "
        params = {"eid": edge_id, "author": author, "comment": comment, "ts": timestamp}
    with driver().session() as s:
        c = s.run(match + sets + " RETURN count(r) AS c", **params).single()["c"]
        if c > 0 and props:
            s.run(match + "SET r.props_json=$p",
                  **{**params, "p": json.dumps(props, ensure_ascii=False)})
    return c > 0


def search_concepts(type: Optional[str] = None, q: Optional[str] = None,
                    comparable: bool = False, limit: int = 20) -> List[Dict[str, Any]]:
    """Graph-wide concept search for the Compare page dropdown.

    Matches name/name_en/aliases (case-insensitive CONTAINS) over ALL Entity nodes of
    the given `type` (Process|Equipment|Material|…). `comparable` keeps only nodes with
    at least one operates_at_condition | measured | uses_material link (in either
    direction) — those are the ones worth comparing. Comparable nodes sort first, then
    by link count desc. LIMIT + a per-query transaction timeout keep it cheap.
    """
    from neo4j import Query  # local import: keeps module import surface unchanged

    limit = max(1, min(int(limit or 20), 200))
    ql = (q or "").strip().lower() or None
    cypher = """
    MATCH (n:Entity)
    WHERE ($type IS NULL OR n.type = $type)
      AND ($q IS NULL
           OR toLower(coalesce(n.name,'')) CONTAINS $q
           OR toLower(coalesce(n.name_en,'')) CONTAINS $q
           OR any(a IN coalesce(n.aliases, []) WHERE toLower(a) CONTAINS $q))
    OPTIONAL MATCH (n)-[r:operates_at_condition|measured|uses_material]-()
    WITH n, count(r) AS n_links
    WHERE ($comparable = false OR n_links > 0)
    RETURN n, n_links
    ORDER BY (n_links > 0) DESC, n_links DESC, toLower(coalesce(n.name,''))
    LIMIT $limit
    """
    out: List[Dict[str, Any]] = []
    params = {"type": type or None, "q": ql, "comparable": bool(comparable),
              "limit": limit}
    try:
        with driver().session() as s:
            for rec in s.run(Query(cypher, timeout=8.0), **params):
                d = _node_dict(dict(rec["n"]))
                n_links = int(rec["n_links"])
                out.append({
                    "id": d["id"], "type": d["type"],
                    "name": d["name"], "name_en": d["name_en"],
                    "comparable": n_links > 0, "n_links": n_links,
                })
    except Exception:
        return []
    return out


def review_assertion(assert_id: str, status: str, author: str, timestamp: str) -> bool:
    q = """
    MATCH (a:Assertion {id:$id})
    SET a.review_status=$status, a.reviewed_by=$author, a.reviewed_at=$ts
    RETURN count(a) AS c
    """
    with driver().session() as s:
        return s.run(q, id=assert_id, status=status, author=author,
                     ts=timestamp).single()["c"] > 0
