import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { UploadJobStatus, UploadResult, UploadStage } from '../api/types'

// ============================================================================
// «Добавить документ» — канонический pipeline по docs/CONTRACT_UPLOAD.md:
//   POST /api/upload (multipart) → job_id → поллинг GET /api/upload/{job_id} ~1с
//   стадии: извлечение → чанки → эмбеддинги → индексация → извлечение знаний →
//   объединение с графом → done (+ сводка и graph_preview ≤30 узлов).
// Стадии embedding / extracting_knowledge могут быть skipped/deferred —
// показываем нейтрально («отложено»), это не ошибка.
// Фича включена по умолчанию; kill-switch: VITE_FEATURE_UPLOAD=0.
// ============================================================================

export const UPLOAD_ENABLED = import.meta.env.VITE_FEATURE_UPLOAD !== '0'

// Мини-превью графа переиспользует GraphView (cytoscape) — лениво, чтобы не
// тащить cytoscape в основной бандл SearchPage.
const LazyGraphView = lazy(() =>
  import('./GraphView').then((m) => ({ default: m.GraphView })),
)

type PipelineStage = Exclude<UploadStage, 'queued' | 'done' | 'failed'>

const STAGES: { key: PipelineStage; label: string; icon: string; hint: string }[] = [
  { key: 'extracting_text', label: 'Извлечение текста', icon: '📄', hint: 'PyMuPDF/docx/pptx/xlsx, OCR при необходимости' },
  { key: 'chunking', label: 'Разбиение на чанки', icon: '✂️', hint: '≤1200 токенов с перекрытием' },
  { key: 'embedding', label: 'Эмбеддинги', icon: '🧠', hint: 'векторное пространство (best-effort)' },
  { key: 'indexing', label: 'Индексация', icon: '🗂', hint: 'Elasticsearch — документ уже ищется' },
  { key: 'extracting_knowledge', label: 'Извлечение знаний', icon: '🔬', hint: 'LLM: сущности, факты, связи' },
  { key: 'merging_graph', label: 'Фрагмент графа', icon: '🕸', hint: 'MERGE в общий граф знаний (Neo4j)' },
]

const STAGE_ORDER: UploadStage[] = [
  'queued', 'extracting_text', 'chunking', 'embedding', 'indexing',
  'extracting_knowledge', 'merging_graph', 'done',
]

type StepState = 'pending' | 'active' | 'done' | 'skipped' | 'deferred'

function stepState(stage: PipelineStage, job: UploadJobStatus | null): StepState {
  if (!job) return 'pending'
  // финальная диагностика по стадиям (result.stages) — точнее текущего указателя
  const info = job.result?.stages?.[stage]
  const cur = STAGE_ORDER.indexOf(job.stage)
  const idx = STAGE_ORDER.indexOf(stage)
  if (info) {
    if (info.status === 'skipped') return 'skipped'
    if (info.status === 'deferred') return 'deferred'
    if (cur > idx || job.stage === 'done') return 'done'
  }
  if (job.stage === stage) return 'active'
  if (cur > idx || job.stage === 'done') return 'done'
  return 'pending'
}

export function UploadModal({ onClose }: { onClose: () => void }) {
  const nav = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [job, setJob] = useState<UploadJobStatus | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const pollRef = useRef<number | null>(null)

  // очистка поллинга при размонтировании
  useEffect(() => () => { if (pollRef.current) window.clearTimeout(pollRef.current) }, [])

  const start = useCallback(async () => {
    if (!file || running) return
    setRunning(true)
    setError(null)
    setJob(null)
    try {
      const started = await api.upload(file)
      // поллинг ~1 с до done/failed (при cached=true done придёт первым же ответом)
      const poll = async () => {
        try {
          const st = await api.uploadStatus(started.job_id)
          setJob(st)
          if (st.stage === 'done' || st.stage === 'failed') {
            setRunning(false)
            if (st.stage === 'failed') setError(st.detail || st.error || 'Ошибка обработки документа')
            return
          }
          pollRef.current = window.setTimeout(poll, 1000)
        } catch (e) {
          setRunning(false)
          setError(e instanceof Error ? e.message : 'Ошибка запроса статуса')
        }
      }
      await poll()
    } catch (e) {
      setRunning(false)
      setError(e instanceof Error ? e.message : 'Ошибка загрузки файла')
    }
  }, [file, running])

  const result: UploadResult | null | undefined = job?.stage === 'done' ? job.result : null
  const finished = job?.stage === 'done'
  const pct = Math.round((job?.progress ?? 0) * 100)

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      onClick={running ? undefined : onClose}
      data-testid="upload-modal"
    >
      <div className="absolute inset-0 bg-black/60" />
      <div
        className="relative card p-6 w-full max-w-xl space-y-5 max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-fg">Добавить документ</h2>
            <p className="text-xs text-fg-muted mt-0.5">
              Загрузка → извлечение → чанки → индексация → фрагмент графа знаний.
            </p>
          </div>
          {!running && (
            <button onClick={onClose} className="text-fg-muted hover:text-fg text-2xl leading-none">×</button>
          )}
        </div>

        {/* Выбор файла */}
        {!finished && (
          <button
            onClick={() => inputRef.current?.click()}
            disabled={running}
            className="w-full rounded-xl border-2 border-dashed border-ink-600 hover:border-accent bg-ink-800 px-4 py-6 text-center transition-colors disabled:opacity-50"
          >
            <div className="text-3xl mb-1">⭳</div>
            <div className="text-sm text-fg-body">
              {file ? file.name : 'Выберите файл (PDF, DOCX, PPTX, XLSX…)'}
            </div>
            {file && <div className="text-[11px] text-fg-muted mt-0.5">{(file.size / 1024).toFixed(0)} КБ</div>}
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.doc,.docx,.docm,.pptx,.xlsx,.xls"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </button>
        )}

        {/* Прогресс по стадиям */}
        {job && (
          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-xs text-fg-muted">
              <span className="truncate">{job.detail ?? '…'}</span>
              <span className="font-semibold text-fg-body shrink-0 ml-3">{pct}%</span>
            </div>
            <div className="h-2 rounded-full bg-ink-700 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-accent-dim to-accent transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="grid gap-2">
              {STAGES.map((st) => {
                const s = stepState(st.key, job)
                const info = job.result?.stages?.[st.key]
                return (
                  <div key={st.key} className="flex items-center gap-3 text-sm">
                    <span className="text-lg w-6 text-center">
                      {s === 'done' ? '✓' : s === 'active' ? st.icon : s === 'skipped' || s === 'deferred' ? '◌' : '○'}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className={s === 'pending' ? 'text-fg-faint' : 'text-fg-body'}>
                        {st.label}
                        {s === 'active' && <span className="ml-2 text-accent animate-pulse">…</span>}
                      </div>
                      <div className="text-[11px] text-fg-muted truncate">{info?.detail ?? st.hint}</div>
                    </div>
                    {s === 'done' && (
                      <span className="chip bg-emerald-500/15 text-emerald-700 text-[10px]">готово</span>
                    )}
                    {(s === 'skipped' || s === 'deferred') && (
                      <span
                        className="chip bg-ink-700 text-fg-muted text-[10px]"
                        title={info?.detail ?? 'Стадия отложена — документ всё равно доступен в поиске (full-text)'}
                      >
                        отложено{st.key === 'extracting_knowledge' ? ' (LLM недоступен)' : ''}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Ошибка */}
        {error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/[0.06] p-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        {/* Итог: сводка + мини-превью фрагмента графа */}
        {finished && result && (
          <div className="space-y-4">
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/[0.06] p-3 text-sm text-emerald-800">
              Документ обработан{result.extraction_deferred ? '' : ' и добавлен в граф знаний'} —
              уже доступен в поиске со ссылками на фрагменты.
              {result.extraction_deferred && (
                <span className="block mt-1 text-[11px] text-fg-muted">
                  Извлечение знаний отложено (LLM недоступен) — документ ищется full-text и добавлен
                  в граф как Publication-узел.
                </span>
              )}
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              <SummaryStat value={result.n_chunks} label="чанков" />
              <SummaryStat value={result.n_entities} label="сущностей" />
              <SummaryStat value={result.n_edges} label="связей в графе" />
            </div>

            {result.graph_preview.nodes.length > 0 && (
              <div>
                <div className="text-[11px] uppercase tracking-wide text-fg-muted mb-1.5">
                  Фрагмент графа документа ({result.graph_preview.nodes.length} узлов)
                </div>
                <div className="h-56 rounded-xl border border-ink-700 bg-ink-800 overflow-hidden">
                  <Suspense
                    fallback={
                      <div className="h-full flex items-center justify-center text-xs text-fg-muted">
                        Загрузка превью графа…
                      </div>
                    }
                  >
                    <LazyGraphView graph={result.graph_preview} layoutName="cose" />
                  </Suspense>
                </div>
              </div>
            )}

            <div className="flex flex-wrap justify-end gap-2">
              <button
                onClick={() => {
                  onClose()
                  nav('/graph', { state: { focusNode: `pub:${result.doc_id}` } })
                }}
                className="btn-ghost"
              >
                🕸 Открыть в графе
              </button>
              <button onClick={onClose} className="btn-accent">Готово</button>
            </div>
          </div>
        )}

        {/* Действия до/во время */}
        {!finished && (
          <div className="flex justify-end gap-2">
            <button onClick={start} disabled={!file || running} className="btn-accent">
              {running ? 'Обработка…' : 'Загрузить и обработать'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryStat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-800 py-2.5">
      <div className="text-xl font-semibold text-fg">{value}</div>
      <div className="text-[11px] text-fg-muted">{label}</div>
    </div>
  )
}
