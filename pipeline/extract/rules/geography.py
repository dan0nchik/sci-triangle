"""Гео-детектор: страна/регион из текста и метаданных -> RU / foreign / global.

Возвращает ``{"geo": "RU"|"foreign"|"global"|None, "countries": [...]}``.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# (regex, каноническая страна, класс "RU"/"foreign")
# Города/комбинаты/заводы маппятся на свою страну.
_MARKERS = [
    # --- Россия ---
    (r"\bНорильск\w*", "Россия", "RU"),
    (r"\bМончегорск\w*", "Россия", "RU"),
    (r"Кольск\w*\s+ГМК|\bКГМК\b|Кольская\s+горно", "Россия", "RU"),
    (r"\bТалнах\w*", "Россия", "RU"),
    (r"\bКайеркан\w*", "Россия", "RU"),
    (r"\bЗаполярн\w*", "Россия", "RU"),
    (r"\bНадеждинск\w*|Надеждинский\s+металлург", "Россия", "RU"),
    (r"\bГипроникел\w*", "Россия", "RU"),
    (r"\bПеченг\w*", "Россия", "RU"),
    (r"\bМурманск\w*", "Россия", "RU"),
    (r"\bКрасноярск\w*", "Россия", "RU"),
    (r"\bХараелах\w*", "Россия", "RU"),
    (r"\bОктябрьск\w*\s+месторожд", "Россия", "RU"),
    (r"\bРоссия\b|\bРоссийск\w+|\bРФ\b|\bСССР\b", "Россия", "RU"),
    (r"\bКазахстан\w*", "Казахстан", "foreign"),
    # --- Чили ---
    (r"\bЧили\b|\bChile\b|El\s+Soldado|Chuquicamata|Escondida|Collahuasi", "Чили", "foreign"),
    # --- Австралия ---
    (r"\bАвстрали\w*|\bAustralia\b|Kalgoorlie|Olympic\s+Dam", "Австралия", "foreign"),
    # --- Новая Каледония ---
    (r"Нов\w*\s+Каледони\w*|New\s+Caledonia|Doniambo|\bGoro\b|Koniambo", "Новая Каледония", "foreign"),
    # --- Испания (Уэльва, Las Cruces) ---
    (r"\bУэльв\w*|\bHuelva\b|Las\s+Cruces|\bИспани\w*|\bSpain\b|Atlantic\s+Copper", "Испания", "foreign"),
    # --- Канада ---
    (r"\bКанад\w*|\bCanada\b|\bSudbury\b|Thompson|Voisey", "Канада", "foreign"),
    # --- ЮАР ---
    (r"\bЮАР\b|South\s+Africa|Rustenburg|Stillfontein|Beatrix|Bushveld", "ЮАР", "foreign"),
    # --- Финляндия ---
    (r"\bФинлянди\w*|\bFinland\b|Харьявалт\w*|Harjavalta|\bKevitsa\b", "Финляндия", "foreign"),
    # --- Монголия ---
    (r"\bМонголи\w*|\bMongolia\b|Oyu\s+Tolgoi", "Монголия", "foreign"),
    # --- Куба ---
    (r"\bКуб[аеы]\b|\bCuba\b|Punta\s+Gorda|Moa\b", "Куба", "foreign"),
    # --- Колумбия (Cerro Matoso) ---
    (r"Cerro\s+Matoso|\bКолумби\w*|\bColombia\b", "Колумбия", "foreign"),
    # --- Франция (Sandouville) ---
    (r"Sandouville|\bФранци\w*|\bFrance\b", "Франция", "foreign"),
    # --- Норвегия ---
    (r"\bНорвеги\w*|\bNorway\b|Kristiansand|\bNikkelverk\b", "Норвегия", "foreign"),
    # --- прочие ---
    (r"\bКитай\b|\bChina\b|\bКитайск\w+", "Китай", "foreign"),
    (r"\bИндонези\w*|\bIndonesia\b", "Индонезия", "foreign"),
    (r"\bЗамби\w*|\bZambia\b", "Замбия", "foreign"),
    (r"\bКонго\b|\bDRC\b|Демократическая\s+Республика\s+Конго", "Конго", "foreign"),
    (r"\bБразили\w*|\bBrazil\b", "Бразилия", "foreign"),
    (r"\bПеру\b|\bPeru\b", "Перу", "foreign"),
    (r"\bСША\b|\bUSA\b|United\s+States|\bШтат\w+", "США", "foreign"),
    (r"\bШвеци\w*|\bSweden\b|Rönnskär|Ronnskar|Boliden", "Швеция", "foreign"),
    (r"\bГермани\w*|\bGermany\b|Aurubis", "Германия", "foreign"),
    (r"\bЯпони\w*|\bJapan\b|Sumitomo", "Япония", "foreign"),
]

_GLOBAL_RE = re.compile(
    r"\bв\s+мире\b|\bмиров\w+|\bglobal\b|\bworldwide\b|\binternational\b|\bмеждународн\w+",
    re.IGNORECASE,
)

_COMPILED = [(re.compile(p, re.IGNORECASE), c, g) for p, c, g in _MARKERS]


def detect_geography(text: str, meta: Optional[dict] = None) -> Dict:
    """Определяет географию текста (+метаданных).

    ``meta`` может содержать ``path``/``filename``/``geography_hint`` —
    они также сканируются.
    """
    meta = meta or {}
    haystacks = [text or ""]
    for key in ("path", "filename", "title", "section"):
        v = meta.get(key)
        if isinstance(v, str):
            haystacks.append(v)
    blob = "\n".join(haystacks)

    countries: List[str] = []
    classes = set()
    for rx, country, cls in _COMPILED:
        if rx.search(blob):
            if country not in countries:
                countries.append(country)
            classes.add(cls)

    has_ru = "RU" in classes
    has_foreign = "foreign" in classes

    if has_ru and has_foreign:
        geo = "global"
    elif has_ru:
        geo = "RU"
    elif has_foreign:
        geo = "foreign"
    else:
        geo = None

    # geography_hint из метаданных как fallback
    if geo is None:
        hint = meta.get("geography_hint") or meta.get("geo")
        if hint in ("RU", "foreign", "global"):
            geo = hint

    # мировые маркеры (слабый сигнал) — только если стран не нашли
    if geo is None and _GLOBAL_RE.search(blob):
        geo = "global"

    return {"geo": geo, "countries": countries}
