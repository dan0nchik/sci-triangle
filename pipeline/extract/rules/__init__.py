"""B-rules: детерминированная экстракция чисел/единиц/условий/гео (RU/EN).

Публичный API (согласован с B-llm):
    extract_conditions(text) -> list[dict]
    canonicalize_unit(value, unit) -> (value_canonical, unit_canonical)
    validate_numbers(numbers, chunk_text) -> list[bool]
    detect_geography(text, meta) -> {"geo", "countries"}
"""
from .conditions import extract_conditions
from .units import canonicalize_unit, normalize_unit
from .numbers import validate_numbers, parse_number
from .geography import detect_geography

__all__ = [
    "extract_conditions",
    "canonicalize_unit",
    "normalize_unit",
    "validate_numbers",
    "parse_number",
    "detect_geography",
]
