import type { GraphNode, ReviewStatus } from '../api/types'
import { NODE_COLORS, NODE_LABELS } from '../lib/ontology'

// Карточка узла графа (D4: карточка сущности) + «раскрыть соседей»,
// ссылки на документы-источники и (для admin/lead) review-действия по Assertion.
export function NodeCard({
  node,
  onExpand,
  onClose,
  onOpenDoc,
  editable = false,
  onReview,
  reviewMsg,
}: {
  node: GraphNode
  onExpand: (id: string) => void
  onClose: () => void
  onOpenDoc?: (docId: string) => void
  editable?: boolean
  onReview?: (status: ReviewStatus) => void
  reviewMsg?: string | null
}) {
  const color = NODE_COLORS[node.type] ?? '#90a4ae'
  const props = node.props ?? {}
  const isAssertion = node.type === 'Assertion'
  // Для Publication сам узел является документом (pub:{doc_id})
  const docIds = node.source_docs ?? (node.type === 'Publication' ? [node.id.replace(/^pub:/, '')] : [])

  return (
    <div className="card p-4 space-y-3 max-h-[80vh] overflow-y-auto">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: color }} />
          <span className="chip" style={{ color, backgroundColor: `${color}22` }}>
            {NODE_LABELS[node.type]}
          </span>
          {isAssertion && node.review_status && (
            <span className="chip bg-ink-700 text-slate-400">{node.review_status}</span>
          )}
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white text-lg leading-none">×</button>
      </div>

      <div>
        <div className="font-semibold text-white leading-snug">{node.name}</div>
        {node.name_en && <div className="text-xs text-slate-500">{node.name_en}</div>}
      </div>

      {node.statement && (
        <p className="text-sm text-slate-300 leading-relaxed border-l-2 border-node-assertion/50 pl-2">
          {node.statement}
        </p>
      )}

      {node.aliases && node.aliases.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {node.aliases.map((a) => (
            <span key={a} className="chip bg-ink-700 text-slate-400">{a}</span>
          ))}
        </div>
      )}

      {Object.keys(props).length > 0 && (
        <div className="text-xs font-mono text-slate-400 space-y-0.5 bg-ink-850 rounded-lg p-2.5">
          {Object.entries(props).map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <span className="text-slate-500">{k}:</span>
              <span className="text-slate-300">{String(v)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Ссылки на документы-источники (D4) */}
      {docIds.length > 0 && onOpenDoc && (
        <div className="space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Документы</div>
          <div className="flex flex-wrap gap-1">
            {docIds.map((d) => (
              <button
                key={d}
                onClick={() => onOpenDoc(d)}
                className="chip bg-node-publication/15 text-node-publication hover:brightness-125"
              >
                📄 {d}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-slate-500">
        <span className="font-mono">{node.id}</span>
        {node.confidence != null && <span>conf {(node.confidence * 100).toFixed(0)}%</span>}
      </div>

      {/* Режим правки (D10): review Assertion */}
      {editable && isAssertion && onReview && (
        <div className="border-t border-ink-700 pt-3 space-y-2">
          <div className="text-[11px] uppercase tracking-wide text-cyan-300">Экспертная правка</div>
          <div className="flex gap-1.5">
            <button onClick={() => onReview('confirmed')} className="chip bg-emerald-500/15 text-emerald-300 flex-1 justify-center">✓ Подтвердить</button>
            <button onClick={() => onReview('disputed')} className="chip bg-amber-500/15 text-amber-300 flex-1 justify-center">⚑ Оспорить</button>
            <button onClick={() => onReview('rejected')} className="chip bg-rose-500/15 text-rose-300 flex-1 justify-center">✕ Отклонить</button>
          </div>
          {reviewMsg && <p className="text-[11px] text-slate-400">{reviewMsg}</p>}
        </div>
      )}

      <button onClick={() => onExpand(node.id)} className="btn-accent w-full justify-center">
        ⊕ Раскрыть соседей
      </button>
    </div>
  )
}
