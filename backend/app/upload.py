"""Upload-pipeline: single-document ingestion made demonstrable (PLAN.md §4.1–4.2).

Canonical jury pipeline, exposed over one API and driven stage-by-stage:

    upload → extracting_text → chunking → embedding → indexing
           → extracting_knowledge → merging_graph → done

Every stage reuses the existing project code (NO duplication):
  * text + chunks : pipeline.ingest.textextract / pipeline.ingest.chunker
  * embeddings    : shared.embeddings_gateway (best-effort; skipped if backend down)
  * ES index      : backend/es_indexer  (document + chunks — immediately searchable)
  * LLM knowledge : pipeline.extract.runner.extract_payloads / build_fragment
                    (gateway role="extraction"; if no provider → stage «deferred»)
  * graph merge   : backend/loader (MERGE — idempotent)

The uploaded chunks live in a SEPARATE area (corpus/uploads/) and are NEVER written
into the main corpus/chunks.jsonl. Job state + stages are persisted in sqlite so
GET /api/upload/{job_id} can be polled by the UI.

Dedup: re-uploading the same bytes (sha256) returns the same doc_id and the cached
stages/result of the first successful job.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
for _p in (str(BACKEND), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- reuse: ingest text extraction + chunking (function-level, no CLI coupling) ---
from pipeline.ingest import textextract, chunker  # noqa: E402
# --- reuse: backend ES indexer + Neo4j loader ---
import es_indexer  # noqa: E402
import loader  # noqa: E402

UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(REPO_ROOT / "corpus" / "uploads")))
DB_PATH = Path(os.environ.get("UPLOADS_DB", str(BACKEND / "uploads.sqlite")))

SUPPORTED_EXT = {".pdf", ".docx", ".docm", ".doc", ".pptx", ".xlsx", ".xls"}

# Budget guard for the LLM-extraction stage (env-tunable; live demo uses a small cap).
EXTRACT_MAX_CHUNKS = int(os.environ.get("UPLOAD_EXTRACT_MAX", "40") or 40)
EXTRACT_MODEL = os.environ.get("UPLOAD_EXTRACT_MODEL", "lite")

STAGES = ("queued", "extracting_text", "chunking", "embedding", "indexing",
          "extracting_knowledge", "merging_graph", "done", "failed")

_lock = threading.Lock()
_initialized = False


# --------------------------------------------------------------------------- db
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        with _conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    sha256 TEXT,
                    doc_id TEXT,
                    filename TEXT,
                    stage TEXT,
                    progress REAL,
                    detail TEXT,
                    result TEXT,
                    error TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_sha ON jobs(sha256);

                CREATE TABLE IF NOT EXISTS docs (
                    sha256 TEXT PRIMARY KEY,
                    doc_id TEXT,
                    job_id TEXT,
                    filename TEXT,
                    created_at TEXT
                );
                """
            )
        _initialized = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_stage(job_id: str, stage: str, progress: float,
               detail: str = "", result: Optional[dict] = None,
               error: Optional[str] = None) -> None:
    with _conn() as c:
        row = c.execute("SELECT result FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        result_json = None
        if result is not None:
            result_json = json.dumps(result, ensure_ascii=False)
        elif row and row["result"]:
            result_json = row["result"]
        c.execute(
            "UPDATE jobs SET stage=?, progress=?, detail=?, result=?, error=?, "
            "updated_at=? WHERE job_id=?",
            (stage, progress, detail, result_json, error, _now(), job_id),
        )


def get_job(job_id: str) -> Optional[dict]:
    init()
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    out = {
        "job_id": row["job_id"],
        "doc_id": row["doc_id"],
        "filename": row["filename"],
        "stage": row["stage"],
        "progress": row["progress"],
        "detail": row["detail"] or "",
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    return out


# --------------------------------------------------------------------- helpers
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _derive_meta(filename: str, ext: str) -> dict:
    """Lightweight metadata for an uploaded doc (no data-tree path available)."""
    import re
    stem = Path(filename).stem
    year = None
    m = re.search(r"(19|20)\d{2}", filename)
    if m:
        year = int(m.group(0))
    source_type = {
        ".pdf": "article", ".docx": "article", ".docm": "article", ".doc": "article",
        ".pptx": "presentation", ".xlsx": "report", ".xls": "report",
    }.get(ext, "article")
    return {
        "section": "Загруженные документы",
        "journal": None,
        "year": year,
        "source_type": source_type,
        "geography_hint": None,
        "title": stem[:200] or filename,
    }


def _doc_lang(chunks: List) -> str:
    langs = {c.lang for c in chunks}
    if langs == {"ru"}:
        return "ru"
    if langs == {"en"}:
        return "en"
    return "mixed"


def _title(chunks: List, fallback: str) -> str:
    for c in chunks[:3]:
        if c.section_title:
            return c.section_title[:200]
    return fallback


def _graph_preview(nodes: Dict[str, dict], edges: Dict[Any, dict],
                   pub_id: str, max_nodes: int = 30) -> dict:
    """Fragment for the UI: ≤max_nodes, publication node first, then by degree."""
    node_list = list(nodes.values())
    deg: Dict[str, int] = {}
    for e in edges.values():
        deg[e["src"]] = deg.get(e["src"], 0) + 1
        deg[e["dst"]] = deg.get(e["dst"], 0) + 1
    node_list.sort(key=lambda n: (n["id"] != pub_id, -deg.get(n["id"], 0)))
    keep = node_list[:max_nodes]
    keep_ids = {n["id"] for n in keep}
    prev_nodes = [{
        "id": n["id"], "type": n["type"], "name": n["name"],
        "name_en": n.get("name_en", ""), "confidence": n.get("confidence"),
        "props": n.get("props", {}),
    } for n in keep]
    prev_edges = [{
        "src": e["src"], "dst": e["dst"], "type": e["type"], "props": e.get("props", {}),
    } for e in edges.values() if e["src"] in keep_ids and e["dst"] in keep_ids]
    return {"nodes": prev_nodes, "edges": prev_edges}


# ---------------------------------------------------- embedding (best effort)
def _embed_and_store(chunk_rows: List[dict]) -> dict:
    """Embed chunk texts via the multi-embedding gateway and append them to the
    active precompute store so the vector branch can retrieve them too.

    Fully best-effort: any failure (e.g. dead Yandex key) → stage skipped, the
    document stays searchable through Elasticsearch full-text."""
    try:
        from shared.embeddings_gateway import embed_texts, get_space
        import numpy as np
    except Exception as e:  # noqa: BLE001
        return {"status": "skipped", "detail": f"embeddings gateway unavailable: {e}"}

    texts = [c["text"] for c in chunk_rows]
    try:
        vecs = embed_texts(texts, kind="doc")
    except Exception as e:  # noqa: BLE001
        return {"status": "skipped",
                "detail": f"embedding backend error ({type(e).__name__}); "
                          f"document searchable via full-text"}
    if not vecs or any(v is None for v in vecs):
        return {"status": "skipped", "detail": "embedding backend returned no vectors"}

    # append to graph/embeddings/{space}/chunk_embeddings.npy (+ chunk_ids.json)
    try:
        space = get_space().space_id
        emb_root = REPO_ROOT / "graph" / "embeddings"
        d = emb_root / space
        npy, ids_path = d / "chunk_embeddings.npy", d / "chunk_ids.json"
        if not (npy.exists() and ids_path.exists()) and space == "yandex-256":
            npy, ids_path = emb_root / "chunk_embeddings.npy", emb_root / "chunk_ids.json"
        d.mkdir(parents=True, exist_ok=True)

        new_arr = np.asarray(vecs, dtype=np.float32)
        new_ids = [{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"]} for c in chunk_rows]
        if npy.exists() and ids_path.exists():
            old = np.load(npy).astype(np.float32)
            old_ids = json.load(open(ids_path, encoding="utf-8"))
            have = {r["chunk_id"] for r in old_ids}
            mask = [c["chunk_id"] not in have for c in chunk_rows]
            add_arr = new_arr[mask]
            add_ids = [i for i, m in zip(new_ids, mask) if m]
            if len(add_ids):
                merged = np.vstack([old, add_arr]) if old.size else add_arr
                np.save(npy, merged)
                json.dump(old_ids + add_ids, open(ids_path, "w", encoding="utf-8"),
                          ensure_ascii=False)
            n_added = len(add_ids)
        else:
            np.save(npy, new_arr)
            json.dump(new_ids, open(ids_path, "w", encoding="utf-8"), ensure_ascii=False)
            n_added = len(new_ids)
        return {"status": "ok", "detail": f"embedded {len(vecs)} chunks, "
                f"+{n_added} into vector store ({space})", "n_embedded": len(vecs)}
    except Exception as e:  # noqa: BLE001
        return {"status": "partial",
                "detail": f"embedded but store append failed: {e}", "n_embedded": len(vecs)}


# --------------------------------------------------------------- background job
def _process(job_id: str, tmp_path: Path, doc_id: str, sha: str,
             filename: str, ext: str) -> None:
    init()
    result: Dict[str, Any] = {"doc_id": doc_id, "n_chunks": 0, "n_entities": 0,
                              "n_edges": 0, "graph_preview": {"nodes": [], "edges": []},
                              "stages": {}}
    try:
        meta = _derive_meta(filename, ext)

        # 1) text extraction ------------------------------------------------
        _set_stage(job_id, "extracting_text", 0.10,
                   f"Извлечение текста ({ext}) через pipeline.ingest…", result)
        t0 = time.time()
        res = textextract.extract(tmp_path)
        result["stages"]["extracting_text"] = {
            "status": "ok", "n_pages": res.n_pages, "method": res.method,
            "took_ms": int((time.time() - t0) * 1000)}

        # 2) chunking -------------------------------------------------------
        _set_stage(job_id, "chunking", 0.30,
                   "Чанкование (≤1200 токенов, overlap) …", result)
        t0 = time.time()
        chunks = chunker.chunk_document(res.pages)
        if not chunks:
            raise RuntimeError("no text extracted (0 chunks)")
        chunk_rows = [{
            "chunk_id": f"{doc_id}_c{c.seq:04d}", "doc_id": doc_id, "seq": c.seq,
            "text": c.text, "n_tokens": c.n_tokens, "page_from": c.page_from,
            "page_to": c.page_to, "lang": c.lang, "section_title": c.section_title,
        } for c in chunks]
        # persist chunks into the SEPARATE uploads area (never corpus/chunks.jsonl)
        doc_lang = _doc_lang(chunks)
        doc = {
            "doc_id": doc_id, "path": f"uploads/{filename}", "filename": filename,
            "title": _title(chunks, meta["title"]), "section": meta["section"],
            "journal": meta["journal"], "year": meta["year"], "lang": doc_lang,
            "source_type": meta["source_type"], "geography_hint": meta["geography_hint"],
            "n_pages": res.n_pages, "n_chunks": len(chunks),
            "extract_method": res.method, "status": "ok", "wave": 0,
            "ingested_at": _now(), "sha256": sha, "uploaded": True,
        }
        _write_upload_files(doc_id, doc, chunk_rows)
        result["n_chunks"] = len(chunk_rows)
        result["stages"]["chunking"] = {
            "status": "ok", "n_chunks": len(chunk_rows),
            "took_ms": int((time.time() - t0) * 1000)}

        # 3) embedding (best-effort) ---------------------------------------
        _set_stage(job_id, "embedding", 0.45,
                   "Эмбеддинги чанков (shared.embeddings_gateway) …", result)
        t0 = time.time()
        emb = _embed_and_store(chunk_rows)
        emb["took_ms"] = int((time.time() - t0) * 1000)
        result["stages"]["embedding"] = emb

        # 4) ES indexing (document + chunks -> immediately searchable) ------
        _set_stage(job_id, "indexing", 0.60,
                   "Индексация в Elasticsearch (документ + чанки) …", result)
        t0 = time.time()
        es = es_indexer.es_client()
        es_indexer.create_indexes(es, recreate=False)
        n_docs = es_indexer.index_documents(es, [doc])
        n_ch = es_indexer.index_chunks(es, chunk_rows, {doc_id: doc})
        es.indices.refresh(index=[es_indexer.ES_DOCUMENTS, es_indexer.ES_CHUNKS])
        result["stages"]["indexing"] = {
            "status": "ok", "documents": n_docs, "chunks": n_ch,
            "took_ms": int((time.time() - t0) * 1000)}

        # 5) LLM knowledge extraction (deferred if no provider) ------------
        _set_stage(job_id, "extracting_knowledge", 0.75,
                   "LLM-извлечение сущностей/фактов/связей …", result)
        t0 = time.time()
        from pipeline.extract import runner as extract_runner
        to_extract = chunk_rows[:EXTRACT_MAX_CHUNKS]
        extractions = extract_runner.extract_payloads(
            to_extract, model=EXTRACT_MODEL, limit=EXTRACT_MAX_CHUNKS)
        n_ok = sum(1 for e in extractions if e.get("ok"))
        deferred = n_ok == 0
        gb = extract_runner.build_fragment(extractions, use_embedding=False)
        result["stages"]["extracting_knowledge"] = {
            "status": "deferred" if deferred else "ok",
            "chunks_sent": len(to_extract), "chunks_ok": n_ok,
            "detail": ("LLM-провайдер недоступен — извлечение знаний отложено; "
                       "документ уже в поиске и как Publication-узел в графе")
                      if deferred else
                      f"извлечено из {n_ok}/{len(to_extract)} чанков",
            "entities": gb.stats.get("entities", 0),
            "relations": gb.stats.get("relations", 0),
            "assertions": gb.stats.get("assertions", 0),
            "took_ms": int((time.time() - t0) * 1000)}

        # 6) merge fragment into Neo4j (MERGE — idempotent) ----------------
        _set_stage(job_id, "merging_graph", 0.90,
                   "Объединение фрагмента с общим графом (Neo4j MERGE) …", result)
        t0 = time.time()
        pub_id = f"pub:{doc_id}"
        if pub_id not in gb.nodes:
            # even without LLM, publish the document as a graph node
            gb.process(chunk_rows[0]["chunk_id"], doc_id, chunk_rows[0]["text"], {})
        _augment_pub_node(gb, pub_id, doc)
        nodes = list(gb.nodes.values())
        edges = list(gb.edges.values())
        with loader._driver() as drv:
            with drv.session() as sess:
                loader.create_schema(sess)
                # Non-destructive merge: the loader does a full `SET n += {...}`, which
                # would clobber provenance of pre-existing SHARED nodes (e.g. mat:nickel,
                # proc:electrowinning) down to this single upload. Pre-union the fragment
                # nodes with what's already in the graph so the overwrite preserves it.
                _preserve_existing(sess, nodes)
                n_nodes = loader.load_nodes(sess, nodes)
                n_edges, _ = loader.load_edges(sess, edges)
        result["n_entities"] = len([n for n in nodes if n["type"] not in ("Publication",)])
        result["n_edges"] = n_edges
        result["graph_preview"] = _graph_preview(gb.nodes, gb.edges, pub_id)
        result["stages"]["merging_graph"] = {
            "status": "ok", "nodes_merged": n_nodes, "edges_merged": n_edges,
            "took_ms": int((time.time() - t0) * 1000)}

        # done -------------------------------------------------------------
        result["extraction_deferred"] = deferred
        _set_stage(job_id, "done", 1.0,
                   "Готово: документ в поиске и в графе."
                   + (" Извлечение знаний отложено (нет LLM)." if deferred else ""),
                   result)
    except Exception as e:  # noqa: BLE001
        import traceback
        _set_stage(job_id, "failed", result.get("progress", 0.0) or 0.0,
                   f"Ошибка: {e}", result, error=traceback.format_exc()[:2000])
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _write_upload_files(doc_id: str, doc: dict, chunk_rows: List[dict]) -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / f"{doc_id}.doc.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with open(UPLOADS_DIR / f"{doc_id}.chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunk_rows:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def _preserve_existing(session, nodes: List[dict]) -> None:
    """Union each fragment node with the graph's current state so the loader's
    full-overwrite SET keeps pre-existing provenance instead of clobbering it.

    Merges source_docs (union), confidence (max), aliases (union) and props
    (existing ∪ fragment; fragment wins on key conflicts)."""
    ids = [n["id"] for n in nodes]
    if not ids:
        return
    existing: Dict[str, dict] = {}
    for r in session.run(
        "MATCH (n:Entity) WHERE n.id IN $ids "
        "RETURN n.id AS id, n.source_docs AS sd, n.confidence AS conf, "
        "n.aliases AS al, n.props_json AS pj", ids=ids):
        existing[r["id"]] = {"sd": r["sd"], "conf": r["conf"], "al": r["al"], "pj": r["pj"]}
    for n in nodes:
        ex = existing.get(n["id"])
        if not ex:
            continue
        sd = set(ex["sd"] or []) | set(n.get("source_docs") or [])
        n["source_docs"] = sorted(sd)
        if ex["conf"] is not None:
            n["confidence"] = max(float(n.get("confidence") or 0.0), float(ex["conf"]))
        al = {a for a in (list(ex["al"] or []) + list(n.get("aliases") or [])) if a}
        n["aliases"] = sorted(al)
        if ex["pj"]:
            try:
                old_props = json.loads(ex["pj"])
                merged = {**old_props, **(n.get("props") or {})}
                n["props"] = {k: v for k, v in merged.items() if v is not None}
            except Exception:  # noqa: BLE001
                pass


def _augment_pub_node(gb, pub_id: str, doc: dict) -> None:
    n = gb.nodes.get(pub_id)
    if not n:
        return
    n["name"] = doc.get("title") or n["name"]
    props = n.setdefault("props", {})
    props.update({
        "doc_id": doc["doc_id"], "title": doc.get("title"), "year": doc.get("year"),
        "section": doc.get("section"), "source_type": doc.get("source_type"),
        "geography": doc.get("geography_hint"), "filename": doc.get("filename"),
        "lang": doc.get("lang"), "n_chunks": doc.get("n_chunks"),
        "ingested_at": doc.get("ingested_at"), "uploaded": True,
    })
    props = {k: v for k, v in props.items() if v is not None}
    n["props"] = props


# ------------------------------------------------------------------- entry API
def submit(data: bytes, filename: str) -> dict:
    """Persist the upload, dedup by sha256, and start background processing.

    Returns {job_id, doc_id, cached, stage}. If the same bytes were already
    processed to `done`, returns that job (cached stages/result)."""
    init()
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ValueError(
            f"unsupported file type {ext!r}; supported: {sorted(SUPPORTED_EXT)}")
    sha = _sha256_bytes(data)

    # dedup: reuse the last successful job for these exact bytes
    with _conn() as c:
        prev = c.execute(
            "SELECT job_id, doc_id FROM jobs WHERE sha256=? AND stage='done' "
            "ORDER BY created_at DESC LIMIT 1", (sha,)).fetchone()
    if prev:
        return {"job_id": prev["job_id"], "doc_id": prev["doc_id"],
                "cached": True, "stage": "done"}

    doc_id = "up_" + sha[:12]
    job_id = "job_" + uuid.uuid4().hex[:12]
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = UPLOADS_DIR / f"_incoming_{job_id}{ext}"
    tmp_path.write_bytes(data)

    ts = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO jobs (job_id, sha256, doc_id, filename, stage, progress, "
            "detail, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, sha, doc_id, filename, "queued", 0.0,
             "Задача принята, обработка запускается…", ts, ts))
        c.execute(
            "INSERT OR REPLACE INTO docs (sha256, doc_id, job_id, filename, created_at) "
            "VALUES (?,?,?,?,?)", (sha, doc_id, job_id, filename, ts))

    th = threading.Thread(target=_process,
                          args=(job_id, tmp_path, doc_id, sha, filename, ext),
                          daemon=True)
    th.start()
    return {"job_id": job_id, "doc_id": doc_id, "cached": False, "stage": "queued"}
