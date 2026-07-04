import type { Confidence } from '../api/types'
import { CONFIDENCE_META } from '../lib/ontology'

export function ConfidenceBadge({ level }: { level?: Confidence }) {
  const meta = CONFIDENCE_META[level ?? 'medium']
  return (
    <span
      className="chip"
      style={{ color: meta.color, backgroundColor: meta.bg }}
      title={`Достоверность: ${meta.label}`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
      {meta.label}
    </span>
  )
}
