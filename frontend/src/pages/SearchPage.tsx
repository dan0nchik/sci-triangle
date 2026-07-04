import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { Citation, ExportFormat, SearchFilters, SearchResponse } from '../api/types'
import { GOLDEN_QUERIES } from '../lib/ontology'
import { downloadText, downloadBase64 } from '../lib/download'
import { useApp, RESTRICTED_ROLE } from '../store'
import { FiltersPanel } from '../components/FiltersPanel'
import { AnswerMarkdown } from '../components/AnswerMarkdown'
import { SourceDrawer } from '../components/SourceDrawer'
import { ConfidenceBadge } from '../components/ConfidenceBadge'
import {
  ContradictionsSection,
  ExpertsSection,
  GapsSection,
} from '../components/PacketSections'

const DEFAULT_FILTERS: SearchFilters = {
  year_from: 2000,
  year_to: 2026,
  geography: 'all',
  confidence_min: 0,
}

const INTENT_LABEL: Record<string, string> = {
  lookup: 'точечный поиск',
  review: 'обзор',
  compare: 'сравнение',
  aggregate: 'агрегация',
  gap: 'поиск пробелов',
}

export function SearchPage() {
  const nav = useNavigate()
  const { role, lastResult, setLastResult, lastQuery, setLastQuery, history, pushHistory } = useApp()
  const [query, setQuery] = useState(lastQuery)
  const [filters, setFilters] = useState<SearchFilters>(DEFAULT_FILTERS)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [denied, setDenied] = useState(false)
  const [drawer, setDrawer] = useState<{ c: Citation; i: number } | null>(null)
  const [exporting, setExporting] = useState<ExportFormat | null>(null)
  const [exportMsg, setExportMsg] = useState<string | null>(null)

  const result = lastResult

  async function run(q: string) {
    const text = q.trim()
    if (!text) return
    setLoading(true)
    setError(null)
    setDenied(false)
    setLastQuery(text)
    try {
      const res: SearchResponse = await api.search({ query: text, filters, role_ctx: role })
      setLastResult(res)
      pushHistory({
        query: text,
        ts: Date.now(),
        search_id: res.search_id,
        intent: res.intent.type,
        n_citations: res.citations.length,
      })
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setDenied(true)
        setLastResult(null)
      } else {
        setError(e instanceof Error ? e.message : 'Ошибка запроса к API')
        setLastResult(null)
      }
    } finally {
      setLoading(false)
    }
  }

  async function doExport(format: ExportFormat) {
    if (!result?.search_id) return
    setExporting(format)
    setExportMsg(null)
    try {
      const r = await api.exportSearch(result.search_id, format)
      if (r.encoding === 'base64' || r.encoding === 'base64-html') {
        downloadBase64(r.filename, r.content, r.mime)
      } else {
        downloadText(r.filename, r.content, r.mime)
      }
      setExportMsg(`Скачано: ${r.filename}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setExportMsg(
        /unsupported|400|404/i.test(msg)
          ? `Формат ${format} недоступен на сервере (для demo — попробуйте md/JSON-LD)`
          : `Ошибка экспорта: ${msg}`,
      )
    } finally {
      setExporting(null)
    }
  }

  const openCite = (index: number) => {
    const c = result?.citations[index - 1]
    if (c) setDrawer({ c, i: index })
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-white">Поиск по карте знаний R&D</h1>
        <p className="text-slate-400 mt-1">
          Задайте вопрос на естественном языке — система вернёт связный ответ с доказательствами,
          источниками, подграфом знаний и экспертами.
        </p>
      </header>

      {/* Крупная NL-строка */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run(query)
            }}
            rows={2}
            placeholder="Например: оптимальная скорость циркуляции католита при электроэкстракции никеля…"
            className="w-full resize-none rounded-xl bg-ink-800 border border-ink-600 px-4 py-3.5 text-base text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-accent"
          />
          <span className="absolute right-3 bottom-2.5 text-[11px] text-slate-600">⌘/Ctrl + Enter</span>
        </div>
        <button
          onClick={() => run(query)}
          disabled={loading || !query.trim()}
          className="btn-accent px-6 self-stretch"
        >
          {loading ? 'Поиск…' : 'Найти'}
        </button>
      </div>

      {/* 4 кликабельных примера — golden queries */}
      <div className="mt-3 flex flex-wrap gap-2">
        <span className="text-xs text-slate-500 self-center mr-1">Примеры:</span>
        {GOLDEN_QUERIES.map((g) => (
          <button
            key={g.title}
            onClick={() => {
              setQuery(g.query)
              run(g.query)
            }}
            title={g.hint}
            className="chip bg-ink-800 border border-ink-600 text-slate-300 hover:border-accent hover:text-accent-soft"
          >
            {g.title}
          </button>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
        {/* Панель фильтров + история */}
        <div className="lg:sticky lg:top-6 self-start w-full space-y-4">
          <FiltersPanel filters={filters} onChange={setFilters} />
          <HistoryPanel history={history} onRun={(q) => { setQuery(q); run(q) }} />
        </div>

        {/* Область результатов */}
        <div className="min-w-0 space-y-6">
          {loading && <LoadingSkeleton />}

          {error && !loading && (
            <div className="card p-5 border-rose-500/40 bg-rose-500/[0.06]">
              <div className="text-rose-300 font-medium">Ошибка запроса</div>
              <p className="text-sm text-slate-400 mt-1">{error}</p>
              <p className="text-xs text-slate-500 mt-2">
                Проверьте, что бэкенд доступен (VITE_API_URL), или уберите переменную для работы на моках.
              </p>
            </div>
          )}

          {denied && !loading && (
            <div className="card p-5 border-amber-500/40 bg-amber-500/[0.06]">
              <div className="text-amber-300 font-medium">Недостаточно прав (401/403)</div>
              <p className="text-sm text-slate-400 mt-1">
                Для роли «{role === RESTRICTED_ROLE ? 'внешний партнёр' : role}» часть данных недоступна:
                внутренние разделы (Статьи, Доклады) скрыты на уровне выдачи. Смените роль в левой панели
                или уточните запрос по открытым источникам.
              </p>
            </div>
          )}

          {!loading && !error && !denied && !result && <EmptyState />}

          {!loading && result && (
            <>
              {/* Мета-строка ответа */}
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="chip bg-accent-dim/30 text-accent-soft">
                  интент: {INTENT_LABEL[result.intent.type] ?? result.intent.type}
                </span>
                <ConfidenceBadge level={result.confidence_summary.overall} />
                <span className="chip bg-ink-700 text-slate-400">
                  источников: {result.citations.length}
                </span>
                <span className="chip bg-ink-700 text-slate-400">
                  узлов: {result.subgraph.nodes.length}
                </span>
                <span className="chip bg-ink-700 text-slate-400">{result.took_ms} мс</span>
                <button
                  onClick={() => nav('/graph')}
                  className="chip bg-node-process/15 text-node-process hover:brightness-125 ml-auto"
                >
                  🕸 Открыть подграф в графе →
                </button>
              </div>

              {/* Экспорт evidence packet (D7) */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500 mr-1">Экспорт:</span>
                {(['md', 'jsonld', 'pdf', 'xlsx'] as ExportFormat[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => doExport(f)}
                    disabled={exporting !== null}
                    className="chip bg-ink-700 text-slate-300 hover:text-accent-soft border border-ink-600 disabled:opacity-40"
                  >
                    {exporting === f ? '…' : '⭳'} {f === 'jsonld' ? 'JSON-LD' : f.toUpperCase()}
                  </button>
                ))}
                {exportMsg && <span className="text-xs text-slate-400">{exportMsg}</span>}
              </div>

              {/* Markdown-ответ с inline-цитатами */}
              <div className="card p-6">
                <AnswerMarkdown markdown={result.answer_md} onCite={openCite} />
                {result.confidence_summary.note && (
                  <p className="mt-4 pt-3 border-t border-ink-700 text-xs text-slate-500">
                    ℹ {result.confidence_summary.note} (высокая: {result.confidence_summary.n_high},
                    средняя: {result.confidence_summary.n_medium}, низкая: {result.confidence_summary.n_low})
                  </p>
                )}
              </div>

              {/* Список источников */}
              {result.citations.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-lg font-semibold text-white">Источники</h3>
                  <div className="grid gap-2">
                    {result.citations.map((c, i) => (
                      <button
                        key={c.chunk_id + i}
                        onClick={() => setDrawer({ c, i: i + 1 })}
                        className="card p-3 text-left hover:border-accent-dim transition-colors flex items-start gap-3"
                      >
                        <span className="chip bg-accent-dim/40 text-accent-soft shrink-0 mt-0.5">
                          [{i + 1}]
                        </span>
                        <div className="min-w-0">
                          <div className="text-sm text-slate-200 truncate">{c.title}</div>
                          <div className="text-xs text-slate-500 truncate">
                            {c.year} · {c.doc_id} · «{c.quote.slice(0, 90)}…»
                          </div>
                        </div>
                        <div className="ml-auto shrink-0">
                          <ConfidenceBadge level={c.confidence} />
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              <ContradictionsSection items={result.contradictions} />
              <GapsSection items={result.gaps} />
              <ExpertsSection items={result.experts} />
            </>
          )}
        </div>
      </div>

      <SourceDrawer
        citation={drawer?.c ?? null}
        index={drawer?.i ?? null}
        onClose={() => setDrawer(null)}
      />
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="skeleton h-6 w-24" />
        <div className="skeleton h-6 w-20" />
        <div className="skeleton h-6 w-28" />
      </div>
      <div className="card p-6 space-y-3">
        <div className="skeleton h-6 w-2/3" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-5/6" />
        <div className="skeleton h-4 w-3/4" />
        <div className="skeleton h-24 w-full mt-2" />
      </div>
      <div className="grid gap-2">
        <div className="skeleton h-14 w-full" />
        <div className="skeleton h-14 w-full" />
      </div>
      <p className="text-center text-sm text-slate-500 animate-pulse">
        Идёт retrieval и синтез evidence packet… (может занять до 5 с)
      </p>
    </div>
  )
}

function HistoryPanel({
  history,
  onRun,
}: {
  history: import('../api/types').QueryHistoryItem[]
  onRun: (q: string) => void
}) {
  if (!history.length) return null
  return (
    <div className="card p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white text-sm">История запросов</h3>
        <span className="chip bg-ink-700 text-slate-500">{history.length}</span>
      </div>
      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {history.map((h) => (
          <button
            key={h.ts}
            onClick={() => onRun(h.query)}
            title={h.query}
            className="w-full text-left rounded-lg border border-ink-700 hover:border-accent-dim bg-ink-850 px-2.5 py-1.5"
          >
            <div className="text-xs text-slate-200 truncate">{h.query}</div>
            <div className="text-[10px] text-slate-500">
              {new Date(h.ts).toLocaleString('ru')}
              {h.n_citations != null ? ` · ${h.n_citations} источн.` : ''}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="card p-10 text-center">
      <div className="text-5xl mb-3">🧭</div>
      <h3 className="text-lg font-semibold text-white">Начните с вопроса</h3>
      <p className="text-slate-400 mt-1 max-w-md mx-auto">
        Введите запрос выше или выберите один из готовых примеров (golden queries). Ответ придёт
        со ссылками на дословные фрагменты источников.
      </p>
    </div>
  )
}
