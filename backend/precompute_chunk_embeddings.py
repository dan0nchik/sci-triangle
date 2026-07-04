"""Versioned precompute of chunk doc-embeddings via the Embeddings-Gateway.

Any embedding SPACE (yandex-256, e5-large, …) with one flag: `--space`. Output is
namespaced per space so different models never collide:

    graph/embeddings/{space_id}/chunk_embeddings.npy   [N, dim] float32
    graph/embeddings/{space_id}/chunk_ids.json         [{chunk_id, doc_id}] row order
    graph/embeddings/{space_id}/meta.json              {space, model, dim, created, n, src}

Back-compat: space_id == "yandex-256" ALSO mirrors to the legacy flat path
(graph/embeddings/chunk_embeddings.npy) unless --no-legacy, so a running backend
that still points at the flat path keeps working.

Robustness (kept from the Yandex-only version):
  * TRUNCATE every chunk to --trunc chars (giant table-dump chunks can't blow the
    model's token limit).
  * PER-BATCH ERROR ISOLATION: on a batch failure, retry per-text; a single bad text
    can't poison the whole batch. Last resort = deterministic hash vector (logged).
  * RESUME: reuses the existing prefix if chunk_ids match (chunk order == chunks.jsonl).
  * Incremental save (npy + ids + meta) every batch — checkpoint tests can read a
    growing precompute.

CLI:
  ../.venv-c/bin/python precompute_chunk_embeddings.py --space e5-large \
      --input ../corpus/chunks.jsonl --trunc 1800 --batch 64
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "shared"))
from shared import embeddings_gateway as gw  # noqa: E402

OUT_ROOT = _ROOT / "graph" / "embeddings"


def _fallback_vec(text: str, dim: int) -> list[float]:
    import hashlib
    h = hashlib.sha256(text.encode("utf-8")).digest()
    v = np.frombuffer((h * (dim // len(h) + 1))[:dim], dtype=np.uint8).astype(np.float32)
    v = v / (np.linalg.norm(v) or 1.0)
    return v.tolist()


def _embed_batch(texts: list[str], space: str, dim: int) -> list[list[float]]:
    try:
        return gw.embed_texts(texts, kind="doc", space=space)
    except Exception as e:  # noqa: BLE001 — isolate the poison chunk
        print(f"[warn] batch failed ({e!r}); falling back per-text", flush=True)
        out = []
        for t in texts:
            try:
                out.append(gw.embed_texts([t], kind="doc", space=space)[0])
            except Exception:  # noqa: BLE001
                try:
                    out.append(gw.embed_texts([t[:1200]], kind="doc", space=space)[0])
                except Exception as e2:  # noqa: BLE001
                    print(f"[warn] per-text embed failed ({e2!r}); hash fallback", flush=True)
                    out.append(_fallback_vec(t, dim))
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="yandex-256", help="embedding space id (SPACES registry)")
    ap.add_argument("--input", default=str(_ROOT / "corpus" / "chunks.jsonl"))
    ap.add_argument("--trunc", type=int, default=1800)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--restart", action="store_true", help="ignore existing output")
    ap.add_argument("--no-legacy", action="store_true",
                    help="do not mirror yandex-256 to the flat legacy path")
    ap.add_argument("--limit", type=int, default=0, help="only embed first N chunks (checkpoint)")
    args = ap.parse_args()

    sp = gw.get_space(args.space)
    dim = sp.dim
    out_dir = OUT_ROOT / args.space
    out_dir.mkdir(parents=True, exist_ok=True)
    NPY = out_dir / "chunk_embeddings.npy"
    IDS = out_dir / "chunk_ids.json"
    META = out_dir / "meta.json"
    legacy_npy = OUT_ROOT / "chunk_embeddings.npy"
    legacy_ids = OUT_ROOT / "chunk_ids.json"
    mirror_legacy = (args.space == "yandex-256") and not args.no_legacy

    rows = [json.loads(l) for l in Path(args.input).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    if args.limit:
        rows = rows[: args.limit]
    ids = [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"]} for r in rows]
    texts = [(r.get("text") or "")[: args.trunc] for r in rows]
    n = len(rows)

    def _save(vecs_list):
        arr = np.array(vecs_list, dtype=np.float32)
        np.save(NPY, arr)
        json.dump(ids[: len(vecs_list)], open(IDS, "w", encoding="utf-8"), ensure_ascii=False)
        meta = sp.meta()
        meta.update({"created": datetime.now(timezone.utc).isoformat(),
                     "n": len(vecs_list), "n_total": n})
        json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        if mirror_legacy:
            np.save(legacy_npy, arr)
            json.dump(ids[: len(vecs_list)], open(legacy_ids, "w", encoding="utf-8"),
                      ensure_ascii=False)

    # resume
    vecs: list[list[float]] = []
    start = 0
    if not args.restart and NPY.exists() and IDS.exists():
        try:
            prev_ids = json.load(open(IDS, encoding="utf-8"))
            prev = np.load(NPY)
            k = len(prev_ids)
            if k <= n and prev.shape[1] == dim and all(
                    prev_ids[i]["chunk_id"] == ids[i]["chunk_id"] for i in range(min(k, 50))):
                vecs = [row.tolist() for row in prev[:k]]
                start = k
                print(f"[resume] reusing {k} existing {args.space} embeddings", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[resume] could not reuse ({e!r}); starting fresh", flush=True)

    print(f"[space] {args.space} provider={sp.provider} model={sp.model} dim={dim} "
          f"| n={n} start={start}", flush=True)

    import time
    t_run = time.time()
    for i in range(start, n, args.batch):
        part = texts[i: i + args.batch]
        t0 = time.time()
        vecs.extend(_embed_batch(part, args.space, dim))
        _save(vecs)
        dt = time.time() - t0
        rate = len(part) / dt if dt else 0.0
        overall = (len(vecs) - start) / (time.time() - t_run + 1e-9)
        print(f"[emb] {len(vecs)}/{n} | +{len(part)} in {dt:.1f}s "
              f"({rate:.1f} ch/s batch, {overall:.1f} ch/s avg)", flush=True)

    print(f"[done] saved {len(vecs)}x{dim} -> {NPY}", flush=True)


if __name__ == "__main__":
    main()
