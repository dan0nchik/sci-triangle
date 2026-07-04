import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { AuditEntry, StatsResponse } from '../api/types'

const CORPUS_TOTAL = 1453 // весь корпус (§3 плана)

// Дашборд руководителя (D11): покрытие по доменам/разделам/годам, зоны риска,
// счётчик корпуса «обработано X из 1453», сводки доменов, активность (аудит).
export function DashboardPage() {
  const nav = useNavigate()
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e instanceof Error ? e.message : 'Ошибка /api/stats'))
    api.audit().then(setAudit).catch(() => setAudit([]))
  }, [])

  const total = stats?.n_corpus_total ?? CORPUS_TOTAL
  const processed = stats?.n_documents ?? 0
  const pct = total ? Math.min(100, Math.round((processed / total) * 100)) : 0

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-white">Дашборд руководителя</h1>
        <p className="text-slate-400 mt-1">
          Покрытие корпуса по доменам, разделам и годам, зоны риска, сводки доменов и активность.
        </p>
      </header>

      {error && <div className="card p-4 border-rose-500/40 bg-rose-500/[0.06] text-sm text-rose-300">{error}</div>}

      {!stats ? (
        <div className="grid gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-24" />
          ))}
        </div>
      ) : (
        <>
          {/* Счётчик корпуса */}
          <div className="card p-5">
            <div className="flex items-end justify-between mb-2">
              <div>
                <div className="text-sm text-slate-400">Обработано корпуса</div>
                <div className="text-2xl font-semibold text-white">
                  {processed.toLocaleString('ru')} <span className="text-slate-500 text-lg">из {total.toLocaleString('ru')}</span>
                </div>
              </div>
              <div className="text-3xl font-semibold text-accent">{pct}%</div>
            </div>
            <div className="h-2.5 rounded-full bg-ink-700 overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-accent-dim to-accent" style={{ width: `${pct}%` }} />
            </div>
          </div>

          {/* KPI */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Узлов графа" value={stats.n_nodes.toLocaleString('ru')} icon="⬡" />
            <Kpi label="Рёбер графа" value={stats.n_edges.toLocaleString('ru')} icon="⇄" />
            <Kpi label="Утверждений (Assertion)" value={stats.n_assertions.toLocaleString('ru')} icon="✎" />
            <button onClick={() => nav('/graph')} className="text-left">
              <Kpi label="Противоречий → в граф" value={String(stats.n_contradictions)} icon="⚠" accent="rose" />
            </button>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-4">Покрытие по доменам</h3>
              {stats.by_domain.length ? (
                <BarList items={stats.by_domain.map((d) => ({ label: d.label, value: d.n_docs, sub: d.n_assertions ? `${d.n_assertions} утв.` : undefined }))} />
              ) : (
                <Empty />
              )}
            </div>
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-4">Покрытие по разделам</h3>
              {stats.by_section.length ? (
                <BarList items={stats.by_section.map((d) => ({ label: d.label, value: d.n_docs, sub: d.n_assertions ? `${d.n_assertions} утв.` : undefined }))} color="#81c784" />
              ) : (
                <Empty />
              )}
            </div>
          </div>

          {/* Распределение типов узлов */}
          {stats.node_types && Object.keys(stats.node_types).length > 0 && (
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-4">Распределение типов узлов</h3>
              <BarList
                items={Object.entries(stats.node_types)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => ({ label: k, value: v }))}
                color="#ba68c8"
              />
            </div>
          )}

          {/* Годы */}
          {stats.by_year.length > 0 && (
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-4">Динамика документов по годам</h3>
              <YearChart data={stats.by_year} />
            </div>
          )}

          {/* Сводки доменов (GraphRAG) */}
          {stats.domain_summaries && Object.keys(stats.domain_summaries).length > 0 && (
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-3">Сводки по доменам</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                {Object.values(stats.domain_summaries).map((d) => (
                  <div key={d.domain} className="rounded-lg border border-ink-700 bg-ink-850 p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-slate-100 capitalize">{d.domain}</span>
                      <span className="chip bg-ink-700 text-slate-400">{d.n_processes} проц.</span>
                    </div>
                    <p className="text-xs text-slate-400 leading-relaxed">{d.summary}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Зоны риска */}
          {stats.top_gaps.length > 0 && (
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-3">Зоны риска — приоритетные пробелы</h3>
              <div className="grid gap-3 sm:grid-cols-3">
                {stats.top_gaps.map((g) => (
                  <button
                    key={g.id}
                    onClick={() => nav('/graph')}
                    className="text-left rounded-lg border border-ink-700 bg-ink-850 p-3 hover:border-accent-dim"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-slate-100 text-sm">{g.title}</span>
                      <span
                        className="chip"
                        style={{
                          color: g.severity === 'high' ? '#f87171' : '#fbbf24',
                          backgroundColor: g.severity === 'high' ? '#f8717122' : '#fbbf2422',
                        }}
                      >
                        {g.severity === 'high' ? 'высокая' : 'средняя'}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400">{g.description}</p>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Активность (аудит) */}
          {audit.length > 0 && (
            <div className="card p-5">
              <h3 className="font-semibold text-white mb-3">Активность (аудит)</h3>
              <div className="space-y-1.5">
                {audit.slice(0, 8).map((a, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs border-b border-ink-800 last:border-0 py-1.5">
                    <span className="chip bg-ink-700 text-slate-400 w-24 justify-center">{a.role}</span>
                    <span className="chip bg-accent-dim/25 text-accent-soft w-20 justify-center">{a.action}</span>
                    <span className="text-slate-300 truncate flex-1">{a.detail}</span>
                    <span className="text-slate-600 whitespace-nowrap">{new Date(a.ts).toLocaleTimeString('ru')}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Empty() {
  return <p className="text-sm text-slate-500">Нет данных.</p>
}

function Kpi({ label, value, icon, accent }: { label: string; value: string; icon: string; accent?: 'rose' }) {
  return (
    <div className="card p-5 h-full">
      <div className="flex items-center justify-between">
        <span className="text-2xl">{icon}</span>
        <span className={`text-2xl font-semibold ${accent === 'rose' ? 'text-rose-300' : 'text-white'}`}>{value}</span>
      </div>
      <div className="text-sm text-slate-400 mt-2">{label}</div>
    </div>
  )
}

function BarList({
  items,
  color = '#3ea6ff',
}: {
  items: { label: string; value: number; sub?: string }[]
  color?: string
}) {
  const max = Math.max(...items.map((i) => i.value), 1)
  return (
    <div className="space-y-2.5">
      {items.map((it) => (
        <div key={it.label}>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-slate-300 capitalize">{it.label}</span>
            <span className="text-slate-500">
              {it.value}
              {it.sub ? ` · ${it.sub}` : ''}
            </span>
          </div>
          <div className="h-2 rounded-full bg-ink-700 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${(it.value / max) * 100}%`, backgroundColor: color }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function YearChart({ data }: { data: { year: number; n_docs: number }[] }) {
  const max = Math.max(...data.map((d) => d.n_docs), 1)
  return (
    <div className="flex items-end gap-3 h-40">
      {data.map((d) => (
        <div key={d.year} className="flex-1 flex flex-col items-center gap-1.5">
          <div className="text-[11px] text-slate-500">{d.n_docs}</div>
          <div
            className="w-full rounded-t bg-gradient-to-t from-accent-dim to-accent"
            style={{ height: `${(d.n_docs / max) * 100}%` }}
          />
          <div className="text-[11px] text-slate-500">{d.year}</div>
        </div>
      ))}
    </div>
  )
}
