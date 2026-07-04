// ============================================================================
// Реалистичные моки по golden-темам (docs/PLAN.md §3).
// Используются, когда VITE_API_URL не задан. Полный evidence packet по контракту.
// ============================================================================
import type {
  AuditEntry,
  Citation,
  CompareResponse,
  DocumentMeta,
  EdgePatch,
  ExportFormat,
  ExportResult,
  ExpertSummary,
  GraphEdge,
  GraphNode,
  ReviewResult,
  ReviewStatus,
  Role,
  SearchRequest,
  SearchResponse,
  StatsResponse,
  Subgraph,
  Subscription,
  SubscriptionUpdate,
  TokenResponse,
} from './types'

// --- общие переиспользуемые узлы -------------------------------------------
const N = {
  nickel: {
    id: 'mat:nickel', type: 'Material', name: 'никель', name_en: 'nickel',
    aliases: ['Ni', 'катодный никель'], props: { class: 'metal' }, confidence: 0.97,
  } as GraphNode,
  matte: {
    id: 'mat:matte', type: 'Material', name: 'штейн', name_en: 'matte',
    aliases: ['медно-никелевый штейн'], props: { class: 'intermediate' }, confidence: 0.95,
  } as GraphNode,
  slag: {
    id: 'mat:slag', type: 'Material', name: 'шлак', name_en: 'slag',
    aliases: ['отвальный шлак'], props: { class: 'waste' }, confidence: 0.95,
  } as GraphNode,
}

// --- Эксперты (сквозные) ---------------------------------------------------
const kosov: ExpertSummary = {
  id: 'person:kosov_ya_i',
  name: 'Косов Я.И.',
  affiliation: 'ЛГМ (Лаборатория гидрометаллургии)',
  n_works: 14,
  topics: ['электроэкстракция никеля', 'циркуляция католита', 'обессоливание растворов'],
  facility_type: 'lab',
}

const experts_electro: ExpertSummary[] = [
  kosov,
  {
    id: 'person:petrov_a_v', name: 'Петров А.В.',
    affiliation: 'ЛГМ (Лаборатория гидрометаллургии)', n_works: 9,
    topics: ['диафрагменные ячейки', 'массоперенос'], facility_type: 'lab',
  },
  {
    id: 'person:ivanova_m_s', name: 'Иванова М.С.',
    affiliation: 'ИАЦ (Инженерно-аналитический центр)', n_works: 6,
    topics: ['ТЭП электролиза', 'энергоэффективность'], facility_type: 'institute',
  },
]

const experts_water: ExpertSummary[] = [
  {
    id: 'person:sidorov_p_n', name: 'Сидоров П.Н.',
    affiliation: 'ЛПМ (Лаборатория пирометаллургии и обогащения)', n_works: 7,
    topics: ['обессоливание шахтных вод', 'обратный осмос'], facility_type: 'lab',
  },
  kosov,
  {
    id: 'person:volkova_e_a', name: 'Волкова Е.А.',
    affiliation: 'ИАЦ (Инженерно-аналитический центр)', n_works: 5,
    topics: ['водоочистка ОФ', 'нанофильтрация'], facility_type: 'institute',
  },
]

const experts_pgm: ExpertSummary[] = [
  {
    id: 'person:kozlov_d_i', name: 'Козлов Д.И.',
    affiliation: 'ЛПМ (Лаборатория пирометаллургии и обогащения)', n_works: 11,
    topics: ['распределение МПГ', 'обеднение шлака'], facility_type: 'lab',
  },
  {
    id: 'person:smirnov_v_p', name: 'Смирнов В.П.',
    affiliation: 'Институт Гипроникель', n_works: 8,
    topics: ['плавка на штейн', 'коэффициент распределения'], facility_type: 'institute',
  },
]

// --- ГОЛДЕН-ТЕМА 1: Обессоливание шахтных/оборотных вод ОФ -------------------
function packetWater(): SearchResponse {
  const nodes: GraphNode[] = [
    { id: 'proc:desalination', type: 'Process', name: 'обессоливание воды', name_en: 'water desalination', props: { domain: 'водоочистка' }, confidence: 0.93 },
    { id: 'proc:reverse_osmosis', type: 'Process', name: 'обратный осмос', name_en: 'reverse osmosis', aliases: ['RO', 'ОО'], props: { domain: 'водоочистка' }, confidence: 0.94 },
    { id: 'proc:nanofiltration', type: 'Process', name: 'нанофильтрация', name_en: 'nanofiltration', aliases: ['НФ'], props: { domain: 'водоочистка' }, confidence: 0.9 },
    { id: 'proc:electrodialysis', type: 'Process', name: 'электродиализ', name_en: 'electrodialysis', aliases: ['ЭД'], props: { domain: 'водоочистка' }, confidence: 0.88 },
    { id: 'mat:mine_water', type: 'Material', name: 'шахтная вода', name_en: 'mine water', props: { class: 'solution' }, confidence: 0.95 },
    { id: 'mat:permeate', type: 'Material', name: 'пермеат (очищенная вода)', name_en: 'permeate', props: { class: 'solution' }, confidence: 0.9 },
    { id: 'mat:concentrate_brine', type: 'Material', name: 'концентрат (рассол)', name_en: 'brine concentrate', props: { class: 'waste' }, confidence: 0.9 },
    { id: 'eq:ro_membrane', type: 'Equipment', name: 'мембранный аппарат ОО', name_en: 'RO membrane unit', confidence: 0.88 },
    { id: 'eq:ed_stack', type: 'Equipment', name: 'электродиализный аппарат', name_en: 'ED stack', confidence: 0.85 },
    { id: 'param:sulfates', type: 'Parameter', name: 'концентрация сульфатов', props: { unit_canonical: 'мг/л' }, confidence: 0.96 },
    { id: 'param:dry_residue', type: 'Parameter', name: 'сухой остаток', props: { unit_canonical: 'мг/дм³' }, confidence: 0.94 },
    { id: 'cond:sulfates_200_300', type: 'Condition', name: 'сульфаты 200–300 мг/л', props: { param: 'сульфаты', op: 'range', value: 200, value2: 300, unit: 'мг/л' }, confidence: 0.9 },
    { id: 'cond:chlorides_200_300', type: 'Condition', name: 'хлориды 200–300 мг/л', props: { param: 'хлориды', op: 'range', value: 200, value2: 300, unit: 'мг/л' }, confidence: 0.88 },
    { id: 'cond:ca_mg_na_200_300', type: 'Condition', name: 'Ca/Mg/Na 200–300 мг/л', props: { param: 'Ca,Mg,Na', op: 'range', value: 200, value2: 300, unit: 'мг/л' }, confidence: 0.86 },
    { id: 'cond:dry_le_1000', type: 'Condition', name: 'сухой остаток ≤1000 мг/дм³', props: { param: 'сухой остаток', op: '<=', value: 1000, unit: 'мг/дм³' }, confidence: 0.9 },
    { id: 'meas:ro_recovery_92', type: 'Measurement', name: 'извлечение воды 92 %', props: { param: 'выход пермеата', value: 92, unit: '%' }, confidence: 0.85 },
    { id: 'assert:ro_best_for_of', type: 'Assertion', name: 'ОО — предпочтителен для ОФ', statement: 'Обратный осмос обеспечивает сухой остаток ≤1000 мг/дм³ при исходных 200–300 мг/л по каждому иону и рекомендуется как основная ступень для оборотной воды ОФ.', review_status: 'confirmed', confidence: 0.88 },
    { id: 'assert:nf_softening', type: 'Assertion', name: 'НФ для умягчения', statement: 'Нанофильтрация эффективна для селективного удаления Ca/Mg (умягчение) при меньших энергозатратах, но недостаточно снижает Na и сухой остаток.', review_status: 'auto', confidence: 0.72 },
    { id: 'pub:d000412', type: 'Publication', name: 'Обзор технологий обессоливания оборотных вод ОФ', props: { year: 2022, source_type: 'review', geography: 'RU' }, confidence: 0.95 },
    { id: 'pub:d000517', type: 'Publication', name: 'Опыт нанофильтрации шахтных вод', props: { year: 2021, source_type: 'article', geography: 'RU' }, confidence: 0.9 },
    { id: 'fac:lpm', type: 'Facility', name: 'ЛПМ', props: { type: 'lab', country: 'RU' }, confidence: 0.95 },
    { id: 'person:sidorov_p_n', type: 'Expert', name: 'Сидоров П.Н.', props: { affiliation: 'ЛПМ' }, confidence: 0.9 },
  ]
  const edges: GraphEdge[] = [
    { src: 'proc:desalination', dst: 'mat:mine_water', type: 'uses_material', confidence: 0.9, method: 'llm' },
    { src: 'proc:reverse_osmosis', dst: 'mat:permeate', type: 'produces_output', confidence: 0.9, method: 'llm' },
    { src: 'proc:reverse_osmosis', dst: 'mat:concentrate_brine', type: 'produces_output', confidence: 0.85, method: 'llm' },
    { src: 'proc:reverse_osmosis', dst: 'eq:ro_membrane', type: 'uses_equipment', confidence: 0.9, method: 'rule' },
    { src: 'proc:electrodialysis', dst: 'eq:ed_stack', type: 'uses_equipment', confidence: 0.85, method: 'rule' },
    { src: 'proc:reverse_osmosis', dst: 'cond:sulfates_200_300', type: 'operates_at_condition', props: { param: 'сульфаты', op: 'range', value: 200, value2: 300, unit: 'мг/л' }, confidence: 0.88, method: 'rule' },
    { src: 'proc:reverse_osmosis', dst: 'cond:chlorides_200_300', type: 'operates_at_condition', confidence: 0.85, method: 'rule' },
    { src: 'proc:reverse_osmosis', dst: 'cond:ca_mg_na_200_300', type: 'operates_at_condition', confidence: 0.83, method: 'rule' },
    { src: 'proc:reverse_osmosis', dst: 'cond:dry_le_1000', type: 'operates_at_condition', confidence: 0.88, method: 'rule' },
    { src: 'proc:nanofiltration', dst: 'cond:ca_mg_na_200_300', type: 'operates_at_condition', confidence: 0.8, method: 'rule' },
    { src: 'proc:reverse_osmosis', dst: 'meas:ro_recovery_92', type: 'measured', confidence: 0.82, method: 'rule' },
    { src: 'assert:ro_best_for_of', dst: 'proc:reverse_osmosis', type: 'about', confidence: 0.9, method: 'llm' },
    { src: 'assert:ro_best_for_of', dst: 'pub:d000412', type: 'validated_by', confidence: 0.9, method: 'llm' },
    { src: 'assert:nf_softening', dst: 'pub:d000517', type: 'validated_by', confidence: 0.75, method: 'llm' },
    { src: 'assert:nf_softening', dst: 'proc:nanofiltration', type: 'about', confidence: 0.8, method: 'llm' },
    { src: 'proc:desalination', dst: 'pub:d000412', type: 'described_in', confidence: 0.9, method: 'llm' },
    { src: 'proc:nanofiltration', dst: 'pub:d000517', type: 'described_in', confidence: 0.85, method: 'llm' },
    { src: 'pub:d000412', dst: 'person:sidorov_p_n', type: 'authored_by', confidence: 0.9, method: 'rule' },
    { src: 'person:sidorov_p_n', dst: 'fac:lpm', type: 'works_at', confidence: 0.95, method: 'rule' },
    { src: 'person:sidorov_p_n', dst: 'proc:desalination', type: 'expert_in', confidence: 0.85, method: 'llm' },
  ]
  const citations: Citation[] = [
    {
      doc_id: 'd000412', title: 'Обзор технологий обессоливания оборотных вод обогатительных фабрик', year: 2022,
      chunk_id: 'd000412_c0011', section: 'Обзоры', source_type: 'review', geography: 'RU', journal: null, confidence: 'high', page_from: 8, page_to: 9,
      quote: 'При исходной минерализации по сульфатам, хлоридам и катионам Ca, Mg, Na в диапазоне 200–300 мг/л обратный осмос обеспечивает снижение сухого остатка до величины не более 1000 мг/дм³ и рекомендуется как базовая ступень водоподготовки оборотного цикла ОФ.',
    },
    {
      doc_id: 'd000412', title: 'Обзор технологий обессоливания оборотных вод обогатительных фабрик', year: 2022,
      chunk_id: 'd000412_c0014', section: 'Обзоры', source_type: 'review', geography: 'RU', journal: null, confidence: 'high', page_from: 11, page_to: 11,
      quote: 'Выход пермеата на пилотной установке составил 92 % при удельном расходе электроэнергии 2,8–3,2 кВт·ч/м³.',
    },
    {
      doc_id: 'd000517', title: 'Опыт применения нанофильтрации для умягчения шахтных вод', year: 2021,
      chunk_id: 'd000517_c0006', section: 'Статьи', source_type: 'article', geography: 'RU', journal: 'Цветные металлы', confidence: 'medium', page_from: 3, page_to: 4,
      quote: 'Нанофильтрационные мембраны обеспечивают удаление ионов кальция и магния на 85–90 %, однако задержание одновалентного натрия не превышает 40–50 %, что ограничивает снижение сухого остатка.',
    },
  ]
  return {
    answer_md: `## Методы обессоливания воды для обогатительных фабрик

При исходной минерализации **200–300 мг/л** по сульфатам, хлоридам и катионам Ca/Mg/Na и целевом **сухом остатке ≤1000 мг/дм³** в корпусе выделяются три технологии:

1. **Обратный осмос (ОО)** — базовая рекомендуемая ступень. Обеспечивает выполнение целевого сухого остатка ≤1000 мг/дм³ при указанном исходном составе, выход пермеата до 92 % [1][2]. Основной недостаток — образование концентрата-рассола, требующего утилизации.
2. **Нанофильтрация (НФ)** — эффективна для умягчения (Ca/Mg удаляются на 85–90 %), но задержание Na 40–50 % недостаточно для целевого сухого остатка [3]. Применяется как ступень предподготовки перед ОО.
3. **Электродиализ (ЭД)** — упоминается как альтернатива для солоноватых вод, но по корпусу данных о выполнении целевого сухого остатка на составе ОФ недостаточно (см. «Пробелы»).

**Вывод:** для условий ОФ (200–300 мг/л, сухой остаток ≤1000 мг/дм³) основным методом является обратный осмос, при необходимости — в связке НФ (умягчение) → ОО (обессоливание).`,
    intent: {
      type: 'review',
      concepts: ['обессоливание воды', 'обратный осмос', 'нанофильтрация', 'электродиализ', 'обогатительная фабрика'],
      numeric_constraints: ['сульфаты/хлориды/Ca/Mg/Na 200–300 мг/л', 'сухой остаток ≤1000 мг/дм³'],
      geography: 'all', years: [2000, 2026],
    },
    citations,
    subgraph: { nodes, edges },
    experts: experts_water,
    contradictions: [],
    gaps: [
      { id: 'gap:ed_of', title: 'Электродиализ на составе ОФ', description: 'Нет измеренных данных о достижении сухого остатка ≤1000 мг/дм³ методом электродиализа именно на оборотной воде ОФ (200–300 мг/л). Есть только общие упоминания.', severity: 'medium' },
      { id: 'gap:brine_util', title: 'Утилизация концентрата ОО', description: 'Слабо покрыт вопрос обращения с рассолом-концентратом обратного осмоса в условиях холодного климата.', severity: 'medium' },
    ],
    confidence_summary: { overall: 'high', n_high: 2, n_medium: 1, n_low: 0, note: 'Ключевой вывод по ОО подтверждён обзором с дословными числовыми условиями.' },
    took_ms: 3120,
    search_id: 'srch_water_001',
  }
}

// --- ГОЛДЕН-ТЕМА 2: Циркуляция католита при электроэкстракции Ni ------------
function packetElectro(): SearchResponse {
  const nodes: GraphNode[] = [
    { id: 'proc:electrowinning_ni', type: 'Process', name: 'электроэкстракция никеля', name_en: 'nickel electrowinning', aliases: ['ЭЭ Ni'], props: { domain: 'hydro' }, confidence: 0.96 },
    N.nickel,
    { id: 'mat:catholyte', type: 'Material', name: 'католит', name_en: 'catholyte', props: { class: 'solution' }, confidence: 0.94 },
    { id: 'mat:anolyte', type: 'Material', name: 'анолит', name_en: 'anolyte', props: { class: 'solution' }, confidence: 0.9 },
    { id: 'eq:ew_cell', type: 'Equipment', name: 'ванна электроэкстракции', name_en: 'electrowinning cell', confidence: 0.92 },
    { id: 'eq:diaphragm_cell', type: 'Equipment', name: 'диафрагменная ячейка', name_en: 'diaphragm cell', aliases: ['ПВП'], confidence: 0.9 },
    { id: 'eq:circulation_pump', type: 'Equipment', name: 'насос циркуляции католита', name_en: 'catholyte circulation pump', confidence: 0.86 },
    { id: 'param:circ_rate', type: 'Parameter', name: 'скорость циркуляции католита', props: { unit_canonical: 'м³/ч' }, confidence: 0.93 },
    { id: 'param:current_density', type: 'Parameter', name: 'плотность тока', props: { unit_canonical: 'А/м²' }, confidence: 0.9 },
    { id: 'param:ni_recovery', type: 'Parameter', name: 'извлечение никеля', props: { unit_canonical: '%' }, confidence: 0.9 },
    { id: 'cond:circ_1_2', type: 'Condition', name: 'скорость циркуляции 1,2 м³/ч', props: { param: 'скорость циркуляции', op: '=', value: 1.2, unit: 'м³/ч' }, confidence: 0.85 },
    { id: 'cond:current_250', type: 'Condition', name: 'плотность тока 250 А/м²', props: { param: 'плотность тока', op: '=', value: 250, unit: 'А/м²' }, confidence: 0.87 },
    { id: 'cond:ph_2_4', type: 'Condition', name: 'pH 2–4', props: { param: 'pH', op: 'range', value: 2, value2: 4 }, confidence: 0.84 },
    { id: 'meas:ni_recovery_925', type: 'Measurement', name: 'извлечение Ni 92,5 %', props: { param: 'извлечение никеля', value: 92.5, unit: '%' }, confidence: 0.86 },
    { id: 'exp:circ_opt', type: 'Experiment', name: 'опыт оптимизации циркуляции католита', props: { facility: 'ЛГМ', status: 'завершён' }, confidence: 0.85 },
    { id: 'assert:circ_opt_12', type: 'Assertion', name: 'оптимум циркуляции 1,2 м³/ч', statement: 'Оптимальная скорость циркуляции католита составляет ≈1,2 м³/ч на ванну: обеспечивает выравнивание концентрации Ni²⁺ у катода без чрезмерного захвата аэрозолей и извлечение 92,5 %.', review_status: 'confirmed', confidence: 0.85 },
    { id: 'assert:diaphragm_needed', type: 'Assertion', name: 'диафрагма обязательна', statement: 'Разделение католита и анолита диафрагмой (ПВП) необходимо для поддержания pH католита 2–4 и снижения обратного окисления.', review_status: 'auto', confidence: 0.78 },
    { id: 'pub:d000231', type: 'Publication', name: 'Технические решения по циркуляции католита при ЭЭ Ni', props: { year: 2023, source_type: 'article', geography: 'RU' }, confidence: 0.94 },
    { id: 'pub:d000188', type: 'Publication', name: 'Доклад: массоперенос в диафрагменной ячейке', props: { year: 2020, source_type: 'report', geography: 'RU' }, confidence: 0.9 },
    { id: 'fac:lgm', type: 'Facility', name: 'ЛГМ', props: { type: 'lab', country: 'RU' }, confidence: 0.96 },
    { id: 'person:kosov_ya_i', type: 'Expert', name: 'Косов Я.И.', props: { affiliation: 'ЛГМ' }, confidence: 0.93 },
    { id: 'person:petrov_a_v', type: 'Expert', name: 'Петров А.В.', props: { affiliation: 'ЛГМ' }, confidence: 0.88 },
  ]
  const edges: GraphEdge[] = [
    { src: 'proc:electrowinning_ni', dst: 'mat:nickel', type: 'produces_output', confidence: 0.95, method: 'llm' },
    { src: 'proc:electrowinning_ni', dst: 'mat:catholyte', type: 'uses_material', confidence: 0.92, method: 'llm' },
    { src: 'proc:electrowinning_ni', dst: 'mat:anolyte', type: 'produces_output', confidence: 0.85, method: 'llm' },
    { src: 'proc:electrowinning_ni', dst: 'eq:ew_cell', type: 'uses_equipment', confidence: 0.93, method: 'rule' },
    { src: 'proc:electrowinning_ni', dst: 'eq:diaphragm_cell', type: 'uses_equipment', confidence: 0.9, method: 'rule' },
    { src: 'proc:electrowinning_ni', dst: 'eq:circulation_pump', type: 'uses_equipment', confidence: 0.85, method: 'rule' },
    { src: 'proc:electrowinning_ni', dst: 'cond:circ_1_2', type: 'operates_at_condition', props: { param: 'скорость циркуляции', op: '=', value: 1.2, unit: 'м³/ч' }, confidence: 0.85, method: 'rule' },
    { src: 'proc:electrowinning_ni', dst: 'cond:current_250', type: 'operates_at_condition', confidence: 0.87, method: 'rule' },
    { src: 'proc:electrowinning_ni', dst: 'cond:ph_2_4', type: 'operates_at_condition', confidence: 0.84, method: 'rule' },
    { src: 'exp:circ_opt', dst: 'meas:ni_recovery_925', type: 'measured', confidence: 0.86, method: 'rule' },
    { src: 'exp:circ_opt', dst: 'cond:circ_1_2', type: 'operates_at_condition', confidence: 0.85, method: 'rule' },
    { src: 'assert:circ_opt_12', dst: 'proc:electrowinning_ni', type: 'about', confidence: 0.9, method: 'llm' },
    { src: 'assert:circ_opt_12', dst: 'exp:circ_opt', type: 'validated_by', confidence: 0.88, method: 'llm' },
    { src: 'assert:circ_opt_12', dst: 'pub:d000231', type: 'validated_by', confidence: 0.9, method: 'llm' },
    { src: 'assert:diaphragm_needed', dst: 'eq:diaphragm_cell', type: 'about', confidence: 0.8, method: 'llm' },
    { src: 'assert:diaphragm_needed', dst: 'pub:d000188', type: 'validated_by', confidence: 0.78, method: 'llm' },
    { src: 'proc:electrowinning_ni', dst: 'pub:d000231', type: 'described_in', confidence: 0.92, method: 'llm' },
    { src: 'eq:diaphragm_cell', dst: 'pub:d000188', type: 'described_in', confidence: 0.88, method: 'llm' },
    { src: 'pub:d000231', dst: 'person:kosov_ya_i', type: 'authored_by', confidence: 0.93, method: 'rule' },
    { src: 'pub:d000188', dst: 'person:petrov_a_v', type: 'authored_by', confidence: 0.9, method: 'rule' },
    { src: 'person:kosov_ya_i', dst: 'fac:lgm', type: 'works_at', confidence: 0.96, method: 'rule' },
    { src: 'person:petrov_a_v', dst: 'fac:lgm', type: 'works_at', confidence: 0.95, method: 'rule' },
    { src: 'person:kosov_ya_i', dst: 'proc:electrowinning_ni', type: 'expert_in', confidence: 0.9, method: 'llm' },
  ]
  const citations: Citation[] = [
    {
      doc_id: 'd000231', title: 'Технические решения по организации циркуляции католита при электроэкстракции никеля', year: 2023,
      chunk_id: 'd000231_c0009', section: 'Статьи', source_type: 'article', geography: 'RU', journal: 'Цветные металлы', confidence: 'high', page_from: 5, page_to: 6,
      quote: 'Экспериментально установлено, что оптимальная скорость циркуляции католита составляет 1,2 м³/ч на ванну; при этом достигается выравнивание концентрации никеля в прикатодном слое и извлечение никеля 92,5 % при плотности тока 250 А/м².',
    },
    {
      doc_id: 'd000231', title: 'Технические решения по организации циркуляции католита при электроэкстракции никеля', year: 2023,
      chunk_id: 'd000231_c0012', section: 'Статьи', source_type: 'article', geography: 'RU', journal: 'Цветные металлы', confidence: 'high', page_from: 7, page_to: 7,
      quote: 'Дальнейшее увеличение скорости циркуляции свыше 1,5 м³/ч приводило к росту захвата аэрозолей и снижению выхода по току без прироста извлечения.',
    },
    {
      doc_id: 'd000188', title: 'Массоперенос в диафрагменной ячейке электроэкстракции никеля', year: 2020,
      chunk_id: 'd000188_c0004', section: 'Доклады', source_type: 'report', geography: 'RU', journal: null, confidence: 'medium', page_from: 2, page_to: 3,
      quote: 'Разделение прикатодного и прианодного пространств полупроницаемой диафрагмой обеспечивает поддержание pH католита в диапазоне 2–4 и снижает обратное окисление осаждённого никеля.',
    },
  ]
  return {
    answer_md: `## Циркуляция католита при электроэкстракции никеля

**Технические решения** (по корпусу):
- Принудительная циркуляция католита насосом через диафрагменную ячейку (ПВП), отделяющую католит от анолита [3].
- Поддержание **плотности тока 250 А/м²** и **pH католита 2–4** [1][3].
- Контур циркуляции выравнивает концентрацию Ni²⁺ в прикатодном слое, предотвращая обеднение у катода.

**Оптимальная скорость потока:** экспериментально установлено значение **≈1,2 м³/ч на ванну** — при нём достигается извлечение никеля **92,5 %** [1]. Превышение **1,5 м³/ч** ухудшает выход по току из-за захвата аэрозолей без прироста извлечения [2].

**Вывод:** рекомендуемый режим — циркуляция ≈1,2 м³/ч на ванну при 250 А/м² и pH 2–4 с обязательным диафрагменным разделением. Работы выполнены в ЛГМ (Косов Я.И., Петров А.В.).`,
    intent: {
      type: 'lookup',
      concepts: ['электроэкстракция никеля', 'циркуляция католита', 'диафрагменная ячейка', 'скорость потока'],
      numeric_constraints: ['скорость циркуляции ~1,2 м³/ч', 'плотность тока 250 А/м²', 'pH 2–4'],
      geography: 'RU', years: [2000, 2026],
    },
    citations,
    subgraph: { nodes, edges },
    experts: experts_electro,
    contradictions: [],
    gaps: [
      { id: 'gap:circ_scale', title: 'Масштабирование на промышленную серию ванн', description: 'Оптимум 1,2 м³/ч получен на лабораторной/пилотной ванне; данных о поведении в промышленной серии из десятков ванн в корпусе нет.', severity: 'medium' },
    ],
    confidence_summary: { overall: 'high', n_high: 2, n_medium: 1, n_low: 0, note: 'Числовой оптимум подтверждён дословной цитатой и привязан к эксперименту ЛГМ.' },
    took_ms: 2680,
    search_id: 'srch_electro_002',
  }
}

// --- ГОЛДЕН-ТЕМА 3: Распределение Au/Ag/МПГ между штейном и шлаком -----------
function packetPGM(): SearchResponse {
  const nodes: GraphNode[] = [
    { id: 'proc:matte_smelting', type: 'Process', name: 'плавка на штейн', name_en: 'matte smelting', props: { domain: 'pyro' }, confidence: 0.94 },
    { id: 'proc:slag_depletion', type: 'Process', name: 'обеднение шлака', name_en: 'slag depletion', props: { domain: 'pyro' }, confidence: 0.9 },
    N.matte, N.slag,
    { id: 'mat:pgm', type: 'Material', name: 'МПГ (Pt, Pd, Rh)', name_en: 'PGM', aliases: ['платиноиды'], props: { class: 'metal' }, confidence: 0.93 },
    { id: 'mat:gold', type: 'Material', name: 'золото', name_en: 'gold', aliases: ['Au'], props: { class: 'metal' }, confidence: 0.95 },
    { id: 'mat:silver', type: 'Material', name: 'серебро', name_en: 'silver', aliases: ['Ag'], props: { class: 'metal' }, confidence: 0.94 },
    { id: 'param:dist_coef', type: 'Parameter', name: 'коэффициент распределения штейн/шлак', props: { unit_canonical: 'отн.' }, confidence: 0.9 },
    { id: 'param:temp', type: 'Parameter', name: 'температура', props: { unit_canonical: '°C' }, confidence: 0.92 },
    { id: 'cond:temp_1250', type: 'Condition', name: 'T = 1250 °C', props: { param: 'температура', op: '=', value: 1250, unit: '°C' }, confidence: 0.88 },
    { id: 'cond:temp_1300', type: 'Condition', name: 'T = 1300 °C', props: { param: 'температура', op: '=', value: 1300, unit: '°C' }, confidence: 0.85 },
    { id: 'meas:pd_matte_98', type: 'Measurement', name: 'Pd в штейн 98 %', props: { param: 'доля Pd в штейн', value: 98, unit: '%' }, confidence: 0.83 },
    { id: 'meas:pd_matte_94', type: 'Measurement', name: 'Pd в штейн 94 %', props: { param: 'доля Pd в штейн', value: 94, unit: '%' }, confidence: 0.8 },
    { id: 'exp:pgm_dist_2023', type: 'Experiment', name: 'опыт распределения МПГ при обеднении шлака', props: { facility: 'ЛПМ', status: 'завершён', date: '2023' }, confidence: 0.85 },
    { id: 'assert:pgm_to_matte_high', type: 'Assertion', name: 'МПГ почти полностью в штейн', statement: 'При плавке на штейн 96–98 % палладия и платины концентрируется в штейне; потери с отвальным шлаком не превышают 2–4 %.', review_status: 'disputed', confidence: 0.75 },
    { id: 'assert:pgm_to_matte_low', type: 'Assertion', name: 'потери МПГ со шлаком выше', statement: 'В условиях повышенной температуры (1300 °C) и высокой основности шлака в штейн переходит лишь ~94 % палладия, а потери со шлаком достигают 6 %.', review_status: 'disputed', confidence: 0.72 },
    { id: 'pub:d000305', type: 'Publication', name: 'Распределение благородных металлов между штейном и шлаком', props: { year: 2023, source_type: 'proceedings', geography: 'global' }, confidence: 0.92 },
    { id: 'pub:d000341', type: 'Publication', name: 'Обеднение шлака и потери МПГ при высокой T', props: { year: 2022, source_type: 'article', geography: 'foreign' }, confidence: 0.9 },
    { id: 'fac:lpm', type: 'Facility', name: 'ЛПМ', props: { type: 'lab', country: 'RU' }, confidence: 0.95 },
    { id: 'person:kozlov_d_i', type: 'Expert', name: 'Козлов Д.И.', props: { affiliation: 'ЛПМ' }, confidence: 0.91 },
    { id: 'person:smirnov_v_p', type: 'Expert', name: 'Смирнов В.П.', props: { affiliation: 'Институт Гипроникель' }, confidence: 0.88 },
  ]
  const edges: GraphEdge[] = [
    { src: 'proc:matte_smelting', dst: 'mat:matte', type: 'produces_output', confidence: 0.93, method: 'llm' },
    { src: 'proc:matte_smelting', dst: 'mat:slag', type: 'produces_output', confidence: 0.9, method: 'llm' },
    { src: 'proc:matte_smelting', dst: 'mat:pgm', type: 'uses_material', confidence: 0.85, method: 'llm' },
    { src: 'proc:slag_depletion', dst: 'mat:slag', type: 'uses_material', confidence: 0.88, method: 'llm' },
    { src: 'mat:pgm', dst: 'mat:matte', type: 'about', confidence: 0.8, method: 'llm' },
    { src: 'proc:matte_smelting', dst: 'cond:temp_1250', type: 'operates_at_condition', confidence: 0.85, method: 'rule' },
    { src: 'proc:slag_depletion', dst: 'cond:temp_1300', type: 'operates_at_condition', confidence: 0.83, method: 'rule' },
    { src: 'exp:pgm_dist_2023', dst: 'meas:pd_matte_98', type: 'measured', confidence: 0.83, method: 'rule' },
    { src: 'exp:pgm_dist_2023', dst: 'cond:temp_1250', type: 'operates_at_condition', confidence: 0.84, method: 'rule' },
    { src: 'assert:pgm_to_matte_high', dst: 'meas:pd_matte_98', type: 'validated_by', confidence: 0.8, method: 'llm' },
    { src: 'assert:pgm_to_matte_high', dst: 'pub:d000305', type: 'validated_by', confidence: 0.85, method: 'llm' },
    { src: 'assert:pgm_to_matte_low', dst: 'meas:pd_matte_94', type: 'validated_by', confidence: 0.78, method: 'llm' },
    { src: 'assert:pgm_to_matte_low', dst: 'pub:d000341', type: 'validated_by', confidence: 0.8, method: 'llm' },
    // ПРОТИВОРЕЧИЕ
    { src: 'assert:pgm_to_matte_high', dst: 'assert:pgm_to_matte_low', type: 'contradicts', confidence: 0.7, method: 'llm', props: { param: 'доля Pd в штейн', reason: 'несовместимые значения при разной T' } },
    { src: 'assert:pgm_to_matte_high', dst: 'mat:pgm', type: 'about', confidence: 0.85, method: 'llm' },
    { src: 'assert:pgm_to_matte_low', dst: 'mat:pgm', type: 'about', confidence: 0.83, method: 'llm' },
    { src: 'proc:matte_smelting', dst: 'pub:d000305', type: 'described_in', confidence: 0.9, method: 'llm' },
    { src: 'proc:slag_depletion', dst: 'pub:d000341', type: 'described_in', confidence: 0.88, method: 'llm' },
    { src: 'pub:d000305', dst: 'person:kozlov_d_i', type: 'authored_by', confidence: 0.9, method: 'rule' },
    { src: 'pub:d000341', dst: 'person:smirnov_v_p', type: 'authored_by', confidence: 0.85, method: 'rule' },
    { src: 'person:kozlov_d_i', dst: 'fac:lpm', type: 'works_at', confidence: 0.95, method: 'rule' },
    { src: 'person:kozlov_d_i', dst: 'mat:pgm', type: 'expert_in', confidence: 0.88, method: 'llm' },
  ]
  const cit_high: Citation = {
    doc_id: 'd000305', title: 'Распределение благородных металлов между штейном и шлаком при плавке', year: 2023,
    chunk_id: 'd000305_c0008', section: 'Материалы конференций', source_type: 'proceedings', geography: 'global', journal: null, confidence: 'medium', page_from: 4, page_to: 5,
    quote: 'При температуре 1250 °C в штейн переходит 96–98 % палладия и платины, тогда как потери благородных металлов с отвальным шлаком не превышают 2–4 %.',
  }
  const cit_low: Citation = {
    doc_id: 'd000341', title: 'Обеднение шлака и потери металлов платиновой группы при повышенных температурах', year: 2022,
    chunk_id: 'd000341_c0005', section: 'Статьи', source_type: 'article', geography: 'foreign', journal: 'JOM', confidence: 'medium', page_from: 3, page_to: 3,
    quote: 'At 1300 °C and increased slag basicity, only about 94 % of palladium reports to the matte, and PGM losses to the slag reach up to 6 %.',
  }
  const citations: Citation[] = [
    cit_high, cit_low,
    {
      doc_id: 'd000305', title: 'Распределение благородных металлов между штейном и шлаком при плавке', year: 2023,
      chunk_id: 'd000305_c0011', section: 'Материалы конференций', source_type: 'proceedings', geography: 'global', journal: null, confidence: 'medium', page_from: 6, page_to: 6,
      quote: 'Золото и серебро распределяются аналогично палладию, преимущественно концентрируясь в штейновой фазе.',
    },
  ]
  return {
    answer_md: `## Распределение Au, Ag и МПГ между штейном и шлаком (последние 5 лет)

По данным корпуса за 2021–2025 благородные металлы **преимущественно концентрируются в штейне**:

- При **T = 1250 °C** в штейн переходит **96–98 %** палладия и платины; потери со шлаком **2–4 %** [1].
- **Золото и серебро** ведут себя аналогично палладию, также концентрируясь в штейновой фазе [3].

⚠️ **Обнаружено противоречие** (см. раздел «Противоречия»): при **T = 1300 °C** и повышенной основности шлака доля Pd в штейне падает до **~94 %**, а потери со шлаком достигают **6 %** [2]. Источники расходятся из-за разных температурных режимов и основности шлака — это не ошибка, а зависимость от условий.

**Вывод:** доминирует переход МПГ/Au/Ag в штейн (>94 %), но конкретная величина потерь чувствительна к температуре и основности шлака. Требуется уточнение режима обеднения шлака.`,
    intent: {
      type: 'review',
      concepts: ['распределение МПГ', 'штейн', 'шлак', 'золото', 'серебро', 'плавка на штейн', 'обеднение шлака'],
      numeric_constraints: ['за последние 5 лет (2021–2025)', 'T 1250–1300 °C'],
      geography: 'all', years: [2021, 2026],
    },
    citations,
    subgraph: { nodes, edges },
    experts: experts_pgm,
    contradictions: [
      {
        id: 'contra:pgm_matte_share',
        topic: 'Доля палладия, переходящего в штейн при плавке',
        a: { assertion_id: 'assert:pgm_to_matte_high', statement: 'При 1250 °C в штейн переходит 96–98 % Pd/Pt, потери со шлаком 2–4 %.', confidence: 'medium', citation: cit_high },
        b: { assertion_id: 'assert:pgm_to_matte_low', statement: 'При 1300 °C и высокой основности шлака в штейн переходит ~94 % Pd, потери до 6 %.', confidence: 'medium', citation: cit_low },
        note: 'Расхождение объясняется разными температурами (1250 vs 1300 °C) и основностью шлака. Оба утверждения помечены review_status=disputed; требуется экспертное разрешение (Козлов Д.И., ЛПМ).',
      },
    ],
    gaps: [
      { id: 'gap:au_ag_numbers', title: 'Числовые доли для Au и Ag', description: 'По золоту и серебру есть только качественное «аналогично палладию»; точных дословных числовых долей распределения в корпусе не найдено.', severity: 'high' },
      { id: 'gap:rh_ir', title: 'Rh, Ir, Ru', description: 'Распределение родия, иридия и рутения между штейном и шлаком практически не покрыто.', severity: 'medium' },
    ],
    confidence_summary: { overall: 'medium', n_high: 0, n_medium: 3, n_low: 0, note: 'Есть подтверждённое противоречие двух источников по доле Pd; вывод устойчив на уровне «>94 % в штейн».' },
    took_ms: 3980,
    search_id: 'srch_pgm_003',
  }
}

// --- ГОЛДЕН-ТЕМА 4: Закачка шахтных вод в глубокие горизонты (RU vs зарубеж) --
function packetInjection(): SearchResponse {
  const nodes: GraphNode[] = [
    { id: 'proc:deep_injection', type: 'Process', name: 'закачка вод в глубокие горизонты', name_en: 'deep well injection', props: { domain: 'экология' }, confidence: 0.9 },
    { id: 'mat:mine_water', type: 'Material', name: 'шахтная вода', name_en: 'mine water', props: { class: 'solution' }, confidence: 0.93 },
    { id: 'eq:injection_well', type: 'Equipment', name: 'нагнетательная скважина', name_en: 'injection well', confidence: 0.85 },
    { id: 'param:capex', type: 'Parameter', name: 'CAPEX', props: { unit_canonical: 'млн ₽' }, confidence: 0.8 },
    { id: 'param:opex', type: 'Parameter', name: 'OPEX', props: { unit_canonical: '₽/м³' }, confidence: 0.8 },
    { id: 'cond:depth_1500', type: 'Condition', name: 'глубина ≥1500 м', props: { param: 'глубина', op: '>=', value: 1500, unit: 'м' }, confidence: 0.82 },
    { id: 'meas:opex_ru', type: 'Measurement', name: 'OPEX РФ 45 ₽/м³', props: { param: 'OPEX', value: 45, unit: '₽/м³' }, confidence: 0.72 },
    { id: 'meas:opex_us', type: 'Measurement', name: 'OPEX США 0,6 $/м³', props: { param: 'OPEX', value: 0.6, unit: '$/м³' }, confidence: 0.72 },
    { id: 'assert:ru_practice', type: 'Assertion', name: 'РФ: закачка на глубину ≥1500 м', statement: 'В российской практике шахтные воды закачивают в глубокие поглощающие горизонты на глубину ≥1500 м после механической очистки; метод рассматривается как альтернатива поверхностному сбросу в холодном климате.', review_status: 'auto', confidence: 0.72 },
    { id: 'assert:foreign_practice', type: 'Assertion', name: 'Зарубеж: жёсткое регулирование UIC', statement: 'За рубежом (США, класс скважин UIC I–V) глубинная закачка жёстко регулируется по риску сейсмичности и загрязнения водоносных горизонтов; практикуется предварительная стабилизация состава.', review_status: 'auto', confidence: 0.7 },
    { id: 'pub:d000602', type: 'Publication', name: 'Опыт закачки шахтных вод в РФ: ТЭП', props: { year: 2021, source_type: 'report', geography: 'RU' }, confidence: 0.88 },
    { id: 'pub:d000634', type: 'Publication', name: 'Deep well injection practice (UIC), review', props: { year: 2020, source_type: 'review', geography: 'foreign' }, confidence: 0.88 },
    { id: 'fac:iac', type: 'Facility', name: 'ИАЦ', props: { type: 'institute', country: 'RU' }, confidence: 0.9 },
    { id: 'person:volkova_e_a', type: 'Expert', name: 'Волкова Е.А.', props: { affiliation: 'ИАЦ' }, confidence: 0.85 },
    { id: 'geo:ru', type: 'Facility', name: 'Россия', props: { type: 'region', country: 'RU' }, confidence: 0.9 },
    { id: 'geo:us', type: 'Facility', name: 'США', props: { type: 'region', country: 'US' }, confidence: 0.9 },
  ]
  const edges: GraphEdge[] = [
    { src: 'proc:deep_injection', dst: 'mat:mine_water', type: 'uses_material', confidence: 0.88, method: 'llm' },
    { src: 'proc:deep_injection', dst: 'eq:injection_well', type: 'uses_equipment', confidence: 0.85, method: 'rule' },
    { src: 'proc:deep_injection', dst: 'cond:depth_1500', type: 'operates_at_condition', confidence: 0.82, method: 'rule' },
    { src: 'assert:ru_practice', dst: 'meas:opex_ru', type: 'validated_by', confidence: 0.7, method: 'llm' },
    { src: 'assert:ru_practice', dst: 'pub:d000602', type: 'validated_by', confidence: 0.85, method: 'llm' },
    { src: 'assert:foreign_practice', dst: 'meas:opex_us', type: 'validated_by', confidence: 0.7, method: 'llm' },
    { src: 'assert:foreign_practice', dst: 'pub:d000634', type: 'validated_by', confidence: 0.85, method: 'llm' },
    { src: 'assert:ru_practice', dst: 'proc:deep_injection', type: 'about', confidence: 0.85, method: 'llm' },
    { src: 'assert:foreign_practice', dst: 'proc:deep_injection', type: 'about', confidence: 0.83, method: 'llm' },
    { src: 'proc:deep_injection', dst: 'pub:d000602', type: 'described_in', confidence: 0.88, method: 'llm' },
    { src: 'proc:deep_injection', dst: 'pub:d000634', type: 'described_in', confidence: 0.86, method: 'llm' },
    { src: 'pub:d000602', dst: 'person:volkova_e_a', type: 'authored_by', confidence: 0.85, method: 'rule' },
    { src: 'person:volkova_e_a', dst: 'fac:iac', type: 'works_at', confidence: 0.9, method: 'rule' },
    { src: 'pub:d000602', dst: 'geo:ru', type: 'located_in', confidence: 0.9, method: 'rule' },
    { src: 'pub:d000634', dst: 'geo:us', type: 'located_in', confidence: 0.9, method: 'rule' },
    { src: 'assert:ru_practice', dst: 'geo:ru', type: 'located_in', confidence: 0.85, method: 'llm' },
    { src: 'assert:foreign_practice', dst: 'geo:us', type: 'located_in', confidence: 0.85, method: 'llm' },
  ]
  const citations: Citation[] = [
    {
      doc_id: 'd000602', title: 'Опыт закачки шахтных вод в глубокие горизонты в условиях РФ: технико-экономические показатели', year: 2021,
      chunk_id: 'd000602_c0007', section: 'Доклады', source_type: 'report', geography: 'RU', journal: null, confidence: 'medium', page_from: 4, page_to: 5,
      quote: 'Закачка осуществляется в поглощающие горизонты на глубину не менее 1500 м после механической очистки; удельные эксплуатационные затраты оцениваются в 45 руб./м³.',
    },
    {
      doc_id: 'd000634', title: 'Deep well injection practice under UIC regulation: a review', year: 2020,
      chunk_id: 'd000634_c0009', section: 'Обзоры', source_type: 'review', geography: 'foreign', journal: 'Mine Water and the Environment', confidence: 'medium', page_from: 11, page_to: 12,
      quote: 'Class I injection wells are strictly regulated with respect to induced seismicity and protection of underground sources of drinking water; typical operating cost is about 0.6 USD per cubic meter.',
    },
  ]
  return {
    answer_md: `## Закачка шахтных вод в глубокие горизонты: РФ vs зарубеж

**РФ.** Закачка в поглощающие горизонты на **глубину ≥1500 м** после механической очистки; рассматривается как альтернатива поверхностному сбросу в холодном климате. Оценка OPEX — **≈45 ₽/м³** [1].

**Зарубеж (США, UIC).** Глубинная закачка жёстко регулируется по классу скважин (UIC I–V), с приоритетом на **предотвращение наведённой сейсмичности** и защиту питьевых водоносных горизонтов; типичный OPEX ≈ **0,6 $/м³** [2].

**Сравнение ТЭП:**

| Показатель | РФ | Зарубеж (США) |
|---|---|---|
| Глубина | ≥1500 м | класс UIC I (глубокие) |
| OPEX | ~45 ₽/м³ | ~0,6 $/м³ |
| Регулирование | СанПиН / недропользование | UIC (EPA), контроль сейсмики |
| Драйвер | холодный климат, сброс | защита водоносных горизонтов |

**Вывод:** метод применяется в обеих практиках, но за рубежом акцент на экологическом/сейсмическом регулировании, в РФ — на технической реализуемости в холодном климате. Числовые ТЭП покрыты частично (см. «Пробелы»).`,
    intent: {
      type: 'compare',
      concepts: ['закачка шахтных вод', 'глубокие горизонты', 'нагнетательная скважина', 'ТЭП'],
      numeric_constraints: ['глубина ≥1500 м', 'OPEX'],
      geography: 'all', years: [2000, 2026],
    },
    citations,
    subgraph: { nodes, edges },
    experts: [experts_water[2], kosov],
    contradictions: [],
    gaps: [
      { id: 'gap:capex_inject', title: 'CAPEX закачки', description: 'Капитальные затраты (бурение скважин, обустройство) по обеим практикам в корпусе почти не оцифрованы.', severity: 'high' },
      { id: 'gap:seismic_ru', title: 'Сейсмические риски в РФ', description: 'Отсутствуют данные о мониторинге наведённой сейсмичности при закачке в российской практике.', severity: 'medium' },
    ],
    confidence_summary: { overall: 'medium', n_high: 0, n_medium: 2, n_low: 0, note: 'Сравнение опирается на два обзора; числовые ТЭП имеют пометку medium.' },
    took_ms: 3450,
    search_id: 'srch_inject_004',
  }
}

// --- Fallback для произвольного запроса -------------------------------------
function packetGeneric(query: string): SearchResponse {
  const el = packetElectro()
  return {
    ...el,
    answer_md: `## Результаты по запросу «${query}»

По вашему запросу в корпусе найдены релевантные материалы. Ниже показан пример структуры evidence packet на близкой теме (электроэкстракция никеля). В демо-режиме (моки) детальные ответы подготовлены для 4 golden-запросов — выберите один из примеров на экране поиска для полного сценария.

Основной результат: система возвращает связный ответ со ссылками на источники [n], подграф знаний, экспертов по теме, а также блоки противоречий и пробелов.`,
    intent: { ...el.intent, concepts: [query] },
    search_id: 'srch_generic_' + Math.random().toString(36).slice(2, 8),
    took_ms: 2200,
  }
}

// --- Роутер моков по тексту запроса -----------------------------------------
function pickPacket(query: string): SearchResponse {
  const q = query.toLowerCase()
  if (/(обессол|сульфат|хлорид|сухой остаток|водоочист|осмос|нанофильтр|воды для оф|шахтн.*вод.*оф)/.test(q))
    return packetWater()
  if (/(закачк|глубок.*горизонт|нагнетат|скважин|utilization|injection)/.test(q))
    return packetInjection()
  if (/(католит|электроэкстракц|циркуляц|electrowinning)/.test(q))
    return packetElectro()
  if (/(мпг|платин|палладий|штейн|шлак|au|ag|золот|серебр|благородн)/.test(q))
    return packetPGM()
  return packetGeneric(query)
}

// --- Публичный API мок-слоя --------------------------------------------------
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function mockSearch(req: SearchRequest): Promise<SearchResponse> {
  // Ответ может идти до 5 с — имитируем 2.2–4 с
  await delay(2200 + Math.random() * 1800)
  const base = pickPacket(req.query)
  // Применим фильтр порога достоверности к цитатам (демо ABAC/фильтрации)
  const cmin = req.filters?.confidence_min
  if (cmin && cmin > 0) {
    const rank = { high: 0.9, medium: 0.65, low: 0.4 }
    return {
      ...base,
      citations: base.citations.filter((c) => rank[c.confidence ?? 'medium'] >= cmin),
    }
  }
  return base
}

// Объединённый обзорный граф из всех тем (для экрана «Граф», обзорный режим)
export function mockOverviewGraph(): Subgraph {
  const packs = [packetWater(), packetElectro(), packetPGM(), packetInjection()]
  const nodeMap = new Map<string, GraphNode>()
  const edgeSet = new Set<string>()
  const edges: GraphEdge[] = []
  for (const p of packs) {
    for (const n of p.subgraph.nodes) if (!nodeMap.has(n.id)) nodeMap.set(n.id, n)
    for (const e of p.subgraph.edges) {
      const key = `${e.src}|${e.type}|${e.dst}`
      if (!edgeSet.has(key)) {
        edgeSet.add(key)
        edges.push(e)
      }
    }
  }
  return { nodes: Array.from(nodeMap.values()), edges }
}

// Раскрытие соседей узла (демо GET /api/graph/node/{id})
export function mockNodeNeighbors(id: string) {
  const g = mockOverviewGraph()
  const node = g.nodes.find((n) => n.id === id)
  const edges = g.edges.filter((e) => e.src === id || e.dst === id)
  const ids = new Set<string>([id])
  for (const e of edges) {
    ids.add(e.src)
    ids.add(e.dst)
  }
  const nodes = g.nodes.filter((n) => ids.has(n.id))
  return { node: node ?? nodes[0], neighbors: { nodes, edges } }
}

export async function mockStats(): Promise<StatsResponse> {
  await delay(400)
  return {
    n_documents: 1453,
    n_nodes: 9124,
    n_edges: 21877,
    n_assertions: 3160,
    n_contradictions: 42,
    n_corpus_total: 1453,
    node_types: {
      Material: 1820, Process: 640, Equipment: 410, Parameter: 380, Condition: 720,
      Measurement: 540, Experiment: 210, Publication: 1453, Expert: 190, Facility: 24, Assertion: 3160,
    },
    by_domain: [
      { key: 'hydro', label: 'Гидрометаллургия', n_docs: 312, n_assertions: 820 },
      { key: 'pyro', label: 'Пирометаллургия', n_docs: 401, n_assertions: 940 },
      { key: 'обогащение', label: 'Обогащение', n_docs: 268, n_assertions: 610 },
      { key: 'экология', label: 'Экология', n_docs: 154, n_assertions: 300 },
      { key: 'горное дело', label: 'Горное дело', n_docs: 188, n_assertions: 290 },
      { key: 'водоочистка', label: 'Водоочистка', n_docs: 130, n_assertions: 200 },
    ],
    by_section: [
      { key: 'Обзоры', label: 'Обзоры', n_docs: 180, n_assertions: 540 },
      { key: 'Статьи', label: 'Статьи', n_docs: 470, n_assertions: 1210 },
      { key: 'Доклады', label: 'Доклады', n_docs: 210, n_assertions: 480 },
      { key: 'Журналы', label: 'Журналы', n_docs: 380, n_assertions: 640 },
      { key: 'Материалы конференций', label: 'Конференции', n_docs: 213, n_assertions: 290 },
    ],
    by_year: [
      { year: 2018, n_docs: 96 }, { year: 2019, n_docs: 128 }, { year: 2020, n_docs: 164 },
      { year: 2021, n_docs: 201 }, { year: 2022, n_docs: 233 }, { year: 2023, n_docs: 251 },
      { year: 2024, n_docs: 218 }, { year: 2025, n_docs: 162 },
    ],
    top_gaps: [
      { id: 'g1', title: 'Числовые доли распределения Au/Ag', description: 'Качественные данные есть, точных чисел нет.', severity: 'high' },
      { id: 'g2', title: 'CAPEX глубинной закачки', description: 'Капзатраты почти не оцифрованы.', severity: 'high' },
      { id: 'g3', title: 'Электродиализ на составе ОФ', description: 'Нет измерений сухого остатка.', severity: 'medium' },
    ],
  }
}

export async function mockDocument(doc_id: string): Promise<DocumentMeta> {
  await delay(300)
  return {
    doc_id,
    title: 'Технические решения по организации циркуляции католита при электроэкстракции никеля',
    section: 'Статьи',
    journal: 'Цветные металлы',
    year: 2023,
    lang: 'ru',
    source_type: 'article',
    geography_hint: 'RU',
    n_pages: 12,
    n_chunks: 34,
    chunks: [
      { chunk_id: `${doc_id}_c0009`, seq: 9, page_from: 5, page_to: 6, section_title: '3.2 Скорость циркуляции', text: 'Экспериментально установлено, что оптимальная скорость циркуляции католита составляет 1,2 м³/ч на ванну…' },
      { chunk_id: `${doc_id}_c0012`, seq: 12, page_from: 7, page_to: 7, section_title: '3.3 Влияние избыточной циркуляции', text: 'Дальнейшее увеличение скорости циркуляции свыше 1,5 м³/ч приводило к росту захвата аэрозолей…' },
    ],
  }
}

export async function mockSubscriptions(): Promise<Subscription[]> {
  await delay(200)
  return [
    { id: 'sub_001', query: 'Циркуляция католита при электроэкстракции Ni', email: 'researcher@nornik.ru', created_at: '2026-06-28', n_new: 2 },
    { id: 'sub_002', query: 'Распределение МПГ между штейном и шлаком', created_at: '2026-06-30', n_new: 1 },
  ]
}

export async function mockSubscriptionUpdates(_id: string): Promise<SubscriptionUpdate[]> {
  await delay(200)
  return [
    { doc_id: 'd000231', title: 'Технические решения по циркуляции католита при ЭЭ Ni', year: 2023, added_at: '2026-07-02', reason: 'Новый документ волны 2, релевантность 0.91' },
    { doc_id: 'd000188', title: 'Массоперенос в диафрагменной ячейке', year: 2020, added_at: '2026-07-01', reason: 'Совпадение по концепту «диафрагменная ячейка»' },
  ]
}

let _mockSubSeq = 100
export async function mockSubscriptionCreate(query: string, email?: string): Promise<Subscription> {
  await delay(250)
  return {
    id: 'sub_' + ++_mockSubSeq,
    query,
    email,
    created_at: new Date().toISOString().slice(0, 10),
    n_new: 0,
  }
}

// --- Сравнение технологий (D5) ---------------------------------------------
const COMPARE_PARAMS: Record<string, Record<string, string>> = {
  'proc:reverse_osmosis': {
    домен: 'водоочистка',
    эффективность: 'сухой остаток ≤1000 мг/дм³, извлечение воды до 92 %',
    условия: 'сульфаты 200–300 мг/л → ≤300 мг/л; pH 5–8',
    CAPEX: 'высокий (мембранные модули, насосы ВД)',
    OPEX: '2,8–3,2 кВт·ч/м³',
    'холодный климат': 'требует обогрева, чувствителен к минусовым t',
    экология: 'образует концентрат-рассол, требует утилизации',
  },
  'proc:lime_softening': {
    домен: 'водоочистка',
    эффективность: 'частичное удаление сульфатов и жёсткости',
    условия: 'дозирование извести, образование гипса',
    CAPEX: 'средний (реагентное хозяйство, отстойники)',
    OPEX: 'расход извести, шламообразование',
    'холодный климат': 'устойчив, простая технология',
    экология: 'техногенный гипс — вторичный отход',
  },
  'proc:nanofiltration': {
    домен: 'водоочистка',
    эффективность: 'удаление Ca/Mg 85–90 %, Na 40–50 %',
    условия: 'умягчение, предподготовка перед ОО',
    CAPEX: 'средний',
    OPEX: 'ниже, чем у ОО',
    'холодный климат': 'аналогично ОО',
    экология: 'меньший объём концентрата',
  },
  'proc:electrowinning_ni': {
    домен: 'гидрометаллургия',
    эффективность: 'извлечение никеля 92,5 % при 1,2 м³/ч',
    условия: 'pH 2–4, 250 А/м², циркуляция католита',
    CAPEX: 'высокий (ванны, ВГ-оборудование)',
    OPEX: 'энергоёмкий процесс',
    'холодный климат': 'помещения с климат-контролем',
    экология: 'замкнутый цикл электролита',
  },
}

export async function mockCompare(techA: string, techB: string, params: string[]): Promise<CompareResponse> {
  await delay(400)
  const a = COMPARE_PARAMS[techA] ?? {}
  const b = COMPARE_PARAMS[techB] ?? {}
  const keys = params.length
    ? params
    : ['домен', 'эффективность', 'условия', 'CAPEX', 'OPEX', 'холодный климат', 'экология']
  return {
    techs: [
      { id: techA, name: (techA.split(':')[1] ?? techA).replace(/_/g, ' ') },
      { id: techB, name: (techB.split(':')[1] ?? techB).replace(/_/g, ' ') },
    ],
    rows: keys.map((p) => ({ param: p, values: [a[p] ?? null, b[p] ?? null] })),
  }
}

// --- Экспорт (D7) ----------------------------------------------------------
export async function mockExport(search_id: string, format: ExportFormat): Promise<ExportResult> {
  await delay(300)
  if (format === 'jsonld') {
    return {
      filename: `${search_id}.jsonld`,
      mime: 'application/ld+json',
      content: JSON.stringify(
        {
          '@context': ['https://schema.org', { prov: 'http://www.w3.org/ns/prov#' }],
          '@type': 'Dataset',
          identifier: search_id,
          name: 'Evidence packet (demo export)',
          'prov:wasGeneratedBy': 'sci-tangle query synthesis',
        },
        null,
        2,
      ),
    }
  }
  if (format === 'md') {
    return {
      filename: `${search_id}.md`,
      mime: 'text/markdown',
      content: `# Evidence packet ${search_id}\n\n> Демо-экспорт (моки). На живом API возвращается синтезированный ответ с цитатами.\n`,
    }
  }
  return {
    filename: `${search_id}.${format}`,
    mime: 'application/octet-stream',
    content: `Демо-экспорт формата ${format} (${search_id}). На живом API формат ${format} может быть недоступен.`,
  }
}

// --- Аудит (D11) -----------------------------------------------------------
export async function mockAudit(): Promise<AuditEntry[]> {
  await delay(200)
  const now = Date.now()
  return [
    { ts: new Date(now - 60000).toISOString(), role: 'analyst', action: 'search', detail: 'Циркуляция католита при электроэкстракции никеля' },
    { ts: new Date(now - 220000).toISOString(), role: 'project_lead', action: 'export', detail: 'md · srch_electro_002' },
    { ts: new Date(now - 540000).toISOString(), role: 'admin', action: 'review', detail: 'assert:pgm_to_matte_high → disputed' },
    { ts: new Date(now - 900000).toISOString(), role: 'researcher', action: 'search', detail: 'Методы обессоливания воды для ОФ' },
  ]
}

// --- RBAC (D10) ------------------------------------------------------------
export async function mockAuthToken(role: Role): Promise<TokenResponse> {
  await delay(150)
  // Демо-JWT (не подписан по-настоящему) — только для показа Authorization-хедера.
  const payload = btoa(JSON.stringify({ role, iss: 'sci-tangle-demo', iat: Date.now() }))
  return { access_token: `demo.${payload}.mock`, role }
}

// --- Ручная правка (D10) ---------------------------------------------------
export async function mockPatchEdge(id: string, patch: EdgePatch): Promise<ReviewResult> {
  await delay(250)
  return {
    id,
    review_status: 'confirmed',
    author: patch.author,
    comment: patch.comment,
    version: 2,
    updated_at: new Date().toISOString(),
  }
}

export async function mockReviewAssertion(
  id: string,
  status: ReviewStatus,
  comment: string,
  author: string,
): Promise<ReviewResult> {
  await delay(250)
  return { id, review_status: status, author, comment, version: 2, updated_at: new Date().toISOString() }
}

// --- Эксперты по теме (D4) -------------------------------------------------
export async function mockExperts(topic: string): Promise<ExpertSummary[]> {
  await delay(250)
  const t = topic.toLowerCase()
  if (/(вод|осмос|обессол|сульфат)/.test(t)) return experts_water
  if (/(мпг|штейн|шлак|платин|золот|серебр)/.test(t)) return experts_pgm
  return experts_electro
}
