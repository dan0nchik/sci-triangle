import type { Domain, SearchFilters, Section, SourceType } from '../api/types'

const GEO: { value: NonNullable<SearchFilters['geography']>; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'RU', label: 'Россия' },
  { value: 'foreign', label: 'Зарубеж' },
  { value: 'global', label: 'Мир' },
]

const SOURCE_TYPES: { value: SourceType; label: string }[] = [
  { value: 'review', label: 'Обзор' },
  { value: 'article', label: 'Статья' },
  { value: 'report', label: 'Доклад' },
  { value: 'proceedings', label: 'Конференция' },
  { value: 'patent', label: 'Патент' },
  { value: 'book', label: 'Книга' },
  { value: 'market_report', label: 'Рыночный отчёт' },
  { value: 'presentation', label: 'Презентация' },
]

const SECTIONS: Section[] = ['Обзоры', 'Статьи', 'Доклады', 'Журналы', 'Материалы конференций']

const DOMAINS: { value: Domain; label: string }[] = [
  { value: 'hydro', label: 'Гидрометаллургия' },
  { value: 'pyro', label: 'Пирометаллургия' },
  { value: 'обогащение', label: 'Обогащение' },
  { value: 'экология', label: 'Экология' },
  { value: 'горное дело', label: 'Горное дело' },
  { value: 'водоочистка', label: 'Водоочистка' },
]

export function FiltersPanel({
  filters,
  onChange,
}: {
  filters: SearchFilters
  onChange: (f: SearchFilters) => void
}) {
  const set = (patch: Partial<SearchFilters>) => onChange({ ...filters, ...patch })
  const yFrom = filters.year_from ?? 2000
  const yTo = filters.year_to ?? 2026
  const cmin = filters.confidence_min ?? 0

  return (
    <div className="card p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white">Фильтры</h3>
        <button
          onClick={() =>
            onChange({ year_from: 2000, year_to: 2026, geography: 'all', confidence_min: 0 })
          }
          className="text-xs text-slate-500 hover:text-accent"
        >
          сбросить
        </button>
      </div>

      {/* Слайдер годов 2000–2026 (двойной) */}
      <div className="space-y-2">
        <label className="text-xs uppercase tracking-wide text-slate-500">
          Годы: <span className="text-slate-300">{yFrom} — {yTo}</span>
        </label>
        <div className="flex items-center gap-2">
          <input
            type="range" min={2000} max={2026} value={yFrom}
            onChange={(e) => set({ year_from: Math.min(Number(e.target.value), yTo) })}
            className="w-full accent-accent"
          />
          <input
            type="range" min={2000} max={2026} value={yTo}
            onChange={(e) => set({ year_to: Math.max(Number(e.target.value), yFrom) })}
            className="w-full accent-accent"
          />
        </div>
      </div>

      {/* География */}
      <div className="space-y-2">
        <label className="text-xs uppercase tracking-wide text-slate-500">География</label>
        <div className="flex flex-wrap gap-1.5">
          {GEO.map((g) => (
            <button
              key={g.value}
              onClick={() => set({ geography: g.value })}
              className={`chip border ${
                (filters.geography ?? 'all') === g.value
                  ? 'bg-accent-dim/40 border-accent-dim text-accent-soft'
                  : 'bg-ink-800 border-ink-600 text-slate-400 hover:text-slate-200'
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
      </div>

      {/* Тип источника */}
      <div className="space-y-2">
        <label className="text-xs uppercase tracking-wide text-slate-500">Тип источника</label>
        <select
          value={filters.source_type ?? ''}
          onChange={(e) => set({ source_type: (e.target.value || null) as SourceType | null })}
          className="w-full bg-ink-800 border border-ink-600 rounded-lg px-2.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-accent"
        >
          <option value="">любой</option>
          {SOURCE_TYPES.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>

      {/* Раздел */}
      <div className="space-y-2">
        <label className="text-xs uppercase tracking-wide text-slate-500">Раздел</label>
        <select
          value={filters.section ?? ''}
          onChange={(e) => set({ section: (e.target.value || null) as Section | null })}
          className="w-full bg-ink-800 border border-ink-600 rounded-lg px-2.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-accent"
        >
          <option value="">любой</option>
          {SECTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Домен */}
      <div className="space-y-2">
        <label className="text-xs uppercase tracking-wide text-slate-500">Домен</label>
        <select
          value={filters.domain ?? ''}
          onChange={(e) => set({ domain: (e.target.value || null) as Domain | null })}
          className="w-full bg-ink-800 border border-ink-600 rounded-lg px-2.5 py-2 text-sm text-slate-200 focus:outline-none focus:border-accent"
        >
          <option value="">любой</option>
          {DOMAINS.map((d) => (
            <option key={d.value} value={d.value}>{d.label}</option>
          ))}
        </select>
      </div>

      {/* Порог достоверности */}
      <div className="space-y-2">
        <label className="text-xs uppercase tracking-wide text-slate-500">
          Порог достоверности: <span className="text-slate-300">{Math.round(cmin * 100)}%</span>
        </label>
        <input
          type="range" min={0} max={0.95} step={0.05} value={cmin}
          onChange={(e) => set({ confidence_min: Number(e.target.value) })}
          className="w-full accent-accent"
        />
      </div>
    </div>
  )
}
