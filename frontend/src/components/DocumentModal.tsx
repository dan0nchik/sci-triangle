import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { DocumentMeta, GraphNode, Subgraph } from '../api/types'
import { NODE_COLORS, NODE_LABELS } from '../lib/ontology'
import { useApp } from '../store'

const GEO_LABEL: Record<string, string> = { RU: 'Россия', foreign: 'Зарубеж', global: 'Мир' }
const TYPE_LABEL: Record<string, string> = {
  review: 'Обзор', article: 'Статья', report: 'Доклад', presentation: 'Презентация',
  patent: 'Патент', market_report: 'Рыночный отчёт', book: 'Книга', proceedings: 'Конференция',
}

// Полная карточка документа (D4): метаданные, все чанки с подсветкой цитируемого,
// «открыть в графе», ссылки на извлечённые из документа сущности/Assertion.
export function DocumentModal() {
  const { openDocId, openDocChunkId: highlightChunkId, setOpenDocId } = useApp()
  const nav = useNavigate()
  const [doc, setDoc] = useState<DocumentMeta | null>(null)
  const [entities, setEntities] = useState<GraphNode[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!openDocId) {
      setDoc(null)
      setEntities([])
      return
    }
    setLoading(true)
    setError(null)
    api
      .document(openDocId)
      .then(setDoc)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка загрузки документа'))
      .finally(() => setLoading(false))
    // извлечённые из документа сущности — соседи узла pub:{doc_id}
    api
      .nodeNeighbors(`pub:${openDocId}`, 1)
      .then((nb: { neighbors: Subgraph }) =>
        setEntities(nb.neighbors.nodes.filter((n) => n.id !== `pub:${openDocId}`)),
      )
      .catch(() => setEntities([]))
  }, [openDocId])

  if (!openDocId) return null

  const close = () => setOpenDocId(null)
  const openInGraph = () => {
    close()
    nav('/graph', { state: { focusNode: `pub:${openDocId}` } })
  }

  return (
    <div className="fixed inset-0 z-[60] flex">
      <div className="absolute inset-0 bg-black/60" onClick={close} />
      <div className="relative ml-auto h-full w-full max-w-2xl bg-ink-850 border-l border-ink-700 shadow-2xl overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-ink-700 bg-ink-850">
          <div className="flex items-center gap-2">
            <span className="chip bg-node-publication/20 text-node-publication">Документ</span>
            <span className="text-xs font-mono text-slate-500">{openDocId}</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={openInGraph} className="btn-ghost text-xs">🕸 Открыть в графе</button>
            <button onClick={close} className="text-slate-500 hover:text-white text-2xl leading-none">×</button>
          </div>
        </div>

        <div className="px-6 py-5 space-y-5">
          {loading && (
            <div className="space-y-3">
              <div className="skeleton h-7 w-3/4" />
              <div className="skeleton h-5 w-1/2" />
              <div className="skeleton h-24 w-full" />
              <div className="skeleton h-24 w-full" />
            </div>
          )}

          {error && !loading && (
            <div className="card p-4 border-rose-500/40 bg-rose-500/[0.06] text-sm text-rose-300">{error}</div>
          )}

          {doc && !loading && (
            <>
              <div>
                <h2 className="text-xl font-semibold text-white leading-snug">{doc.title}</h2>
                <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                  <span className="chip bg-ink-700 text-slate-300">{doc.year} г.</span>
                  <span className="chip bg-ink-700 text-slate-300">{TYPE_LABEL[doc.source_type] ?? doc.source_type}</span>
                  <span className="chip bg-ink-700 text-slate-300">{doc.section}</span>
                  <span className="chip bg-ink-700 text-slate-300">{GEO_LABEL[doc.geography_hint] ?? doc.geography_hint}</span>
                  {doc.journal && <span className="chip bg-ink-700 text-slate-300">{doc.journal}</span>}
                  <span className="chip bg-ink-700 text-slate-300">{doc.lang.toUpperCase()}</span>
                  {doc.n_pages != null && <span className="chip bg-ink-700 text-slate-400">{doc.n_pages} стр.</span>}
                  {doc.n_chunks != null && <span className="chip bg-ink-700 text-slate-400">{doc.n_chunks} чанков</span>}
                </div>
              </div>

              {/* Извлечённые сущности/Assertion */}
              {entities.length > 0 && (
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">
                    Извлечённые сущности и утверждения ({entities.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {entities.map((e) => (
                      <button
                        key={e.id}
                        onClick={openInGraph}
                        title={e.statement ?? e.name}
                        className="chip border border-ink-600 hover:border-accent"
                        style={{ color: NODE_COLORS[e.type], backgroundColor: `${NODE_COLORS[e.type]}18` }}
                      >
                        {NODE_LABELS[e.type]}: {e.name.length > 28 ? e.name.slice(0, 26) + '…' : e.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Чанки */}
              <div>
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">
                  Фрагменты (чанки){doc.chunks ? ` · ${doc.chunks.length}` : ''}
                </div>
                <div className="space-y-3">
                  {(doc.chunks ?? []).map((c) => {
                    const hl = highlightChunkId && c.chunk_id === highlightChunkId
                    return (
                      <div
                        key={c.chunk_id}
                        className={`rounded-lg p-3 border ${
                          hl ? 'border-accent bg-accent-dim/15' : 'border-ink-700 bg-ink-800'
                        }`}
                      >
                        <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1.5">
                          <span className="font-mono">{c.chunk_id}{c.section_title ? ` · ${c.section_title}` : ''}</span>
                          {c.page_from != null && (
                            <span>стр. {c.page_from}{c.page_to && c.page_to !== c.page_from ? `–${c.page_to}` : ''}</span>
                          )}
                        </div>
                        <p className="text-sm text-slate-200 leading-relaxed">{c.text}</p>
                        {hl && <div className="mt-1.5 text-[11px] text-accent-soft">↑ цитируемый в ответе фрагмент</div>}
                      </div>
                    )
                  })}
                  {(!doc.chunks || doc.chunks.length === 0) && (
                    <p className="text-sm text-slate-500">Чанки документа недоступны.</p>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
