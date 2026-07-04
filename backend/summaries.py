"""C11 — Pre-computed domain summaries (GraphRAG pattern for fast reviews).

For each process `domain` in the graph, gather its processes + linked assertions and
ask YandexGPT Pro for a compact evidence-grounded summary. Results are written to
`backend/domain_summaries.json` and (best-effort) as :DomainSummary nodes in Neo4j.
`/api/stats` surfaces them, and review-type queries pass the matching domain summary
to synthesis as extra context.

Run:  cd backend && ../.venv-c/bin/python summaries.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

import llm  # noqa: E402
from app import db  # noqa: E402

OUT_PATH = BACKEND / "domain_summaries.json"

_SYS = (
    "Ты — аналитик базы знаний горно-металлургической отрасли. По переданным "
    "процессам и утверждениям домена напиши компактную сводку (3–5 предложений): "
    "какие процессы/технологии охвачены, ключевые числовые результаты, пробелы. "
    "Только на основе переданных данных, на русском, без вступлений."
)


def _domain_payload(domain: str, procs: List[Dict]) -> str:
    lines = [f"Домен: {domain}", "Процессы: " +
             ", ".join(p.get("name") for p in procs if p.get("name"))]
    proc_ids = [p["id"] for p in procs]
    asrts = db.assertions_for_entities(proc_ids) if proc_ids else []
    if asrts:
        lines.append("Утверждения:")
        for a in asrts[:12]:
            p = a.get("props") or {}
            lines.append(f"- {p.get('statement') or a.get('name')} "
                         f"(достоверность {p.get('confidence','?')})")
    return "\n".join(lines)


def build_summaries(store_neo4j: bool = True) -> Dict[str, Any]:
    domains = db.domain_processes()
    out: Dict[str, Any] = {}
    for domain, procs in domains.items():
        payload = _domain_payload(domain, procs)
        summary = None
        if llm.llm_enabled_for_synth():
            r = llm.complete([{"role": "system", "text": _SYS},
                              {"role": "user", "text": payload}],
                             model="pro", temperature=0.2, max_tokens=350,
                             max_retries=2)
            if r and r.get("text", "").strip():
                summary = r["text"].strip()
        if not summary:  # deterministic fallback
            summary = (f"Домен «{domain}»: {len(procs)} процесс(ов) — "
                       + ", ".join(p.get("name") for p in procs if p.get("name")) + ".")
        out[domain] = {"domain": domain,
                       "n_processes": len(procs),
                       "processes": [p.get("name") for p in procs],
                       "summary": summary}

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    if store_neo4j:
        try:
            with db.driver().session() as s:
                for domain, rec in out.items():
                    s.run(
                        "MERGE (d:DomainSummary {id:$id}) "
                        "SET d.domain=$domain, d.summary=$summary, "
                        "d.n_processes=$n",
                        id=f"domain:{domain}", domain=domain,
                        summary=rec["summary"], n=rec["n_processes"])
        except Exception:
            pass
    return out


def load_summaries() -> Dict[str, Any]:
    if OUT_PATH.exists():
        try:
            return json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def summary_for_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    data = load_summaries()
    rec = data.get(domain)
    return rec.get("summary") if rec else None


if __name__ == "__main__":
    res = build_summaries()
    print(f"Wrote {len(res)} domain summaries -> {OUT_PATH}")
    for d, r in res.items():
        print(f"\n== {d} ({r['n_processes']} proc) ==\n{r['summary'][:300]}")
