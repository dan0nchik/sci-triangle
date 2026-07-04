"""Детерминированная экстракция числовых условий/измерений из текста (RU/EN).

Публичная функция: ``extract_conditions(text) -> list[dict]``.

Каждый dict:
    {"param", "op", "value", "value2", "unit", "unit_canonical",
     "value_canonical", "span", "quote", "qualitative"}

Покрытие: компараторы (≤ ≥ < > не более/не менее/до/от/свыше/около/up to/at
least/approx…), диапазоны («200–300 мг/л», «от 100 до 200», «between X and
Y», «1250±20 °C»), доменные единицы, русская типографика (запятая-десятичная,
неразрывные пробелы), параметр слева от числа, а также качественные условия
(«холодный климат»).
"""
from __future__ import annotations

import re
from typing import List, Optional

from .numbers import NUM, parse_number
from .units import canonicalize_unit

NUM_G = r"(?:" + NUM + r")"

# ---------------------------------------------------------------------------
# Единицы (в том виде, как встречаются в тексте). Порядок при сборке — по
# убыванию длины, чтобы предпочитать самое длинное совпадение.
# ---------------------------------------------------------------------------
_UNIT_TOKENS = [
    # концентрация
    "мг/дм³", "мг/дм3", "г/дм³", "г/дм3", "мкг/дм³", "мкг/дм3",
    "мкг/л", "мг/л", "г/л", "ммоль/л", "моль/дм³", "моль/дм3", "моль/л",
    # массовое отношение
    "г/т", "кг/т", "мг/т",
    # проценты / промилле
    "масс.%", "мас.%", "об.%", "% масс", "% мас", "%масс", "%мас", "%",
    "ppm", "млн⁻¹", "млн-1",
    # температура
    "°C", "°С", "℃", "K", "К",
    # давление
    "МПа", "кПа", "ГПа", "гПа", "мПа", "Па", "атм", "мбар", "бар",
    "psi", "кгс/см²", "кгс/см2",
    # плотность тока
    "кА/м²", "кА/м2", "А/дм²", "А/дм2", "мА/см²", "мА/см2",
    "А/см²", "А/см2", "А/м²", "А/м2",
    # объёмный расход
    "м³/сут", "м3/сут", "м³/ч", "м3/ч", "м³/с", "м3/с",
    "л/мин", "л/ч", "л/с",
    # массовый расход
    "т/сут", "кг/сут", "т/год", "т/ч", "кг/ч",
    # длина
    "мкм", "нм", "мм", "см",
    # скорость
    "мм/с", "км/ч", "м/с",
    # частота вращения
    "об/мин", "об/с", "rpm",
    # удельная энергия
    "кВт·ч/т", "кВт∙ч/т", "кВт*ч/т", "МВт·ч/т", "kWh/t",
    # деньги
    "USD/т", "USD/t", "$/т", "$/t",
    # объём / молярность
    "м³", "м3", "мл", "л", "М",
]

_UNIT_SORTED = sorted(set(_UNIT_TOKENS), key=len, reverse=True)
_UNIT_ALT = "|".join(re.escape(t) for t in _UNIT_SORTED)
# после единицы не должно идти буквы (чтобы «м» не съедал «мг», «К» — слово)
_UNIT_G = r"(?P<unit>" + _UNIT_ALT + r")(?![A-Za-zА-Яа-яЁё])"

# ---------------------------------------------------------------------------
# Компараторы
# ---------------------------------------------------------------------------
_LE = ["≤", "⩽", "≦", "не более", "не выше", "не превышает", "не должно превышать",
       "до", "at most", "no more than", "up to", "maximum", "max"]
_LT = ["<", "менее", "ниже", "меньше", "below", "under", "less than", "lower than"]
_GE = ["≥", "⩾", "≧", "не менее", "не ниже", "от", "at least", "no less than",
       "minimum", "min"]
_GT = [">", "более", "свыше", "выше", "больше", "превышает", "over", "above",
       "greater than", "more than", "exceeds"]
_EQ = ["=", "равно", "равен", "равна", "составляет", "составляют", "составил",
       "составила", "составляла"]
_APPROX = ["~", "∼", "≈", "≃", "∽", "около", "порядка", "примерно",
           "приблизительно", "ориентировочно", "approx.", "approx",
           "approximately", "about", "around", "circa"]

_SYM = set("≤⩽≦<≥⩾≧>=~∼≈≃∽")


def _build_comp_map():
    m = {}
    for op, lst in (("<=", _LE), ("<", _LT), (">=", _GE), (">", _GT),
                    ("=", _EQ), ("approx", _APPROX)):
        for s in lst:
            m[s.lower()] = op
    return m


_COMP_MAP = _build_comp_map()


def _norm_comp(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(".")


def _comp_alt(surfaces) -> str:
    parts = []
    for s in sorted(surfaces, key=len, reverse=True):
        parts.append(r"\s+".join(re.escape(w) for w in s.split(" ")))
    return "|".join(parts)


_WORD_COMPS = [s for s in _COMP_MAP if s[0] not in _SYM]
_SYM_COMPS = [s for s in _COMP_MAP if s[0] in _SYM]

# слово-компаратор не должен быть внутри слова (лукбехайнд)
_D_WORD = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])(?P<comp>" + _comp_alt(_WORD_COMPS) + r")\s*"
    + r"(?P<num>" + NUM_G + r")(?:\s*" + _UNIT_G + r")?",
    re.IGNORECASE,
)
_D_SYM = re.compile(
    r"(?P<comp>" + _comp_alt(_SYM_COMPS) + r")\s*"
    + r"(?P<num>" + NUM_G + r")(?:\s*" + _UNIT_G + r")?",
)

# диапазон через тире
_DASH = r"\s*(?:–|—|÷|-)\s*"
_C_RANGE = re.compile(
    r"(?P<n1>" + NUM_G + r")" + _DASH + r"(?P<n2>" + NUM_G + r")\s*" + _UNIT_G,
)
# «от X до Y», «between X and Y», «между X и Y», «from X to Y»
_B_RANGE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])(?:от|from|between|между)\s+(?P<n1>" + NUM_G + r")\s+"
    r"(?:до|to|and|и)\s+(?P<n2>" + NUM_G + r")(?:\s*" + _UNIT_G + r")?",
    re.IGNORECASE,
)
# ± (толеранс): 1250±20 °C
_A_PM = re.compile(
    r"(?P<n1>" + NUM_G + r")\s*(?:±|\+/-|\+-)\s*(?P<n2>" + NUM_G + r")"
    r"(?:\s*" + _UNIT_G + r")?",
)
# pH
_F_PH = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])(?P<ph>рН|pH|ph|рн)\s*[=:—–]?\s*"
    r"(?P<comp>" + _comp_alt(_SYM_COMPS) + r")?\s*"
    r"(?P<n1>" + NUM_G + r")(?:" + _DASH + r"(?P<n2>" + NUM_G + r"))?",
)
# измерение: число + единица (op «=»)
_E_MEAS = re.compile(
    r"(?<![\d.,])(?P<num>" + NUM_G + r")\s*" + _UNIT_G,
)

# ---------------------------------------------------------------------------
# Качественные условия
# ---------------------------------------------------------------------------
_QUAL = [
    (re.compile(r"холодн\w*\s+климат\w*|климат\w*[\s:.—–-]+холодн\w*|"
                r"cold\s+climate|арктическ\w+\s+климат|суров\w+\s+климат", re.I),
     "холодный климат"),
    (re.compile(r"жарк\w+\s+климат|hot\s+climate|тропическ\w+\s+климат", re.I),
     "жаркий климат"),
    (re.compile(r"засушлив\w+|аридн\w+|arid|дефицит\w*\s+вод\w+", re.I),
     "засушливый климат"),
    (re.compile(r"коррозионн\w+\s+сред\w+|corrosive\s+environment", re.I),
     "коррозионная среда"),
]

_PARAM_STRIP = {"по", "до", "от", "в", "во", "на", "с", "и", "около", "порядка",
                "равно", "составляет", "примерно", "не", "более", "менее",
                "of", "the", "a", "at", "to", "is", "около"}
_SPLIT_PARAM = re.compile(r"[.;:,()\[\]«»\"“”\n]|–|—")


def _left_param(text: str, start: int) -> Optional[str]:
    left = text[max(0, start - 70):start]
    segs = [s.strip(" \t=-—– ") for s in _SPLIT_PARAM.split(left)]
    segs = [s for s in segs if re.search(r"[A-Za-zА-Яа-яЁё]", s)]
    if not segs:
        return None
    seg = segs[-1]
    # убираем хвостовые предлоги/остатки компараторов
    words = seg.split()
    while words and words[-1].lower() in _PARAM_STRIP:
        words.pop()
    while words and words[0].lower() in _PARAM_STRIP:
        words.pop(0)
    seg = " ".join(words).strip()
    if len(seg) > 60:
        seg = seg[-60:].strip()
    return seg or None


def _overlaps(span, occupied) -> bool:
    s, e = span
    for (os_, oe) in occupied:
        if not (e <= os_ or s >= oe):
            return True
    return False


def _canon(value, unit):
    if unit is None or value is None:
        return None, None
    return canonicalize_unit(value, unit)


def _make(op, value, value2, unit, span, text, param, qualitative=None):
    vc, uc = _canon(value, unit)
    return {
        "param": param,
        "op": op,
        "value": value,
        "value2": value2,
        "unit": unit,
        "unit_canonical": uc,
        "value_canonical": vc,
        "span": [span[0], span[1]],
        "quote": text[span[0]:span[1]],
        "qualitative": qualitative,
    }


def extract_conditions(text: str) -> List[dict]:
    """Извлекает все числовые условия/измерения и качественные условия."""
    if not text:
        return []
    out = []
    occupied = []

    def _try_num(s):
        try:
            return parse_number(s)
        except (ValueError, IndexError):
            return None

    # --- A: ± ---
    for m in _A_PM.finditer(text):
        v1, v2 = _try_num(m.group("n1")), _try_num(m.group("n2"))
        if v1 is None or v2 is None:
            continue
        span = (m.start(), m.end())
        if _overlaps(span, occupied):
            continue
        occupied.append(span)
        out.append(_make("approx", v1, v2, m.group("unit"), span, text,
                         _left_param(text, m.start())))

    # --- B: от X до Y / between / между ---
    for m in _B_RANGE.finditer(text):
        v1, v2 = _try_num(m.group("n1")), _try_num(m.group("n2"))
        if v1 is None or v2 is None:
            continue
        span = (m.start(), m.end())
        if _overlaps(span, occupied):
            continue
        occupied.append(span)
        out.append(_make("range", v1, v2, m.group("unit"), span, text,
                         _left_param(text, m.start())))

    # --- F: pH ---
    for m in _F_PH.finditer(text):
        v1 = _try_num(m.group("n1"))
        if v1 is None:
            continue
        v2 = _try_num(m.group("n2")) if m.group("n2") else None
        span = (m.start(), m.end())
        if _overlaps(span, occupied):
            continue
        occupied.append(span)
        if v2 is not None:
            op = "range"
        elif m.group("comp"):
            op = _COMP_MAP.get(_norm_comp(m.group("comp")), "=")
        else:
            op = "="
        out.append(_make(op, v1, v2, None, span, text, "рН"))

    # --- C: диапазон через тире (с единицей) ---
    for m in _C_RANGE.finditer(text):
        v1, v2 = _try_num(m.group("n1")), _try_num(m.group("n2"))
        if v1 is None or v2 is None:
            continue
        span = (m.start(), m.end())
        if _overlaps(span, occupied):
            continue
        occupied.append(span)
        out.append(_make("range", v1, v2, m.group("unit"), span, text,
                         _left_param(text, m.start())))

    # --- D: компаратор + число (символы, затем слова) ---
    for rx in (_D_SYM, _D_WORD):
        for m in rx.finditer(text):
            v = _try_num(m.group("num"))
            if v is None:
                continue
            span = (m.start("comp"), m.end())
            if _overlaps(span, occupied):
                continue
            op = _COMP_MAP.get(_norm_comp(m.group("comp")))
            if op is None:
                continue
            occupied.append(span)
            out.append(_make(op, v, None, m.group("unit"), span, text,
                             _left_param(text, m.start("comp"))))

    # --- E: измерение число+единица (op «=») ---
    for m in _E_MEAS.finditer(text):
        v = _try_num(m.group("num"))
        if v is None:
            continue
        span = (m.start(), m.end())
        if _overlaps(span, occupied):
            continue
        occupied.append(span)
        out.append(_make("=", v, None, m.group("unit"), span, text,
                         _left_param(text, m.start())))

    # --- качественные условия ---
    for rx, label in _QUAL:
        for m in rx.finditer(text):
            span = (m.start(), m.end())
            out.append({
                "param": None, "op": None, "value": None, "value2": None,
                "unit": None, "unit_canonical": None, "value_canonical": None,
                "span": [span[0], span[1]], "quote": text[span[0]:span[1]],
                "qualitative": label,
            })

    out.sort(key=lambda d: d["span"][0])
    return out
