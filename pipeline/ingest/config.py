"""Central configuration and path constants for the ingest pipeline (direction A)."""
from __future__ import annotations

import os
from pathlib import Path

# --- Repo layout -----------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data" / "Задача 2. Научный клубок" / "Источники информации"
CORPUS_DIR = REPO_ROOT / "corpus"

MANIFEST_PATH = CORPUS_DIR / "manifest.jsonl"
DOCUMENTS_PATH = CORPUS_DIR / "documents.jsonl"
CHUNKS_PATH = CORPUS_DIR / "chunks.jsonl"
README_PATH = CORPUS_DIR / "README.md"

# Working dirs (kept inside corpus/, gitignored)
EXTRACT_DIR = CORPUS_DIR / "_extracted"      # archive extraction target
OCR_CACHE_DIR = CORPUS_DIR / "ocr_cache"     # sha256 -> markdown
STATE_DIR = CORPUS_DIR / "_state"            # id counter etc.

# --- Chunking --------------------------------------------------------------
CHARS_PER_TOKEN = 3.5            # russian estimate
CHUNK_TOKENS = 1000
OVERLAP_TOKENS = 100
CHUNK_CHARS = int(CHUNK_TOKENS * CHARS_PER_TOKEN)      # ~3500
OVERLAP_CHARS = int(OVERLAP_TOKENS * CHARS_PER_TOKEN)  # ~350
MIN_CHUNK_CHARS = 120           # drop tiny trailing junk chunks
MAX_CHUNK_TOKENS = 1200         # hard cap on chunk size
MAX_CHUNK_CHARS = int(MAX_CHUNK_TOKENS * CHARS_PER_TOKEN)  # ~4200

# --- OCR -------------------------------------------------------------------
OCR_API_URL = os.environ.get("OCR_API_URL", "http://ithse.ru:1170").rstrip("/")
OCR_CONVERT_ENDPOINT = OCR_API_URL + "/api/v1/docling/convert"
OCR_MIN_TEXT_CHARS = 50         # page with < this many chars -> needs OCR
OCR_CONCURRENCY = 3
OCR_RETRIES = 3
OCR_TIMEOUT = 180               # seconds per request
OCR_MAX_PAGES_PER_BATCH = 20    # pages per mini-pdf sent to service

# --- Archive safety --------------------------------------------------------
ARCHIVE_UNPACK_LIMIT = 2 * 1024 * 1024 * 1024   # 2 GB per archive (zip bomb guard)
ARCHIVE_MAX_DEPTH = 3                             # nested archive depth

# --- Extraction ------------------------------------------------------------
SUPPORTED_TEXT_EXT = {".pdf", ".docx", ".docm", ".doc", ".pptx", ".xls", ".xlsx"}
ARCHIVE_EXT = {".zip", ".rar", ".7z"}

# extensions we deliberately skip (images / binaries with no text value)
SKIP_EXT = {".gif", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".ds_store"}


def ensure_dirs() -> None:
    for d in (CORPUS_DIR, EXTRACT_DIR, OCR_CACHE_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
