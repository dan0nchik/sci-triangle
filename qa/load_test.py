#!/usr/bin/env python3
"""sci-tangle — нагрузочный тест (F4): N параллельных запросов к /api/search.

Цель из PLAN.md: 20 параллельных запросов, p95 ≤ 5 с.

Запуск:
  .venv-f/bin/python qa/load_test.py                 # 20 параллельных, 1 волна
  .venv-f/bin/python qa/load_test.py --n 20 --waves 2
  QA_API_BASE=http://localhost:8001 .venv-f/bin/python qa/load_test.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent


def _pctl(vals, p):
    vals = sorted(vals)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


async def one(client: httpx.AsyncClient, base: str, query: str):
    t0 = time.time()
    try:
        r = await client.post(f"{base}/api/search", json={"query": query}, timeout=120)
        ok = r.status_code == 200
        code = r.status_code
    except Exception as e:
        ok, code = False, type(e).__name__
    return {"query": query[:60], "ok": ok, "code": code,
            "latency_ms": round((time.time() - t0) * 1000, 1)}


async def run(base: str, n: int, waves: int):
    cases = yaml.safe_load((ROOT / "eval_set.yaml").read_text(encoding="utf-8"))["queries"]
    # разнообразные запросы (не один и тот же — иначе кэш всё скроет)
    queries = [c["query"] for c in cases if not c["expected"].get("expect_empty")]
    results = []
    async with httpx.AsyncClient(trust_env=False) as client:
        for w in range(waves):
            batch = [queries[(w * n + i) % len(queries)] for i in range(n)]
            t0 = time.time()
            res = await asyncio.gather(*[one(client, base, q) for q in batch])
            wall = round((time.time() - t0) * 1000, 1)
            results.extend(res)
            lat = [r["latency_ms"] for r in res if r["ok"]]
            print(f"волна {w + 1}/{waves}: {sum(r['ok'] for r in res)}/{n} ok, "
                  f"wall={wall} мс, p50={_pctl(lat, .5)} p95={_pctl(lat, .95)} мс")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="параллельных запросов в волне")
    ap.add_argument("--waves", type=int, default=1)
    ap.add_argument("--base", default=os.environ.get("QA_API_BASE", "http://localhost:8000"))
    args = ap.parse_args()

    results = asyncio.run(run(args.base.rstrip("/"), args.n, args.waves))
    ok_lat = [r["latency_ms"] for r in results if r["ok"]]
    n_fail = sum(1 for r in results if not r["ok"])
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": args.base, "parallel": args.n, "waves": args.waves,
        "total": len(results), "failed": n_fail,
        "p50_ms": _pctl(ok_lat, .5), "p95_ms": _pctl(ok_lat, .95),
        "max_ms": max(ok_lat) if ok_lat else None,
        "mean_ms": round(statistics.mean(ok_lat), 1) if ok_lat else None,
        "target_p95_le_5000": (_pctl(ok_lat, .95) or 9e9) <= 5000,
    }
    print("\n=== LOAD SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    out = ROOT / "reports" / f"load_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {out}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
