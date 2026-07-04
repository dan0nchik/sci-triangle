"""One-off maintenance: mark documents that contain oversized chunks
(> max_tokens) as stale in the manifest so the next `python -m ingest`
run re-extracts and re-chunks them with the current chunker.

Usage:  python -m ingest.fixup_oversized [max_tokens=1400]
"""
from __future__ import annotations

import sys

from . import config
from .util import read_jsonl, write_jsonl, log


def main() -> int:
    max_tokens = int(sys.argv[1]) if len(sys.argv) > 1 else config.MAX_CHUNK_TOKENS
    max_chars = 6000
    bad_docs: set[str] = set()
    for c in read_jsonl(config.CHUNKS_PATH):
        if c.get("n_tokens", 0) > max_tokens or len(c.get("text", "")) > max_chars:
            bad_docs.add(c["doc_id"])
    if not bad_docs:
        log("no oversized chunks found")
        return 0
    log(f"{len(bad_docs)} documents contain chunks > {max_tokens} tokens")

    manifest = list(read_jsonl(config.MANIFEST_PATH))
    n = 0
    for m in manifest:
        if m.get("doc_id") in bad_docs and m.get("docstatus") == "ok":
            m["docstatus"] = "stale"
            n += 1
    write_jsonl(config.MANIFEST_PATH, manifest)
    log(f"marked {n} manifest rows stale — rerun `python -m ingest --wave N`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
