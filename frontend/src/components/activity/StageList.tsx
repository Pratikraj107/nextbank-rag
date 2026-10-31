import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'

import { formatDuration } from '../../lib/format'
import { STAGE_LABELS, type JobStage } from '../../lib/uploads'

/** The job's processing stages with status, duration and any error. */
export function StageList({ stages }: { stages: JobStage[] }) {
  return (
    <ol className="space-y-2" aria-label="Processing stages">
      {stages.map((stage) => (
        <li key={stage.name} className="flex items-start gap-2.5 text-sm">
          <span className="mt-0.5" aria-hidden>
            {stage.status === 'failed' ? (
              <CircleAlert className="h-4 w-4 text-red-600" />
            ) : stage.status === 'completed' ? (
              <CircleCheck className="h-4 w-4 text-emerald-600" />
            ) : stage.status === 'running' ? (
              <LoaderCircle className="h-4 w-4 animate-spin text-accent" />
            ) : (
              <span className="block h-4 w-4 rounded-full border border-line-strong" />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3">
              <span className={stage.status === 'pending' ? 'text-muted' : 'text-ink'}>
                {STAGE_LABELS[stage.name] ?? stage.name}
                <span className="sr-only"> ({stage.status})</span>
              </span>
              <span className="shrink-0 text-xs text-muted tabular-nums">
                {stage.status === 'completed' || stage.status === 'failed' ? formatDuration(stage.durationMs) : stage.status === 'running' ? 'running…' : ''}
              </span>
            </div>
            {stage.error && <p className="mt-0.5 text-xs text-red-800">{stage.error}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
