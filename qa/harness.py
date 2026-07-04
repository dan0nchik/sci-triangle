#!/usr/bin/env python3
"""sci-tangle — QA/Eval harness (направление F, задачи F1–F2).

Гоняет eval-set (qa/eval_set.yaml) против REST API (контракт PLAN.md §4.3) и
считает метрики качества retrieval/синтеза:

  * retrieval hit-rate  — упомянуты ли ожидаемые документы в citations
  * doc recall          — доля найденных ожидаемых паттернов документов
  * number accuracy     — все ли must_contain_numbers присутствуют в ответе/цитатах
  * citation-rate       — доля запросов с обязательными цитатами, где цитаты есть
  * honesty-rate        — на adversarial (expect_empty): нет галлюцинаций
  * латентность         — p50 / p95 (wall-clock round-trip)

Харнесс НЕ зависит от того, fixture это или реальный граф: ожидаемые документы
матчатся по подстроке в (filename + title) процитированных doc_id, а метаданные
берутся из corpus/documents.jsonl и/или из GET /api/documents/{doc_id}.

Запуск:
  .venv-f/bin/python qa/harness.py                       # base = http://localhost:8000
  QA_API_BASE=http://localhost:8001 .venv-f/bin/python qa/harness.py
  .venv-f/bin/python qa/harness.py --eval qa/eval_set.yaml --out qa/reports

Выход: qa/reports/eval_YYYYMMDD_HHMM.md  и  .json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DOCS = ROOT / "corpus" / "documents.jsonl"

NOT_FOUND_MARKERS = [
    "не найден", "не найдено", "не обнаруж", "отсутству",
    "нет данных", "no relevant", "not found", "no evidence",
]


# --------------------------------------------------------------------------- utils
def norm_num(s: str) -> List[str]:
    """Варианты записи числа, толерантные к запятой/точке и пробелам."""
    s = str(s).strip()
    out = {s, s.replace(",", "."), s.replace(".", ",")}
    return [v for v in out if v]


def text_contains_number(haystack: str, num: str) -> bool:
    return any(v in haystack for v in norm_num(num))


def pattern_matches(pattern: str, text: str) -> bool:
    return pattern.lower() in text.lower()


# --------------------------------------------------------------------------- doc index
class DocIndex:
    """doc_id -> строка для матчинга (filename + title), с ленивой дозагрузкой из API."""

    def __init__(self, api_base: str, client: httpx.Client):
        self.api_base = api_base
        self.client = client
        self.by_id: Dict[str, str] = {}
        self._load_corpus()

    def _load_corpus(self) -> None:
        if not CORPUS_DOCS.exists():
            return
        for line in CORPUS_DOCS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            did = d.get("doc_id")
            if did:
                self.by_id[did] = f"{d.get('filename', '')} {d.get('title', '')}".strip()

    def label(self, doc_id: str) -> str:
        if doc_id in self.by_id:
            return self.by_id[doc_id]
        # ленивая дозагрузка (fixture-документы вроде d000101 живут только в API)
        label = doc_id
        try:
            r = self.client.get(f"{self.api_base}/api/documents/{doc_id}", timeout=15)
            if r.status_code == 200:
                d = r.json()
                label = f"{d.get('title', '')} {d.get('doc_id', '')}".strip()
        except Exception:
            pass
        self.by_id[doc_id] = label
        return label


# --------------------------------------------------------------------------- scoring
def score_case(case: Dict[str, Any], resp: Dict[str, Any], docidx: DocIndex,
               latency_ms: float, lang: str, query: str) -> Dict[str, Any]:
    exp = case.get("expected", {}) or {}
    must_docs: List[str] = exp.get("must_mention_docs") or []
    must_nums: List[str] = [str(n) for n in (exp.get("must_contain_numbers") or [])]
    must_cite: bool = bool(exp.get("must_have_citations"))
    expect_empty: bool = bool(exp.get("expect_empty"))

    citations = resp.get("citations") or []
    answer = resp.get("answer_md") or ""

    # текст для поиска чисел = ответ + все цитаты
    cite_text = " ".join((c.get("quote") or "") for c in citations)
    # Из ответа вырезаем эхо самого запроса (шаблонные ответы повторяют query,
    # иначе числа из текста запроса «проходили» бы проверку сами по себе).
    answer_for_nums = answer.replace(query, "") if query else answer
    full_text = answer_for_nums + "\n" + cite_text

    # метки процитированных документов (filename + title)
    cited_labels = []
    for c in citations:
        did = c.get("doc_id")
        if did:
            cited_labels.append(docidx.label(did))
    cited_blob = " || ".join(cited_labels)

    # --- document hit / recall ---
    doc_matched = []
    doc_missed = []
    for pat in must_docs:
        if pattern_matches(pat, cited_blob):
            doc_matched.append(pat)
        else:
            doc_missed.append(pat)
    doc_hit: Optional[bool] = None
    doc_recall: Optional[float] = None
    if must_docs:
        doc_hit = len(doc_matched) > 0
        doc_recall = round(len(doc_matched) / len(must_docs), 2)

    # --- number accuracy ---
    num_found = []
    num_missing = []
    for n in must_nums:
        if text_contains_number(full_text, n):
            num_found.append(n)
        else:
            num_missing.append(n)
    num_ok: Optional[bool] = None
    num_recall: Optional[float] = None
    if must_nums:
        num_ok = len(num_missing) == 0
        num_recall = round(len(num_found) / len(must_nums), 2)

    # --- citations ---
    has_citations = len(citations) > 0
    citation_ok: Optional[bool] = None
    if must_cite:
        citation_ok = has_citations

    # --- honesty (adversarial / expect_empty) ---
    honest: Optional[bool] = None
    row_said_not_found: Optional[bool] = None
    if expect_empty:
        # Строгое определение: для темы вне корпуса ЛЮБАЯ возвращённая цитата —
        # ложное срабатывание/галлюцинация. Честно = нет процитированных источников.
        # (флаг said_not_found пишем в отчёт для диагностики синтеза)
        honest = not has_citations
        row_said_not_found = any(m in answer.lower() for m in NOT_FOUND_MARKERS)

    return {
        "id": case["id"],
        "lang": lang,
        "class": case.get("class"),
        "query": query,
        "latency_ms": round(latency_ms, 1),
        "took_ms": resp.get("took_ms"),
        "n_citations": len(citations),
        "confidence": resp.get("confidence_summary"),
        "doc_hit": doc_hit,
        "doc_recall": doc_recall,
        "doc_matched": doc_matched,
        "doc_missed": doc_missed,
        "num_ok": num_ok,
        "num_recall": num_recall,
        "num_missing": num_missing,
        "citation_ok": citation_ok,
        "expect_empty": expect_empty,
        "honest": honest,
        "said_not_found": row_said_not_found,
        "answer_head": answer[:180].replace("\n", " "),
        "error": None,
    }


def run_query(client: httpx.Client, api_base: str, query: str) -> (Dict[str, Any], float):
    t0 = time.time()
    r = client.post(f"{api_base}/api/search", json={"query": query}, timeout=60)
    latency = (time.time() - t0) * 1000
    r.raise_for_status()
    return r.json(), latency


# --------------------------------------------------------------------------- aggregation
def _mean(vals: List[float]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


def _pct(cond: List[bool]) -> Optional[float]:
    cond = [c for c in cond if c is not None]
    return round(100 * sum(1 for c in cond if c) / len(cond), 1) if cond else None


def _pctl(vals: List[float], p: float) -> Optional[float]:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 1)


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    lat = [r["latency_ms"] for r in rows if r.get("error") is None]
    return {
        "n_rows": len(rows),
        "n_errors": sum(1 for r in rows if r.get("error")),
        "retrieval_hit_rate_pct": _pct([r["doc_hit"] for r in rows]),
        "doc_recall_avg": _mean([r["doc_recall"] for r in rows]),
        "number_accuracy_pct": _pct([r["num_ok"] for r in rows]),
        "number_recall_avg": _mean([r["num_recall"] for r in rows]),
        "citation_rate_pct": _pct([r["citation_ok"] for r in rows]),
        "honesty_rate_pct": _pct([r["honest"] for r in rows]),
        "latency_p50_ms": _pctl(lat, 0.50),
        "latency_p95_ms": _pctl(lat, 0.95),
        "latency_max_ms": round(max(lat), 1) if lat else None,
    }


def by_class(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    classes = sorted({r["class"] for r in rows if r.get("class")})
    out = {}
    for cl in classes:
        sub = [r for r in rows if r["class"] == cl]
        out[cl] = {
            "n": len(sub),
            "retrieval_hit_rate_pct": _pct([r["doc_hit"] for r in sub]),
            "number_accuracy_pct": _pct([r["num_ok"] for r in sub]),
            "citation_rate_pct": _pct([r["citation_ok"] for r in sub]),
            "honesty_rate_pct": _pct([r["honest"] for r in sub]),
        }
    return out


# --------------------------------------------------------------------------- report
def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✅" if v else "❌"
    return str(v)


def write_reports(rows, agg, cls, meta, out_dir: Path) -> (Path, Path):
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"eval_{ts}.md"
    json_path = out_dir / f"eval_{ts}.json"

    json_path.write_text(json.dumps(
        {"meta": meta, "summary": agg, "by_class": cls, "rows": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")

    L: List[str] = []
    L.append(f"# sci-tangle — QA eval report ({ts})\n")
    L.append(f"- API base: `{meta['api_base']}`")
    L.append(f"- eval-set: `{meta['eval_path']}` — {meta['n_cases']} кейсов "
             f"({meta['n_rows']} прогонов с учётом EN-вариантов)")
    L.append(f"- backend health: `{meta.get('health')}`")
    L.append(f"- запуск: {meta['run_at']}\n")

    L.append("## Сводка\n")
    L.append("| Метрика | Значение |")
    L.append("|---|---|")
    L.append(f"| Прогонов / ошибок | {agg['n_rows']} / {agg['n_errors']} |")
    L.append(f"| Retrieval hit-rate | {_fmt(agg['retrieval_hit_rate_pct'])}% |")
    L.append(f"| Doc recall (avg) | {_fmt(agg['doc_recall_avg'])} |")
    L.append(f"| Number accuracy (все числа) | {_fmt(agg['number_accuracy_pct'])}% |")
    L.append(f"| Number recall (avg) | {_fmt(agg['number_recall_avg'])} |")
    L.append(f"| Citation-rate | {_fmt(agg['citation_rate_pct'])}% |")
    L.append(f"| Honesty-rate (adversarial) | {_fmt(agg['honesty_rate_pct'])}% |")
    L.append(f"| Latency p50 / p95 / max | "
             f"{_fmt(agg['latency_p50_ms'])} / {_fmt(agg['latency_p95_ms'])} / "
             f"{_fmt(agg['latency_max_ms'])} мс |")
    L.append("")

    L.append("## По классам\n")
    L.append("| Класс | N | Hit-rate | Number acc | Citation | Honesty |")
    L.append("|---|---|---|---|---|---|")
    for cl, s in cls.items():
        L.append(f"| {cl} | {s['n']} | {_fmt(s['retrieval_hit_rate_pct'])}% | "
                 f"{_fmt(s['number_accuracy_pct'])}% | {_fmt(s['citation_rate_pct'])}% | "
                 f"{_fmt(s['honesty_rate_pct'])}% |")
    L.append("")

    L.append("## По запросам\n")
    L.append("| id | lang | class | hit | doc_recall | num_ok | cite | honest | lat,мс | ответ |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r.get("error"):
            L.append(f"| {r['id']} | {r['lang']} | {r['class']} | ⚠️ERR | — | — | — | — | "
                     f"— | {r['error']} |")
            continue
        L.append(
            f"| {r['id']} | {r['lang']} | {r['class']} | {_fmt(r['doc_hit'])} | "
            f"{_fmt(r['doc_recall'])} | {_fmt(r['num_ok'])} | {_fmt(r['citation_ok'])} | "
            f"{_fmt(r['honest'])} | {r['latency_ms']} | "
            f"{r['answer_head'][:70]}… |"
        )
    L.append("")

    # промахи с деталями (для фидбека B/C)
    L.append("## Детали промахов (фидбек B/C)\n")
    for r in rows:
        if r.get("error"):
            continue
        problems = []
        if r["doc_hit"] is False:
            problems.append(f"нет ожидаемых документов: {r['doc_missed']}")
        if r["num_ok"] is False:
            problems.append(f"нет чисел: {r['num_missing']}")
        if r["citation_ok"] is False:
            problems.append("нет цитат")
        if r["honest"] is False:
            problems.append(f"⚠️ ГАЛЛЮЦИНАЦИЯ: adversarial вернул {r['n_citations']} цитат")
        if problems:
            L.append(f"- **{r['id']}** ({r['lang']}, {r['class']}): " + "; ".join(problems))
    L.append("")

    md_path.write_text("\n".join(L), encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="sci-tangle QA eval harness")
    ap.add_argument("--eval", default=str(Path(__file__).parent / "eval_set.yaml"))
    ap.add_argument("--out", default=str(Path(__file__).parent / "reports"))
    ap.add_argument("--base", default=os.environ.get("QA_API_BASE", "http://localhost:8000"))
    ap.add_argument("--no-en", action="store_true", help="не прогонять EN-варианты")
    args = ap.parse_args()

    api_base = args.base.rstrip("/")
    eval_path = Path(args.eval)
    cases = yaml.safe_load(eval_path.read_text(encoding="utf-8"))["queries"]

    # trust_env=False: не гонять localhost через корпоративный HTTP(S)_PROXY из .env
    client = httpx.Client(trust_env=False)

    # health-check
    health = None
    try:
        h = client.get(f"{api_base}/api/health", timeout=10)
        health = h.json() if h.status_code == 200 else f"HTTP {h.status_code}"
    except Exception as e:
        print(f"[FATAL] API недоступен на {api_base}: {e}", file=sys.stderr)
        print("Подними backend:  cd backend && ../.venv-c/bin/python -m uvicorn app.main:app --port 8000",
              file=sys.stderr)
        return 2
    print(f"[ok] API health: {health}")

    docidx = DocIndex(api_base, client)

    # собираем список прогонов (RU + опц. EN)
    runs = []
    for c in cases:
        runs.append((c, "ru", c["query"]))
        if not args.no_en and c.get("query_en"):
            runs.append((c, "en", c["query_en"]))

    rows: List[Dict[str, Any]] = []
    for c, lang, q in runs:
        try:
            resp, lat = run_query(client, api_base, q)
            row = score_case(c, resp, docidx, lat, lang, q)
        except Exception as e:
            row = {"id": c["id"], "lang": lang, "class": c.get("class"),
                   "query": q, "error": str(e), "latency_ms": None,
                   "doc_hit": None, "doc_recall": None, "num_ok": None,
                   "num_recall": None, "citation_ok": None, "honest": None,
                   "n_citations": 0, "answer_head": ""}
        rows.append(row)
        flag = "ERR" if row.get("error") else "ok"
        print(f"  [{flag}] {row['id']:>4} {lang}  hit={_fmt(row.get('doc_hit'))} "
              f"num={_fmt(row.get('num_ok'))} cite={_fmt(row.get('citation_ok'))} "
              f"honest={_fmt(row.get('honest'))} lat={row.get('latency_ms')}ms")

    agg = aggregate(rows)
    cls = by_class(rows)
    meta = {
        "api_base": api_base,
        "eval_path": str(eval_path),
        "n_cases": len(cases),
        "n_rows": len(rows),
        "health": health,
        "run_at": datetime.now().isoformat(timespec="seconds"),
    }
    md_path, json_path = write_reports(rows, agg, cls, meta, Path(args.out))

    print("\n=== СВОДКА ===")
    for k, v in agg.items():
        print(f"  {k}: {v}")
    print(f"\nОтчёт: {md_path}\n       {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
