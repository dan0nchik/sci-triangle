"""
normalize.py — нормализация извлечённых сущностей к concept_id и генерация
ID узлов по конвенции PLAN §4.2.

Стратегия сопоставления (PLAN B9):
  1. точное совпадение по label_ru/label_en/alias (регистр/пробелы нормализуются)
  2. эмбеддинг-матчинг: cosine(имя, концепт) > THRESHOLD (0.85)
  3. иначе — новый auto-концепт (пометка matched='auto')

ID-конвенция §4.2:
  mat: proc: eq: param: cond: meas: exp: pub:{doc_id} person: fac: assert: + slug (лат.)
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent
CONCEPTS_PATH = _ROOT / "shared" / "concepts.yaml"

# Порог косинуса для эмбеддинг-матчинга. ВАЖНО: сопоставляем в ОДНОМ пространстве
# (text-search-doc для обеих сторон). Пары doc/query у Yandex асимметричны и дают
# заниженный косинус (~0.52 у синонимов) — для матчинга концептов непригодны.
# В doc-doc пространстве истинные синонимы дают ~0.83+, поэтому берём 0.83
# (контракт §B9 ориентировался на 0.85 в предположении общего пространства).
EMB_THRESHOLD = 0.83

TYPE_PREFIX = {
    "Material": "mat",
    "Process": "proc",
    "Equipment": "eq",
    "Parameter": "param",
    "Facility": "fac",
    "Expert": "person",
    "Experiment": "exp",
    "Publication": "pub",
    "Condition": "cond",
    "Measurement": "meas",
    "Assertion": "assert",
}

# --- транслитерация RU->LAT для slug ----------------------------------------
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str, maxlen: int = 40) -> str:
    text = text.lower().strip()
    out = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in " -_/":
            out.append("_")
        # прочее (не-ascii, знаки) отбрасываем
    slug = "".join(out)
    slug = re.sub(r"_+", "_", slug).strip("_")
    slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
    return slug[:maxlen] or "x"


def _norm_key(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("ё", "е")
    return s


class ConceptRegistry:
    def __init__(self, path: str | Path = CONCEPTS_PATH):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.concepts: list[dict] = data["concepts"]
        self.by_id = {c["concept_id"]: c for c in self.concepts}
        self.alias_index: dict[str, str] = {}  # norm_key -> concept_id
        for c in self.concepts:
            keys = [c.get("label_ru", ""), c.get("label_en", "")]
            keys += c.get("aliases", []) or []
            for k in keys:
                if k:
                    self.alias_index.setdefault(_norm_key(k), c["concept_id"])
        # для эмбеддинг-матчинга (ленивая инициализация)
        self._emb_matrix = None
        self._emb_ids: list[str] = []
        # runtime auto-концепты
        self.auto: dict[str, dict] = {}

    # --- точное / алиас -----------------------------------------------------
    def match_exact(self, name: str, name_en: str | None = None) -> str | None:
        cid = self.alias_index.get(_norm_key(name))
        if cid:
            return cid
        if name_en:
            return self.alias_index.get(_norm_key(name_en))
        return None

    def _param_aliases(self):
        if getattr(self, "_param_alias_cache", None) is None:
            pa = []
            for c in self.concepts:
                if c.get("type") != "Parameter":
                    continue
                for k in [c.get("label_ru", ""), c.get("label_en", "")] + (c.get("aliases") or []):
                    if k and len(k) >= 3:
                        pa.append((_norm_key(k), c["concept_id"]))
            pa.sort(key=lambda x: -len(x[0]))  # длинные алиасы первыми
            self._param_alias_cache = pa
        return self._param_alias_cache

    def match_param(self, text: str) -> str | None:
        """Ищет известный Parameter-концепт как подстроку в тексте (для шумного param
        из rule-экстракции). Возвращает concept_id самого длинного совпавшего алиаса."""
        t = _norm_key(text)
        for alias, cid in self._param_aliases():
            if alias in t:
                return cid
        return None

    # --- эмбеддинг-матчинг --------------------------------------------------
    def _ensure_embeddings(self):
        if self._emb_matrix is not None:
            return
        import sys

        sys.path.insert(0, str(_ROOT))
        from shared.yandex_client import embed  # noqa

        texts = []
        ids = []
        for c in self.concepts:
            txt = f"{c.get('label_ru','')} {c.get('label_en','')}".strip()
            texts.append(txt)
            ids.append(c["concept_id"])
        vecs = embed(texts, kind="doc")
        self._emb_matrix = vecs
        self._emb_ids = ids

    def match_embedding(
        self, name: str, threshold: float = EMB_THRESHOLD, query_vec=None
    ) -> tuple[str | None, float]:
        import sys

        sys.path.insert(0, str(_ROOT))
        from shared.yandex_client import embed, cosine  # noqa

        self._ensure_embeddings()
        # то же пространство, что и у концептов (doc), иначе косинус занижен
        qv = query_vec if query_vec is not None else embed([name], kind="doc")[0]
        best_id, best = None, 0.0
        for cid, cv in zip(self._emb_ids, self._emb_matrix):
            s = cosine(qv, cv)
            if s > best:
                best, best_id = s, cid
        if best >= threshold:
            return best_id, best
        return None, best

    # --- полный резолвинг сущности -----------------------------------------
    def resolve(
        self, name: str, etype: str, name_en: str | None = None, use_embedding: bool = True,
        query_vec=None,
    ) -> dict[str, Any]:
        """
        Возвращает dict: {concept_id, node_id, matched, score, canonical_name, canonical_en}
        matched in {exact, alias, embed, auto}
        """
        prefix = TYPE_PREFIX.get(etype, "ent")

        cid = self.match_exact(name, name_en)
        matched = "exact"
        score = 1.0
        if cid is None and use_embedding and len(name) >= 3:
            cid, score = self.match_embedding(name, query_vec=query_vec)
            matched = "embed" if cid else None
        if cid is None:
            # новый auto-концепт
            cid = self._make_auto(name, etype, name_en)
            matched = "auto"
            score = 0.0

        c = self.by_id.get(cid) or self.auto.get(cid, {})
        # node_id: prefix + slug концепта
        base_slug = cid[2:] if cid.startswith("c_") else slugify(name_en or name)
        node_id = f"{prefix}:{slugify(base_slug)}"
        return {
            "concept_id": cid,
            "node_id": node_id,
            "matched": matched,
            "score": round(score, 3),
            "canonical_name": c.get("label_ru", name),
            "canonical_en": c.get("label_en", name_en or ""),
            "class": c.get("class"),
            "domain": c.get("domain"),
            "unit": c.get("unit"),
        }

    def _make_auto(self, name: str, etype: str, name_en: str | None) -> str:
        cid = "c_auto_" + slugify(name_en or name)
        if cid not in self.auto and cid not in self.by_id:
            self.auto[cid] = {
                "concept_id": cid,
                "type": etype,
                "label_ru": name,
                "label_en": name_en or "",
                "aliases": [],
                "auto": True,
            }
        return cid


# --- генерация ID для условий/измерений/ассертов ----------------------------
def condition_id(param_concept: str, op: str, value, unit: str) -> str:
    op_word = {"=": "eq", "<": "lt", ">": "gt", "<=": "le", ">=": "ge", "range": "rng"}.get(op, "eq")
    base = param_concept[2:] if param_concept.startswith("c_") else param_concept
    return f"cond:{slugify(base)}_{op_word}_{slugify(str(value))}{('_'+slugify(unit)) if unit else ''}"


def measurement_id(param_concept: str, value, unit: str) -> str:
    base = param_concept[2:] if param_concept.startswith("c_") else param_concept
    return f"meas:{slugify(base)}_{slugify(str(value))}{('_'+slugify(unit)) if unit else ''}"


def assertion_id(statement: str, chunk_id: str) -> str:
    import hashlib

    h = hashlib.sha1((chunk_id + "|" + statement).encode("utf-8")).hexdigest()[:10]
    return f"assert:{h}"
