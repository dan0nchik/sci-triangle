import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type {
  Contradiction,
  ExpertSummary,
  KnowledgeGap,
} from '../api/types'
import { ConfidenceBadge } from './ConfidenceBadge'

const SEVERITY: Record<string, { label: string; color: string }> = {
  high: { label: 'высокая', color: '#f87171' },
  medium: { label: 'средняя', color: '#fbbf24' },
  low: { label: 'низкая', color: '#94a3b8' },
}

// Блок «Противоречия» — красная подсветка.
export function ContradictionsSection({ items }: { items: Contradiction[] }) {
  if (!items.length) return null
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
        <span className="text-rose-400">⚠</span> Противоречия
        <span className="chip bg-rose-500/15 text-rose-300">{items.length}</span>
      </h3>
      {items.map((c) => (
        <div
          key={c.id}
          className="rounded-xl border border-rose-500/40 bg-rose-500/[0.06] p-4 space-y-3"
        >
          <div className="text-sm font-medium text-rose-200">{c.topic}</div>
          <div className="grid gap-3 md:grid-cols-2">
            {[c.a, c.b].map((side, i) => (
              <div key={i} className="rounded-lg bg-ink-800 border border-ink-700 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="chip bg-ink-700 text-slate-400">Версия {i === 0 ? 'A' : 'B'}</span>
                  <ConfidenceBadge level={side.confidence} />
                </div>
                <p className="text-sm text-slate-300 leading-relaxed">{side.statement}</p>
                {side.citation && (
                  <blockquote className="border-l-2 border-rose-400/50 pl-2 text-xs text-slate-500 italic">
                    «{side.citation.quote}» — {side.citation.title}, {side.citation.year}
                  </blockquote>
                )}
              </div>
            ))}
          </div>
          {c.note && <p className="text-xs text-slate-400">{c.note}</p>}
        </div>
      ))}
    </section>
  )
}

// Блок «Пробелы знаний».
export function GapsSection({ items }: { items: KnowledgeGap[] }) {
  if (!items.length) return null
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
        <span className="text-amber-400">◇</span> Пробелы знаний
        <span className="chip bg-amber-500/15 text-amber-300">{items.length}</span>
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((g) => {
          const sev = SEVERITY[g.severity]
          return (
            <div key={g.id} className="card p-4 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-medium text-slate-100">{g.title}</span>
                <span className="chip" style={{ color: sev.color, backgroundColor: `${sev.color}22` }}>
                  {sev.label}
                </span>
              </div>
              <p className="text-sm text-slate-400 leading-relaxed">{g.description}</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// Блок «Эксперты по теме» — карточки с лабораторией.
export function ExpertsSection({ items }: { items: ExpertSummary[] }) {
  const [active, setActive] = useState<ExpertSummary | null>(null)
  if (!items.length) return null
  const FAC: Record<string, string> = { lab: 'Лаборатория', plant: 'Завод', institute: 'Институт' }
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
        <span className="text-yellow-300">★</span> Эксперты по теме
        <span className="chip bg-yellow-500/15 text-yellow-200">{items.length}</span>
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((e) => (
          <button
            key={e.id}
            onClick={() => setActive(e)}
            className="card p-4 space-y-2 text-left hover:border-accent-dim transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-node-expert/20 border border-node-expert/40 flex items-center justify-center text-node-expert font-semibold">
                {e.name.replace(/[^А-ЯA-Z]/g, '').slice(0, 2)}
              </div>
              <div className="min-w-0">
                <div className="font-medium text-white truncate">{e.name}</div>
                <div className="text-xs text-slate-400 truncate">{e.affiliation}</div>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 text-[11px]">
              {e.facility_type && (
                <span className="chip bg-node-facility/15 text-node-facility">
                  {FAC[e.facility_type] ?? e.facility_type}
                </span>
              )}
              <span className="chip bg-ink-700 text-slate-400">{e.n_works} работ(ы)</span>
            </div>
            {e.topics && e.topics.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-0.5">
                {e.topics.slice(0, 3).map((t) => (
                  <span key={t} className="chip bg-accent-dim/25 text-accent-soft">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </button>
        ))}
      </div>
      {active && <ExpertModal expert={active} onClose={() => setActive(null)} />}
    </section>
  )
}

// Карточка эксперта (D4): работы, темы, лаборатория, «найти в графе».
function ExpertModal({ expert, onClose }: { expert: ExpertSummary; onClose: () => void }) {
  const nav = useNavigate()
  const FAC: Record<string, string> = { lab: 'Лаборатория', plant: 'Завод', institute: 'Институт' }
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" />
      <div className="relative card p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="h-12 w-12 rounded-full bg-node-expert/20 border border-node-expert/40 flex items-center justify-center text-node-expert font-semibold text-lg">
              {expert.name.replace(/[^А-ЯA-Z]/g, '').slice(0, 2)}
            </div>
            <div>
              <div className="text-lg font-semibold text-white">{expert.name}</div>
              <div className="text-sm text-slate-400">{expert.affiliation}</div>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="flex flex-wrap gap-1.5 text-xs">
          {expert.facility_type && (
            <span className="chip bg-node-facility/15 text-node-facility">{FAC[expert.facility_type] ?? expert.facility_type}</span>
          )}
          <span className="chip bg-ink-700 text-slate-300">{expert.n_works} работ(ы)</span>
        </div>

        {expert.topics && expert.topics.length > 0 && (
          <div>
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Темы</div>
            <div className="flex flex-wrap gap-1.5">
              {expert.topics.map((t) => (
                <span key={t} className="chip bg-accent-dim/25 text-accent-soft">{t}</span>
              ))}
            </div>
          </div>
        )}

        <button
          onClick={() => {
            onClose()
            nav('/graph', { state: { focusNode: expert.id } })
          }}
          className="btn-accent w-full justify-center"
        >
          🕸 Найти в графе
        </button>
      </div>
    </div>
  )
}
