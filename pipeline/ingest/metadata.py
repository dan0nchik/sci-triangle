"""A2: derive document metadata from the file path / name.

Fields produced (contract §4.1): section, journal, year, source_type,
geography_hint, wave.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Optional

# Top-level section directory name -> canonical section label
SECTION_MAP = {
    "обзоры": "Обзоры",
    "статьи": "Статьи",
    "доклады": "Доклады",
    "журналы": "Журналы",
    "материалы конференций": "Материалы конференций",
}

# Known journal directory names (under Журналы/)
KNOWN_JOURNALS = {
    "цветные металлы": "Цветные металлы",
    "горная промышленность": "Горная промышленность",
    "горный журнал": "Горный журнал",
    "обогащение руд": "Обогащение руд",
}

# Foreign / market-report source markers found in "Материалы конференций"
FOREIGN_MARKERS = (
    "copper", "alta", "new caledonia", "ausimm", "mill operators",
    "handbook", "flotation", "corrosion atlas", "mitsui", "cru", "gfms",
    "icsg", "antaike", "barclays", "brook hunt", "metal bulletin", "bme",
)
MARKET_REPORT_MARKERS = (
    "источники данных", "cru", "gfms", "mitsui", "icsg", "antaike",
    "barclays", "brook hunt", "metal bulletin", "bme", "market",
)

_year_re = re.compile(r"(19|20)\d{2}")


def _find_year(parts: list[str], filename: str) -> Optional[int]:
    """Look for a 4-digit year: prefer a path component that IS a year, then
    a year embedded in a component, then in the filename."""
    # 1) a path component that is exactly a year (possibly "2005-2", "2018-все")
    for p in parts:
        m = re.match(r"^((?:19|20)\d{2})", p.strip())
        if m:
            return int(m.group(1))
    # 2) year embedded anywhere in a directory component
    for p in parts:
        m = _year_re.search(p)
        if m:
            y = int(m.group(0))
            if 1950 <= y <= 2026:
                return y
    # 3) filename (e.g. CM_01_11.pdf -> 2011 handled elsewhere; generic year)
    m = _year_re.search(filename)
    if m:
        y = int(m.group(0))
        if 1950 <= y <= 2026:
            return y
    # 4) two-digit journal codes like CM_01_11 -> 2011
    m2 = re.search(r"_(\d{2})(?:[._]|$)", filename)
    if m2:
        yy = int(m2.group(1))
        if 0 <= yy <= 26:
            return 2000 + yy
        if 95 <= yy <= 99:
            return 1900 + yy
    return None


def _ext(filename: str) -> str:
    i = filename.rfind(".")
    return filename[i:].lower() if i >= 0 else ""


def derive(rel_path: str) -> dict:
    """rel_path is relative to DATA_ROOT, posix-style.

    Returns dict with section, journal, year, source_type, geography_hint, wave.
    """
    pp = PurePosixPath(rel_path)
    parts = list(pp.parts)
    filename = pp.name
    ext = _ext(filename)
    lower_parts = [p.lower() for p in parts]
    full_lower = rel_path.lower()

    # --- section -----------------------------------------------------------
    section = None
    for p in lower_parts:
        if p in SECTION_MAP:
            section = SECTION_MAP[p]
            break
    if section is None:
        section = "Материалы конференций"  # default bucket

    # --- journal -----------------------------------------------------------
    journal = None
    if section == "Журналы":
        for p in lower_parts:
            if p in KNOWN_JOURNALS:
                journal = KNOWN_JOURNALS[p]
                break

    # --- year --------------------------------------------------------------
    # only look at path components *below* the section for cleaner years
    year = _find_year(parts, filename)

    # --- source_type -------------------------------------------------------
    if section == "Обзоры":
        source_type = "review"
    elif section == "Статьи":
        source_type = "article"
    elif section == "Доклады":
        source_type = "presentation" if ext in (".pptx", ".ppt") else "report"
    elif section == "Журналы":
        source_type = "article"
    else:  # Материалы конференций
        if any(m in full_lower for m in MARKET_REPORT_MARKERS):
            source_type = "market_report"
        elif ext in (".xls", ".xlsx"):
            source_type = "market_report"
        elif "handbook" in full_lower or "atlas" in full_lower:
            source_type = "book"
        else:
            source_type = "proceedings"

    # --- geography_hint ----------------------------------------------------
    if section in ("Обзоры", "Статьи", "Доклады"):
        geography_hint = "RU"
    elif section == "Журналы":
        geography_hint = "RU"
    else:
        if any(m in full_lower for m in FOREIGN_MARKERS):
            geography_hint = "foreign"
        else:
            geography_hint = "global"

    # --- wave (§3) ---------------------------------------------------------
    wave = _wave(section, source_type, year, full_lower)

    return {
        "section": section,
        "journal": journal,
        "year": year,
        "source_type": source_type,
        "geography_hint": geography_hint,
        "wave": wave,
    }


def _wave(section: str, source_type: str, year: Optional[int], full_lower: str) -> int:
    # Wave 1: Обзоры + Статьи + Доклады
    if section in ("Обзоры", "Статьи", "Доклады"):
        return 1
    # Wave 2: Журналы 2015-2025 ; older journals -> wave 4
    if section == "Журналы":
        if year is not None and 2015 <= year <= 2025:
            return 2
        return 4
    # Материалы конференций
    if source_type == "market_report":
        return 4
    # conferences + books -> wave 3
    if source_type in ("proceedings", "book"):
        return 3
    return 4
