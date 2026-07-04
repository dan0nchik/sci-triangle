"""A4/A7/A8: OCR fallback for PDF pages with no/insufficient text layer.

For each page needing OCR we build a single-page mini-PDF, hash its bytes,
consult the on-disk cache (corpus/ocr_cache/<sha>.md), and otherwise POST it
to the docling convert endpoint. Concurrency + retries + disk cache.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from . import config
from .util import log, sha256_bytes


def _cache_path(sha: str) -> Path:
    return config.OCR_CACHE_DIR / f"{sha}.md"


def _single_page_pdf(doc, page_index_0: int) -> bytes:
    import fitz
    out = fitz.open()
    out.insert_pdf(doc, from_page=page_index_0, to_page=page_index_0)
    data = out.tobytes()
    out.close()
    return data


def _post_ocr(pdf_bytes: bytes, name: str) -> tuple[bool, str, str]:
    """Return (success, markdown, error)."""
    files = {"file": (name, pdf_bytes, "application/pdf")}
    data = {"do_ocr": "true"}
    last_err = ""
    for attempt in range(1, config.OCR_RETRIES + 1):
        try:
            r = requests.post(config.OCR_CONVERT_ENDPOINT, files=files, data=data,
                              timeout=config.OCR_TIMEOUT)
            if r.status_code != 200:
                last_err = f"http {r.status_code}"
            else:
                js = r.json()
                if js.get("success"):
                    return True, js.get("markdown") or "", ""
                last_err = js.get("error") or "success=false"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(min(2 ** attempt, 15))
    return False, "", last_err


def ocr_pages(path: Path, page_numbers: list[int]) -> tuple[dict[int, str], list[str]]:
    """OCR the given 1-based *page_numbers* of *path*.

    Returns (mapping page_no -> markdown text, warnings)."""
    import fitz

    if not page_numbers:
        return {}, []
    config.OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    result: dict[int, str] = {}

    # build per-page mini-pdfs + hashes first (cheap, single-threaded)
    jobs: list[tuple[int, str, bytes]] = []  # (page_no, sha, bytes)
    with fitz.open(path) as doc:
        for pno in page_numbers:
            if pno - 1 >= doc.page_count:
                continue
            data = _single_page_pdf(doc, pno - 1)
            sha = sha256_bytes(data)
            cp = _cache_path(sha)
            if cp.exists():
                result[pno] = cp.read_text("utf-8", "replace")
            else:
                jobs.append((pno, sha, data))

    if not jobs:
        return result, warnings

    log(f"    OCR: {len(jobs)} page(s) via docling "
        f"({len(page_numbers) - len(jobs)} cache hit)")

    def _run(job):
        pno, sha, data = job
        ok, md, err = _post_ocr(data, f"{path.stem}_p{pno}.pdf")
        return pno, sha, ok, md, err

    with ThreadPoolExecutor(max_workers=config.OCR_CONCURRENCY) as ex:
        futs = [ex.submit(_run, j) for j in jobs]
        for fut in as_completed(futs):
            pno, sha, ok, md, err = fut.result()
            if ok:
                _cache_path(sha).write_text(md, "utf-8")
                result[pno] = md
            else:
                warnings.append(f"ocr page {pno} failed: {err}")
    return result, warnings
