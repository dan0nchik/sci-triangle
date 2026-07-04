import { useMemo, useState } from 'react'
import type { NodeType, SearchResponse } from '../api/types'
import { NODE_COLORS } from '../lib/ontology'

// ============================================================================
// «Как получен ответ» (объяснимость — главная новая фича по Q&A).
// Разворачиваемый блок под ответом:
//   (а) разобранный интент понятными словами (материалы/процессы/условия/гео/годы);
//   (б) какие ветки поиска сработали (лексическая / семантическая / графовая);
//   (в) мини-путь по графу: запрос → концепты → документы (кликабельно в граф).
// ============================================================================

const INTENT_LABEL: Record<string, string> = {
  lookup: 'точечный поиск факта',
  review: 'обзор темы',
  compare: 'сравнение',
  aggregate: 'агрегация',
  gap: 'поиск пробелов',
}

const BRANCH_META: Record<
  string,
  { label: string; icon: string; color: string }
> = {
  lexical: { label: 'Лексическая', icon: '🔤', color: '#0077C8' },
  semantic: { label: 'Семантическая', icon: '🧠', color: '#17A2A2' },
  graph: { label: 'Графовая', icon: '🕸', color: '#7A5AC2' },
}

function namesOfType(r: SearchResponse, type: NodeType, limit = 6): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const n of r.subgraph.nodes) {
    if (n.type === type && !seen.has(n.name)) {
      seen.add(n.name)
      out.push(n.name)
      if (out.length >= limit) break
    }
  }
  return out
}

export function ExplainPanel({
  result,
  onOpenGraph,
  onOpenDoc,
}: {
  result: SearchResponse
  onOpenGraph: (focusNodeId?: string) => void
  onOpenDoc: (docId: string) => void
}) {
  const [open, setOpen] = useState(false)

  const parsed = useMemo(() => {
    const materials = namesOfType(result, 'Material')
    const processes = namesOfType(result, 'Process')
    const equipment = namesOfType(result, 'Equipment')
    const conditions = [
      ...(result.intent.numeric_constraints ?? []),
      ...namesOfType(result, 'Condition', 4),
    ]
    // концепты для мини-пути (кликабельно в граф) — привязываем к id узла
    const conceptNodes = result.subgraph.nodes
      .filter((n) => n.type === 'Material' || n.type === 'Process' || n.type === 'Assertion')
      .slice(0, 6)
    // документы: уникальные doc_id из цитат
    const docs: { doc_id: string; title: string }[] = []
    const seenDoc = new Set<string>()
    for (const c of result.citations) {
      if (!seenDoc.has(c.doc_id)) {
        seenDoc.add(c.doc_id)
        docs.push({ doc_id: c.doc_id, title: c.title })
      }
    }
    return { materials, processes, equipment, conditions, conceptNodes, docs }
  }, [result])

  const trace = result.retrieval_trace
  const geoLabel =
    result.intent.geography === 'RU'
      ? 'Россия'
      : result.intent.geography === 'foreign'
        ? 'зарубеж'
        : result.intent.geography === 'global'
          ? 'мир'
          : 'все'
  const years = result.intent.years
    ? `${result.intent.years[0]}–${result.intent.years[1]}`
    : 'все'

  return (
    <section className="card overflow-hidden" data-testid="explain-panel">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-ink-900/60 transition-colors"
        aria-expanded={open}
      >
        <span className="text-lg">🧩</span>
        <div className="min-w-0">
          <div className="font-semibold text-fg">Как получен ответ</div>
          <div className="text-xs text-fg-muted">
            разобранный запрос · ветки поиска · путь по графу знаний
          </div>
        </div>
        <span className={`ml-auto text-fg-muted transition-transform ${open ? 'rotate-180' : ''}`}>
          ▾
        </span>
      </button>

      {open && (
        <div className="px-5 pb-5 pt-1 space-y-5 border-t border-ink-700">
          {/* (а) Разобранный интент понятными словами */}
          <div className="space-y-2">
            <div className="text-[11px] uppercase tracking-wide text-fg-muted">
              1 · Как понят запрос
            </div>
            <p className="text-sm text-fg-body leading-relaxed">
              Тип запроса —{' '}
              <span className="font-medium text-fg">
                {INTENT_LABEL[result.intent.type] ?? result.intent.type}
              </span>
              . Система ищет:
            </p>
            <div className="grid gap-1.5 text-sm">
              <ParsedRow label="Материалы" items={parsed.materials} color={NODE_COLORS.Material} />
              <ParsedRow label="Процессы" items={parsed.processes} color={NODE_COLORS.Process} />
              {parsed.equipment.length > 0 && (
                <ParsedRow label="Оборудование" items={parsed.equipment} color={NODE_COLORS.Equipment} />
              )}
              <ParsedRow label="Условия / числа" items={parsed.conditions} color={NODE_COLORS.Condition} />
            </div>
            <div className="flex flex-wrap gap-2 pt-1 text-xs">
              <span className="chip bg-ink-700 text-fg-muted">география: {geoLabel}</span>
              <span className="chip bg-ink-700 text-fg-muted">годы: {years}</span>
            </div>
          </div>

          {/* (б) Какие ветки поиска сработали */}
          {trace && trace.branches.length > 0 && (
            <div className="space-y-2">
              <div className="text-[11px] uppercase tracking-wide text-fg-muted flex items-center gap-2">
                2 · Какие ветки поиска сработали
                {trace.synthesized && (
                  <span
                    className="chip bg-ink-700 text-fg-faint"
                    title="Трасса восстановлена на фронте из ответа; точную отдаёт бэкенд-агент Answer-Quality (retrieval_trace)."
                  >
                    оценка
                  </span>
                )}
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                {trace.branches.map((b) => {
                  const meta = BRANCH_META[b.kind]
                  return (
                    <div
                      key={b.kind}
                      className={`rounded-lg border p-3 ${
                        b.used
                          ? 'border-ink-600 bg-ink-800'
                          : 'border-ink-700 bg-ink-850 opacity-55'
                      }`}
                      style={b.used ? { borderColor: `${meta.color}66` } : undefined}
                    >
                      <div className="flex items-center gap-2">
                        <span>{meta.icon}</span>
                        <span className="text-sm font-medium text-fg">{meta.label}</span>
                        <span
                          className="chip ml-auto text-[10px]"
                          style={{
                            color: b.used ? meta.color : '#8794A1',
                            backgroundColor: b.used ? `${meta.color}1e` : 'transparent',
                          }}
                        >
                          {b.used ? `✓ ${b.hits ?? ''}`.trim() : '—'}
                        </span>
                      </div>
                      {b.note && (
                        <p className="mt-1.5 text-[11px] text-fg-muted leading-snug">{b.note}</p>
                      )}
                    </div>
                  )
                })}
              </div>
              {trace.fusion && (
                <p className="text-[11px] text-fg-muted">
                  Объединение результатов: <span className="text-fg-body">{trace.fusion}</span>
                  {trace.total_candidates != null
                    ? ` · кандидатов: ${trace.total_candidates}`
                    : ''}
                </p>
              )}
            </div>
          )}

          {/* (в) Мини-путь по графу: запрос → концепты → документы */}
          <div className="space-y-2">
            <div className="text-[11px] uppercase tracking-wide text-fg-muted">
              3 · Путь по графу знаний
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="chip bg-accent text-white">запрос</span>
              <span className="text-fg-faint">→</span>
              {parsed.conceptNodes.map((n) => (
                <button
                  key={n.id}
                  onClick={() => onOpenGraph(n.id)}
                  title="Открыть узел в графе"
                  className="chip border hover:brightness-95"
                  style={{ color: NODE_COLORS[n.type], backgroundColor: `${NODE_COLORS[n.type]}18`, borderColor: `${NODE_COLORS[n.type]}55` }}
                >
                  {n.name.length > 26 ? n.name.slice(0, 24) + '…' : n.name}
                </button>
              ))}
              <span className="text-fg-faint">→</span>
              {parsed.docs.map((d) => (
                <button
                  key={d.doc_id}
                  onClick={() => onOpenDoc(d.doc_id)}
                  title={d.title}
                  className="chip bg-node-publication/15 text-node-publication border border-node-publication/40 hover:brightness-95"
                >
                  📄 {d.doc_id}
                </button>
              ))}
            </div>
            <button
              onClick={() => onOpenGraph()}
              className="text-xs text-accent hover:text-accent-soft"
            >
              🕸 Открыть весь подграф ответа в графе →
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

function ParsedRow({ label, items, color }: { label: string; items: string[]; color: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-fg-muted w-32 shrink-0">{label}:</span>
      {items.length ? (
        <span className="flex flex-wrap gap-1">
          {items.map((it, i) => (
            <span
              key={it + i}
              className="chip text-[11px]"
              style={{ color, backgroundColor: `${color}16` }}
            >
              {it}
            </span>
          ))}
        </span>
      ) : (
        <span className="text-fg-faint">—</span>
      )}
    </div>
  )
}
