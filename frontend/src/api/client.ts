// ============================================================================
// Слой API-клиента с переключателем режима.
//   VITE_API_URL задан  → реальный бэкенд (направление C, http://localhost:8000)
//   VITE_API_URL пуст   → встроенные моки (mocks.ts)
//
// Живой бэкенд (fixture) местами отдаёт данные в форме, отличной от контракта
// §4.3 (intent.query_type, confidence_summary-строка, stats-словари, gaps-строки).
// Поэтому ответы нормализуются адаптерами к строгим типам фронтенда.
// ============================================================================
import type {
  AuditEntry,
  CompareResponse,
  DocumentMeta,
  EdgePatch,
  ExportFormat,
  ExportResult,
  ExpertSummary,
  KnowledgeGap,
  NodeNeighbors,
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
import {
  mockAudit,
  mockAuthToken,
  mockCompare,
  mockDocument,
  mockExperts,
  mockExport,
  mockNodeNeighbors,
  mockOverviewGraph,
  mockPatchEdge,
  mockReviewAssertion,
  mockSearch,
  mockStats,
  mockSubscriptionCreate,
  mockSubscriptions,
  mockSubscriptionUpdates,
} from './mocks'

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '')

export const isMockMode = !API_URL

// ---- JWT-токен (RBAC-демо): выставляется store при получении токена ----------
let authToken: string | null = null
export function setAuthToken(t: string | null) {
  authToken = t
}
export function getAuthToken() {
  return authToken
}

// Ошибка с кодом статуса — для отдельной обработки 401/403 в UI.
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  // Демо-токен (RBAC ещё не задеплоен) НЕ отправляем на живой сервер — иначе
  // эндпоинты, валидирующие JWT, отвечают 403. Отправляем только реальные токены.
  const sendAuth = authToken && !authToken.startsWith('demo.')
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(sendAuth ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiError(res.status, `API ${res.status} ${res.statusText}${body ? `: ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

// ============================================================================
// Адаптеры: живой ответ → строгий тип фронтенда
// ============================================================================
type AnyObj = Record<string, unknown>

function adaptSearch(raw: AnyObj): SearchResponse {
  const rawIntent = (raw.intent ?? {}) as AnyObj
  const concepts = Array.isArray(rawIntent.concepts)
    ? (rawIntent.concepts as unknown[]).map((c) =>
        typeof c === 'string' ? c : String((c as AnyObj)?.name ?? ''),
      )
    : []
  const intentType = (rawIntent.type ?? rawIntent.query_type ?? 'lookup') as SearchResponse['intent']['type']

  // confidence_summary может прийти строкой ("high") или объектом
  const rawCS = raw.confidence_summary
  const confidence_summary =
    typeof rawCS === 'string'
      ? { overall: rawCS as 'high' | 'medium' | 'low', n_high: 0, n_medium: 0, n_low: 0 }
      : (rawCS as SearchResponse['confidence_summary']) ?? {
          overall: 'medium',
          n_high: 0,
          n_medium: 0,
          n_low: 0,
        }

  // gaps: живой сервер отдаёт строки; контракт — объекты
  const rawGaps = (raw.gaps ?? []) as unknown[]
  const gaps: KnowledgeGap[] = rawGaps.map((g, i) =>
    typeof g === 'string'
      ? { id: `gap_${i}`, title: g.length > 60 ? g.slice(0, 57) + '…' : g, description: g, severity: 'medium' }
      : (g as KnowledgeGap),
  )

  return {
    answer_md: String(raw.answer_md ?? ''),
    intent: {
      type: intentType,
      concepts,
      numeric_constraints: (rawIntent.numeric_constraints ?? rawIntent.conditions) as string[] | undefined,
      geography: (rawIntent.geography ?? 'all') as SearchResponse['intent']['geography'],
      years: rawIntent.years as [number, number] | undefined,
    },
    citations: (raw.citations ?? []) as SearchResponse['citations'],
    subgraph: (raw.subgraph ?? { nodes: [], edges: [] }) as Subgraph,
    experts: (raw.experts ?? []) as ExpertSummary[],
    contradictions: (raw.contradictions ?? []) as SearchResponse['contradictions'],
    gaps,
    confidence_summary,
    took_ms: Number(raw.took_ms ?? 0),
    search_id: String(raw.search_id ?? ''),
  }
}

function bucketsFromDict(
  dict: unknown,
  labels: Record<string, string> = {},
): { key: string; label: string; n_docs: number; n_assertions: number }[] {
  if (Array.isArray(dict)) return dict as never
  if (!dict || typeof dict !== 'object') return []
  return Object.entries(dict as Record<string, number>).map(([key, v]) => ({
    key,
    label: labels[key] ?? key,
    n_docs: typeof v === 'number' ? v : ((v as AnyObj)?.n_docs as number) ?? 0,
    n_assertions: typeof v === 'number' ? 0 : ((v as AnyObj)?.n_assertions as number) ?? 0,
  }))
}

const DOMAIN_LABELS: Record<string, string> = {
  hydro: 'Гидрометаллургия',
  pyro: 'Пирометаллургия',
  обогащение: 'Обогащение',
  экология: 'Экология',
  'горное дело': 'Горное дело',
  водоочистка: 'Водоочистка',
}

function adaptStats(raw: AnyObj): StatsResponse {
  // Если ответ уже в форме контракта (моки) — by_domain это массив
  const nodeTypes = (raw.node_types ?? {}) as Record<string, number>
  const nAssertions = Number(raw.n_assertions ?? nodeTypes.Assertion ?? 0)
  const nContra =
    typeof raw.n_contradictions === 'number'
      ? raw.n_contradictions
      : Number(raw.contradictions ?? 0)

  const byYearRaw = raw.by_year
  const by_year = Array.isArray(byYearRaw)
    ? (byYearRaw as { year: number; n_docs: number }[])
    : Object.entries((byYearRaw ?? {}) as Record<string, number>)
        .map(([year, n_docs]) => ({ year: Number(year), n_docs: Number(n_docs) }))
        .sort((a, b) => a.year - b.year)

  const rawGaps = (raw.top_gaps ?? raw.gaps ?? []) as unknown[]
  const top_gaps: KnowledgeGap[] = rawGaps.map((g, i) =>
    typeof g === 'string'
      ? { id: `g${i}`, title: g.length > 70 ? g.slice(0, 67) + '…' : g, description: g, severity: 'medium' }
      : (g as KnowledgeGap),
  )

  const domainSummaries = raw.domain_summaries as StatsResponse['domain_summaries']

  return {
    n_documents: Number(raw.n_documents ?? 0),
    n_nodes: Number(raw.n_nodes ?? 0),
    n_edges: Number(raw.n_edges ?? 0),
    n_assertions: nAssertions,
    n_contradictions: nContra,
    node_types: nodeTypes,
    by_domain: bucketsFromDict(raw.by_domain, DOMAIN_LABELS),
    by_section: bucketsFromDict(raw.by_section),
    by_year,
    top_gaps,
    domain_summaries: domainSummaries,
    n_corpus_total: raw.n_corpus_total != null ? Number(raw.n_corpus_total) : undefined,
  }
}

function adaptDocument(raw: AnyObj): DocumentMeta {
  return {
    ...(raw as unknown as DocumentMeta),
    geography_hint: (raw.geography_hint ?? raw.geography ?? 'RU') as DocumentMeta['geography_hint'],
  }
}

function adaptCompare(raw: AnyObj): CompareResponse {
  // живой формат: {tech_a, tech_b, rows:[{param, tech_a, tech_b}]}
  const rawRows = (raw.rows ?? []) as AnyObj[]
  const techs = [
    { id: String(raw.tech_a ?? 'a'), name: nameFromId(String(raw.tech_a ?? 'a')) },
    { id: String(raw.tech_b ?? 'b'), name: nameFromId(String(raw.tech_b ?? 'b')) },
  ]
  const rows = rawRows.map((r) => ({
    param: String(r.param ?? ''),
    values: [
      r.tech_a != null ? String(r.tech_a) : null,
      r.tech_b != null ? String(r.tech_b) : null,
    ],
  }))
  return { techs, rows }
}

function nameFromId(id: string): string {
  return id.replace(/^[a-z]+:/, '').replace(/_/g, ' ')
}

// ============================================================================
// Публичный API
// ============================================================================
export const api = {
  mode: isMockMode ? ('mock' as const) : ('live' as const),
  baseUrl: API_URL ?? null,

  async search(req: SearchRequest): Promise<SearchResponse> {
    if (isMockMode) return mockSearch(req)
    const raw = await http<AnyObj>('/api/search', { method: 'POST', body: JSON.stringify(req) })
    return adaptSearch(raw)
  },

  async nodeNeighbors(id: string, depth = 1): Promise<NodeNeighbors> {
    if (isMockMode) return mockNodeNeighbors(id)
    return http<NodeNeighbors>(`/api/graph/node/${encodeURIComponent(id)}?depth=${depth}`)
  },

  async overview(limit = 300): Promise<Subgraph> {
    if (isMockMode) return mockOverviewGraph()
    return http<Subgraph>(`/api/graph/overview?limit=${limit}`)
  },

  async document(doc_id: string): Promise<DocumentMeta> {
    if (isMockMode) return mockDocument(doc_id)
    const raw = await http<AnyObj>(`/api/documents/${encodeURIComponent(doc_id)}`)
    return adaptDocument(raw)
  },

  async experts(topic: string): Promise<ExpertSummary[]> {
    if (isMockMode) return mockExperts(topic)
    try {
      const raw = await http<AnyObj>(`/api/experts?topic=${encodeURIComponent(topic)}`)
      return (Array.isArray(raw) ? raw : (raw.experts ?? [])) as ExpertSummary[]
    } catch {
      return mockExperts(topic)
    }
  },

  async stats(): Promise<StatsResponse> {
    if (isMockMode) return mockStats()
    const raw = await http<AnyObj>('/api/stats')
    return adaptStats(raw)
  },

  async compare(techA: string, techB: string, params: string[]): Promise<CompareResponse> {
    if (isMockMode) return mockCompare(techA, techB, params)
    const qs = new URLSearchParams()
    qs.set('tech_a', techA)
    qs.set('tech_b', techB)
    if (params.length) qs.set('params', params.join(','))
    const raw = await http<AnyObj>(`/api/compare?${qs.toString()}`)
    return adaptCompare(raw)
  },

  // ---- Экспорт (D7) — все 4 формата (md/jsonld текст, pdf/xlsx base64) --------
  async exportSearch(search_id: string, format: ExportFormat): Promise<ExportResult> {
    if (isMockMode) return mockExport(search_id, format)
    const raw = await http<AnyObj>('/api/export', {
      method: 'POST',
      body: JSON.stringify({ search_id, format }),
    })
    const encoding = (raw.encoding as ExportResult['encoding']) ?? 'text'
    const MIME: Record<string, string> = {
      md: 'text/markdown',
      jsonld: 'application/ld+json',
      pdf: encoding === 'base64-html' ? 'text/html' : 'application/pdf',
      xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }
    return {
      filename: String(raw.filename ?? `${search_id}.${format}`),
      content: String(raw.content ?? ''),
      mime: MIME[format] ?? 'application/octet-stream',
      encoding,
    }
  },

  // ---- Подписки (D6) --------------------------------------------------------
  async subscriptions(): Promise<Subscription[]> {
    if (isMockMode) return mockSubscriptions()
    // Живой сервер отдаёт список через GET /api/subscriptions (SubscriptionListResponse).
    try {
      const raw = await http<AnyObj>('/api/subscriptions')
      const list = (raw.subscriptions ?? raw) as AnyObj[]
      return (Array.isArray(list) ? list : []).map((s) => ({
        id: String(s.id),
        query: String(s.query ?? ''),
        email: (s.email as string | undefined) ?? undefined,
        created_at: String(s.created_at ?? new Date().toISOString()),
        n_new: Number(s.n_new ?? 0),
      }))
    } catch {
      return []
    }
  },

  async createSubscription(query: string, email?: string): Promise<Subscription> {
    if (isMockMode) return mockSubscriptionCreate(query, email)
    const raw = await http<AnyObj>('/api/subscriptions', {
      method: 'POST',
      body: JSON.stringify({ query, email: email ?? null }),
    })
    return {
      id: String(raw.id),
      query: String(raw.query ?? query),
      email: (raw.email as string | undefined) ?? email,
      created_at: String(raw.created_at ?? new Date().toISOString()),
      n_new: Number(raw.n_new ?? 0),
    }
  },

  async subscriptionUpdates(id: string): Promise<SubscriptionUpdate[]> {
    if (isMockMode) return mockSubscriptionUpdates(id)
    try {
      // живой сервер отдаёт конверт {id, query, n_new, updates: [...]}
      const raw = await http<AnyObj>(`/api/subscriptions/${encodeURIComponent(id)}/updates`)
      const list = (Array.isArray(raw) ? raw : (raw.updates ?? [])) as AnyObj[]
      return list.map((u) => ({
        doc_id: String(u.doc_id ?? ''),
        title: String(u.title ?? u.doc_id ?? ''),
        year: Number(u.year ?? 0),
        added_at: String(u.added_at ?? u.ingested_at ?? ''),
        reason: String(u.reason ?? u.quote ?? 'релевантно сохранённому запросу'),
      }))
    } catch {
      return []
    }
  },

  // ---- Аудит (D11) ----------------------------------------------------------
  async audit(): Promise<AuditEntry[]> {
    if (isMockMode) return mockAudit()
    try {
      const raw = await http<AnyObj>('/api/audit/log')
      return ((raw.entries ?? raw) as AuditEntry[]) ?? []
    } catch {
      return mockAudit()
    }
  },

  // ---- RBAC (D10) -----------------------------------------------------------
  async authToken(role: Role): Promise<TokenResponse> {
    if (isMockMode) return mockAuthToken(role)
    try {
      const raw = await http<AnyObj>('/api/auth/token', {
        method: 'POST',
        body: JSON.stringify({ role }),
      })
      return {
        access_token: String(raw.access_token ?? raw.token ?? ''),
        role: (raw.role as Role) ?? role,
      }
    } catch {
      // RBAC ещё не задеплоен — демо-токен локально
      return mockAuthToken(role)
    }
  },

  // ---- Ручная правка графа (D10) --------------------------------------------
  async patchEdge(id: string, patch: EdgePatch): Promise<ReviewResult> {
    if (isMockMode) return mockPatchEdge(id, patch)
    return http<ReviewResult>(`/api/graph/edge/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  async reviewAssertion(
    id: string,
    status: ReviewStatus,
    comment: string,
    author: string,
  ): Promise<ReviewResult> {
    if (isMockMode) return mockReviewAssertion(id, status, comment, author)
    return http<ReviewResult>(`/api/assertions/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      body: JSON.stringify({ status, comment, author }),
    })
  },
}
