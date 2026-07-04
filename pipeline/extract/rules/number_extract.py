"""Парсинг чисел и валидатор дословного присутствия числа в тексте.

Ключевой принцип: число, отсутствующее дословно в источнике, в граф не
попадает. ``validate_numbers`` возвращает ``True`` только если число реально
встречается в тексте (с учётом форматов: запятая/точка десятичный
разделитель, пробелы-разделители тысяч, диапазоны «200–300», «±»).
"""
from __future__ import annotations

import math
import re
from typing import List, Union

# Число: сгруппированные тысячи ("1 250", "25 000") ИЛИ обычное целое/дробное.
NUM = r"\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_NUM_RE = re.compile(NUM)

_SP = "    "


def _norm_spaces(s: str) -> str:
    for c in _SP:
        s = s.replace(c, " ")
    # схлопываем повторные пробелы для сравнения подстрок
    return s


def parse_number(raw: str) -> float:
    """Разбирает строковое представление числа в float.

    Обрабатывает: «92,5» (запятая-десятичная, RU по умолчанию),
    «1,250.5» (запятая-тысячи, точка-десятичная), «1.250,5» (европейская),
    «1 250» / «25 000» (пробелы-тысячи), знаки «+/-», юникод-минус.
    """
    s = raw.strip()
    for c in _SP:
        s = s.replace(c, " ")
    s = s.replace("−", "-").replace("–", "-")
    neg = s[:1] == "-"
    s = s.lstrip("+-").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # запятая — десятичная, точка — тысячи
            s = s.replace(".", "").replace(",", ".")
        else:
            # точка — десятичная, запятая — тысячи
            s = s.replace(",", "")
    elif "," in s:
        # только запятая — по умолчанию десятичная (RU)
        s = s.replace(",", ".")
    val = float(s)
    return -val if neg else val


def _text_floats(text: str) -> set:
    """Множество float-значений, встречающихся в тексте дословно."""
    out = set()
    t = _norm_spaces(text)
    for m in _NUM_RE.finditer(t):
        tok = m.group(0)
        try:
            out.add(parse_number(tok))
        except ValueError:
            continue
        # неоднозначные «1,250» / «1.250» — добавляем и тысячную трактовку
        if re.fullmatch(r"\d{1,3},\d{3}", tok):
            out.add(float(tok.replace(",", "")))
        if re.fullmatch(r"\d{1,3}\.\d{3}", tok):
            out.add(float(tok.replace(".", "")))
    return out


def _float_in(val: float, floats: set) -> bool:
    return any(math.isclose(val, f, rel_tol=1e-9, abs_tol=1e-9) for f in floats)


def _format_variants(val: float) -> List[str]:
    out = []
    if val == int(val):
        iv = int(val)
        out.append(str(iv))
        # с пробелами-разделителями тысяч
        s = f"{iv:,}".replace(",", " ")
        out.append(s)
        out.append(f"{iv:,}")  # 1,250
    else:
        s = repr(val)
        out.append(s)
        out.append(s.replace(".", ","))
    return out


def validate_numbers(numbers: List[Union[float, str]], chunk_text: str) -> List[bool]:
    """Для каждого числа проверяет дословное присутствие в ``chunk_text``.

    ``numbers`` — список float/int или строк. Возвращает список bool той же
    длины.
    """
    floats = _text_floats(chunk_text)
    norm_text = _norm_spaces(chunk_text)
    results: List[bool] = []
    for q in numbers:
        ok = False
        if isinstance(q, str):
            raw = q.strip()
            if raw and _norm_spaces(raw) in norm_text:
                ok = True
            else:
                try:
                    val = parse_number(raw)
                except (ValueError, IndexError):
                    val = None
                if val is not None and _float_in(val, floats):
                    ok = True
        else:
            try:
                val = float(q)
            except (TypeError, ValueError):
                results.append(False)
                continue
            if _float_in(val, floats):
                ok = True
            else:
                for s in _format_variants(val):
                    if s in norm_text:
                        ok = True
                        break
        results.append(ok)
    return results
