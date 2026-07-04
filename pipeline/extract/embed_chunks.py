"""
embed_chunks.py — эмбеддинги чанков корпуса в graph/embeddings/ (PLAN B14 helper).

Считает text-search-doc эмбеддинги (256-dim) для чанков и сохраняет:
  graph/embeddings/chunk_embeddings.npy   — float32 матрица [N, 256]
  graph/embeddings/chunk_ids.json         — [{chunk_id, doc_id}] в порядке строк матрицы

Использует sqlite-кэш shared/emb_cache.sqlite (кэш обязателен по запросу координатора).
Конкурентность держим низкой (квота Yandex общая на ключ).

CLI:
  python pipeline/extract/embed_chunks.py --input corpus/chunks.jsonl [--limit N] [--concurrency 3]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import sys

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from shared.yandex_client import embed, USAGE  # noqa: E402

OUT_DIR = _ROOT / "graph" / "embeddings"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(_ROOT / "corpus" / "chunks.jsonl"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.input).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ids = [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"]} for r in rows]
    texts = [r["text"][:2000] for r in rows]  # усечение под лимит модели

    vecs: list[list[float]] = []
    for i in range(0, len(texts), args.batch):
        part = texts[i : i + args.batch]
        vecs.extend(embed(part, kind="doc", concurrency=args.concurrency))
        u = USAGE.snapshot()
        print(f"[emb] {min(i+args.batch,len(texts))}/{len(texts)} | "
              f"emb_toks {u['embedding_tokens']} | 429:{u['rate_limit_hits']}", flush=True)
        # инкрементальное сохранение (устойчивость к прерыванию)
        np.save(OUT_DIR / "chunk_embeddings.npy", np.array(vecs, dtype=np.float32))
        json.dump(ids[: len(vecs)], open(OUT_DIR / "chunk_ids.json", "w", encoding="utf-8"),
                  ensure_ascii=False)

    print(f"[emb] saved {len(vecs)}x{len(vecs[0]) if vecs else 0} -> {OUT_DIR/'chunk_embeddings.npy'}")


if __name__ == "__main__":
    main()
