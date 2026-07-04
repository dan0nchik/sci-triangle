import type { Domain, SearchFilters, Section, SourceType } from '../api/types'

// Активные фильтры — видимыми чипами над результатом (Q&A: управляемая
// мультипараметрическая фильтрация = «плюс в карму»). Каждый чип снимается ×.

const GEO_LABEL: Record<string, string> = { RU: 'Россия', foreign: 'Зарубеж', global: 'Мир' }
const SRC_LABEL: Record<SourceType, string> = {
  review: 'Обзор', article: 'Статья', report: 'Доклад', presentation: 'Презентация',
  patent: 'Патент', market_report: 'Рыночный отчёт', book: 'Книга', proceedings: 'Конференция',
}
const DOMAIN_LABEL: Record<Domain, string> = {
  hydro: 'Гидрометаллургия', pyro: 'Пирометаллургия', обогащение: 'Обогащение',
  экология: 'Экология', 'горное дело': 'Горное дело', водоочистка: 'Водоочистка',
}

interface Chip {
  key: string
  label: string
  clear: () => void
}

export function ActiveFilterChips({
  filters,
  onChange,
  onReset,
}: {
  filters: SearchFilters
  onChange: (f: SearchFilters) => void
  onReset: () => void
}) {
  const set = (patch: Partial<SearchFilters>) => onChange({ ...filters, ...patch })
  const chips: Chip[] = []

  const yFrom = filters.year_from ?? 2000
  const yTo = filters.year_to ?? 2026
  if (yFrom !== 2000 || yTo !== 2026) {
    chips.push({ key: 'years', label: `Годы: ${yFrom}–${yTo}`, clear: () => set({ year_from: 2000, year_to: 2026 }) })
  }
  if (filters.geography && filters.geography !== 'all') {
    chips.push({ key: 'geo', label: `География: ${GEO_LABEL[filters.geography] ?? filters.geography}`, clear: () => set({ geography: 'all' }) })
  }
  if (filters.material) {
    chips.push({ key: 'material', label: `Материал: ${filters.material}`, clear: () => set({ material: null }) })
  }
  if (filters.process) {
    chips.push({ key: 'process', label: `Процесс: ${filters.process}`, clear: () => set({ process: null }) })
  }
  if (filters.source_type) {
    chips.push({ key: 'src', label: `Тип: ${SRC_LABEL[filters.source_type] ?? filters.source_type}`, clear: () => set({ source_type: null }) })
  }
  if (filters.section) {
    chips.push({ key: 'section', label: `Раздел: ${filters.section as Section}`, clear: () => set({ section: null }) })
  }
  if (filters.domain) {
    chips.push({ key: 'domain', label: `Домен: ${DOMAIN_LABEL[filters.domain] ?? filters.domain}`, clear: () => set({ domain: null }) })
  }
  const cmin = filters.confidence_min ?? 0
  if (cmin > 0) {
    chips.push({ key: 'cmin', label: `Достоверность ≥${Math.round(cmin * 100)}%`, clear: () => set({ confidence_min: 0 }) })
  }

  if (!chips.length) return null

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="active-filters">
      <span className="text-xs text-fg-muted">Активные фильтры:</span>
      {chips.map((c) => (
        <span key={c.key} className="chip bg-accent-dim/30 text-accent-soft border border-accent-dim/40">
          {c.label}
          <button
            onClick={c.clear}
            className="ml-0.5 text-accent-soft/70 hover:text-accent"
            title="Снять фильтр"
            aria-label={`Снять фильтр: ${c.label}`}
          >
            ×
          </button>
        </span>
      ))}
      <button onClick={onReset} className="text-xs text-fg-muted hover:text-accent underline decoration-dotted">
        сбросить всё
      </button>
    </div>
  )
}
