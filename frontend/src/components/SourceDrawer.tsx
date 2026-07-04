import type { Citation } from '../api/types'
import { ConfidenceBadge } from './ConfidenceBadge'
import { useApp } from '../store'

const GEO_LABEL: Record<string, string> = { RU: 'Россия', foreign: 'Зарубеж', global: 'Мир' }
const TYPE_LABEL: Record<string, string> = {
  review: 'Обзор', article: 'Статья', report: 'Доклад', presentation: 'Презентация',
  patent: 'Патент', market_report: 'Рыночный отчёт', book: 'Книга', proceedings: 'Конференция',
}

// Выезжающая справа карточка источника: метаданные + дословный фрагмент.
export function SourceDrawer({
  citation,
  index,
  onClose,
}: {
  citation: Citation | null
  index: number | null
  onClose: () => void
}) {
  const { openDoc } = useApp()
  const open = !!citation
  return (
    <>
      <div
        className={`fixed inset-0 bg-black/50 transition-opacity z-40 ${
          open ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed top-0 right-0 h-full w-full max-w-md bg-ink-850 border-l border-ink-700 z-50 shadow-2xl transition-transform duration-300 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {citation && (
          <div className="flex flex-col h-full">
            <div className="flex items-start justify-between px-5 py-4 border-b border-ink-700">
              <div className="flex items-center gap-2">
                <span className="chip bg-accent-dim/50 text-accent-soft">Источник [{index}]</span>
                <ConfidenceBadge level={citation.confidence} />
              </div>
              <button onClick={onClose} className="text-slate-500 hover:text-white text-xl leading-none">
                ×
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <div>
                <h3 className="text-white font-semibold leading-snug">{citation.title}</h3>
                <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                  <span className="chip bg-ink-700 text-slate-300">{citation.year} г.</span>
                  {citation.source_type && (
                    <span className="chip bg-ink-700 text-slate-300">
                      {TYPE_LABEL[citation.source_type] ?? citation.source_type}
                    </span>
                  )}
                  {citation.section && (
                    <span className="chip bg-ink-700 text-slate-300">{citation.section}</span>
                  )}
                  {citation.geography && (
                    <span className="chip bg-ink-700 text-slate-300">
                      {GEO_LABEL[citation.geography] ?? citation.geography}
                    </span>
                  )}
                  {citation.journal && (
                    <span className="chip bg-ink-700 text-slate-300">{citation.journal}</span>
                  )}
                </div>
              </div>

              <div className="text-xs text-slate-500 font-mono space-y-0.5">
                <div>doc_id: {citation.doc_id}</div>
                <div>chunk_id: {citation.chunk_id}</div>
                {citation.page_from != null && (
                  <div>
                    стр. {citation.page_from}
                    {citation.page_to && citation.page_to !== citation.page_from
                      ? `–${citation.page_to}`
                      : ''}
                  </div>
                )}
              </div>

              <div>
                <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">
                  Дословный фрагмент-основание
                </div>
                <blockquote className="border-l-2 border-accent pl-3 py-1 text-slate-200 leading-relaxed bg-ink-800 rounded-r-lg">
                  «{citation.quote}»
                </blockquote>
              </div>
            </div>

            <div className="px-5 py-3 border-t border-ink-700 space-y-2">
              <button
                onClick={() => {
                  openDoc(citation.doc_id, citation.chunk_id)
                  onClose()
                }}
                className="btn-accent w-full justify-center"
              >
                📄 Открыть полную карточку документа
              </button>
              <p className="text-[11px] text-slate-500">
                Провенанс верифицирован: число присутствует в источнике дословно (rule-first).
              </p>
            </div>
          </div>
        )}
      </aside>
    </>
  )
}
