"""C10 — Evidence-packet synthesis (YandexGPT Pro), replacing the day-1 template.

The model answers ONLY from retrieved evidence: every claim carries a [n] citation,
numbers must come from quotes. Output structure adapts to query_type (review groups
by method/year/geo; compare emits a RU-vs-world Markdown table; gap states what is
NOT studied). A post-check verifies that every number in the answer appears in the
evidence (pipeline validate_numbers, read-only import); otherwise it retries once,
then strips ungrounded sentences. Falls back to a deterministic template if the LLM
is unavailable.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# YandexGPT Pro has a ~5s latency floor (independent of output length), which breaks
# the p95<=5s target; yandexgpt-lite returns equally well-grounded answers in ~2.5s.
# Default to lite for the interactive path; override to "pro" for max fluency.
SYNTH_MODEL = os.environ.get("SCITANGLE_SYNTH_MODEL", "lite")

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO))

import llm  # noqa: E402

try:  # read-only import of the rule-based number validator
    from pipeline.extract.rules.numbers import validate_numbers  # type: ignore
except Exception:  # pragma: no cover
    def validate_numbers(numbers, chunk_text):  # type: ignore
        return [str(nn).replace(",", ".") in (chunk_text or "").replace(",", ".")
                for nn in numbers]

_NUM_RE = re.compile(r"\d+(?:[.,\s]\d+)*")

_SYS = (
    "Ты — аналитик базы знаний R&D горно-металлургической отрасли. "
    "Отвечай ТОЛЬКО на основе переданных доказательств. Каждое содержательное "
    "утверждение сопровождай ссылкой на номер доказательства в виде [n]. "
    "Числа приводи ИСКЛЮЧИТЕЛЬНО из доказательств — ничего не выдумывай и не "
    "оценивай. Если доказательств для ответа недостаточно, прямо скажи об этом. "
    "Пиши на русском, в формате Markdown, БЕЗ вступлений и общих фраз, максимально "
    "сжато: только суть, до ~8 пунктов/предложений."
)

_STRUCT = {
    "review": "Сгруппируй методы/технологии; где возможно — по методам, годам или "
              "географии. В конце — короткий вывод.",
    "compare": "Построй сравнительную таблицу в Markdown с колонками "
               "«Параметр | Россия | Мир/зарубеж» по доступным доказательствам, "
               "затем краткий вывод. Не заполняй ячейки, для которых нет доказательств "
               "(ставь «—»).",
    "aggregate": "Дай агрегированную сводку по доказательствам (по годам / географии / "
                 "значениям параметров).",
    "gap": "Явно раздели: что в корпусе ИЗУЧЕНО и что НЕ изучено (пробел). "
           "Предложи ближайшие смежные темы, по которым данные есть.",
    "lookup": "Дай точный ответ с конкретными числами из доказательств.",
}


def _evidence_packet(citations: List[Dict], assertions: List[Dict],
                     measurements: List[Dict], conditions: List[Dict],
                     contradictions: List[Dict], experts: List[Dict]) -> str:
    lines: List[str] = ["ДОКАЗАТЕЛЬСТВА (цитаты источников):"]
    for i, c in enumerate(citations, 1):
        title = c.get("title") or c.get("doc_id")
        yr = f", {c['year']}" if c.get("year") else ""
        lines.append(f"[{i}] {title}{yr}: «{(c.get('quote') or '').strip()}»")
    if assertions:
        lines.append("\nСТРУКТУРНЫЕ УТВЕРЖДЕНИЯ (граф знаний):")
        for a in assertions:
            p = a.get("props") or {}
            stmt = p.get("statement") or a.get("name")
            lines.append(f"- {stmt} (достоверность: {p.get('confidence','?')}, "
                         f"статус: {p.get('review_status','auto')})")
    if conditions:
        lines.append("\nЧИСЛОВЫЕ УСЛОВИЯ:")
        for c in conditions:
            p = c.get("props") or {}
            if p.get("op") == "range":
                lines.append(f"- {p.get('param')}: {p.get('value')}–{p.get('value2')} "
                             f"{p.get('unit','')}")
            elif p.get("value") is not None:
                lines.append(f"- {p.get('param')}: {p.get('op','')} {p.get('value')} "
                             f"{p.get('unit','')}")
    if measurements:
        lines.append("\nИЗМЕРЕНИЯ:")
        for m in measurements:
            p = m.get("props") or {}
            lines.append(f"- {m.get('name')} ({p.get('context','')})")
    if contradictions:
        lines.append("\nПРОТИВОРЕЧИЯ:")
        for c in contradictions:
            lines.append(f"- «{c.get('a_statement')}» ↔ «{c.get('b_statement')}»")
    if experts:
        names = ", ".join(f"{e.get('name')} ({e.get('affiliation')})"
                          for e in experts if e.get("name"))
        if names:
            lines.append("\nЭКСПЕРТЫ ПО ТЕМЕ: " + names)
    return "\n".join(lines)


def _allowed_number_text(citations, assertions, measurements, conditions) -> str:
    parts = [c.get("quote") or "" for c in citations]
    parts += [c.get("title") or "" for c in citations]
    parts += [str(c.get("year") or "") for c in citations]
    for a in assertions:
        parts.append((a.get("props") or {}).get("statement") or a.get("name") or "")
    for m in measurements:
        parts.append(m.get("name") or "")
        parts.append(str((m.get("props") or {}).get("value") or ""))
    for c in conditions:
        p = c.get("props") or {}
        parts.append(f"{p.get('value')} {p.get('value2')}")
    return "  ".join(parts)


def _numbers_in(text: str) -> List[str]:
    out = []
    for m in _NUM_RE.finditer(text):
        tok = m.group(0).strip()
        # ignore bare citation markers already stripped; keep meaningful numbers
        if tok:
            out.append(tok)
    return out


def _ground_numbers(answer: str, allowed_text: str) -> str:
    """Remove sentences whose numbers are absent from the evidence (anti-hallucination)."""
    # strip citation markers [n] before number scan so they aren't treated as numbers
    scan = re.sub(r"\[\d+\]", " ", answer)
    nums = _numbers_in(scan)
    if not nums:
        return answer
    flags = validate_numbers(nums, allowed_text)
    bad = {n for n, ok in zip(nums, flags) if not ok}
    if not bad:
        return answer
    kept_lines = []
    for line in answer.split("\n"):
        if "|" in line:  # keep table rows intact
            kept_lines.append(line)
            continue
        # split into sentences, drop those containing an ungrounded number
        sentences = re.split(r"(?<=[.!?])\s+", line)
        good = []
        for svar in sentences:
            s_scan = re.sub(r"\[\d+\]", " ", svar)
            s_nums = set(_numbers_in(s_scan))
            if s_nums & bad:
                continue
            good.append(svar)
        kept_lines.append(" ".join(good))
    return "\n".join(l for l in kept_lines).strip()


_REL_SCHEMA = {
    "type": "object",
    "properties": {"relevant": {"type": "boolean"}},
    "required": ["relevant"],
}
_REL_SYS = (
    "Ты — контролёр релевантности базы знаний R&D горно-металлургической отрасли "
    "(никель, медь, кобальт, МПГ, платиноиды, руды, обогащение, пиро/гидрометаллургия, "
    "водоочистка и экология ГМК). Тебе дают запрос и цитаты-кандидаты. Ответь строго "
    "JSON {\"relevant\": true|false}. relevant=true, если цитаты относятся к предмету "
    "запроса ПО СУЩЕСТВУ. relevant=false, если ПРЕДМЕТ запроса — посторонняя область "
    "(выплавка алюминия Холла—Эру, кремниевые солнечные панели / метод Чохральского для "
    "полупроводников, животноводство/сельское хозяйство, языковые модели/ИТ/GPU, "
    "виноделие/пищепром и подобное), а цитаты лишь косвенно её задевают."
)


def judge_relevance(query: str, citations: List[Dict]) -> bool:
    """Cheap LLM verdict: are the evidence snippets actually about the query's subject?
    Used only for SUSPICIOUS passes (no distinctive material matched) to reject
    domain-adjacent out-of-corpus queries. Fails open (True) if the LLM is unavailable."""
    if not citations or not llm.llm_enabled_for_synth():
        return True
    snippets = "\n".join(f"[{i}] «{(c.get('quote') or '')[:220]}»"
                         for i, c in enumerate(citations[:5], 1))
    user = (f"Запрос (RU или EN): {query}\n\nЦитаты-кандидаты (русскоязычный корпус):\n"
            f"{snippets}\n\nОпредели ПРЕДМЕТ запроса. Если он вне домена корпуса "
            "(никель/медь/кобальт/МПГ, руды, обогащение, металлургия, водоочистка ГМК) — "
            "relevant=false. Верни JSON {\"relevant\": true|false}.")
    r = llm.complete([{"role": "system", "text": _REL_SYS},
                      {"role": "user", "text": user}],
                     model="lite", temperature=0.0, max_tokens=20,
                     json_schema=_REL_SCHEMA, parse_json=True, max_retries=2)
    if not r:
        return True
    j = r.get("json")
    if isinstance(j, dict) and "relevant" in j:
        return bool(j["relevant"])
    return True


def confidence_summary(assertions: List[Dict], citations: List[Dict]) -> str:
    levels = [(a.get("props") or {}).get("confidence") for a in assertions]
    if "high" in levels:
        return "high"
    if any(levels) or citations:
        return "medium"
    return "low"


def synthesize(query: str, intent: Dict, citations: List[Dict],
               assertions: List[Dict], measurements: List[Dict],
               conditions: List[Dict], contradictions: List[Dict],
               experts: List[Dict], adjacent: List[str] | None = None,
               domain_summary: str | None = None) -> Dict[str, Any]:
    qtype = intent.get("query_type", "lookup")

    # ---- honest empty answer (score-gate produced nothing) ----
    if not citations and not assertions:
        adj = adjacent or []
        lines = [f"**По запросу «{query}» доказательств в корпусе не найдено.**", "",
                 "Система не синтезирует ответ без опоры на источники "
                 "(во избежание галлюцинаций)."]
        gaps = ["В корпусе не найдено доказательств по этому запросу."]
        if adj:
            lines += ["", "Ближайшие смежные темы, по которым данные есть: "
                      + ", ".join(adj[:5]) + "."]
            gaps.append("Смежные темы с данными: " + ", ".join(adj[:5]))
        return {"answer_md": "\n".join(lines),
                "confidence_summary": "low", "gaps": gaps, "synth": "empty"}

    packet = _evidence_packet(citations, assertions, measurements, conditions,
                              contradictions, experts)
    allowed = _allowed_number_text(citations, assertions, measurements, conditions)

    answer_md = None
    if llm.llm_enabled_for_synth():
        extra = f"\n\nКОНТЕКСТ ДОМЕНА: {domain_summary}" if domain_summary else ""
        user = (f"Запрос пользователя: {query}\n\n{packet}{extra}\n\n"
                f"Задача ({qtype}): {_STRUCT.get(qtype, _STRUCT['lookup'])}\n"
                "Ответь строго по доказательствам, со ссылками [n].")
        r = llm.complete([{"role": "system", "text": _SYS},
                          {"role": "user", "text": user}],
                         model=SYNTH_MODEL, temperature=0.2, max_tokens=550, max_retries=2)
        if r and r.get("text", "").strip():
            answer_md = _ground_numbers(r["text"].strip(), allowed)
            # if grounding stripped a lot / left invalid numbers, retry once stricter
            if re.sub(r"\s", "", answer_md) == "" or _has_ungrounded(answer_md, allowed):
                allowed_nums = sorted(set(_numbers_in(allowed)))
                user2 = user + ("\n\nВАЖНО: используй ТОЛЬКО эти числа: "
                                + ", ".join(allowed_nums) + ". Другие числа не приводи.")
                r2 = llm.complete([{"role": "system", "text": _SYS},
                                   {"role": "user", "text": user2}],
                                  model=SYNTH_MODEL, temperature=0.1, max_tokens=550,
                                  max_retries=2)
                if r2 and r2.get("text", "").strip():
                    answer_md = _ground_numbers(r2["text"].strip(), allowed)

    if not answer_md or not answer_md.strip():
        answer_md = _template(query, qtype, citations, assertions, measurements,
                              conditions, contradictions)
        synth = "template"
    else:
        synth = "llm"

    return {"answer_md": answer_md,
            "confidence_summary": confidence_summary(assertions, citations),
            "gaps": [], "synth": synth}


def _has_ungrounded(answer: str, allowed_text: str) -> bool:
    nums = _numbers_in(re.sub(r"\[\d+\]", " ", answer))
    if not nums:
        return False
    return not all(validate_numbers(nums, allowed_text))


# --------------------------------------------------------------------- template
def _template(query, qtype, citations, assertions, measurements, conditions,
              contradictions) -> str:
    lines: List[str] = [f"### Ответ по запросу: {query}", ""]
    if assertions:
        lines.append("**Ключевые утверждения (с доказательствами):**")
        for i, a in enumerate(assertions, 1):
            p = a.get("props") or {}
            lines.append(f"{i}. {p.get('statement') or a.get('name')} "
                         f"_(достоверность: {p.get('confidence','?')}, "
                         f"статус: {p.get('review_status','auto')})_")
        lines.append("")
    if conditions:
        lines.append("**Числовые условия:**")
        for c in conditions:
            p = c.get("props") or {}
            if p.get("op") == "range":
                lines.append(f"- {p.get('param')}: {p.get('value')}–{p.get('value2')} "
                             f"{p.get('unit','')}")
            elif p.get("value") is not None:
                lines.append(f"- {p.get('param')}: {p.get('op','')} {p.get('value')} "
                             f"{p.get('unit','')}")
        lines.append("")
    if measurements:
        lines.append("**Измеренные результаты:**")
        for m in measurements:
            lines.append(f"- {m.get('name')} ({(m.get('props') or {}).get('context','')})")
        lines.append("")
    if contradictions:
        lines.append("**⚠️ Противоречия:**")
        for c in contradictions:
            lines.append(f"- «{c.get('a_statement')}» ↔ «{c.get('b_statement')}»")
        lines.append("")
    if citations:
        lines.append("**Источники:**")
        for i, c in enumerate(citations, 1):
            lines.append(f"[{i}] {c.get('title') or c.get('doc_id')}: "
                         f"«{(c.get('quote') or '')[:160]}…»")
    return "\n".join(lines)
