"""
prompts.py — промпты LLM-экстракции знаний (PLAN §2 онтология, §4.2 граф).

Из чанка извлекаются:
  - entities   : сущности типов онтологии (Material/Process/Equipment/Parameter/
                 Facility/Experiment/Publication/Expert)
  - relations  : связи между сущностями (типы из §2.2)
  - assertions : утверждения {statement, confidence, quote} — quote ДОСЛОВНАЯ
  - conditions : числовые условия/измерения {param, op, value, value2, unit, quote}

Числа кросс-чекаются детерминированным rules-модулем: значение, отсутствующее
дословно в чанке, отбрасывается (см. runner.py -> validate_numbers).

structured output задаётся jsonSchema (проверено, что работает у YandexGPT).
Схему держим неглубокой: модель следует именам полей нестрого, поэтому
downstream всё валидируется.
"""

from __future__ import annotations

# Разрешённые типы (совпадают с онтологией §2)
ENTITY_TYPES = [
    "Material", "Process", "Equipment", "Parameter",
    "Facility", "Experiment", "Publication", "Expert",
]
RELATION_TYPES = [
    "uses_material", "produces_output", "operates_at_condition", "uses_equipment",
    "measured", "described_in", "authored_by", "works_at", "expert_in",
    "validated_by", "about",
]

# --- JSON-схема ответа -------------------------------------------------------
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "name_en": {"type": "string"},
                    "type": {"type": "string", "enum": ENTITY_TYPES},
                    "subtype": {"type": "string"},
                },
                "required": ["name", "type"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "type": {"type": "string", "enum": RELATION_TYPES},
                },
                "required": ["src", "dst", "type"],
            },
        },
        "assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "quote": {"type": "string"},
                },
                "required": ["statement", "confidence", "quote"],
            },
        },
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                    "op": {"type": "string", "enum": ["=", "<", ">", "<=", ">=", "range"]},
                    "value": {"type": "number"},
                    "value2": {"type": "number"},
                    "unit": {"type": "string"},
                    "kind": {"type": "string", "enum": ["condition", "measurement"]},
                    "quote": {"type": "string"},
                },
                "required": ["param", "value", "unit", "quote"],
            },
        },
    },
    "required": ["entities", "relations", "assertions", "conditions"],
}

SYSTEM_PROMPT = """Ты — эксперт по извлечению знаний из научно-технических текстов \
горно-металлургической отрасли (гидрометаллургия, пирометаллургия, обогащение, \
экология, горное дело, водоочистка). Ты извлекаешь структурированные знания из \
фрагмента документа и возвращаешь СТРОГО валидный JSON по заданной схеме.

Правила:
1. entities — только реально упомянутые в тексте объекты. Типы:
   Material (металл/руда/промпродукт/реагент/раствор/отход/продукт),
   Process (процесс/технология), Equipment (аппарат/оборудование),
   Parameter (измеряемая величина: температура, pH, плотность тока, извлечение...),
   Facility (лаборатория/завод/институт/предприятие),
   Experiment (описанный опыт/испытание), Publication (документ/статья/патент, если назван),
   Expert (конкретное имя человека-исследователя).
   name — как в тексте (рус), name_en — англоязычная форма/символ, если уместно.
2. relations — связи между извлечёнными сущностями (src/dst — их name):
   uses_material, produces_output, operates_at_condition, uses_equipment, measured,
   described_in, authored_by, works_at, expert_in, validated_by, about.
3. assertions — ключевые содержательные утверждения фрагмента. Для КАЖДОГО:
   statement (перефразированный тезис), confidence (high/medium/low по уверенности текста),
   quote — ДОСЛОВНАЯ непрерывная цитата из фрагмента, обосновывающая тезис
   (копируй символ-в-символ, ничего не сочиняй).
4. conditions — числовые условия и измерения. Для КАЖДОГО числа:
   param (что измеряется), op (=,<,>,<=,>=,range), value (число), value2 (для range),
   unit (единица как в тексте), kind (condition — заданное условие / measurement — результат),
   quote — ДОСЛОВНЫЙ фрагмент с этим числом. Числа бери ТОЛЬКО из текста, не вычисляй.
5. Если чего-то нет — верни пустой массив. Не выдумывай. Отвечай только JSON."""

USER_TEMPLATE = """Фрагмент документа (раздел: {section}):
\"\"\"
{text}
\"\"\"

Извлеки знания в JSON по схеме (entities, relations, assertions, conditions)."""


# --- few-shot (реальные фрагменты golden-документов) ------------------------
# Fragment 1 — реальный чанк devec846f_c0010 (Электроэкстракция никеля).
FEWSHOT_1_TEXT = (
    "Опыты вели с синтетическим электролитом с 85 г/л Ni2+ при перемешивании "
    "(350 об/мин), а температура (60 °С) и плотность тока (300 А/м2) взяты примерно "
    "соответствующими условиям на заводе Sao Miguel Paulista компании Vorotantim "
    "Metais, Бразилия. Опыты вели для рН 3 по следующим соображениям. При рН 4 "
    "получалась шероховатая поверхность, наблюдался рост дендритов."
)
FEWSHOT_1_JSON = {
    "entities": [
        {"name": "электроэкстракция", "name_en": "electrowinning", "type": "Process", "subtype": "hydro"},
        {"name": "никель", "name_en": "Ni", "type": "Material", "subtype": "metal"},
        {"name": "электролит", "name_en": "electrolyte", "type": "Material", "subtype": "solution"},
        {"name": "завод Sao Miguel Paulista", "name_en": "Sao Miguel Paulista", "type": "Facility"},
        {"name": "плотность тока", "name_en": "current density", "type": "Parameter"},
        {"name": "температура", "name_en": "temperature", "type": "Parameter"},
    ],
    "relations": [
        {"src": "электроэкстракция", "dst": "никель", "type": "produces_output"},
        {"src": "электроэкстракция", "dst": "электролит", "type": "uses_material"},
    ],
    "assertions": [
        {
            "statement": "При pH 4 поверхность катодного осадка шероховатая с ростом дендритов, поэтому опыты вели при pH 3.",
            "confidence": "high",
            "quote": "Опыты вели для рН 3 по следующим соображениям. При рН 4 получалась шероховатая поверхность, наблюдался рост дендритов.",
        }
    ],
    "conditions": [
        {"param": "концентрация Ni2+", "op": "=", "value": 85, "unit": "г/л", "kind": "condition",
         "quote": "с синтетическим электролитом с 85 г/л Ni2+"},
        {"param": "скорость перемешивания", "op": "=", "value": 350, "unit": "об/мин", "kind": "condition",
         "quote": "при перемешивании (350 об/мин)"},
        {"param": "температура", "op": "=", "value": 60, "unit": "°С", "kind": "condition",
         "quote": "температура (60 °С)"},
        {"param": "плотность тока", "op": "=", "value": 300, "unit": "А/м2", "kind": "condition",
         "quote": "плотность тока (300 А/м2)"},
        {"param": "pH", "op": "=", "value": 3, "unit": "pH", "kind": "condition",
         "quote": "Опыты вели для рН 3"},
    ],
}

# Fragment 2 — реальный чанк devb75187_c0037 (Методы очистки шахтных вод).
FEWSHOT_2_TEXT = (
    "Установка по очистке сточных вод Nolin Creek перерабатывает контактные воды "
    "плавильного завода, рудника Stobie, площадок шлаковых отвалов, О/Ф Clarabelle, "
    "а также избыточную оборотную воду сгустителя О/Ф Clarabelle."
)
FEWSHOT_2_JSON = {
    "entities": [
        {"name": "очистка сточных вод", "name_en": "wastewater treatment", "type": "Process", "subtype": "водоочистка"},
        {"name": "Установка по очистке сточных вод Nolin Creek", "name_en": "Nolin Creek water treatment plant", "type": "Facility"},
        {"name": "рудник Stobie", "name_en": "Stobie mine", "type": "Facility"},
        {"name": "сточные воды", "name_en": "wastewater", "type": "Material", "subtype": "solution"},
    ],
    "relations": [
        {"src": "очистка сточных вод", "dst": "сточные воды", "type": "uses_material"},
    ],
    "assertions": [
        {
            "statement": "Установка Nolin Creek очищает контактные воды плавильного завода, рудника Stobie, шлаковых отвалов и оборотную воду ОФ Clarabelle.",
            "confidence": "high",
            "quote": "Установка по очистке сточных вод Nolin Creek перерабатывает контактные воды плавильного завода, рудника Stobie, площадок шлаковых отвалов, О/Ф Clarabelle, а также избыточную оборотную воду сгустителя О/Ф Clarabelle.",
        }
    ],
    "conditions": [],
}


def build_messages(chunk_text: str, section: str | None = None, few_shot: bool = True):
    """Собирает messages для llm_complete/llm_complete_async."""
    import json as _json

    section = section or "не указан"
    msgs = [{"role": "system", "text": SYSTEM_PROMPT}]
    if few_shot:
        msgs.append({"role": "user", "text": USER_TEMPLATE.format(section="Обзоры", text=FEWSHOT_1_TEXT)})
        msgs.append({"role": "assistant", "text": _json.dumps(FEWSHOT_1_JSON, ensure_ascii=False)})
        msgs.append({"role": "user", "text": USER_TEMPLATE.format(section="Обзоры", text=FEWSHOT_2_TEXT)})
        msgs.append({"role": "assistant", "text": _json.dumps(FEWSHOT_2_JSON, ensure_ascii=False)})
    msgs.append({"role": "user", "text": USER_TEMPLATE.format(section=section, text=chunk_text)})
    return msgs
