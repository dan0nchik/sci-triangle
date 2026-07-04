"""Robust precompute of chunk doc-embeddings -> graph/embeddings/ (agent R, task 1).

Improvements over pipeline/extract/embed_chunks.py:
  * TRUNCATE every chunk text to EMBED_TRUNC chars (default 3500 ~ <2048 tokens),
    so a giant document-dump chunk can never exceed the model's token limit.
  * PER-BATCH ERROR ISOLATION: shared.embed() is all-or-nothing per batch; a single
    failing text raises for the whole batch. We wrap each batch and, on failure,
    fall back to per-text embedding (try/except) so one bad chunk never poisons the
    run. Failed texts get a deterministic hash fallback vector and are logged.
  * RESUME: reuses whatever is already in graph/embeddings/ (chunk_ids.json order is
    stable == chunks.jsonl order), skipping already-embedded prefix.
  * Incremental save (npy + ids) every batch.

Kind = "doc" (text-search-doc): chunks live in DOC space; the query is embedded as
"doc" too at retrieval time (doc-doc match, per direction-B finding).

CLI:
  ../.venv-c/bin/python precompute_chunk_embeddings.py \
      --input ../corpus/chunks.jsonl --trunc 3500 --batch 96 --concurrency 4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from shared.yandex_client import embed, USAGE  # noqa: E402

OUT_DIR = _ROOT / "graph" / "embeddings"
NPY = OUT_DIR / "chunk_embeddings.npy"
IDS = OUT_DIR / "chunk_ids.json"

DIM = 256


def _fallback_vec(text: str) -> list[float]:
    """Deterministic hash embedding (never zero) so a failed text stays scorable low."""
    import hashlib
    h = hashlib.sha256(text.encode("utf-8")).digest()
    v = np.frombuffer((h * (DIM // len(h) + 1))[:DIM], dtype=np.uint8).astype(np.float32)
    v = v / (np.linalg.norm(v) or 1.0)
    return v.tolist()


def _embed_batch(texts: list[str], concurrency: int) -> list[list[float]]:
    try:
        return embed(texts, kind="doc", concurrency=concurrency)
    except Exception as e:  # noqa: BLE001 — isolate the poison chunk
        print(f"[warn] batch failed ({e!r}); falling back per-text", flush=True)
        out = []
        for t in texts:
            try:
                out.append(embed([t], kind="doc", concurrency=1)[0])
            except Exception:  # noqa: BLE001 — likely >2048 tokens; retry harder-truncated
                try:
                    out.append(embed([t[:1200]], kind="doc", concurrency=1)[0])
                except Exception as e2:  # noqa: BLE001
                    print(f"[warn] per-text embed failed ({e2!r}); hash fallback", flush=True)
                    out.append(_fallback_vec(t))
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(_ROOT / "corpus" / "chunks.jsonl"))
    ap.add_argument("--trunc", type=int, default=3500)
    ap.add_argument("--batch", type=int, default=96)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--restart", action="store_true", help="ignore existing output")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.input).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    ids = [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"]} for r in rows]
    texts = [(r.get("text") or "")[: args.trunc] for r in rows]
    n = len(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # resume: keep existing prefix if ids match
    vecs: list[list[float]] = []
    start = 0
    if not args.restart and NPY.exists() and IDS.exists():
        try:
            prev_ids = json.load(open(IDS, encoding="utf-8"))
            prev = np.load(NPY)
            k = len(prev_ids)
            if k <= n and all(prev_ids[i]["chunk_id"] == ids[i]["chunk_id"]
                              for i in range(min(k, 50))):
                vecs = [row.tolist() for row in prev[:k]]
                start = k
                print(f"[resume] reusing {k} existing embeddings", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[resume] could not reuse existing ({e!r}); starting fresh", flush=True)

    for i in range(start, n, args.batch):
        part = texts[i: i + args.batch]
        vecs.extend(_embed_batch(part, args.concurrency))
        np.save(NPY, np.array(vecs, dtype=np.float32))
        json.dump(ids[: len(vecs)], open(IDS, "w", encoding="utf-8"), ensure_ascii=False)
        u = USAGE.snapshot()
        print(f"[emb] {len(vecs)}/{n} | emb_toks {u['embedding_tokens']} "
              f"| req {u['embedding_requests']} | 429:{u['rate_limit_hits']} "
              f"| retries {u['retries']}", flush=True)

    print(f"[done] saved {len(vecs)}x{DIM} -> {NPY}", flush=True)


if __name__ == "__main__":
    main()
