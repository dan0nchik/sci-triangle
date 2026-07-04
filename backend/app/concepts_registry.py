"""Concept registry (shared/concepts.yaml) — read-only term mapping for the planner.

Maps a free surface term (RU/EN, any case) to a canonical concept and to the set
of surface forms (label_ru, label_en, aliases) used to anchor graph entities.

We deliberately match graph entities by *surface form* (name/name_en/aliases), not
by concept_id, because the fixture graph uses its own concept_id scheme
(c_ew_ni, c_catholyte, ...) that differs from the registry (c_electrowinning, ...).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml

_REPO = Path(__file__).resolve().parent.parent.parent
_CONCEPTS_YAML = _REPO / "shared" / "concepts.yaml"

_CONCEPTS: List[dict] = []
_BY_FORM: Dict[str, dict] = {}   # lowercased surface form -> concept dict


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _load() -> None:
    global _CONCEPTS
    if _CONCEPTS:
        return
    try:
        data = yaml.safe_load(_CONCEPTS_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    _CONCEPTS = data.get("concepts", []) or []
    for c in _CONCEPTS:
        forms = surface_forms(c)
        c["_forms"] = forms
        for f in forms:
            key = _norm(f)
            # keep the concept with the longest label as canonical for a form
            if key and key not in _BY_FORM:
                _BY_FORM[key] = c


def surface_forms(concept: dict) -> List[str]:
    forms = []
    for k in ("label_ru", "label_en"):
        if concept.get(k):
            forms.append(concept[k])
    forms += list(concept.get("aliases") or [])
    # dedupe preserve order
    seen, out = set(), []
    for f in forms:
        if f and f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out


def all_concepts() -> List[dict]:
    _load()
    return _CONCEPTS


def match_term(term: str) -> Optional[dict]:
    """Resolve a surface term to a registry concept (exact form, then substring)."""
    _load()
    key = _norm(term)
    if not key:
        return None
    if key in _BY_FORM:
        return _BY_FORM[key]
    # token-aware substring: concept form fully contained in the term or vice versa
    best = None
    best_len = 0
    for form, c in _BY_FORM.items():
        if len(form) < 4:
            continue
        if form in key or key in form:
            if len(form) > best_len:
                best, best_len = c, len(form)
    return best


def expand_forms(term: str) -> List[str]:
    """Return canonical surface forms for a term (itself + registry expansions)."""
    forms = [term]
    c = match_term(term)
    if c:
        forms += c.get("_forms", [])
    # dedupe
    seen, out = set(), []
    for f in forms:
        fl = _norm(f)
        if fl and fl not in seen:
            seen.add(fl)
            out.append(f)
    return out


def concept_type(term: str) -> Optional[str]:
    c = match_term(term)
    return c.get("type") if c else None
