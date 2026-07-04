"""Build the fixture knowledge graph for the golden themes (PLAN.md §3, §4.2).

Themes covered:
  1. Обессоливание / очистка шахтных вод (сульфаты ≤300 мг/л, сухой остаток ≤1000 мг/дм³)
  2. Электроэкстракция никеля с циркуляцией католита (оптимальная скорость потока)
  3. Распределение Au/Ag/МПГ между штейном и шлаком (обеднение шлака)

Emits into backend/fixtures/:
  nodes.jsonl, edges.jsonl        - graph (contract §4.2)
  documents.jsonl, chunks.jsonl   - corpus stubs so ES indexes/search work

Includes Assertion nodes with evidence, Condition nodes with numbers,
Experts/Facilities, a `contradicts` pair, a `supersedes` version chain,
and Publication nodes with `about` links.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # allow `import embeddings`

from embeddings import embed_query  # noqa: E402

TODAY = "2026-07-03"


def n(id, type, name, name_en=None, aliases=None, concept_id=None,
      props=None, confidence=0.9, source_docs=None):
    return {
        "id": id, "type": type, "name": name, "name_en": name_en,
        "aliases": aliases or [], "concept_id": concept_id,
        "props": props or {}, "confidence": confidence,
        "source_docs": source_docs or [],
    }


def e(src, dst, type, props=None, source_doc=None, chunk_id=None,
      confidence=0.85, method="rule", created_by="pipeline"):
    return {
        "id": f"{src}|{type}|{dst}",
        "src": src, "dst": dst, "type": type, "props": props or {},
        "source_doc": source_doc, "chunk_id": chunk_id,
        "confidence": confidence, "method": method,
        "extracted_at": TODAY, "created_by": created_by,
    }


# ---------------------------------------------------------------- NODES
NODES = [
    # --- Materials ---
    n("mat:nickel", "Material", "никель", "nickel", ["Ni", "никель катодный"],
      "c_nickel", {"class": "metal"}, 0.95),
    n("mat:catholyte", "Material", "католит", "catholyte", ["католитный раствор"],
      "c_catholyte", {"class": "solution"}),
    n("mat:mine_water", "Material", "шахтная вода", "mine water",
      ["рудничная вода", "карьерная вода"], "c_mine_water", {"class": "solution"}),
    n("mat:sulfate_ion", "Material", "сульфат-ион", "sulfate", ["SO4", "сульфаты"],
      "c_sulfate", {"class": "ion"}),
    n("mat:permeate", "Material", "пермеат", "permeate", ["очищенная вода"],
      "c_permeate", {"class": "solution"}),
    n("mat:gypsum", "Material", "техногенный гипс", "gypsum", ["ангидрит"],
      "c_gypsum", {"class": "waste"}),
    n("mat:matte", "Material", "штейн", "matte", ["медно-никелевый штейн"],
      "c_matte", {"class": "intermediate"}),
    n("mat:slag", "Material", "шлак", "slag", ["отвальный шлак"],
      "c_slag", {"class": "waste"}),
    n("mat:pgm", "Material", "МПГ", "PGM", ["платиноиды", "металлы платиновой группы"],
      "c_pgm", {"class": "metal"}),
    n("mat:gold", "Material", "золото", "gold", ["Au"], "c_gold", {"class": "metal"}),
    n("mat:silver", "Material", "серебро", "silver", ["Ag"], "c_silver", {"class": "metal"}),

    # --- Processes ---
    n("proc:desalination", "Process", "обессоливание", "desalination",
      ["деминерализация"], "c_desalination", {"domain": "водоочистка"}),
    n("proc:reverse_osmosis", "Process", "обратный осмос", "reverse osmosis",
      ["ОО", "мембранное обессоливание"], "c_ro", {"domain": "водоочистка"}),
    n("proc:lime_softening", "Process", "известковое умягчение", "lime softening",
      ["известкование"], "c_lime", {"domain": "водоочистка"}),
    n("proc:electrowinning_ni", "Process", "электроэкстракция никеля",
      "nickel electrowinning", ["ЭЭ никеля", "электролиз никеля"],
      "c_ew_ni", {"domain": "hydro"}),
    n("proc:slag_depletion", "Process", "обеднение шлака", "slag depletion",
      ["очистка шлака", "обеднение"], "c_slag_depl", {"domain": "pyro"}),
    n("proc:deep_injection", "Process", "закачка шахтных вод в глубокие горизонты",
      "deep well injection", ["подземное захоронение"], "c_injection",
      {"domain": "экология"}),

    # --- Equipment ---
    n("eq:ro_membrane", "Equipment", "рулонный мембранный модуль",
      "spiral-wound RO membrane", ["мембранный модуль"], "c_ro_membrane"),
    n("eq:diaphragm_cell", "Equipment", "диафрагменная ячейка", "diaphragm cell",
      ["диафрагменный электролизёр"], "c_diaphragm"),
    n("eq:ew_bath", "Equipment", "ванна электроэкстракции", "electrowinning bath",
      ["электролизная ванна"], "c_ew_bath"),
    n("eq:electric_furnace", "Equipment", "электропечь", "electric furnace",
      ["руднотермическая печь", "ЭП"], "c_furnace"),

    # --- Parameters ---
    n("param:sulfate_conc", "Parameter", "концентрация сульфатов",
      "sulfate concentration", ["содержание сульфатов"], "c_p_sulfate",
      {"unit_canonical": "мг/л"}),
    n("param:dry_residue", "Parameter", "сухой остаток", "dry residue",
      ["минерализация", "солесодержание"], "c_p_dry", {"unit_canonical": "мг/дм³"}),
    n("param:catholyte_flow", "Parameter", "скорость циркуляции католита",
      "catholyte circulation rate", ["расход католита"], "c_p_flow",
      {"unit_canonical": "м³/ч"}),
    n("param:temperature", "Parameter", "температура", "temperature", ["T"],
      "c_p_temp", {"unit_canonical": "°C"}),
    n("param:pgm_partition", "Parameter", "коэффициент распределения МПГ",
      "PGM partition coefficient", ["распределение МПГ"], "c_p_partition",
      {"unit_canonical": "отн. ед."}),
    n("param:ni_recovery", "Parameter", "извлечение никеля", "nickel recovery",
      ["извлечение Ni"], "c_p_recovery", {"unit_canonical": "%"}),

    # --- Conditions (numeric) ---
    n("cond:sulfates_le_300", "Condition", "сульфаты ≤ 300 мг/л", "sulfates ≤ 300 mg/L",
      [], "c_cond_sulf", {"param": "сульфаты", "op": "<=", "value": 300,
                           "unit": "мг/л", "qualitative": None}),
    n("cond:dry_residue_le_1000", "Condition", "сухой остаток ≤ 1000 мг/дм³",
      "dry residue ≤ 1000 mg/dm3", [], "c_cond_dry",
      {"param": "сухой остаток", "op": "<=", "value": 1000, "unit": "мг/дм³"}),
    n("cond:catholyte_flow_range", "Condition", "скорость циркуляции 1,0–1,5 м³/ч",
      "flow 1.0-1.5 m3/h", [], "c_cond_flow",
      {"param": "скорость циркуляции католита", "op": "range", "value": 1.0,
       "value2": 1.5, "unit": "м³/ч"}),
    n("cond:temp_60", "Condition", "температура 60 °C", "temperature 60 C", [],
      "c_cond_t60", {"param": "температура", "op": "=", "value": 60, "unit": "°C"}),
    n("cond:ph_2_4", "Condition", "pH 2–4", "pH 2-4", [], "c_cond_ph",
      {"param": "pH", "op": "range", "value": 2, "value2": 4, "unit": ""}),
    n("cond:temp_1250", "Condition", "температура 1250 °C", "temperature 1250 C", [],
      "c_cond_t1250", {"param": "температура", "op": "=", "value": 1250, "unit": "°C"}),

    # --- Measurements ---
    n("meas:sulfate_removal_98", "Measurement", "снижение сульфатов на 98 %",
      "98% sulfate removal", [], "c_m_sulf",
      {"param": "степень удаления сульфатов", "value": 98, "unit": "%",
       "context": "пилот обессоливания шахтной воды обратным осмосом"}),
    n("meas:ni_recovery_925", "Measurement", "извлечение никеля 92,5 %",
      "nickel recovery 92.5%", [], "c_m_ni",
      {"param": "извлечение никеля", "value": 92.5, "unit": "%",
       "context": "опыт электроэкстракции с циркуляцией католита 1,2 м³/ч"}),
    n("meas:pgm_slag_loss_5", "Measurement", "потери МПГ со шлаком < 5 %",
      "PGM loss to slag <5%", [], "c_m_pgm",
      {"param": "потери МПГ со шлаком", "value": 5, "op": "<", "unit": "%",
       "context": "обеднение шлака при 1250 °C"}),

    # --- Experiments ---
    n("exp:mine_water_pilot", "Experiment", "пилот обессоливания шахтной воды",
      "mine water desalination pilot", [], "c_e_water",
      {"facility": "ЛГМ", "date": "2023-05", "status": "завершён"}),
    n("exp:electrowinning_test", "Experiment",
      "опыт электроэкстракции никеля с циркуляцией католита",
      "Ni electrowinning catholyte circulation test", [], "c_e_ew",
      {"facility": "ЛПМ", "date": "2024-03", "status": "завершён"}),
    n("exp:slag_depletion_1250", "Experiment", "опыт обеднения шлака при 1250 °C",
      "slag depletion test at 1250 C", [], "c_e_slag",
      {"facility": "Институт Гипроникель", "date": "2022-09", "status": "завершён"}),

    # --- Publications ---
    n("pub:d000101", "Publication", "Методы обессоливания шахтных вод обогатительных фабрик",
      "Desalination methods for concentrator mine waters", [], "c_pub101",
      {"doc_id": "d000101", "year": 2023, "source_type": "article",
       "section": "Статьи", "journal": "Цветные металлы", "lang": "ru",
       "geography": "RU", "sensitivity": "internal",
       "ingested_at": "2023-05-01T00:00:00+00:00"}, source_docs=["d000101"]),
    n("pub:d000102", "Publication",
      "Циркуляция католита при электроэкстракции никеля",
      "Catholyte circulation in nickel electrowinning", [], "c_pub102",
      {"doc_id": "d000102", "year": 2024, "source_type": "article",
       "section": "Статьи", "journal": "Цветные металлы", "lang": "ru",
       "geography": "RU", "sensitivity": "internal",
       "ingested_at": "2024-02-01T00:00:00+00:00"}, source_docs=["d000102"]),
    n("pub:d000103", "Publication",
      "Распределение Au, Ag и МПГ между штейном и шлаком",
      "Distribution of Au, Ag and PGM between matte and slag", [], "c_pub103",
      {"doc_id": "d000103", "year": 2022, "source_type": "article",
       "section": "Статьи", "journal": "Цветные металлы", "lang": "ru",
       "geography": "RU", "sensitivity": "internal",
       "ingested_at": "2022-09-01T00:00:00+00:00"}, source_docs=["d000103"]),
    n("pub:d000104", "Publication",
      "Deep-well injection of mine waters: foreign practice and TEP",
      "Deep-well injection of mine waters", [], "c_pub104",
      {"doc_id": "d000104", "year": 2021, "source_type": "review",
       "section": "Обзоры", "journal": None, "lang": "en",
       "geography": "foreign", "sensitivity": "public",
       "ingested_at": "2021-03-01T00:00:00+00:00"}, source_docs=["d000104"]),

    # --- Experts ---
    n("person:kosov", "Expert", "Косов Я.И.", "Kosov Ya.I.", [], "c_exp_kosov",
      {"affiliation": "ЛГМ", "topics": ["обессоливание", "водоочистка"]}),
    n("person:korzhakov", "Expert", "Коржаков А.А.", "Korzhakov A.A.", [],
      "c_exp_korzhakov",
      {"affiliation": "ЛПМ", "topics": ["электроэкстракция никеля", "гидрометаллургия"]}),
    n("person:tsymbulov", "Expert", "Цымбулов Л.Б.", "Tsymbulov L.B.", [],
      "c_exp_tsymbulov",
      {"affiliation": "Институт Гипроникель",
       "topics": ["пирометаллургия", "распределение МПГ", "обеднение шлака"]}),

    # --- Facilities ---
    n("fac:lgm", "Facility", "ЛГМ", "LGM", ["Лаборатория гидрометаллургии"],
      "c_fac_lgm", {"type": "lab", "country": "Россия", "geography": "RU"}),
    n("fac:lpm", "Facility", "ЛПМ", "LPM", ["Лаборатория пирометаллургии"],
      "c_fac_lpm", {"type": "lab", "country": "Россия", "geography": "RU"}),
    n("fac:gipronickel", "Facility", "Институт Гипроникель", "Gipronickel Institute",
      [], "c_fac_gipro", {"type": "institute", "country": "Россия", "geography": "RU"}),

    # --- Assertions ---
    n("assert:ro_removes_sulfates", "Assertion",
      "Обратный осмос снижает концентрацию сульфатов в шахтной воде ниже 300 мг/л",
      None, [], "c_a_ro",
      {"statement": "Обратный осмос снижает концентрацию сульфатов в шахтной воде "
                    "ниже 300 мг/л при сухом остатке ≤1000 мг/дм³.",
       "confidence": "high", "n_sources": 1, "review_status": "confirmed",
       "version": 1, "valid_from": "2023-05",
       "evidence": [{"doc_id": "d000101", "chunk_id": "d000101_c0003",
                     "quote": "Применение обратного осмоса позволило снизить содержание "
                              "сульфатов с 1800 до 260 мг/л при сухом остатке 950 мг/дм³."}]},
      0.9, ["d000101"]),
    n("assert:catholyte_flow_v1", "Assertion",
      "Оптимальная скорость циркуляции католита — 0,8 м³/ч (версия 1)",
      None, [], "c_a_flow_v1",
      {"statement": "Оптимальная скорость циркуляции католита составляет 0,8 м³/ч.",
       "confidence": "medium", "n_sources": 1, "review_status": "auto",
       "version": 1, "valid_from": "2022-01", "superseded_by": "assert:catholyte_flow_v2",
       "evidence": [{"doc_id": "d000102", "chunk_id": "d000102_c0002",
                     "quote": "В ранних опытах скорость циркуляции католита 0,8 м³/ч "
                              "считалась достаточной."}]},
      0.6, ["d000102"]),
    n("assert:catholyte_flow_v2", "Assertion",
      "Оптимальная скорость циркуляции католита — 1,2 м³/ч (версия 2)",
      None, [], "c_a_flow_v2",
      {"statement": "Оптимальная скорость циркуляции католита при электроэкстракции "
                    "никеля составляет 1,2 м³/ч, обеспечивая извлечение 92,5 %.",
       "confidence": "high", "n_sources": 1, "review_status": "confirmed",
       "version": 2, "valid_from": "2024-03",
       "evidence": [{"doc_id": "d000102", "chunk_id": "d000102_c0007",
                     "quote": "Оптимальная скорость циркуляции католита 1,2 м³/ч "
                              "обеспечила извлечение никеля 92,5 % при стабильном pH."}]},
      0.9, ["d000102"]),
    n("assert:catholyte_flow_dispute", "Assertion",
      "Скорость циркуляции католита должна быть не менее 2,0 м³/ч (спорное)",
      None, [], "c_a_flow_disp",
      {"statement": "Для предотвращения расслоения электролита скорость циркуляции "
                    "католита должна быть не менее 2,0 м³/ч.",
       "confidence": "low", "n_sources": 1, "review_status": "disputed",
       "version": 1, "valid_from": "2021-01",
       "evidence": [{"doc_id": "d000104", "chunk_id": "d000104_c0005",
                     "quote": "Catholyte circulation below 2.0 m3/h led to stratification "
                              "of the electrolyte."}]},
      0.5, ["d000104"]),
    n("assert:pgm_partition_matte", "Assertion",
      "МПГ концентрируются в штейне; потери со шлаком не превышают 5 %",
      None, [], "c_a_pgm",
      {"statement": "При обеднении шлака при 1250 °C металлы платиновой группы "
                    "концентрируются в штейне, потери МПГ со шлаком не превышают 5 %.",
       "confidence": "high", "n_sources": 1, "review_status": "confirmed",
       "version": 1, "valid_from": "2022-09",
       "evidence": [{"doc_id": "d000103", "chunk_id": "d000103_c0004",
                     "quote": "Потери МПГ со шлаком при температуре 1250 °C не превышали "
                              "5 %, основная масса платиноидов переходила в штейн."}]},
      0.9, ["d000103"]),
]

# ---------------------------------------------------------------- EDGES
EDGES = [
    # Theme 1: desalination
    e("proc:reverse_osmosis", "mat:mine_water", "uses_material", source_doc="d000101"),
    e("proc:reverse_osmosis", "mat:permeate", "produces_output", source_doc="d000101"),
    e("proc:reverse_osmosis", "eq:ro_membrane", "uses_equipment", source_doc="d000101"),
    e("proc:reverse_osmosis", "cond:sulfates_le_300", "operates_at_condition",
      {"param": "сульфаты", "op": "<=", "value": 300, "unit": "мг/л"},
      source_doc="d000101", chunk_id="d000101_c0003"),
    e("proc:reverse_osmosis", "cond:dry_residue_le_1000", "operates_at_condition",
      {"param": "сухой остаток", "op": "<=", "value": 1000, "unit": "мг/дм³"},
      source_doc="d000101", chunk_id="d000101_c0003"),
    e("proc:lime_softening", "mat:mine_water", "uses_material", source_doc="d000101"),
    e("proc:lime_softening", "mat:gypsum", "produces_output", source_doc="d000101"),
    e("proc:desalination", "mat:mine_water", "uses_material", source_doc="d000101"),
    e("proc:deep_injection", "mat:mine_water", "uses_material", source_doc="d000104"),
    e("exp:mine_water_pilot", "cond:sulfates_le_300", "operates_at_condition",
      {"param": "сульфаты", "op": "<=", "value": 300, "unit": "мг/л"},
      source_doc="d000101", chunk_id="d000101_c0003"),
    e("exp:mine_water_pilot", "meas:sulfate_removal_98", "measured", source_doc="d000101"),
    e("assert:ro_removes_sulfates", "exp:mine_water_pilot", "validated_by",
      source_doc="d000101", method="llm"),
    e("assert:ro_removes_sulfates", "pub:d000101", "described_in", source_doc="d000101"),
    e("pub:d000101", "proc:reverse_osmosis", "about", source_doc="d000101"),
    e("pub:d000101", "mat:mine_water", "about", source_doc="d000101"),
    e("pub:d000101", "person:kosov", "authored_by", source_doc="d000101"),
    e("person:kosov", "fac:lgm", "works_at"),
    e("person:kosov", "proc:desalination", "expert_in"),
    e("person:kosov", "proc:reverse_osmosis", "expert_in"),

    # Theme 2: nickel electrowinning
    e("proc:electrowinning_ni", "mat:catholyte", "uses_material", source_doc="d000102"),
    e("proc:electrowinning_ni", "mat:nickel", "produces_output", source_doc="d000102"),
    e("proc:electrowinning_ni", "eq:diaphragm_cell", "uses_equipment", source_doc="d000102"),
    e("proc:electrowinning_ni", "eq:ew_bath", "uses_equipment", source_doc="d000102"),
    e("proc:electrowinning_ni", "cond:catholyte_flow_range", "operates_at_condition",
      {"param": "скорость циркуляции католита", "op": "range", "value": 1.0,
       "value2": 1.5, "unit": "м³/ч"}, source_doc="d000102", chunk_id="d000102_c0007"),
    e("proc:electrowinning_ni", "cond:temp_60", "operates_at_condition",
      {"param": "температура", "op": "=", "value": 60, "unit": "°C"}, source_doc="d000102"),
    e("proc:electrowinning_ni", "cond:ph_2_4", "operates_at_condition",
      {"param": "pH", "op": "range", "value": 2, "value2": 4, "unit": ""},
      source_doc="d000102"),
    e("exp:electrowinning_test", "cond:catholyte_flow_range", "operates_at_condition",
      {"param": "скорость циркуляции католита", "op": "range", "value": 1.0,
       "value2": 1.5, "unit": "м³/ч"}, source_doc="d000102", chunk_id="d000102_c0007"),
    e("exp:electrowinning_test", "meas:ni_recovery_925", "measured", source_doc="d000102"),
    e("assert:catholyte_flow_v2", "exp:electrowinning_test", "validated_by",
      source_doc="d000102", method="llm"),
    e("assert:catholyte_flow_v2", "pub:d000102", "described_in", source_doc="d000102"),
    e("assert:catholyte_flow_v1", "pub:d000102", "described_in", source_doc="d000102"),
    e("assert:catholyte_flow_v2", "assert:catholyte_flow_v1", "supersedes",
      source_doc="d000102", method="llm"),
    e("assert:catholyte_flow_dispute", "assert:catholyte_flow_v2", "contradicts",
      source_doc="d000104", method="llm", confidence=0.7),
    e("assert:catholyte_flow_dispute", "pub:d000104", "described_in", source_doc="d000104"),
    e("pub:d000102", "proc:electrowinning_ni", "about", source_doc="d000102"),
    e("pub:d000102", "mat:nickel", "about", source_doc="d000102"),
    e("pub:d000102", "person:korzhakov", "authored_by", source_doc="d000102"),
    e("person:korzhakov", "fac:lpm", "works_at"),
    e("person:korzhakov", "proc:electrowinning_ni", "expert_in"),
    e("person:korzhakov", "mat:nickel", "expert_in"),

    # Theme 3: PGM distribution
    e("proc:slag_depletion", "mat:matte", "uses_material", source_doc="d000103"),
    e("proc:slag_depletion", "mat:slag", "uses_material", source_doc="d000103"),
    e("proc:slag_depletion", "mat:matte", "produces_output", source_doc="d000103"),
    e("proc:slag_depletion", "mat:slag", "produces_output", source_doc="d000103"),
    e("proc:slag_depletion", "eq:electric_furnace", "uses_equipment", source_doc="d000103"),
    e("proc:slag_depletion", "cond:temp_1250", "operates_at_condition",
      {"param": "температура", "op": "=", "value": 1250, "unit": "°C"},
      source_doc="d000103", chunk_id="d000103_c0004"),
    e("exp:slag_depletion_1250", "cond:temp_1250", "operates_at_condition",
      {"param": "температура", "op": "=", "value": 1250, "unit": "°C"},
      source_doc="d000103", chunk_id="d000103_c0004"),
    e("exp:slag_depletion_1250", "meas:pgm_slag_loss_5", "measured", source_doc="d000103"),
    e("assert:pgm_partition_matte", "exp:slag_depletion_1250", "validated_by",
      source_doc="d000103", method="llm"),
    e("assert:pgm_partition_matte", "pub:d000103", "described_in", source_doc="d000103"),
    e("pub:d000103", "proc:slag_depletion", "about", source_doc="d000103"),
    e("pub:d000103", "mat:pgm", "about", source_doc="d000103"),
    e("pub:d000103", "mat:gold", "about", source_doc="d000103"),
    e("pub:d000103", "mat:silver", "about", source_doc="d000103"),
    e("pub:d000103", "person:tsymbulov", "authored_by", source_doc="d000103"),
    e("person:tsymbulov", "fac:gipronickel", "works_at"),
    e("person:tsymbulov", "proc:slag_depletion", "expert_in"),
    e("person:tsymbulov", "mat:pgm", "expert_in"),
    e("pub:d000104", "proc:deep_injection", "about", source_doc="d000104"),

    # facility geography
    e("fac:lgm", "mat:mine_water", "related"),  # keep graph connected across themes
]


# ---------------------------------------------------------------- CORPUS STUBS
DOCUMENTS = [
    {"doc_id": "d000101", "path": "fixtures/d000101.pdf", "filename": "obessolivanie.pdf",
     "title": "Методы обессоливания шахтных вод обогатительных фабрик",
     "section": "Статьи", "journal": "Цветные металлы", "year": 2023, "lang": "ru",
     "source_type": "article", "geography_hint": "RU", "n_pages": 12, "n_chunks": 8,
     "sensitivity": "internal", "ingested_at": "2023-05-01T00:00:00+00:00"},
    {"doc_id": "d000102", "path": "fixtures/d000102.pdf", "filename": "catholyte.pdf",
     "title": "Циркуляция католита при электроэкстракции никеля",
     "section": "Статьи", "journal": "Цветные металлы", "year": 2024, "lang": "ru",
     "source_type": "article", "geography_hint": "RU", "n_pages": 10, "n_chunks": 9,
     "sensitivity": "internal", "ingested_at": "2024-02-01T00:00:00+00:00"},
    {"doc_id": "d000103", "path": "fixtures/d000103.pdf", "filename": "pgm.pdf",
     "title": "Распределение Au, Ag и МПГ между штейном и шлаком",
     "section": "Статьи", "journal": "Цветные металлы", "year": 2022, "lang": "ru",
     "source_type": "article", "geography_hint": "RU", "n_pages": 14, "n_chunks": 7,
     "sensitivity": "internal", "ingested_at": "2022-09-01T00:00:00+00:00"},
    {"doc_id": "d000104", "path": "fixtures/d000104.pdf", "filename": "injection.pdf",
     "title": "Deep-well injection of mine waters: foreign practice and TEP",
     "section": "Обзоры", "journal": None, "year": 2021, "lang": "en",
     "source_type": "review", "geography_hint": "foreign", "n_pages": 20, "n_chunks": 6,
     "sensitivity": "public", "ingested_at": "2021-03-01T00:00:00+00:00"},
]

CHUNKS = [
    {"chunk_id": "d000101_c0003", "doc_id": "d000101", "seq": 3, "lang": "ru",
     "section_title": "3.2 Обратный осмос",
     "text": "Применение обратного осмоса позволило снизить содержание сульфатов "
             "с 1800 до 260 мг/л при сухом остатке 950 мг/дм³. Целевые показатели "
             "качества воды для обогатительной фабрики: сульфаты ≤300 мг/л, "
             "сухой остаток ≤1000 мг/дм³.", "page_from": 4, "page_to": 5},
    {"chunk_id": "d000101_c0005", "doc_id": "d000101", "seq": 5, "lang": "ru",
     "section_title": "3.3 Известковое умягчение",
     "text": "Известковое умягчение шахтной воды сопровождается образованием "
             "техногенного гипса и позволяет частично удалить сульфаты и жёсткость.",
     "page_from": 6, "page_to": 6},
    {"chunk_id": "d000102_c0002", "doc_id": "d000102", "seq": 2, "lang": "ru",
     "section_title": "2 Обзор",
     "text": "В ранних опытах скорость циркуляции католита 0,8 м³/ч считалась "
             "достаточной для поддержания однородности электролита.",
     "page_from": 2, "page_to": 2},
    {"chunk_id": "d000102_c0007", "doc_id": "d000102", "seq": 7, "lang": "ru",
     "section_title": "3.2 Скорость циркуляции",
     "text": "Оптимальная скорость циркуляции католита 1,2 м³/ч обеспечила извлечение "
             "никеля 92,5 % при стабильном pH 2–4 и температуре 60 °C в диафрагменной "
             "ячейке.", "page_from": 5, "page_to": 6},
    {"chunk_id": "d000103_c0004", "doc_id": "d000103", "seq": 4, "lang": "ru",
     "section_title": "4 Распределение платиноидов",
     "text": "Потери МПГ со шлаком при температуре 1250 °C не превышали 5 %, основная "
             "масса платиноидов, а также золота и серебра переходила в штейн.",
     "page_from": 7, "page_to": 8},
    {"chunk_id": "d000104_c0005", "doc_id": "d000104", "seq": 5, "lang": "en",
     "section_title": "5 Catholyte hydrodynamics",
     "text": "Catholyte circulation below 2.0 m3/h led to stratification of the "
             "electrolyte and uneven current distribution.", "page_from": 9, "page_to": 10},
]


def _text_for_node(node: dict) -> str:
    parts = [node.get("name") or "", node.get("name_en") or ""]
    parts += node.get("aliases") or []
    props = node.get("props") or {}
    if props.get("statement"):
        parts.append(props["statement"])
    return " ".join(p for p in parts if p)


# The real corpus (corpus/documents.jsonl, direction A) uses doc_ids d000001..d0001xx,
# which collide with the fixture's d000101..d000104 (different documents). To keep the
# fixture doc namespace disjoint from the real corpus, remap fixture doc_ids into the
# d0009xx range before writing (ids are embedded in node/edge/chunk strings).
DOC_REMAP = {
    "d000101": "d000901", "d000102": "d000902",
    "d000103": "d000903", "d000104": "d000904",
}


def _remap(line: str) -> str:
    for old, new in DOC_REMAP.items():
        line = line.replace(old, new)
    return line


def main() -> None:
    # attach embeddings to entities (for entity_embeddings vector index)
    for node in NODES:
        node["embedding"] = embed_query(_text_for_node(node))

    def _dump(items):
        return "\n".join(_remap(json.dumps(x, ensure_ascii=False)) for x in items) + "\n"

    (HERE / "nodes.jsonl").write_text(_dump(NODES), encoding="utf-8")
    (HERE / "edges.jsonl").write_text(_dump(EDGES), encoding="utf-8")
    (HERE / "documents.jsonl").write_text(_dump(DOCUMENTS), encoding="utf-8")
    (HERE / "chunks.jsonl").write_text(_dump(CHUNKS), encoding="utf-8")
    print(f"Wrote {len(NODES)} nodes, {len(EDGES)} edges, "
          f"{len(DOCUMENTS)} documents, {len(CHUNKS)} chunks "
          f"(fixture doc_ids remapped to d0009xx)")


if __name__ == "__main__":
    main()
