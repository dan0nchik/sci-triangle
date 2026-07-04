"""Тесты B-rules на реальных формулировках (RU/EN) + примеры из ТЗ.

Запуск:  PYTHONPATH=pipeline/extract .venv-rules/bin/pytest -q
"""
import math

import pytest

from rules import (
    extract_conditions,
    canonicalize_unit,
    validate_numbers,
    detect_geography,
    parse_number,
)


def _find(conds, op=None, value=None, unit=None, qualitative=None):
    """Возвращает первое условие, удовлетворяющее заданным полям."""
    for c in conds:
        if op is not None and c["op"] != op:
            continue
        if value is not None and not (
            c["value"] is not None and math.isclose(c["value"], value, abs_tol=1e-9)
        ):
            continue
        if unit is not None and c["unit"] != unit:
            continue
        if qualitative is not None and c["qualitative"] != qualitative:
            continue
        return c
    return None


# ===========================================================================
# 1. parse_number — форматы чисел
# ===========================================================================
@pytest.mark.parametrize("raw,expected", [
    ("92,5", 92.5),
    ("99.98", 99.98),
    ("1 250", 1250.0),
    ("25 000", 25000.0),
    ("1 250", 1250.0),           # неразрывный пробел
    ("1,250.5", 1250.5),              # запятая-тысячи, точка-десятичная
    ("1.250,5", 1250.5),              # европейский формат
    ("300", 300.0),
    ("0,937", 0.937),
    ("-5,5", -5.5),
])
def test_parse_number(raw, expected):
    assert math.isclose(parse_number(raw), expected, abs_tol=1e-9)


# ===========================================================================
# 2. extract_conditions — примеры из ТЗ
# ===========================================================================
def test_tz_sulfates_range():
    c = extract_conditions("сульфаты, хлориды, Ca, Mg, Na по 200–300 мг/л")
    r = _find(c, op="range", value=200)
    assert r and r["value2"] == 300 and r["unit"] == "мг/л"
    assert r["unit_canonical"] == "мг/л"


def test_tz_dry_residue_le():
    c = extract_conditions("требуемый сухой остаток — ≤1000 мг/дм³")
    r = _find(c, op="<=", value=1000)
    assert r and r["unit"] == "мг/дм³"
    assert r["unit_canonical"] == "мг/л" and r["value_canonical"] == 1000
    assert "сухой остаток" in (r["param"] or "")


def test_tz_productivity_from():
    c = extract_conditions("производительность: от 100 т/сут")
    r = _find(c, op=">=", value=100)
    assert r and r["unit"] == "т/сут"


def test_tz_cold_climate():
    c = extract_conditions("климат: холодный")
    assert _find(c, qualitative="холодный климат") is not None


def test_tz_cold_climate_direct():
    c = extract_conditions("процесс должен работать в условиях холодного климата")
    assert _find(c, qualitative="холодный климат") is not None


# ===========================================================================
# 3. Компараторы (RU/EN)
# ===========================================================================
@pytest.mark.parametrize("text,op,value", [
    ("концентрация сульфатов ≤300 мг/л", "<=", 300),
    ("не более 1000 мг/дм³", "<=", 1000),
    ("не менее 95 %", ">=", 95),
    ("свыше 200 т/сут", ">", 200),
    ("около 50 мг/л", "approx", 50),
    ("порядка 1250 °C", "approx", 1250),
    ("до 300 мг/л", "<=", 300),
    ("от 80 г/л", ">=", 80),
    ("менее 4 мг/л", "<", 4),
    ("более 99 %", ">", 99),
    ("up to 300 мг/л", "<=", 300),
    ("at least 100 т/сут", ">=", 100),
    ("below 200 мг/л", "<", 200),
    ("approx 38 %", "approx", 38),
    (">99,98 %", ">", 99.98),
    ("≥4,3", ">=", 4.3),
])
def test_comparators(text, op, value):
    c = extract_conditions(text)
    assert _find(c, op=op, value=value) is not None, (text, c)


# ===========================================================================
# 4. Диапазоны
# ===========================================================================
def test_range_dash():
    c = extract_conditions("скорость потока 0,5–1,2 м³/ч")
    r = _find(c, op="range", value=0.5)
    assert r and r["value2"] == 1.2 and r["unit"] == "м³/ч"


def test_range_ot_do():
    c = extract_conditions("от 100 до 200 мг/л")
    r = _find(c, op="range", value=100)
    assert r and r["value2"] == 200


def test_range_between_en():
    c = extract_conditions("temperature between 60 and 80 °C")
    r = _find(c, op="range", value=60)
    assert r and r["value2"] == 80 and r["unit"] == "°C"


def test_range_mezhdu():
    c = extract_conditions("между 25 и 45 %")
    r = _find(c, op="range", value=25)
    assert r and r["value2"] == 45


def test_pm_tolerance():
    c = extract_conditions("температура 1250±20 °C")
    r = _find(c, op="approx", value=1250)
    assert r and r["value2"] == 20 and r["unit"] == "°C"


def test_ph_range():
    c = extract_conditions("рН 2–4")
    r = _find(c, op="range", value=2)
    assert r and r["value2"] == 4 and r["param"] == "рН"


def test_ph_single():
    c = extract_conditions("pH = 3")
    r = _find(c, value=3)
    assert r and r["param"] == "рН"


# ===========================================================================
# 5. Единицы / канонизация внутри extract_conditions
# ===========================================================================
def test_extract_percent_measurement():
    c = extract_conditions("извлечение 92,5 %")
    r = _find(c, op="=", value=92.5)
    assert r and r["unit"] == "%"


def test_extract_current_density():
    c = extract_conditions("плотность тока 300 А/м2")
    r = _find(c, op="=", value=300)
    assert r["unit_canonical"] == "А/м²"


def test_extract_molar():
    c = extract_conditions("При 0,937 М NiCl2 и 60 °С")
    assert _find(c, value=0.937, unit="М") is not None
    assert _find(c, value=60) is not None  # 60 °С


# ===========================================================================
# 6. canonicalize_unit
# ===========================================================================
@pytest.mark.parametrize("value,unit,exp_val,exp_unit", [
    (1000, "мг/дм³", 1000, "мг/л"),
    (10, "г/дм3", 10, "г/л"),
    (500, "ppm", 500, "мг/л"),
    (300, "кА/м²", 300000, "А/м²"),
    (100, "А/дм2", 10000, "А/м²"),
    (363, "К", 89.85, "°C"),
    (65, "°С", 65, "°C"),
    (100, "кПа", 0.1, "МПа"),
    (1, "атм", 0.101325, "МПа"),
    (10, "бар", 1.0, "МПа"),
    (2, "кг/сут", 0.002, "т/сут"),
    (5, "г/т", 5, "г/т"),
    (1000, "мкм", 1.0, "мм"),
    (100, "kWh/t", 100, "кВт·ч/т"),
    (0.937, "М", 0.937, "моль/л"),
])
def test_canonicalize(value, unit, exp_val, exp_unit):
    v, u = canonicalize_unit(value, unit)
    assert u == exp_unit
    assert math.isclose(v, exp_val, rel_tol=1e-6, abs_tol=1e-6)


def test_canonicalize_unknown_untouched():
    assert canonicalize_unit(5, "штук") == (5, "штук")


def test_canonicalize_none():
    assert canonicalize_unit(5, None) == (5, None)


# ===========================================================================
# 7. validate_numbers — дословное присутствие
# ===========================================================================
def test_validate_present_variants():
    text = "остаток 1000 мг/л, извлечение 92,5 %, диапазон 1 250 и 300"
    res = validate_numbers([1000, "92,5", 92.5, "1 250", 1250, 300], text)
    assert res == [True, True, True, True, True, True]


def test_validate_absent():
    text = "концентрация 300 мг/л"
    res = validate_numbers([301, 42, "999"], text)
    assert res == [False, False, False]


def test_validate_range_members():
    text = "диапазон 200–300 мг/л"
    assert validate_numbers([200, 300, 250], text) == [True, True, False]


def test_validate_thousands_english():
    text = "output 1,250 tons"
    # 1250 присутствует как «1,250»; 1.25 — как десятичная трактовка
    assert validate_numbers([1250, 1.25], text) == [True, True]


def test_validate_hallucinated_number_rejected():
    text = "температура 1250 °C, извлечение 90 %"
    assert validate_numbers([1230, 1270, 95], text) == [False, False, False]


# ===========================================================================
# 8. detect_geography
# ===========================================================================
def test_geo_ru():
    g = detect_geography("исследования в Норильске, Кольская ГМК", {})
    assert g["geo"] == "RU" and "Россия" in g["countries"]


def test_geo_foreign_chile():
    g = detect_geography("на медном руднике El Soldado в Чили", {})
    assert g["geo"] == "foreign" and "Чили" in g["countries"]


def test_geo_foreign_new_caledonia():
    g = detect_geography("завод Doniambo, New Caledonia", {})
    assert g["geo"] == "foreign" and "Новая Каледония" in g["countries"]


def test_geo_foreign_huelva():
    g = detect_geography("металлургический комплекс Уэльва (Atlantic Copper)", {})
    assert g["geo"] == "foreign" and "Испания" in g["countries"]


def test_geo_global_mixed():
    g = detect_geography("сравнение практики Норильска и рудников Чили", {})
    assert g["geo"] == "global"
    assert "Россия" in g["countries"] and "Чили" in g["countries"]


def test_geo_none():
    g = detect_geography("общий обзор процесса электроэкстракции", {})
    assert g["geo"] is None and g["countries"] == []


def test_geo_from_meta_path():
    g = detect_geography("описание процесса", {"path": "Обзоры/Металлургический комплекс Уэльва.docx"})
    assert g["geo"] == "foreign"


def test_geo_hint_fallback():
    g = detect_geography("нейтральный текст", {"geography_hint": "global"})
    assert g["geo"] == "global"


# ===========================================================================
# 9. Реальные фрагменты корпуса (Обзоры/*.docx)
# ===========================================================================
def test_corpus_sulfate_removal_range():
    c = extract_conditions("В типичном случае можно удалить 1500-2500 мг/л сульфата.")
    r = _find(c, op="range", value=1500)
    assert r and r["value2"] == 2500 and r["unit_canonical"] == "мг/л"


def test_corpus_sulfateq_lt300():
    c = extract_conditions(
        "SULFATEQ – эффективный процесс удаления сульфата (<300 мг/л) без извести.")
    assert _find(c, op="<", value=300, unit="мг/л") is not None


def test_corpus_ca_mg_limits():
    c = extract_conditions("удалять Ca (<100 мг/л), Mg (<4 мг/л)")
    assert _find(c, op="<", value=100) is not None
    assert _find(c, op="<", value=4) is not None


def test_corpus_sulfateq_input_and_ph():
    c = extract_conditions("концентрации сульфата на входе в SULFATEQ 1000-25000 мг/л и рН 2-8.")
    assert _find(c, op="range", value=1000) is not None
    r = _find(c, op="range", value=2)
    assert r and r["param"] == "рН"


def test_corpus_temperature_range():
    c = extract_conditions("- температура 0-80°С,")
    r = _find(c, op="range", value=0)
    assert r and r["value2"] == 80 and r["unit_canonical"] == "°C"


def test_corpus_ni_purity():
    c = extract_conditions("никелевые катоды высокой чистоты: обычно >99,98 %, иногда 99,99 %.")
    assert _find(c, op=">", value=99.98) is not None
    assert _find(c, op="=", value=99.99) is not None


def test_corpus_mn_concentration():
    c = extract_conditions("Влияние ионов Mn2+ на КПД (Mn2+ 10 г/дм3)")
    r = _find(c, op="=", value=10, unit="г/дм3")
    assert r and r["unit_canonical"] == "г/л"


def test_corpus_economy_approx():
    c = extract_conditions("шлам оседает быстрее (экономия ∼38%).")
    assert _find(c, op="approx", value=38, unit="%") is not None


def test_corpus_solids_content():
    c = extract_conditions("пульпу с содержанием твердого 25-45%")
    assert _find(c, op="range", value=25) is not None


def test_corpus_water_treated_and_conc():
    c = extract_conditions(
        "переработано 500 м3 воды с концентрацией сульфата от 800 мг/л до <200 мг/л.")
    assert _find(c, value=500) is not None
    assert _find(c, op=">=", value=800) is not None
    assert _find(c, op="<", value=200) is not None


def test_corpus_electrolyte_concentrations():
    c = extract_conditions("ρ(Ni2+) = 120 г/л; ρ (Na+) = 15 г/л; θ = 65°C; pH = 3")
    assert _find(c, op="=", value=120, unit="г/л") is not None
    assert _find(c, op="=", value=65) is not None
    r = _find(c, value=3)
    assert r and r["param"] == "рН"


def test_corpus_current_density_measurements():
    c = extract_conditions("морфология поверхности при плотности тока 100 А/м2 и рН 2")
    assert _find(c, op="=", value=100) is not None
    assert _find(c, value=2, unit=None) is not None  # рН 2


# ===========================================================================
# 10. Устойчивость: пустой ввод, отсутствие ложных срабатываний
# ===========================================================================
def test_empty_input():
    assert extract_conditions("") == []
    assert extract_conditions(None) == []


def test_no_false_positive_on_year():
    # «в 2019 г» не должно давать 2019 граммов
    c = extract_conditions("исследование проведено в 2019 г на комбинате")
    assert all(cc["unit"] not in ("г", "т") for cc in c)


def test_quote_matches_span():
    text = "сухой остаток ≤1000 мг/дм³ в норме"
    c = extract_conditions(text)
    for cc in c:
        s, e = cc["span"]
        assert text[s:e] == cc["quote"]


def test_qualitative_fields_are_none():
    c = extract_conditions("работа в условиях холодного климата")
    q = _find(c, qualitative="холодный климат")
    assert q["value"] is None and q["op"] is None and q["unit"] is None
