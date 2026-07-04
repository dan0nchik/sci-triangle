"""Elasticsearch index management + loaders (contract PLAN.md §4.1/§4.3).

Creates three indexes:
  * chunks     - full text with Russian + English analyzers, doc_id/year/section/geography/lang
  * documents  - document facets for aggregations & filtering
  * conditions - numeric condition fields (param/op/value/unit) for range queries

Also provides helpers to bulk-index corpus chunks/documents and graph conditions.
Safe to run when corpus files are absent (fixtures still index conditions from the graph).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch, helpers

from config import ES_CHUNKS, ES_CONDITIONS, ES_DOCUMENTS, ES_URL, FIXTURES_DIR, REPO_ROOT

# --- analyzer settings: multi-field text with ru + en morphology ---
_TEXT_ANALYSIS = {
    "analysis": {
        "char_filter": {
            # filenames join words with _ and . («Куба_ПунтаГорда_2018.docx») — the
            # standard tokenizer would keep that as ONE token; split explicitly.
            "fname_seps": {"type": "mapping",
                           "mappings": ["_ => ' '", ". => ' '", "- => ' '"]},
        },
        "filter": {
            "russian_stop": {"type": "stop", "stopwords": "_russian_"},
            "russian_stemmer": {"type": "stemmer", "language": "russian"},
            "english_stop": {"type": "stop", "stopwords": "_english_"},
            "english_stemmer": {"type": "stemmer", "language": "english"},
        },
        "analyzer": {
            "ru_analyzer": {
                "tokenizer": "standard",
                "filter": ["lowercase", "russian_stop", "russian_stemmer"],
            },
            "en_analyzer": {
                "tokenizer": "standard",
                "filter": ["lowercase", "english_stop", "english_stemmer"],
            },
            "fname_ru": {
                "tokenizer": "standard",
                "char_filter": ["fname_seps"],
                "filter": ["lowercase", "russian_stop", "russian_stemmer"],
            },
        },
    }
}

CHUNKS_MAPPING = {
    "settings": _TEXT_ANALYSIS,
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "seq": {"type": "integer"},
            # text analyzed both ways via sub-fields
            "text": {
                "type": "text",
                "analyzer": "ru_analyzer",
                "fields": {"en": {"type": "text", "analyzer": "en_analyzer"}},
            },
            "section": {"type": "keyword"},
            "section_title": {"type": "text"},
            "year": {"type": "integer"},
            "geography": {"type": "keyword"},
            "lang": {"type": "keyword"},
            "sensitivity": {"type": "keyword"},
            "page_from": {"type": "integer"},
            "page_to": {"type": "integer"},
        }
    },
}

DOCUMENTS_MAPPING = {
    "settings": _TEXT_ANALYSIS,
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "ru_analyzer",
                      "fields": {"en": {"type": "text", "analyzer": "en_analyzer"},
                                 "raw": {"type": "keyword"}}},
            # real corpus: FILENAME often carries the true document title
            # («Наилучшие доступные технологии … .docx»), while `title` is OCR junk
            # («УТВЕРЖДАЮ»). Indexed for the doc-level lexical branch (agent R).
            "filename": {"type": "text", "analyzer": "fname_ru",
                         "fields": {"en": {"type": "text", "analyzer": "en_analyzer"}}},
            "section": {"type": "keyword"},
            "journal": {"type": "keyword"},
            "year": {"type": "integer"},
            "lang": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "geography": {"type": "keyword"},
            "sensitivity": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "n_pages": {"type": "integer"},
            "n_chunks": {"type": "integer"},
        }
    },
}

CONDITIONS_MAPPING = {
    "settings": _TEXT_ANALYSIS,
    "mappings": {
        "properties": {
            "cond_id": {"type": "keyword"},
            "process_id": {"type": "keyword"},
            "process_name": {"type": "text", "analyzer": "ru_analyzer"},
            "param": {"type": "keyword"},
            "param_text": {"type": "text", "analyzer": "ru_analyzer"},
            "op": {"type": "keyword"},
            "value": {"type": "double"},
            "value2": {"type": "double"},
            "unit": {"type": "keyword"},
            "qualitative": {"type": "text", "analyzer": "ru_analyzer"},
            "source_doc": {"type": "keyword"},
            "chunk_id": {"type": "keyword"},
            "year": {"type": "integer"},
            "geography": {"type": "keyword"},
        }
    },
}

INDEXES = {
    ES_CHUNKS: CHUNKS_MAPPING,
    ES_DOCUMENTS: DOCUMENTS_MAPPING,
    ES_CONDITIONS: CONDITIONS_MAPPING,
}


def es_client() -> Elasticsearch:
    return Elasticsearch(ES_URL, request_timeout=30)


def create_indexes(es: Elasticsearch, recreate: bool = False) -> List[str]:
    created = []
    for name, body in INDEXES.items():
        if es.indices.exists(index=name):
            if recreate:
                es.indices.delete(index=name)
            else:
                continue
        es.indices.create(index=name, **body)
        created.append(name)
    return created


def _read_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


INTERNAL_SECTIONS = {"Статьи", "Доклады"}


def _sensitivity(d: dict) -> str:
    """ABAC attribute: explicit `sensitivity` wins; else heuristic by section."""
    if d.get("sensitivity"):
        return d["sensitivity"]
    return "internal" if d.get("section") in INTERNAL_SECTIONS else "public"


def index_documents(es: Elasticsearch, docs: Iterable[dict]) -> int:
    actions = []
    for d in docs:
        actions.append({
            "_index": ES_DOCUMENTS,
            "_id": d["doc_id"],
            "_source": {
                "doc_id": d["doc_id"], "title": d.get("title"),
                "filename": d.get("filename"),
                "section": d.get("section"), "journal": d.get("journal"),
                "year": d.get("year"), "lang": d.get("lang"),
                "source_type": d.get("source_type"),
                "geography": d.get("geography_hint") or d.get("geography"),
                "sensitivity": _sensitivity(d),
                "ingested_at": d.get("ingested_at"),
                "n_pages": d.get("n_pages"), "n_chunks": d.get("n_chunks"),
            },
        })
    if not actions:
        return 0
    helpers.bulk(es, actions)
    return len(actions)


def index_chunks(es: Elasticsearch, chunks: Iterable[dict],
                 doc_meta: Optional[Dict[str, dict]] = None) -> int:
    doc_meta = doc_meta or {}
    actions = []
    for c in chunks:
        meta = doc_meta.get(c.get("doc_id"), {})
        actions.append({
            "_index": ES_CHUNKS,
            "_id": c["chunk_id"],
            "_source": {
                "chunk_id": c["chunk_id"], "doc_id": c.get("doc_id"),
                "seq": c.get("seq"), "text": c.get("text"),
                "section": c.get("section") or meta.get("section"),
                "section_title": c.get("section_title"),
                "year": c.get("year") or meta.get("year"),
                "geography": c.get("geography") or meta.get("geography_hint"),
                "lang": c.get("lang"),
                "sensitivity": _sensitivity(meta) if meta else None,
                "page_from": c.get("page_from"), "page_to": c.get("page_to"),
            },
        })
    if not actions:
        return 0
    helpers.bulk(es, actions)
    return len(actions)


def index_conditions(es: Elasticsearch, conditions: Iterable[dict]) -> int:
    actions = []
    for c in conditions:
        actions.append({"_index": ES_CONDITIONS, "_id": c["cond_id"], "_source": c})
    if not actions:
        return 0
    helpers.bulk(es, actions)
    return len(actions)


def conditions_from_graph(nodes_path: Path, edges_path: Path) -> List[dict]:
    """Derive `conditions` docs from graph: operates_at_condition edges + Condition nodes."""
    nodes = {n["id"]: n for n in _read_jsonl(nodes_path)}
    out: List[dict] = []
    for e in _read_jsonl(edges_path):
        if e.get("type") != "operates_at_condition":
            continue
        props = e.get("props") or {}
        cond_node = nodes.get(e["dst"], {})
        cond_props = cond_node.get("props") or {}
        proc_node = nodes.get(e["src"], {})
        out.append({
            "cond_id": e.get("id") or f"{e['src']}|{e['dst']}",
            "process_id": e["src"],
            "process_name": proc_node.get("name"),
            "param": props.get("param") or cond_props.get("param"),
            "param_text": props.get("param") or cond_props.get("param"),
            "op": props.get("op") or cond_props.get("op"),
            "value": props.get("value") if props.get("value") is not None
                     else cond_props.get("value"),
            "value2": props.get("value2") if props.get("value2") is not None
                      else cond_props.get("value2"),
            "unit": props.get("unit") or cond_props.get("unit"),
            "qualitative": cond_props.get("qualitative"),
            "source_doc": e.get("source_doc"),
            "chunk_id": e.get("chunk_id"),
            "geography": (nodes.get(e["src"], {}).get("props") or {}).get("geography"),
        })
    return out


def build_all(recreate: bool = False, use_fixtures: bool = False) -> dict:
    es = es_client()
    created = create_indexes(es, recreate=recreate)

    if use_fixtures:
        nodes_path = FIXTURES_DIR / "nodes.jsonl"
        edges_path = FIXTURES_DIR / "edges.jsonl"
        docs_path = FIXTURES_DIR / "documents.jsonl"
        chunks_path = FIXTURES_DIR / "chunks.jsonl"
    else:
        nodes_path = REPO_ROOT / "graph" / "nodes.jsonl"
        edges_path = REPO_ROOT / "graph" / "edges.jsonl"
        docs_path = REPO_ROOT / "corpus" / "documents.jsonl"
        chunks_path = REPO_ROOT / "corpus" / "chunks.jsonl"

    docs = list(_read_jsonl(docs_path))
    doc_meta = {d["doc_id"]: d for d in docs}
    n_docs = index_documents(es, docs)
    n_chunks = index_chunks(es, _read_jsonl(chunks_path), doc_meta)
    n_conds = index_conditions(es, conditions_from_graph(nodes_path, edges_path))
    es.indices.refresh(index=list(INDEXES.keys()))
    return {"created_indexes": created, "documents": n_docs,
            "chunks": n_chunks, "conditions": n_conds}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--fixtures", action="store_true")
    args = ap.parse_args()
    print(build_all(recreate=args.recreate, use_fixtures=args.fixtures))


if __name__ == "__main__":
    main()
