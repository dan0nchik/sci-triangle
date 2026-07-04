"""C7 — Query planner: NL query -> structured intent.

Primary path: YandexGPT (jsonSchema structured output) extracts concepts,
numeric conditions, geography, years, query_type. Terms are normalized through the
concept registry (shared/concepts.yaml). Plans are cached (sqlite) by normalized
query. A deterministic regex+registry fallback runs when the LLM is unavailable.

Numbers ({value, unit}) are ALWAYS extracted deterministically (regex) and merged
in, so grounding/tests never depend on LLM output.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import llm  # noqa: E402
from app import concepts_registry as reg  # noqa: E402

PLANNER_MODEL = "lite"   # lite keeps the interactive path fast; Pro is used for synthesis
_CACHE_PATH = BACKEND / "plan_cache.sqlite"

_NUM_UNIT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(мг/л|мг/дм3|мг/дм³|м3/ч|м³/ч|%|°c|мкм|г/т|л/с|т/сут|°с)?",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")

_GEO_RU = ["росси", "рф", "отечествен", "российск"]
_GEO_FOREIGN = ["зарубеж", "мировой", "мировы", "иностран", "foreign", "world",
                "global", "за рубежом"]


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _detect_language(q: str) -> str:
    cyr = len(re.findall(r"[а-яё]", q, re.IGNORECASE))
    lat = len(re.findall(r"[a-z]", q, re.IGNORECASE))
    if cyr and lat and lat > cyr * 0.4:
        return "mixed"
    return "en" if lat > cyr else "ru"


def _query_type(q: str) -> str:
    ql = q.lower()
    if any(w in ql for w in ["сравн", " vs ", "против", "compare", "comparison",
                             "versus", "российск", "и зарубеж"]) and \
            any(w in ql for w in ["сравн", "vs", "compare", "versus", "против",
                                  "зарубеж"]):
        return "compare"
    if any(w in ql for w in ["пробел", "нет данных", "отсутству", "gap", "не изучен",
                             "чего не хватает", "без числовых"]):
        return "gap"
    if any(w in ql for w in ["сколько", "динамик", "распределение по", "по годам",
                             "how many", "count", "ведущих", "производителей"]):
        return "aggregate"
    if any(w in ql for w in ["обзор", "методы", "review", "какие", "существуют",
                             "способы", "технологии", "overview", "what methods"]):
        return "review"
    return "lookup"


def parse_numbers(query: str) -> List[Dict[str, Any]]:
    numbers = []
    for m in _NUM_UNIT.finditer(query):
        unit = (m.group(2) or "").lower()
        if not unit:
            continue
        unit = unit.replace("°с", "°c")
        numbers.append({"value": float(m.group(1).replace(",", ".")), "unit": unit})
    return numbers


def _geography(q: str) -> str | None:
    ql = q.lower()
    ru = any(w in ql for w in _GEO_RU)
    fg = any(w in ql for w in _GEO_FOREIGN)
    if ru and fg:
        return "global"
    if ru:
        return "RU"
    if fg:
        return "foreign"
    return None


def _years(q: str) -> Dict[str, Any]:
    yrs = [int(m.group(0)) for m in _YEAR.finditer(q)]
    out: Dict[str, Any] = {}
    if yrs:
        out["year_from"] = min(yrs)
        out["year_to"] = max(yrs)
    m = re.search(r"за последн\w*\s+(\d+)\s+(?:лет|год)", q.lower())
    if m:
        out["year_from"] = 2026 - int(m.group(1))
    return out


def _concepts_from_registry(query: str) -> List[Dict[str, Any]]:
    """Scan query for registry surface forms (word-boundary, forms of length>=3)."""
    ql = _norm(query)
    found: Dict[str, Dict[str, Any]] = {}
    for c in reg.all_concepts():
        for form in c.get("_forms", []) or reg.surface_forms(c):
            fl = form.lower()
            if len(fl) < 3:
                continue
            if re.search(r"(?<![а-яёa-z])" + re.escape(fl) + r"(?![а-яёa-z])", ql):
                cid = c["concept_id"]
                if cid not in found:
                    found[cid] = {"name": c.get("label_ru") or form,
                                  "type": c.get("type"), "concept_id": cid}
                break
    return list(found.values())


# --------------------------------------------------------------------- LLM planner
_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "query_type": {"type": "string",
                       "enum": ["lookup", "review", "compare", "aggregate", "gap"]},
        "language": {"type": "string", "enum": ["ru", "en", "mixed"]},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "conditions": {"type": "array", "items": {
            "type": "object",
            "properties": {"param": {"type": "string"}, "op": {"type": "string"},
                           "value": {"type": "number"}, "unit": {"type": "string"}}}},
        "geography": {"type": "string"},
        "compare_axes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["query_type", "concepts"],
}

_SYS_PROMPT = (
    "Ты — планировщик запросов к базе знаний R&D горно-металлургической отрасли "
    "(гидрометаллургия, пирометаллургия, обогащение, водоочистка, экология, горное дело). "
    "Разбери запрос пользователя в структурный интент. Извлеки ключевые концепты "
    "(материалы, процессы, оборудование, параметры) — по возможности приводи их к "
    "каноническим РУССКИМ терминам отрасли (например 'catholyte'->'католит', "
    "'nickel electrowinning'->'электроэкстракция никеля'). Не выдумывай концепты, "
    "которых нет в запросе. Определи тип запроса: lookup (точечный факт), review "
    "(обзор методов), compare (сравнение), aggregate (агрегация/статистика), gap "
    "(пробелы в данных). Верни строго JSON по схеме. Поле concepts — массив СТРОК "
    "с конкретными терминами ИЗ запроса, а не названий категорий (не 'materials', "
    "'processes'). Пример для «Циркуляция католита при электроэкстракции никеля»: "
    '{"query_type":"lookup","language":"ru","concepts":["католит",'
    '"электроэкстракция никеля","никель"],"conditions":[],"geography":"",'
    '"compare_axes":[]}'
)


def _llm_plan(query: str) -> Dict[str, Any] | None:
    r = llm.complete(
        [{"role": "system", "text": _SYS_PROMPT},
         {"role": "user", "text": query}],
        model=PLANNER_MODEL, temperature=0.0, max_tokens=400,
        json_schema=_INTENT_SCHEMA, parse_json=True, max_retries=2,
    )
    if not r:
        return None
    data = r.get("json")
    if not isinstance(data, dict):
        return None
    return data


# --------------------------------------------------------------------- cache
def _cache_get(key: str) -> Dict[str, Any] | None:
    try:
        conn = sqlite3.connect(_CACHE_PATH)
        conn.execute("CREATE TABLE IF NOT EXISTS plans (k TEXT PRIMARY KEY, v TEXT)")
        row = conn.execute("SELECT v FROM plans WHERE k=?", (key,)).fetchone()
        conn.close()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def _cache_put(key: str, intent: Dict[str, Any]) -> None:
    try:
        conn = sqlite3.connect(_CACHE_PATH)
        conn.execute("CREATE TABLE IF NOT EXISTS plans (k TEXT PRIMARY KEY, v TEXT)")
        conn.execute("INSERT OR REPLACE INTO plans (k, v) VALUES (?,?)",
                     (key, json.dumps(intent, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except Exception:
        pass


# --------------------------------------------------------------------- public
def plan(query: str, use_cache: bool = True) -> Dict[str, Any]:
    key = _norm(query) + "|" + ("llm" if llm.llm_enabled_for_planner() else "fb")
    if use_cache:
        cached = _cache_get(key)
        if cached:
            return cached

    numbers = parse_numbers(query)
    intent: Dict[str, Any] = {
        "raw": query,
        "language": _detect_language(query),
        "query_type": _query_type(query),
        "concepts": [],
        "conditions": [],
        "numbers": numbers,          # deterministic, back-compat
        "geography": _geography(query),
        "compare_axes": [],
        "planner": "fallback",
    }
    intent.update(_years(query))

    llm_data = _llm_plan(query) if llm.llm_enabled_for_planner() else None
    if llm_data:
        intent["planner"] = "llm"
        intent["query_type"] = llm_data.get("query_type") or intent["query_type"]
        if llm_data.get("language"):
            intent["language"] = llm_data["language"]
        if llm_data.get("geography"):
            intent["geography"] = llm_data["geography"]
        intent["compare_axes"] = llm_data.get("compare_axes") or []
        intent["conditions"] = llm_data.get("conditions") or []
        concepts = []
        for c in llm_data.get("concepts") or []:
            if isinstance(c, str):
                c = {"name": c}
            elif not isinstance(c, dict):
                continue
            name = (c.get("name") or "").strip()
            if not name:
                continue
            ctype = c.get("type") or reg.concept_type(name)
            entry = {"name": name, "type": ctype}
            rc = reg.match_term(name)
            if rc:
                entry["concept_id"] = rc["concept_id"]
                entry["type"] = entry["type"] or rc.get("type")
            concepts.append(entry)
        intent["concepts"] = concepts

    # Always union registry-scanned concepts (robustness / recall).
    reg_concepts = _concepts_from_registry(query)
    have = {(_norm(c["name"])) for c in intent["concepts"]}
    have_cids = {c.get("concept_id") for c in intent["concepts"] if c.get("concept_id")}
    for rc in reg_concepts:
        if rc["concept_id"] not in have_cids and _norm(rc["name"]) not in have:
            intent["concepts"].append(rc)

    # surface forms to anchor graph entities (registry-expanded)
    forms: List[str] = []
    for c in intent["concepts"]:
        forms.extend(reg.expand_forms(c["name"]))
    # dedupe
    seen, uforms = set(), []
    for f in forms:
        fl = _norm(f)
        if fl and fl not in seen:
            seen.add(fl)
            uforms.append(f)
    intent["concept_forms"] = uforms

    if use_cache:
        _cache_put(key, intent)
    return intent
