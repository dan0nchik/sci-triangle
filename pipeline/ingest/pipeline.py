"""A5/A6: orchestration, manifest, idempotency, wave runs.

Produces corpus/manifest.jsonl (one row per source file, with docstatus for
idempotent reruns), corpus/documents.jsonl and corpus/chunks.jsonl
(contract §4.1).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import config, metadata, textextract, ocr, chunker
from .scan import SourceFile, scan
from .util import log, sha256_file, read_jsonl, write_jsonl

# top-level data dirs relevant to each wave (to avoid scanning everything)
WAVE_TOPDIRS = {
    1: ["Обзоры", "Статьи", "Доклады"],
    2: ["Журналы"],
    3: ["Материалы конференций"],
    4: ["Журналы", "Материалы конференций"],
}


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


class Corpus:
    """In-memory view of the three jsonl outputs, loaded for idempotent updates."""

    def __init__(self) -> None:
        # manifest keyed by sha256
        self.manifest: dict[str, dict] = {}
        # documents keyed by doc_id
        self.documents: dict[str, dict] = {}
        # chunks keyed by doc_id -> list
        self.chunks: dict[str, list[dict]] = {}
        self._max_id = 0
        self._load()

    def _load(self) -> None:
        for row in read_jsonl(config.MANIFEST_PATH):
            self.manifest[row["sha256"]] = row
            did = row.get("doc_id")
            if did:
                self._max_id = max(self._max_id, int(did[1:]))
        for row in read_jsonl(config.DOCUMENTS_PATH):
            self.documents[row["doc_id"]] = row
        for row in read_jsonl(config.CHUNKS_PATH):
            self.chunks.setdefault(row["doc_id"], []).append(row)

    def next_doc_id(self, sha: str) -> str:
        existing = self.manifest.get(sha, {}).get("doc_id")
        if existing:
            return existing
        self._max_id += 1
        return f"d{self._max_id:06d}"

    def flush(self) -> None:
        config.ensure_dirs()
        write_jsonl(config.MANIFEST_PATH, self.manifest.values())
        write_jsonl(config.DOCUMENTS_PATH, self.documents.values())
        all_chunks = [c for lst in self.chunks.values() for c in lst]
        write_jsonl(config.CHUNKS_PATH, all_chunks)


def _process_file(sf: SourceFile, corpus: Corpus, use_ocr: bool) -> dict:
    """Process one source file -> manifest row (also writes doc+chunks into corpus)."""
    abs_path = sf.abs_path
    meta = metadata.derive(sf.rel_path)
    ext = abs_path.suffix.lower()

    # unsupported / archive-warning placeholder
    if sf.warnings and ext not in config.SUPPORTED_TEXT_EXT:
        sha = sha256_file(abs_path)
        return _mk_manifest(sha, sf, meta, None, "skipped",
                            "; ".join(sf.warnings))

    sha = sha256_file(abs_path)

    # idempotency: already processed OK with a document present -> skip
    prev = corpus.manifest.get(sha)
    if prev and prev.get("docstatus") == "ok" and prev.get("doc_id") in corpus.documents:
        return prev

    doc_id = corpus.next_doc_id(sha)

    try:
        res = textextract.extract(abs_path)
    except Exception as e:  # noqa: BLE001
        return _mk_manifest(sha, sf, meta, doc_id, "failed",
                            f"extract error: {e}")

    warnings = list(sf.warnings) + list(res.warnings)
    method = res.method

    # OCR fallback for thin/empty pdf pages
    if use_ocr and res.ocr_pages:
        try:
            ocr_map, ocr_warn = ocr.ocr_pages(abs_path, res.ocr_pages)
            warnings += ocr_warn
            if ocr_map:
                method = "ocr_docling"
                pages = []
                for pno, txt in res.pages:
                    if pno in ocr_map and len(txt.strip()) < config.OCR_MIN_TEXT_CHARS:
                        pages.append((pno, ocr_map[pno]))
                    else:
                        pages.append((pno, txt))
                res.pages = pages
        except Exception as e:  # noqa: BLE001
            warnings.append(f"ocr error: {e}")

    chunks = chunker.chunk_document(res.pages)
    if not chunks:
        return _mk_manifest(sha, sf, meta, doc_id, "failed",
                            "no text extracted (0 chunks)", warnings)

    # doc-level language
    langs = {c.lang for c in chunks}
    if langs == {"ru"}:
        doc_lang = "ru"
    elif langs == {"en"}:
        doc_lang = "en"
    else:
        doc_lang = "mixed"

    title = _title(abs_path, chunks)

    doc = {
        "doc_id": doc_id,
        "path": sf.rel_path,
        "filename": abs_path.name,
        "title": title,
        "section": meta["section"],
        "journal": meta["journal"],
        "year": meta["year"],
        "lang": doc_lang,
        "source_type": meta["source_type"],
        "geography_hint": meta["geography_hint"],
        "n_pages": res.n_pages,
        "n_chunks": len(chunks),
        "extract_method": method,
        "status": "ok",
        "wave": meta["wave"],
        "ingested_at": _now(),
    }
    corpus.documents[doc_id] = doc
    corpus.chunks[doc_id] = [{
        "chunk_id": f"{doc_id}_c{c.seq:04d}",
        "doc_id": doc_id,
        "seq": c.seq,
        "text": c.text,
        "n_tokens": c.n_tokens,
        "page_from": c.page_from,
        "page_to": c.page_to,
        "lang": c.lang,
        "section_title": c.section_title,
    } for c in chunks]

    return _mk_manifest(sha, sf, meta, doc_id, "ok",
                        "; ".join(warnings) if warnings else "",
                        extra={"n_chunks": len(chunks), "extract_method": method})


def _mk_manifest(sha, sf, meta, doc_id, docstatus, error, warnings=None, extra=None):
    row = {
        "sha256": sha,
        "path": sf.rel_path,
        "abs_path": str(sf.abs_path),
        "origin": sf.origin,
        "archive_rel": sf.archive_rel,
        "doc_id": doc_id,
        "section": meta["section"],
        "wave": meta["wave"],
        "docstatus": docstatus,
        "error": error or "",
        "updated_at": _now(),
    }
    if extra:
        row.update(extra)
    return row


def _title(path: Path, chunks) -> str:
    # prefer first heading-like section title, else filename stem
    for c in chunks[:3]:
        if c.section_title:
            return c.section_title[:200]
    stem = path.stem
    stem = stem.strip()
    return stem[:200] or path.name


def run(waves: list[int], limit: int | None = None, use_ocr: bool = True) -> dict:
    config.ensure_dirs()
    corpus = Corpus()

    topdirs: set[str] = set()
    for w in waves:
        topdirs.update(WAVE_TOPDIRS.get(w, []))

    log(f"Scanning data tree for waves {waves} (dirs: {sorted(topdirs)}) ...")
    all_files: list[SourceFile] = []
    for td in sorted(topdirs):
        root = config.DATA_ROOT / td
        files = scan(root, rel_prefix=td)
        all_files.extend(files)
    log(f"Found {len(all_files)} candidate files after archive expansion.")

    # filter to requested waves via per-file metadata
    targets: list[SourceFile] = []
    for sf in all_files:
        m = metadata.derive(sf.rel_path)
        if m["wave"] in waves:
            targets.append(sf)
    log(f"{len(targets)} files match requested waves.")

    if limit:
        targets = targets[:limit]

    stats = {"ok": 0, "failed": 0, "skipped": 0, "cached": 0,
             "ocr_docs": 0, "chunks": 0, "tokens": 0}
    n = len(targets)
    for i, sf in enumerate(targets, 1):
        name = Path(sf.rel_path).name
        try:
            row = _process_file(sf, corpus, use_ocr)
        except Exception as e:  # noqa: BLE001
            sha = sha256_file(sf.abs_path)
            row = _mk_manifest(sha, sf, metadata.derive(sf.rel_path), None,
                               "failed", f"unhandled: {e}")
        corpus.manifest[row["sha256"]] = row
        status = row["docstatus"]
        stats[status] = stats.get(status, 0) + 1
        if status == "ok" and row.get("extract_method") == "ocr_docling":
            stats["ocr_docs"] += 1
        did = row.get("doc_id")
        if status == "ok" and did in corpus.chunks:
            nch = len(corpus.chunks[did])
            stats["chunks"] += nch
            stats["tokens"] += sum(c["n_tokens"] for c in corpus.chunks[did])
        if i % 10 == 0 or i == n:
            log(f"  [{i}/{n}] {status:7s} {name[:70]}")
        # periodic checkpoint
        if i % 25 == 0:
            corpus.flush()

    corpus.flush()
    log(f"Done. ok={stats['ok']} failed={stats['failed']} "
        f"skipped={stats['skipped']} ocr_docs={stats['ocr_docs']} "
        f"chunks={stats['chunks']} ~tokens={stats['tokens']}")
    return stats
