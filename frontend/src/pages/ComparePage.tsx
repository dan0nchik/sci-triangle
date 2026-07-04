import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { CompareResponse, GraphNode } from '../api/types'
import { downloadCsv } from '../lib/download'
import { useApp } from '../store'

type Mode = 'tech' | 'ru_world'

const PARAM_PRESETS: Record<Mode, string[]> = {
  tech: ['домен', 'эффективность', 'условия', 'CAPEX', 'OPEX', 'холодный климат', 'экология'],
  ru_world: ['домен', 'условия', 'CAPEX', 'OPEX', 'холодный климат', 'экология', 'регулирование'],
}

// D5: сравнительный анализ технологий по параметрам + режим «РФ vs мир».
export function ComparePage() {
  const { lastResult } = useApp()
  const [mode, setMode] = useState<Mode>('tech')
  const [suggestions, setSuggestions] = useState<GraphNode[]>([])
  const [techA, setTechA] = useState('')
  const [techB, setTechB] = useState('')
  const [params, setParams] = useState<string[]>(PARAM_PRESETS.tech)
  const [data, setData] = useState<CompareResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Автокомплит: концепты (Process/Material) из результата поиска + обзорный граф.
  useEffect(() => {
    const fromResult = (lastResult?.subgraph.nodes ?? []).filter(
      (n) => n.type === 'Process' || n.type === 'Material',
    )
    api
      .overview(300)
      .then((g) => {
        const map = new Map<string, GraphNode>()
        for (const n of [...fromResult, ...g.nodes]) {
          if ((n.type === 'Process' || n.type === 'Material') && !map.has(n.id)) map.set(n.id, n)
        }
        const list = [...map.values()]
        setSuggestions(list)
        if (!techA && list[0]) setTechA(list[0].id)
        if (!techB && list[1]) setTechB(list[1].id)
      })
      .catch(() => setSuggestions(fromResult))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const switchMode = (m: Mode) => {
    setMode(m)
    setParams(PARAM_PRESETS[m])
    setData(null)
  }

  async function run() {
    if (!techA || !techB) {
      setError('Выберите две технологии для сравнения')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await api.compare(techA, techB, params)
      setData(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка сравнения')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  const exportXlsx = () => {
    if (!data) return
    const header = ['Параметр', ...data.techs.map((t) => t.name)]
    const rows = data.rows.map((r) => [r.param, ...r.values.map((v) => v ?? '—')])
    downloadCsv(`compare_${techA.split(':').pop()}_vs_${techB.split(':').pop()}.csv`, [header, ...rows])
  }

  const toggleParam = (p: string) =>
    setParams((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]))

  const allParams = useMemo(
    () => Array.from(new Set([...PARAM_PRESETS.tech, ...PARAM_PRESETS.ru_world])),
    [],
  )

  return (
    <div className="mx-auto max-w-6xl px-6 py-8 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-white">Сравнительный анализ</h1>
        <p className="text-slate-400 mt-1">
          Сравнение технологий по ключевым параметрам (эффективность, условия, CAPEX, климат, экология).
        </p>
      </header>

      {/* Режим */}
      <div className="flex rounded-lg border border-ink-600 overflow-hidden w-max">
        <button
          onClick={() => switchMode('tech')}
          className={`px-4 py-1.5 text-sm ${mode === 'tech' ? 'bg-accent-dim/50 text-white' : 'text-slate-400 hover:bg-ink-700'}`}
        >
          Технология vs технология
        </button>
        <button
          onClick={() => switchMode('ru_world')}
          className={`px-4 py-1.5 text-sm ${mode === 'ru_world' ? 'bg-accent-dim/50 text-white' : 'text-slate-400 hover:bg-ink-700'}`}
        >
          РФ vs мир
        </button>
      </div>

      {/* Выбор технологий */}
      <div className="grid gap-4 sm:grid-cols-2">
        <TechSelect label="Технология A" value={techA} onChange={setTechA} options={suggestions} />
        <TechSelect label="Технология B" value={techB} onChange={setTechB} options={suggestions} />
      </div>

      {/* Параметры */}
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Параметры сравнения</div>
        <div className="flex flex-wrap gap-1.5">
          {allParams.map((p) => (
            <button
              key={p}
              onClick={() => toggleParam(p)}
              className={`chip border ${
                params.includes(p)
                  ? 'bg-accent-dim/40 border-accent-dim text-accent-soft'
                  : 'bg-ink-800 border-ink-600 text-slate-400 hover:text-slate-200'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-3">
        <button onClick={run} disabled={loading} className="btn-accent px-6">
          {loading ? 'Сравнение…' : 'Сравнить'}
        </button>
        {data && (
          <button onClick={exportXlsx} className="btn-ghost">⭳ Экспорт таблицы (xlsx/CSV)</button>
        )}
      </div>

      {error && <div className="card p-4 border-rose-500/40 bg-rose-500/[0.06] text-sm text-rose-300">{error}</div>}

      {loading && <div className="skeleton h-48 w-full" />}

      {data && !loading && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-700">
                <th className="text-left px-4 py-3 text-slate-400 font-medium w-48">Параметр</th>
                {data.techs.map((t) => (
                  <th key={t.id} className="text-left px-4 py-3 text-white font-semibold">
                    {t.name}
                    <div className="text-[11px] font-normal font-mono text-slate-500">{t.id}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.param} className="border-b border-ink-800 last:border-0">
                  <td className="px-4 py-3 text-slate-400 align-top capitalize">{r.param}</td>
                  {r.values.map((v, i) => (
                    <td key={i} className="px-4 py-3 text-slate-200 align-top">
                      {v ?? <span className="text-slate-600">— нет данных</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!data && !loading && !error && (
        <div className="card p-10 text-center text-slate-500">
          Выберите две технологии и параметры, затем нажмите «Сравнить».
          {suggestions.length === 0 && ' Загрузка списка технологий…'}
        </div>
      )}
    </div>
  )
}

function TechSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: GraphNode[]
}) {
  const [q, setQ] = useState('')
  const filtered = q
    ? options.filter((o) => (o.name + ' ' + o.id).toLowerCase().includes(q.toLowerCase()))
    : options
  return (
    <div className="card p-4 space-y-2">
      <label className="text-xs uppercase tracking-wide text-slate-500">{label}</label>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="фильтр по названию…"
        className="w-full bg-ink-800 border border-ink-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent"
      />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        size={5}
        className="w-full bg-ink-800 border border-ink-600 rounded-lg px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-accent"
      >
        {filtered.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name} ({o.type === 'Process' ? 'процесс' : 'материал'})
          </option>
        ))}
      </select>
    </div>
  )
}
