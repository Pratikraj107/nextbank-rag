import type { LucideIcon } from 'lucide-react'
import { CircleAlert, CircleCheck, CircleDashed, FileText, RotateCw, Search } from 'lucide-react'

import type { ChatResponse } from '../lib/api'
import { humanize } from '../lib/sources'

type Tone = 'positive' | 'warning' | 'neutral'

const TONE_CLASSES: Record<Tone, string> = {
  positive: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  neutral: 'border-line bg-white text-ink-soft',
}

function Chip({ icon: Icon, tone, children }: { icon: LucideIcon; tone: Tone; children: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {children}
    </span>
  )
}

function CheckChip({ label, value }: { label: string; value: boolean | null }) {
  if (value === true) {
    return <Chip icon={CircleCheck} tone="positive">{`${label}: passed`}</Chip>
  }

  if (value === false) {
    return <Chip icon={CircleAlert} tone="warning">{`${label}: not verified`}</Chip>
  }

  return <Chip icon={CircleDashed} tone="neutral">{`${label}: not reported`}</Chip>
}

function searchModeLabel(mode: string | null): string {
  switch (mode) {
    case 'semantic':
      return 'Semantic search'
    case 'exact':
      return 'Exact text search'
    case 'conflict':
      return 'Identifier conflict'
    case null:
      return 'Search mode not reported'
    default:
      return humanize(mode)
  }
}

interface ValidationStatusProps {
  response: ChatResponse
  onShowSources?: () => void
}

/** Compact, secondary metadata row describing how an answer was produced. */
export function ValidationStatus({ response, onShowSources }: ValidationStatusProps) {
  const mode = response.search_mode
  const attempts = response.attempts
  const sourceCount = response.sources.length

  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Response details">
      <Chip icon={Search} tone="neutral">
        {searchModeLabel(mode)}
      </Chip>

      {attempts !== null && attempts > 0 && (
        <Chip icon={RotateCw} tone="neutral">
          {`${attempts} ${attempts === 1 ? 'attempt' : 'attempts'}`}
        </Chip>
      )}

      {mode === 'exact' ? (
        // The exact-search branch returns literal matches and skips the validators.
        <Chip icon={CircleDashed} tone="neutral">
          Validation not run for exact search
        </Chip>
      ) : (
        <>
          <CheckChip label="Basic checks" value={response.basic_validation_passed} />
          <CheckChip label="Evidence validation" value={response.evidence_validation_passed} />
        </>
      )}

      {onShowSources && sourceCount > 0 && (
        <button
          type="button"
          onClick={onShowSources}
          className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium text-accent hover:bg-accent-soft"
        >
          <FileText className="h-3.5 w-3.5" aria-hidden />
          {`${sourceCount} ${sourceCount === 1 ? 'source' : 'sources'}`}
        </button>
      )}
    </div>
  )
}
