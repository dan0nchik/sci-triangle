# SHACL-валидация графа sci-tangle

_Сгенерировано `backend/validate_graph.py` · 2026-07-04 14:45 UTC_

Реальный прогон pyshacl по `docs/shapes.ttl` (словарь `docs/ontology.ttl`) на выборке живого графа `graph/nodes.jsonl` + `graph/edges.jsonl`. Нарушения — это честная картина шума извлечения, а не подгонка данных.

## Итог прогона

- Выборка: **28159 узлов** + **47722 рёбер** (весь граф), 722300 RDF-триплетов.
- `sh:conforms` = **False** (наличие нарушений ожидаемо и допустимо).
- Всего результатов валидации: **1437** (по severity: {'Violation': 256, 'Warning': 1181}).

### Проверенные типы узлов

| Тип | Кол-во в выборке |
|---|---|
| Assertion | 6702 |
| Facility | 4483 |
| Condition | 4023 |
| Material | 3369 |
| Measurement | 2965 |
| Expert | 1896 |
| Equipment | 1825 |
| Process | 1786 |
| Publication | 526 |
| Parameter | 526 |
| Experiment | 58 |

### Проверенные типы рёбер (реифицированы как `sct:Fact`)

| Тип связи | Кол-во |
|---|---|
| described_in | 20459 |
| validated_by | 6704 |
| operates_at_condition | 6210 |
| measured | 3737 |
| about | 3301 |
| uses_material | 2233 |
| produces_output | 2192 |
| works_at | 1671 |
| uses_equipment | 839 |
| expert_in | 255 |
| authored_by | 121 |

## Топ категорий нарушений

| # | Severity | Кол-во | Свойство | Сообщение | Примеры (focus node) |
|---|---|---|---|---|---|
| 1 | Warning | 526 | `year` | У публикации желателен год (year) — источник: documents.jsonl. | pub:metals_x; pub:list_of_references; pub:fig_4 |
| 2 | Warning | 526 | `sourceType` | У публикации желателен тип источника (source_type) — источник: documents.jsonl. | pub:metals_x; pub:list_of_references; pub:fig_4 |
| 3 | Violation | 127 | `value` | value условия обязательно и должно быть числом (xsd:double). | cond:recovery_eq_none; cond:free_tip_shiny_eq_f_kategoriya  (value=F); cond:free_stepen_okisleniya_sery_pri_vyschela_eq_otnoshenie_obrazovavshikhsya_pri_vyschel  (value=отношение образовавшихся при выщелачивании СС сульфатных ионов к содержанию серы в исходном сырье) |
| 4 | Warning | 103 | `unit` | У условия желательна единица измерения (unit). | cond:recovery_eq_none; cond:free_stepen_okisleniya_sery_pri_vyschela_eq_otnoshenie_obrazovavshikhsya_pri_vyschel; cond:temperature_eq_dostatochno_nizkaya |
| 5 | Violation | 55 | `op` | op условия обязателен и ∈ {=, <, >, <=, >=, range, approx}. | cond:grade_eq_45_x  (value=gt); cond:free_kontsentratsiya_ni_eq_750_g_l  (value=~=); cond:free_sootnoshenie_klausa_eq_126_null  (value=≈) |
| 6 | Violation | 42 | `op` | op измерения обязателен и ∈ {=, <, >, <=, >=, range, approx}. | meas:free_kontsentratsiya_as_02_mg_l  (value=≤); meas:grade_550_x  (value=min); meas:free_vybrosy_svintsa_i_ego_soedineniy_70_mg_nm3  (value=≤) |
| 7 | Violation | 32 | `value` | value измерения обязательно и должно быть числом (xsd:double). | meas:grade_suschestvenno_vyshe_protsent  (value=существенно выше); meas:free_tip_filtrov_gipsa_vakuumnlentochn_tip  (value=Вакуумн.ленточн.); meas:recovery_snizilsya_ne_ukazano  (value=снизился) |
| 8 | Warning | 26 | `unit` | У измерения желательна единица измерения (unit). | meas:free_indeks_prirodno_resursnogo_potentsi_602; meas:free_stepen_vozgonki_tsinka_vysokaya; meas:free_tip_drenirovaniya_drained |

## Интерпретация

- **`op` вне канонического набора** — шум поля оператора в извлечении (`gt`, `lt`, `≥`, `≤`, `min`, `max`, `~`, `→`, естественноязычные варианты). Кандидат на нормализацию в rule-слое (маппинг синонимов оператора).
- **`value` не xsd:double** — качественные значения ("существенно снизилось") и пустые значения там, где ожидается число: сигнал доработать rule-first фильтр.
- **Publication `year` / `source_type` (Warning)** — эти поля живут в `corpus/documents.jsonl` и не денормализованы на узлы Publication графа; требуют join при загрузке, поэтому помечены как Warning, а не Violation.
- Провенанс факт-рёбер (`source_doc`, `confidence` 0..1, `method`, `extracted_at`) и структура Assertion (`statement`, `confidence` high/medium/low, `review_status`, непустой `evidence`) проходят валидацию на подавляющем большинстве элементов.
