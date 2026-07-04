// ============================================================================
// Строгие типы фронтенда по контракту REST API (docs/PLAN.md §4.2, §4.3).
// Единственный источник правды для типов данных направления D.
// ============================================================================

// ---- Онтология: типы узлов (§2.1) --------------------------------------------
export type NodeType =
  | 'Material'
  | 'Process'
  | 'Equipment'
  | 'Parameter'
  | 'Condition'
  | 'Measurement'
  | 'Experiment'
  | 'Publication'
  | 'Expert'
  | 'Facility'
  | 'Assertion'

// ---- Онтология: типы связей (§2.2) -------------------------------------------
export type EdgeType =
  | 'uses_material'
  | 'produces_output'
  | 'operates_at_condition'
  | 'uses_equipment'
  | 'measured'
  | 'described_in'
  | 'authored_by'
  | 'works_at'
  | 'expert_in'
  | 'validated_by'
  | 'contradicts'
  | 'supersedes'
  | 'located_in'
  | 'about'

export type Confidence = 'high' | 'medium' | 'low'
export type ReviewStatus = 'auto' | 'confirmed' | 'disputed' | 'rejected'
export type Geography = 'RU' | 'foreign' | 'global'
export type ExtractMethod = 'rule' | 'llm' | 'manual'

export type SourceType =
  | 'review'
  | 'article'
  | 'report'
  | 'presentation'
  | 'patent'
  | 'market_report'
  | 'book'
  | 'proceedings'

export type Section =
  | 'Обзоры'
  | 'Статьи'
  | 'Доклады'
  | 'Журналы'
  | 'Материалы конференций'

export type Domain =
  | 'hydro'
  | 'pyro'
  | 'обогащение'
  | 'экология'
  | 'горное дело'
  | 'водоочистка'

// ---- Граф (§4.2) -------------------------------------------------------------
export interface GraphNode {
  id: string
  type: NodeType
  name: string
  name_en?: string
  aliases?: string[]
  concept_id?: string
  props?: Record<string, unknown>
  confidence?: number // 0..1
  source_docs?: string[]
  // для Assertion-узлов
  statement?: string
  review_status?: ReviewStatus
}

export interface GraphEdge {
  id?: string
  src: string
  dst: string
  type: EdgeType
  props?: Record<string, unknown>
  source_doc?: string
  chunk_id?: string
  confidence?: number // 0..1
  method?: ExtractMethod
  extracted_at?: string
  created_by?: string // pipeline | имя эксперта (для ручных правок)
}

export interface Subgraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ---- Поиск: запрос (§4.3 POST /api/search) -----------------------------------
export interface SearchFilters {
  year_from?: number
  year_to?: number
  geography?: Geography | 'all'
  section?: Section | null
  source_type?: SourceType | null
  confidence_min?: number // 0..1
  domain?: Domain | null
  // Мультипараметрическая фильтрация «материал / процесс» (Q&A: «плюс в карму»).
  // Клиентская подсказка — заполняется быстрым выбором концептов из ответа;
  // бэкенд может игнорировать (поля опциональны, вне обязательного контракта §4.3).
  material?: string | null
  process?: string | null
}

export type Role =
  | 'researcher'
  | 'analyst'
  | 'project_lead'
  | 'admin'
  | 'external_partner'

export interface SearchRequest {
  query: string
  filters?: SearchFilters
  role_ctx?: Role
}

// ---- Поиск: ответ (§4.3) -----------------------------------------------------
export interface Citation {
  doc_id: string
  title: string
  year: number
  chunk_id: string
  quote: string // дословный фрагмент-основание
  // опциональные метаданные для карточки источника
  section?: Section
  source_type?: SourceType
  geography?: Geography
  journal?: string | null
  confidence?: Confidence
  page_from?: number
  page_to?: number
}

export type IntentType = 'lookup' | 'review' | 'compare' | 'aggregate' | 'gap'

export interface Intent {
  type: IntentType
  concepts: string[]
  numeric_constraints?: string[]
  geography?: Geography | 'all'
  years?: [number, number]
}

// ---- Объяснимость: как получен ответ (retrieval trace) -----------------------
// Форма согласуется с backend-агентом «Answer-Quality» через docs/CONTRACT_TRACE.md.
// Пока контракта нет — фронтенд принимает этот shape, а при его отсутствии
// синтезирует правдоподобный trace из ответа (adaptSearch → deriveTrace).
export type RetrievalBranchKind = 'lexical' | 'semantic' | 'graph'

export interface RetrievalBranch {
  kind: RetrievalBranchKind
  hits?: number // сколько кандидатов дала ветка
  used: boolean // сработала ли ветка (внесла вклад в фьюжн)
  note?: string // пояснение понятными словами
}

export interface RetrievalTrace {
  branches: RetrievalBranch[]
  fusion?: string // напр. «RRF (k=60) + скор-гейтинг»
  total_candidates?: number
  synthesized?: boolean // true = собрано на фронте (бэкенд не прислал поле)
}

export interface ExpertSummary {
  id: string
  name: string
  affiliation: string // лаборатория/организация
  n_works: number
  topics?: string[]
  facility_type?: 'lab' | 'plant' | 'institute'
}

export interface ContradictionSide {
  assertion_id: string
  statement: string
  confidence: Confidence
  citation?: Citation
}

export interface Contradiction {
  id: string
  topic: string
  a: ContradictionSide
  b: ContradictionSide
  note?: string
}

export interface KnowledgeGap {
  id: string
  title: string
  description: string
  severity: 'high' | 'medium' | 'low'
}

export interface ConfidenceSummary {
  overall: Confidence
  n_high: number
  n_medium: number
  n_low: number
  note?: string
}

export interface SearchResponse {
  answer_md: string
  intent: Intent
  citations: Citation[]
  subgraph: Subgraph
  experts: ExpertSummary[]
  contradictions: Contradiction[]
  gaps: KnowledgeGap[]
  confidence_summary: ConfidenceSummary
  took_ms: number
  search_id: string
  // Трасса извлечения (объяснимость). Опционально: бэкенд-агент «Answer-Quality»
  // добавляет её в /api/search; при отсутствии — синтезируется адаптером.
  retrieval_trace?: RetrievalTrace
}

// ---- Граф: node/overview (§4.3 GET /api/graph/*) -----------------------------
export interface NodeNeighbors {
  node: GraphNode
  neighbors: Subgraph
}

// ---- Документы (§4.3 GET /api/documents/{doc_id}) ----------------------------
export interface DocumentChunk {
  chunk_id: string
  seq: number
  text: string
  page_from?: number
  page_to?: number
  section_title?: string
}

export interface DocumentMeta {
  doc_id: string
  title: string
  section: Section
  journal?: string | null
  year: number
  lang: 'ru' | 'en' | 'mixed'
  source_type: SourceType
  geography_hint: Geography
  n_pages?: number
  n_chunks?: number
  chunks?: DocumentChunk[]
}

// ---- Статистика/дашборд (§4.3 GET /api/stats) --------------------------------
export interface CoverageBucket {
  key: string
  label: string
  n_docs: number
  n_assertions: number
}

export interface DomainSummary {
  domain: string
  n_processes: number
  processes: string[]
  summary: string
}

export interface StatsResponse {
  n_documents: number
  n_nodes: number
  n_edges: number
  n_assertions: number
  n_contradictions: number
  node_types?: Record<string, number>
  by_domain: CoverageBucket[]
  by_section: CoverageBucket[]
  by_year: { year: number; n_docs: number }[]
  top_gaps: KnowledgeGap[]
  domain_summaries?: Record<string, DomainSummary>
  n_corpus_total?: number // «обработано X из 1453»
}

// ---- Подписки (§4.3 POST /api/subscriptions) ---------------------------------
export interface Subscription {
  id: string
  query: string
  email?: string
  created_at: string
  n_new: number
}

export interface SubscriptionUpdate {
  doc_id: string
  title: string
  year: number
  added_at: string
  reason: string
}

// ---- Сравнение технологий (§4.3 GET /api/compare) ----------------------------
export interface CompareRow {
  param: string
  values: (string | null)[] // по одному значению на технологию (в порядке techs)
}

export interface CompareTech {
  id: string
  name: string
}

export interface CompareResponse {
  techs: CompareTech[]
  rows: CompareRow[]
}

// ---- Экспорт (§4.3 POST /api/export) -----------------------------------------
export type ExportFormat = 'md' | 'jsonld' | 'pdf' | 'xlsx'

export interface ExportResult {
  filename: string
  content: string // текст (md/jsonld) или base64 (pdf/xlsx) — скачиваем клиентом
  mime: string
  encoding?: 'text' | 'base64' | 'base64-html'
}

// ---- Аудит (§4.3 GET /api/audit/log) -----------------------------------------
export interface AuditEntry {
  ts: string
  role: string
  action: string
  detail: string
}

// ---- Аутентификация (§4.3 POST /api/auth/token) ------------------------------
export interface TokenResponse {
  access_token: string
  role: Role
}

// ---- Ручная правка графа / review (D10) --------------------------------------
export interface EdgePatch {
  author: string
  comment: string
  confidence?: number
}

export interface ReviewResult {
  id: string
  review_status: ReviewStatus
  author?: string
  comment?: string
  version?: number
  updated_at?: string
}

// ---- Поиск концептов для сравнения (GET /api/concepts) ------------------------
// Контракт: ?type=Process|Equipment|Material&q=<подстрока>&comparable=1&limit=20 —
// поиск по name/name_en/aliases всех узлов графа (регистронезависимый CONTAINS);
// comparable=1 → только узлы с operates_at_condition/measured/uses_material.
export interface ConceptHit {
  id: string
  type: NodeType
  name: string
  name_en?: string
  aliases?: string[]
  comparable?: boolean // есть параметры для сравнения
}

// ---- Загрузка документа (docs/CONTRACT_UPLOAD.md) -----------------------------
export type UploadStage =
  | 'queued'
  | 'extracting_text'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'extracting_knowledge'
  | 'merging_graph'
  | 'done'
  | 'failed'

export type UploadStageStatus = 'ok' | 'skipped' | 'deferred' | 'partial'

export interface UploadStageInfo {
  status: UploadStageStatus
  detail?: string
  took_ms?: number
  [k: string]: unknown
}

export interface UploadResult {
  doc_id: string
  n_chunks: number
  n_entities: number
  n_edges: number
  extraction_deferred: boolean
  graph_preview: Subgraph // ≤30 узлов, та же онтология, что и subgraph ответа
  stages: Partial<Record<Exclude<UploadStage, 'queued' | 'done' | 'failed'>, UploadStageInfo>>
}

export interface UploadStartResponse {
  job_id: string
  doc_id: string
  cached: boolean
  stage: UploadStage
}

export interface UploadJobStatus {
  job_id: string
  doc_id: string
  filename?: string
  stage: UploadStage
  progress: number // 0..1
  detail?: string
  error?: string | null
  result?: UploadResult | null
}

// ---- История запросов (D7, localStorage) -------------------------------------
export interface QueryHistoryItem {
  query: string
  ts: number
  search_id?: string
  intent?: IntentType
  n_citations?: number
}
