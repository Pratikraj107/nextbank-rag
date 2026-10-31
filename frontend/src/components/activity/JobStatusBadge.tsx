import { CircleAlert, CircleCheck, Clock, LoaderCircle } from 'lucide-react'

import type { JobStatus } from '../../lib/uploads'

const STYLES: Record<JobStatus, string> = {
  uploaded: 'border-line bg-canvas text-ink-soft',
  processing: 'border-accent/30 bg-accent-soft text-accent',
  ready: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  failed: 'border-red-200 bg-red-50 text-red-800',
}

const LABELS: Record<JobStatus, string> = {
  uploaded: 'Queued',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
}

/** Status pill with an icon, so status is not conveyed by colour alone. */
export function JobStatusBadge({ status }: { status: JobStatus }) {
  const icon = 'h-3.5 w-3.5'
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${STYLES[status]}`}>
      {status === 'uploaded' && <Clock className={icon} aria-hidden />}
      {status === 'processing' && <LoaderCircle className={`${icon} animate-spin`} aria-hidden />}
      {status === 'ready' && <CircleCheck className={icon} aria-hidden />}
      {status === 'failed' && <CircleAlert className={icon} aria-hidden />}
      {LABELS[status]}
    </span>
  )
}
