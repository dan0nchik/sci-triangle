import { useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../api/client'
import type { GraphEdge, GraphNode, NodeType, ReviewStatus, Subgraph } from '../api/types'
import { GraphView, mergeSubgraphs } from '../components/GraphView'
import { NodeCard } from '../components/NodeCard'
import { LEGEND_PRIMARY, LEGEND_SECONDARY, NODE_COLORS, NODE_LABELS, EDGE_LABELS } from '../lib/ontology'
import { useApp, EDIT_ROLES } from '../store'

type Mode = 'answer' | 'overview'

export function GraphPage() {
  const { lastResult, role, openDoc } = useApp()
  const location = useLocation()
  const focusNode = (location.state as { focusNode?: string } | null)?.focusNode ?? null

  const [mode, setMode] = useState<Mode>(lastResult ? 'answer' : 'overview')
  const [overview, setOverview] = useState<Subgraph | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null)
  const [expanded, setExpanded] = useState<Subgraph>({ nodes: [], edges: [] })
  const [highlightChain, setHighlightChain] = useState(false)
  const [hiddenTypes, setHiddenTypes] = useState<Set<NodeType>>(new Set())
  const [search, setSearch] = useState('')
  const [focusId, setFocusId] = useState<string | null>(focusNode)
  const [editMode, setEditMode] = useState(false)
  const [reviewMsg, setReviewMsg] = useState<string | null>(null)

  const canEdit = EDIT_ROLES.includes(role)

  useEffect(() => {
    if (mode === 'overview' && !overview) {
      api.overview().then(setOverview).catch(() => setOverview({ nodes: [], edges: [] }))
    }
  }, [mode, overview])

  // Навигация «найти в графе» → фокус на узле
  useEffect(() => {
    if (focusNode) {
      setMode(lastResult?.subgraph.nodes.some((n) => n.id === focusNode) ? 'answer' : 'overview')
      setFocusId(focusNode)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNode])

  const baseGraph: Subgraph = useMemo(() => {
    if (mode === 'answer') return lastResult?.subgraph ?? { nodes: [], edges: [] }
    return overview ?? { nodes: [], edges: [] }
  }, [mode, lastResult, overview])

  const merged = useMemo(
    () => (expanded.nodes.length ? mergeSubgraphs(baseGraph, expanded) : baseGraph),
    [baseGraph, expanded],
  )

  // D9: фильтр по типам узлов
  const graph = useMemo(() => {
    if (hiddenTypes.size === 0) return merged
    const nodes = merged.nodes.filter((n) => !hiddenTypes.has(n.type))
    const present = new Set(nodes.map((n) => n.id))
    return { nodes, edges: merged.edges.filter((e) => present.has(e.src) && present.has(e.dst)) }
  }, [merged, hiddenTypes])

  // D9: мини-статистика по типам
  const typeCounts = useMemo(() => {
    const m = new Map<NodeType, number>()
    for (const n of graph.nodes) m.set(n.type, (m.get(n.type) ?? 0) + 1)
    return m
  }, [graph])

  const presentTypes = useMemo(() => {
    const s = new Set<NodeType>()
    for (const n of merged.nodes) s.add(n.type)
    return s
  }, [merged])

  async function expand(id: string) {
    try {
      const nb = await api.nodeNeighbors(id, 1)
      setExpanded((prev) => mergeSubgraphs(prev, nb.neighbors))
    } catch {
      /* ignore */
    }
  }

  const switchMode = (m: Mode) => {
    setMode(m)
    setSelected(null)
    setSelectedEdge(null)
    setExpanded({ nodes: [], edges: [] })
    setFocusId(null)
  }

  const toggleType = (t: NodeType) =>
    setHiddenTypes((prev) => {
      const next = new Set(prev)
      next.has(t) ? next.delete(t) : next.add(t)
      return next
    })

  const runSearch = () => {
    const q = search.trim().toLowerCase()
    if (!q) return
    const hit = graph.nodes.find(
      (n) => n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q),
    )
    if (hit) setFocusId(hit.id + '#' + Date.now().toString()) // force-маркер для повторного фокуса
  }

  async function reviewAssertion(status: ReviewStatus) {
    if (!selected) return
    const comment = window.prompt('Комментарий эксперта к правке:', '') ?? ''
    setReviewMsg('Отправка…')
    try {
      const r = await api.reviewAssertion(selected.id, status, comment, role)
      setReviewMsg(`Готово: статус «${r.review_status}»${r.version ? `, версия ${r.version}` : ''}`)
      setSelected({ ...selected, review_status: r.review_status })
    } catch (e) {
      setReviewMsg(e instanceof Error ? `Ошибка: ${e.message}` : 'Ошибка правки')
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Панель управления */}
      <div className="flex flex-wrap items-center gap-3 px-6 py-3 border-b border-ink-700 bg-ink-850">
        <h1 className="text-lg font-semibold text-fg mr-2">Граф знаний</h1>
        <div className="flex rounded-lg border border-ink-600 overflow-hidden">
          <button
            onClick={() => switchMode('answer')}
            disabled={!lastResult}
            className={`px-3 py-1.5 text-sm ${mode === 'answer' ? 'bg-accent-dim/50 text-fg' : 'text-fg-muted hover:bg-ink-700'} disabled:opacity-40`}
          >
            Подграф ответа
          </button>
          <button
            onClick={() => switchMode('overview')}
            className={`px-3 py-1.5 text-sm ${mode === 'overview' ? 'bg-accent-dim/50 text-fg' : 'text-fg-muted hover:bg-ink-700'}`}
          >
            Обзорный режим
          </button>
        </div>

        {/* D9: поиск узла */}
        <div className="flex items-center gap-1">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runSearch()}
            placeholder="найти узел…"
            className="w-40 bg-ink-800 border border-ink-600 rounded-lg px-2.5 py-1.5 text-sm text-fg-body placeholder:text-fg-faint focus:outline-none focus:border-accent"
          />
          <button onClick={runSearch} className="btn-ghost text-xs px-2 py-1.5">→</button>
        </div>

        <label className="flex items-center gap-2 text-sm text-fg-muted cursor-pointer">
          <input type="checkbox" checked={highlightChain} onChange={(e) => setHighlightChain(e.target.checked)} className="accent-accent" />
          Цепочка мат→проц→обор
        </label>

        {/* D10: режим правки для admin/lead */}
        {canEdit && (
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={editMode} onChange={(e) => setEditMode(e.target.checked)} className="accent-cyan-400" />
            <span className={editMode ? 'text-cyan-700' : 'text-fg-muted'}>Режим правки (эксперт)</span>
          </label>
        )}

        <span className="ml-auto text-xs text-fg-muted">
          {graph.nodes.length} узлов · {graph.edges.length} рёбер
          {expanded.nodes.length > 0 && ' (+соседи)'}
        </span>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Легенда + фильтры + мини-стата */}
        <div className="w-56 shrink-0 border-r border-ink-700 bg-ink-850 p-4 overflow-y-auto">
          <div className="text-xs uppercase tracking-wide text-fg-muted mb-2">Типы узлов (фильтр)</div>
          <div className="space-y-1">
            {[...LEGEND_PRIMARY, ...LEGEND_SECONDARY]
              .filter((t) => presentTypes.has(t))
              .map((t) => (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={`flex items-center gap-2 text-sm w-full text-left rounded px-1 py-0.5 ${
                    hiddenTypes.has(t) ? 'opacity-35' : 'hover:bg-ink-700'
                  }`}
                >
                  <span className="h-3 w-3 rounded-full shrink-0" style={{ backgroundColor: NODE_COLORS[t] }} />
                  <span className="text-fg-body flex-1">{NODE_LABELS[t]}</span>
                  <span className="text-[11px] text-fg-muted">{typeCounts.get(t) ?? 0}</span>
                </button>
              ))}
          </div>
          {hiddenTypes.size > 0 && (
            <button onClick={() => setHiddenTypes(new Set())} className="text-[11px] text-accent mt-2 hover:underline">
              показать все типы
            </button>
          )}

          <div className="text-xs uppercase tracking-wide text-fg-muted mt-4 mb-2">Рёбра</div>
          <div className="space-y-2 text-xs text-fg-muted">
            <div className="flex items-center gap-2"><span className="inline-block w-6 border-t border-dashed border-rose-500" /> противоречие</div>
            <div className="flex items-center gap-2"><span className="inline-block w-6 border-t border-dotted border-teal-600" /> ручная правка</div>
            <div className="flex items-center gap-2"><span className="inline-block w-6 border-t-2 border-accent" /> цепочка</div>
          </div>

          <p className="text-[11px] text-fg-faint mt-4 leading-relaxed">
            Клик по узлу — карточка. {editMode ? 'Клик по ребру — правка связи.' : 'Клик по пустому — сброс.'}
          </p>
        </div>

        {/* Холст */}
        <div className="flex-1 relative min-w-0 bg-ink-900">
          {graph.nodes.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center text-fg-muted">
              {mode === 'answer' ? 'Нет подграфа ответа — сначала выполните поиск.' : 'Загрузка обзорного графа…'}
            </div>
          ) : (
            <GraphView
              key={mode + graph.nodes.length + [...hiddenTypes].join()}
              graph={graph}
              onSelectNode={(n) => { setSelected(n); setSelectedEdge(null); setReviewMsg(null) }}
              onSelectEdge={editMode ? setSelectedEdge : undefined}
              highlightChain={highlightChain}
              layoutName="cose"
              focusId={focusId}
            />
          )}

          {/* Карточка узла */}
          {selected && (
            <div className="absolute top-4 right-4 w-72">
              <NodeCard
                node={selected}
                onExpand={expand}
                onClose={() => setSelected(null)}
                onOpenDoc={(d) => openDoc(d)}
                editable={editMode && canEdit}
                onReview={reviewAssertion}
                reviewMsg={reviewMsg}
              />
            </div>
          )}

          {/* Панель правки ребра (D10) */}
          {selectedEdge && editMode && (
            <EdgeEditPanel edge={selectedEdge} author={role} onClose={() => setSelectedEdge(null)} />
          )}
        </div>
      </div>
    </div>
  )
}

function EdgeEditPanel({ edge, author, onClose }: { edge: GraphEdge; author: string; onClose: () => void }) {
  const [comment, setComment] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (kind: 'confirm' | 'dispute' | 'correct') => {
    setBusy(true)
    setMsg(null)
    const note =
      (kind === 'confirm' ? '[подтверждено] ' : kind === 'dispute' ? '[оспорено] ' : '[исправлено] ') + comment
    try {
      const id = edge.id ?? `${edge.src}|${edge.type}|${edge.dst}`
      const r = await api.patchEdge(id, { author, comment: note, confidence: edge.confidence })
      setMsg(`Сохранено (v${r.version ?? '2'}, ${r.review_status ?? 'confirmed'}). Правка помечена как ручная.`)
    } catch (e) {
      setMsg(e instanceof Error ? `Ошибка: ${e.message}` : 'Ошибка правки')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="absolute top-4 right-4 w-80">
      <div className="card p-4 space-y-3 border-cyan-500/40">
        <div className="flex items-center justify-between">
          <span className="chip bg-cyan-500/15 text-cyan-700">Правка связи</span>
          <button onClick={onClose} className="text-fg-muted hover:text-fg text-lg leading-none">×</button>
        </div>
        <div className="text-sm text-fg-body">
          <span className="font-mono text-xs text-fg-muted">{edge.src}</span>
          <div className="text-accent-soft my-0.5">— {EDGE_LABELS[edge.type] ?? edge.type} →</div>
          <span className="font-mono text-xs text-fg-muted">{edge.dst}</span>
        </div>
        {edge.confidence != null && (
          <div className="text-xs text-fg-muted">confidence: {(edge.confidence * 100).toFixed(0)}% · метод: {edge.method ?? '—'}</div>
        )}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          placeholder="Комментарий эксперта…"
          className="w-full resize-none rounded-lg bg-ink-800 border border-ink-600 px-2.5 py-1.5 text-sm text-fg-body placeholder:text-fg-faint focus:outline-none focus:border-accent"
        />
        <div className="flex gap-1.5">
          <button disabled={busy} onClick={() => submit('confirm')} className="chip bg-emerald-500/15 text-emerald-600 flex-1 justify-center">✓ Подтвердить</button>
          <button disabled={busy} onClick={() => submit('dispute')} className="chip bg-amber-500/15 text-amber-600 flex-1 justify-center">⚑ Оспорить</button>
          <button disabled={busy} onClick={() => submit('correct')} className="chip bg-cyan-500/15 text-cyan-700 flex-1 justify-center">✎ Исправить</button>
        </div>
        {msg && <p className="text-[11px] text-fg-muted">{msg}</p>}
      </div>
    </div>
  )
}
