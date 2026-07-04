#!/usr/bin/env python3
"""Answer-cache warmer (Answer-Cache agent).

Runs a list of representative queries through /api/search WITHOUT skip_cache so the
answer-cache (backend/answer_cache.sqlite) is populated before a demo / defense.
After warming, the same questions return instantly (`cached=true`, <300 ms).

Query list = the 4 golden themes + the top of qa/eval_set.yaml (~15 total). A second
verification pass confirms every warmed query now hits the cache.

Usage:
  ../.venv-c/bin/python backend/warm_cache.py
  QA_API_BASE=http://localhost:8000 python backend/warm_cache.py --n 15
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parent.parent
EVAL_SET = REPO / "qa" / "eval_set.yaml"

# The 4 golden themes (kept explicit so warming works even without eval_set.yaml).
GOLDEN = [
    "Методы обессоливания воды для обогатительной фабрики: сульфаты и хлориды "
    "200–300 мг/л, сухой остаток не выше 1000 мг/дм³",
    "Циркуляция католита при электроэкстракции никеля: технические решения и "
    "оптимальная скорость потока",
    "Эксперименты и публикации по распределению золота, серебра и МПГ между "
    "штейном и шлаком за последние 5 лет",
    "Закачка шахтных вод в глубокие горизонты: сравнение российской и зарубежной "
    "практики и технико-экономические показатели",
]


def load_queries(n: int) -> list[str]:
    queries = list(GOLDEN)
    try:
        data = yaml.safe_load(EVAL_SET.read_text(encoding="utf-8"))
        for c in data.get("queries", []):
            q = c.get("query")
            if q and q not in queries:
                queries.append(q)
    except Exception as e:
        print(f"[warn] eval_set unreadable ({e}); warming golden only")
    return queries[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description="Answer-cache warmer")
    ap.add_argument("--base", default=os.environ.get("QA_API_BASE",
                                                      "http://localhost:8000"))
    ap.add_argument("--n", type=int, default=15, help="how many queries to warm")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    client = httpx.Client(trust_env=False, timeout=90)
    try:
        h = client.get(f"{base}/api/health", timeout=10)
        print(f"[ok] API health: {h.json().get('status')}")
    except Exception as e:
        print(f"[FATAL] API недоступен на {base}: {e}")
        return 2

    queries = load_queries(args.n)
    print(f"[warm] {len(queries)} запросов через {base}/api/search\n")

    # pass 1 — populate
    for i, q in enumerate(queries, 1):
        t0 = time.time()
        try:
            r = client.post(f"{base}/api/search", json={"query": q})
            r.raise_for_status()
            j = r.json()
            dt = (time.time() - t0) * 1000
            print(f"  [{i:>2}] warm  {dt:7.0f}ms  cached={j.get('cached')}  "
                  f"{q[:60]}…")
        except Exception as e:
            print(f"  [{i:>2}] ERR   {e}")

    # pass 2 — verify hits
    print("\n[verify] повторный прогон (ожидаем cached=true, <300 ms)\n")
    hits = 0
    for i, q in enumerate(queries, 1):
        t0 = time.time()
        try:
            r = client.post(f"{base}/api/search", json={"query": q})
            r.raise_for_status()
            j = r.json()
            dt = (time.time() - t0) * 1000
            ok = bool(j.get("cached"))
            hits += ok
            flag = "HIT " if ok else "MISS"
            print(f"  [{i:>2}] {flag}  {dt:7.0f}ms  {q[:60]}…")
        except Exception as e:
            print(f"  [{i:>2}] ERR   {e}")

    print(f"\n[done] прогрето: {hits}/{len(queries)} запросов в кэше")
    try:
        cache = client.get(f"{base}/api/stats").json().get("cache", {})
        print(f"[cache] {cache}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
