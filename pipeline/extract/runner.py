"""
runner.py — батч-раннер LLM-экстракции (PLAN B8/B10).

Пайплайн:
  chunks.jsonl -> LLM (completionAsync, lite, конкурентность<=5) -> extractions.sqlite
              -> нормализация (concept_id) + валидация чисел (rules) -> nodes.jsonl/edges.jsonl

Чекпойнты и возобновление: обработанные chunk_id хранятся в SQLite; повторный
запуск обрабатывает только новые чанки. Граф строится из всех накопленных
экстракций (идемпотентно, с дедупликацией).

CLI:
  python -m pipeline.extract.runner --input corpus/dev_chunks.jsonl --limit 60
  python -m pipeline.extract.runner --build-only   # только пересобрать граф
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "pipeline" / "extract"))

# Completion goes through the multi-provider gateway (yandex / openai_compatible /
# mock via .env). USAGE is the gateway's cross-provider accumulator (superset of the
# yandex_client counters, so the progress log is unchanged for LLM_PROVIDER=yandex).
from shared.llm_gateway import gateway as _gateway, USAGE  # noqa: E402
import prompts  # noqa: E402
import normalize as norm  # noqa: E402


def complete_batch(tasks, model="lite", json_schema=None, temperature=0.1,
                   max_tokens=2000, parse_json=True, concurrency=None, on_result=None):
    """Batch extraction via the gateway (role=extraction). For LLM_PROVIDER=yandex this
    delegates to the existing completionAsync path in shared/yandex_client.py."""
    return _gateway.complete_batch(
        list(tasks), json_schema=json_schema, model_role="extraction",
        default_model=model, temperature=temperature, max_tokens=max_tokens,
        parse_json=parse_json, concurrency=concurrency, on_result=on_result,
    )

CKPT_DB = _ROOT / "pipeline" / "extract" / "extractions.sqlite"
NODES_OUT = _ROOT / "graph" / "nodes.jsonl"
EDGES_OUT = _ROOT / "graph" / "edges.jsonl"


# --- rules-модуль (детерминированная валидация чисел) -----------------------
# Контракт другого агента: extract_conditions(text), canonicalize_unit(value,unit),
# validate_numbers(numbers, chunk_text)->list[bool]. Если модуля нет — fallback.
try:
    from rules import (  # type: ignore  # noqa
        validate_numbers, canonicalize_unit, extract_conditions, detect_geography,
    )
    _HAS_RULES = True
except Exception:  # noqa: BLE001
    _HAS_RULES = False

    def _num_variants(v) -> list[str]:
        out = set()
        try:
            f = float(v)
        except (TypeError, ValueError):
            return [str(v)]
        if f == int(f):
            out.add(str(int(f)))
        s = ("%g" % f)
        out.add(s)
        out.add(s.replace(".", ","))  # рус. десятичная запятая
        return list(out)

    def validate_numbers(numbers, chunk_text: str) -> list[bool]:  # type: ignore
        """Fallback: число валидно, если дословно присутствует в тексте чанка."""
        res = []
        for v in numbers:
            res.append(any(var in chunk_text for var in _num_variants(v)))
        return res

    def canonicalize_unit(value, unit):  # type: ignore
        return value, unit

    def extract_conditions(text):  # type: ignore
        return []

    def detect_geography(text, meta=None):  # type: ignore
        return {"geo": None, "countries": []}


# --- checkpoint DB ----------------------------------------------------------
def _ckpt_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(CKPT_DB, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS extractions ("
        " chunk_id TEXT PRIMARY KEY, doc_id TEXT, section TEXT, text TEXT,"
        " payload TEXT, ok INTEGER, error TEXT, ts REAL)"
    )
    return conn


def _done_ids(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT chunk_id FROM extractions").fetchall()}


# --- загрузка чанков --------------------------------------------------------
def load_chunks(input_path: Path) -> list[dict]:
    return [json.loads(l) for l in input_path.read_text(encoding="utf-8").splitlines() if l.strip()]


# приоритет разделов (golden-темы в «Обзорах»/«Статьях»)
_SECTION_PRIORITY = {"Обзоры": 0, "Статьи": 1, "Доклады": 2,
                     "Материалы конференций": 3, "Журналы": 4}


def _doc_sections() -> dict[str, str]:
    docs = _ROOT / "corpus" / "documents.jsonl"
    out: dict[str, str] = {}
    if docs.exists():
        for l in docs.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            try:
                d = json.loads(l)
                out[d["doc_id"]] = d.get("section", "")
            except Exception:
                pass
    return out


def prioritize(chunks: list[dict]) -> list[dict]:
    sec = _doc_sections()
    return sorted(
        chunks,
        key=lambda c: (_SECTION_PRIORITY.get(sec.get(c["doc_id"], ""), 9),
                       c["doc_id"], c.get("seq", 0)),
    )


# --- фаза 1: LLM-экстракция -------------------------------------------------
def run_extraction(input_path: Path, limit: int | None, batch_size: int, model: str):
    conn = _ckpt_conn()
    done = _done_ids(conn)
    chunks = prioritize(load_chunks(input_path))
    todo = [c for c in chunks if c["chunk_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"[extract] всего чанков: {len(chunks)} | уже готово: {len(done)} | к обработке: {len(todo)}")
    if not todo:
        return

    import threading
    db_lock = threading.Lock()
    t0 = time.time()
    processed = 0
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        tasks = [
            prompts.build_messages(c["text"], c.get("section_title")) for c in batch
        ]

        def _save(idx, result):
            c = batch[idx]
            if isinstance(result, Exception):
                row = (c["chunk_id"], c["doc_id"], c.get("section_title"), c["text"],
                       None, 0, str(result)[:400], time.time())
            else:
                payload = result.get("json")
                ok = 1 if isinstance(payload, dict) else 0
                row = (c["chunk_id"], c["doc_id"], c.get("section_title"), c["text"],
                       json.dumps(payload, ensure_ascii=False) if payload else None,
                       ok, None if ok else "json_parse_failed", time.time())
            with db_lock:
                conn.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?)", row)
                conn.commit()

        complete_batch(
            tasks, model=model, json_schema=prompts.EXTRACTION_SCHEMA,
            temperature=0.1, max_tokens=3000, parse_json=True, on_result=_save,
        )
        processed += len(batch)
        el = time.time() - t0
        u = USAGE.snapshot()
        print(f"[extract] {processed}/{len(todo)} чанков | {el:.0f}s | "
              f"toks in/out {u['completion_input_tokens']}/{u['completion_output_tokens']} | "
              f"429:{u['rate_limit_hits']} retries:{u['retries']}")
    conn.close()


# --- фаза 2: построение графа -----------------------------------------------
class GraphBuilder:
    def __init__(self, use_embedding: bool = True):
        self.reg = norm.ConceptRegistry()
        self.use_embedding = use_embedding
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple, dict] = {}
        self._resolve_cache: dict[tuple, dict] = {}
        self._name_vecs: dict[str, list] = {}
        self.stats = {
            "chunks": 0, "entities": 0, "relations": 0, "assertions": 0,
            "conditions_in": 0, "conditions_kept": 0, "conditions_dropped": 0,
            "conditions_rule_added": 0,
            "matched": {"exact": 0, "embed": 0, "auto": 0},
        }

    _RESOLVABLE = ("Material", "Process", "Equipment", "Parameter", "Facility")

    def prepare_embeddings(self, rows):
        """Прегенерация эмбеддингов имён сущностей одним батчем (для скорости на масштабе).
        Собираем имена, не имеющие точного совпадения, и эмбеддим их разом (concurrency+cache)."""
        if not self.use_embedding:
            return
        import sys as _sys
        _sys.path.insert(0, str(_ROOT))
        from shared.yandex_client import embed  # noqa
        names: set[str] = set()
        for _cid, _did, _text, payload in rows:
            try:
                d = json.loads(payload)
            except Exception:
                continue
            for e in (d.get("entities") or []):
                if not isinstance(e, dict):
                    continue
                if e.get("type") in self._RESOLVABLE:
                    nm = (e.get("name") or "").strip()
                    if len(nm) >= 3 and self.reg.match_exact(nm, e.get("name_en")) is None:
                        names.add(nm)
            for c in (d.get("conditions") or []):
                if isinstance(c, dict):
                    pn = (c.get("param") or "").strip()
                    if len(pn) >= 3 and self.reg.match_exact(pn, None) is None:
                        names.add(pn)
        names_l = sorted(names)
        if not names_l:
            return
        print(f"[build] батч-эмбеддинг {len(names_l)} уникальных имён сущностей...")
        vecs = embed(names_l, kind="doc")
        self._name_vecs = {n: v for n, v in zip(names_l, vecs)}
        # прогреваем эмбеддинги концептов заранее
        self.reg._ensure_embeddings()

    def _resolve(self, name: str, etype: str, name_en: str | None):
        key = (name.lower().strip(), etype)
        if key in self._resolve_cache:
            return self._resolve_cache[key]
        qv = self._name_vecs.get(name.strip())
        r = self.reg.resolve(name, etype, name_en, use_embedding=self.use_embedding, query_vec=qv)
        self._resolve_cache[key] = r
        self.stats["matched"][r["matched"]] = self.stats["matched"].get(r["matched"], 0) + 1
        return r

    def _add_node(self, node_id, ntype, name, name_en, concept_id, props, conf, doc_id, aliases=None):
        n = self.nodes.get(node_id)
        if n is None:
            self.nodes[node_id] = {
                "id": node_id, "type": ntype, "name": name, "name_en": name_en or "",
                "aliases": sorted(set(aliases or [])), "concept_id": concept_id,
                "props": {k: v for k, v in (props or {}).items() if v is not None},
                "confidence": conf, "source_docs": [doc_id],
            }
        else:
            if doc_id not in n["source_docs"]:
                n["source_docs"].append(doc_id)
            for a in aliases or []:
                if a and a not in n["aliases"]:
                    n["aliases"].append(a)
            n["confidence"] = max(n["confidence"], conf)

    def _add_edge(self, src, dst, etype, props, doc_id, chunk_id, conf, method, extracted_at):
        if not src or not dst or src == dst:
            return
        key = (src, dst, etype, json.dumps(props or {}, sort_keys=True, ensure_ascii=False))
        if key in self.edges:
            return
        self.edges[key] = {
            "src": src, "dst": dst, "type": etype, "props": props or {},
            "source_doc": doc_id, "chunk_id": chunk_id, "confidence": conf,
            "method": method, "extracted_at": extracted_at, "created_by": "pipeline",
        }

    _CONF_MAP = {"high": 0.9, "medium": 0.7, "low": 0.5}

    @staticmethod
    def _quote_grounded(quote: str, text: str) -> bool:
        """Дословность цитаты с допуском на различия пробелов/регистра
        (LLM копирует из чанка, но иногда нормализует пробелы)."""
        if not quote:
            return False
        import re as _re
        q = _re.sub(r"\s+", " ", quote).strip().lower()
        t = _re.sub(r"\s+", " ", text).strip().lower()
        if q in t:
            return True
        # запасной вариант: длинная общая подпоследовательность слов (>=6 слов подряд)
        qw = q.split()
        if len(qw) >= 6:
            for n in (10, 8, 6):
                if len(qw) >= n and " ".join(qw[:n]) in t:
                    return True
        return False

    @staticmethod
    def _to_float(v):
        """Приведение значения к float (модель иногда шлёт строку/список)."""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            import re as _re
            m = _re.search(r"-?\d+(?:[.,]\d+)?", v)
            if m:
                try:
                    return float(m.group(0).replace(",", "."))
                except ValueError:
                    return None
        if isinstance(v, (list, tuple)) and v:
            return GraphBuilder._to_float(v[0])
        return None

    @staticmethod
    def _canon(value, unit):
        num = GraphBuilder._to_float(value)
        if num is None:
            return value, unit
        try:
            cv, cu = canonicalize_unit(num, unit or None)
            return (cv if cv is not None else num), (cu if cu is not None else unit)
        except Exception:  # noqa: BLE001
            return num, unit

    def _add_condition(self, c, doc_id, chunk_id, anchors, today, method="llm",
                       require_known_param=False) -> bool:
        """Создаёт узел Condition/Measurement + рёбра. Возвращает True, если узел новый.

        Parameter-узел создаётся ТОЛЬКО для известного концепта (точное/алиас/подстрока),
        иначе граф засоряется auto-параметрами из шумных param-строк rule-экстракции.
        require_known_param=True — если параметр неизвестен, условие не добавляется вовсе
        (используется для rule-аугментации: отсеивает случайные числа/даты/страницы)."""
        primary_process, primary_experiment, pub_id = anchors
        param_name = (c.get("param") or "").strip()
        quote = c.get("quote", "")
        # только надёжное сопоставление параметра (без embedding/auto)
        pcid = self.reg.match_exact(param_name)
        if pcid is None:
            pcid = self.reg.match_param(param_name + " " + quote)
        pconcept = self.reg.by_id.get(pcid) if pcid else None
        if pconcept and pconcept.get("type") != "Parameter":
            pcid, pconcept = None, None
        if require_known_param and pcid is None:
            return False

        value, unit = self._canon(c.get("value"), c.get("unit", ""))
        op = c.get("op", "=")
        disp_param = (pconcept.get("label_ru") if pconcept else None) or param_name or "показатель"
        cprops = {"param": disp_param, "op": op, "value": value, "unit": unit, "quote": quote}
        if pcid:
            cprops["param_concept"] = pcid
        if c.get("value2") is not None:
            cprops["value2"] = c.get("value2")

        pnode_id = None
        if pcid:
            pnode_id = f"param:{norm.slugify(pcid[2:] if pcid.startswith('c_') else pcid)}"
            self._add_node(pnode_id, "Parameter", pconcept.get("label_ru", disp_param),
                           pconcept.get("label_en", ""), pcid,
                           {"unit_canonical": pconcept.get("unit")}, 0.8, doc_id)

        id_base = pcid or ("free_" + norm.slugify(disp_param))
        kind = c.get("kind", "condition")
        if kind == "measurement":
            cid = norm.measurement_id(id_base, value, unit or "")
            is_new = cid not in self.nodes
            self._add_node(cid, "Measurement", f"{disp_param} {value} {unit}".strip(),
                           "", None, cprops, 0.85, doc_id)
            anchor = primary_experiment or primary_process or pub_id
            self._add_edge(anchor, cid, "measured", cprops, doc_id, chunk_id, 0.85, method, today)
        else:
            cid = norm.condition_id(id_base, op, value, unit or "")
            is_new = cid not in self.nodes
            self._add_node(cid, "Condition", f"{disp_param} {op} {value} {unit}".strip(),
                           "", None, cprops, 0.85, doc_id)
            anchor = primary_process or primary_experiment or pub_id
            self._add_edge(anchor, cid, "operates_at_condition", cprops, doc_id, chunk_id, 0.85, method, today)
        if pnode_id:
            self._add_edge(cid, pnode_id, "about", {}, doc_id, chunk_id, 0.8, method, today)
        return is_new

    def process(self, chunk_id: str, doc_id: str, text: str, payload: dict):
        self.stats["chunks"] += 1
        today = time.strftime("%Y-%m-%d")
        # Publication-узел документа (+ география из rules.detect_geography)
        pub_id = f"pub:{doc_id}"
        self._add_node(pub_id, "Publication", doc_id, "", f"c_pub_{doc_id}",
                       {"doc_id": doc_id}, 0.99, doc_id)
        if _HAS_RULES:
            try:
                geo = detect_geography(text)
                pnode = self.nodes[pub_id]["props"]
                if geo.get("geo"):
                    pnode["geography"] = geo["geo"]
                if geo.get("countries"):
                    have = set(pnode.get("countries", []))
                    pnode["countries"] = sorted(have | set(geo["countries"]))
            except Exception:  # noqa: BLE001
                pass

        name2node: dict[str, dict] = {}
        primary_process = None
        primary_experiment = None
        for e in payload.get("entities", []) or []:
            if not isinstance(e, dict):
                continue
            name = (e.get("name") or "").strip()
            etype = e.get("type")
            if not name or etype not in prompts.ENTITY_TYPES:
                continue
            self.stats["entities"] += 1
            if etype in ("Experiment", "Publication"):
                # экземплярные типы — не резолвим к реестру концептов
                nid = f"{norm.TYPE_PREFIX.get(etype,'ent')}:{norm.slugify(e.get('name_en') or name)}"
                self._add_node(nid, etype, name, e.get("name_en", ""), None, {}, 0.7, doc_id)
                info = {"node_id": nid, "type": etype}
                if etype == "Experiment" and not primary_experiment:
                    primary_experiment = nid
            else:
                r = self._resolve(name, etype, e.get("name_en"))
                props = {}
                if r.get("class"):
                    props["class"] = r["class"]
                if r.get("domain"):
                    props["domain"] = r["domain"]
                if r.get("unit"):
                    props["unit_canonical"] = r["unit"]
                if r["matched"] == "auto":
                    props["auto"] = True
                self._add_node(r["node_id"], etype, r["canonical_name"] or name,
                               r["canonical_en"], r["concept_id"], props, 0.8, doc_id,
                               aliases=[name])
                info = {"node_id": r["node_id"], "type": etype, "concept_id": r["concept_id"]}
                if etype == "Process" and not primary_process:
                    primary_process = r["node_id"]
            name2node[name.lower().strip()] = info
            # described_in -> публикация
            self._add_edge(info["node_id"], pub_id, "described_in", {}, doc_id, chunk_id,
                           0.8, "llm", today)

        # relations
        for rel in payload.get("relations", []) or []:
            if not isinstance(rel, dict):
                continue
            s = name2node.get((rel.get("src") or "").lower().strip())
            d = name2node.get((rel.get("dst") or "").lower().strip())
            rtype = rel.get("type")
            if s and d and rtype in prompts.RELATION_TYPES:
                self.stats["relations"] += 1
                self._add_edge(s["node_id"], d["node_id"], rtype, {}, doc_id, chunk_id,
                               0.75, "llm", today)

        anchors = (primary_process, primary_experiment, pub_id)

        # conditions / measurements от LLM (валидация чисел rules-модулем)
        conds = [c for c in (payload.get("conditions", []) or []) if isinstance(c, dict) and c.get("value") is not None]
        self.stats["conditions_in"] += len(conds)
        if conds:
            values = []
            for c in conds:
                v = c.get("value")
                values.append(v[0] if isinstance(v, (list, tuple)) and v else v)
            try:
                valid = validate_numbers(values, text)
            except Exception:  # noqa: BLE001 — устойчивость к внешнему модулю
                valid = [str(GraphBuilder._to_float(v) or v) in text or str(v) in text for v in values]
            for c, ok in zip(conds, valid):
                if not ok:
                    self.stats["conditions_dropped"] += 1
                    continue
                self.stats["conditions_kept"] += 1
                self._add_condition(c, doc_id, chunk_id, anchors, today, method="llm")

        # АУГМЕНТАЦИЯ: детерминированные условия из rules.extract_conditions
        # (числа уже дословно валидны — из самого текста). Дедуп по (param_concept, op, value, unit).
        if _HAS_RULES:
            try:
                rule_conds = extract_conditions(text)
            except Exception:  # noqa: BLE001
                rule_conds = []
            for rc in rule_conds:
                if rc.get("value") is None:
                    continue
                c = {
                    "param": rc.get("param") or "параметр",
                    "op": rc.get("op", "="),
                    "value": rc.get("value_canonical", rc.get("value")),
                    "value2": rc.get("value2"),
                    "unit": rc.get("unit_canonical") or rc.get("unit") or "",
                    "quote": rc.get("quote", ""),
                    "kind": "condition",
                }
                if self._add_condition(c, doc_id, chunk_id, anchors, today, method="rule",
                                       require_known_param=True):
                    self.stats["conditions_rule_added"] += 1

        # assertions
        for a in payload.get("assertions", []) or []:
            if not isinstance(a, dict):
                continue
            stmt = (a.get("statement") or "").strip()
            quote = (a.get("quote") or "").strip()
            if not stmt:
                continue
            self.stats["assertions"] += 1
            conf = a.get("confidence", "medium")
            aid = norm.assertion_id(stmt, chunk_id)
            self._add_node(aid, "Assertion", stmt, "", None, {
                "statement": stmt, "confidence": conf,
                "review_status": "auto", "n_sources": 1,
                "evidence": [{"doc_id": doc_id, "chunk_id": chunk_id, "quote": quote}],
                "quote_verbatim": self._quote_grounded(quote, text),
            }, self._CONF_MAP.get(conf, 0.7), doc_id)
            self._add_edge(aid, pub_id, "validated_by", {}, doc_id, chunk_id,
                           self._CONF_MAP.get(conf, 0.7), "llm", today)

    def write(self):
        NODES_OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(NODES_OUT, "w", encoding="utf-8") as f:
            for n in self.nodes.values():
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        with open(EDGES_OUT, "w", encoding="utf-8") as f:
            for e in self.edges.values():
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def build_graph(use_embedding: bool = True) -> GraphBuilder:
    conn = _ckpt_conn()
    rows = conn.execute(
        "SELECT chunk_id, doc_id, text, payload FROM extractions WHERE ok=1"
    ).fetchall()
    conn.close()
    gb = GraphBuilder(use_embedding=use_embedding)
    gb.prepare_embeddings(rows)
    for chunk_id, doc_id, text, payload in rows:
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if isinstance(data, dict):
            gb.process(chunk_id, doc_id, text or "", data)
    gb.write()
    return gb


# --- тонкие обёртки для однодокументной онлайн-экстракции (upload-pipeline) --
# Не трогают checkpoint-SQLite и глобальные graph/nodes.jsonl|edges.jsonl:
# работают полностью в памяти на переданном списке чанков и возвращают фрагмент
# графа для немедленного MERGE в Neo4j. Поведение CLI не меняется.

def extract_payloads(chunks, model="lite", limit=None, on_result=None):
    """LLM-экстракция для списка чанков В ПАМЯТИ (без записи в extractions.sqlite).

    chunks: list[dict] с ключами chunk_id, doc_id, text, section_title.
    Возвращает list[dict]: {chunk_id, doc_id, text, section_title, payload, ok, error}.
    Если ни один LLM-провайдер роли extraction недоступен — все строки ok=0
    (потребитель трактует стадию как «отложена»)."""
    todo = list(chunks)[: limit] if limit else list(chunks)
    if not todo:
        return []
    if not _gateway.is_available("extraction", default_model=model):
        return [{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "text": c["text"],
                 "section_title": c.get("section_title"), "payload": None, "ok": 0,
                 "error": "no extraction LLM provider available"} for c in todo]

    tasks = [prompts.build_messages(c["text"], c.get("section_title")) for c in todo]
    results: list = [None] * len(todo)

    def _cb(idx, res):
        c = todo[idx]
        if isinstance(res, Exception):
            row = {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "text": c["text"],
                   "section_title": c.get("section_title"), "payload": None, "ok": 0,
                   "error": str(res)[:400]}
        else:
            payload = (res or {}).get("json")
            ok = 1 if isinstance(payload, dict) else 0
            row = {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "text": c["text"],
                   "section_title": c.get("section_title"), "payload": payload, "ok": ok,
                   "error": None if ok else "json_parse_failed"}
        results[idx] = row
        if on_result:
            on_result(idx, row)

    complete_batch(tasks, model=model, json_schema=prompts.EXTRACTION_SCHEMA,
                   temperature=0.1, max_tokens=3000, parse_json=True, on_result=_cb)
    return [r for r in results if r]


def build_fragment(extractions, use_embedding=False):
    """Строит фрагмент графа (GraphBuilder) из результатов extract_payloads,
    БЕЗ записи в глобальные файлы. Возвращает GraphBuilder (см. .nodes/.edges)."""
    gb = GraphBuilder(use_embedding=use_embedding)
    ok_rows = [e for e in extractions if e.get("ok") and isinstance(e.get("payload"), dict)]
    if use_embedding and ok_rows:
        gb.prepare_embeddings([(e["chunk_id"], e["doc_id"], e["text"],
                                json.dumps(e["payload"], ensure_ascii=False)) for e in ok_rows])
    for e in ok_rows:
        try:
            gb.process(e["chunk_id"], e["doc_id"], e.get("text", ""), e["payload"])
        except Exception:  # noqa: BLE001 — устойчивость к отдельным шумным чанкам
            pass
    return gb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(_ROOT / "corpus" / "chunks.jsonl"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--model", default="lite")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--no-embed-match", action="store_true")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        dev = _ROOT / "corpus" / "dev_chunks.jsonl"
        print(f"[runner] {inp} не найден -> использую dev-выборку {dev}")
        inp = dev

    if not args.build_only:
        run_extraction(inp, args.limit, args.batch_size, args.model)

    print("[build] строю граф из накопленных экстракций...")
    gb = build_graph(use_embedding=not args.no_embed_match)
    print(f"[build] узлов: {len(gb.nodes)} | рёбер: {len(gb.edges)}")
    print("[build] статистика:", json.dumps(gb.stats, ensure_ascii=False))
    print("[usage]", json.dumps(USAGE.snapshot(), ensure_ascii=False))
    # разбивка узлов по типам
    from collections import Counter
    print("[nodes by type]", dict(Counter(n["type"] for n in gb.nodes.values())))
    print("[edges by type]", dict(Counter(e["type"] for e in gb.edges.values())))


if __name__ == "__main__":
    main()
