import { CircleAlert, FileSearch, LoaderCircle, RotateCw, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { useJob } from '../../hooks/useJobs'
import { formatDateTime, formatDuration } from '../../lib/format'
import { humanize } from '../../lib/sources'
import { STAGE_LABELS } from '../../lib/uploads'
import { NotSet } from '../documents/DocumentTable'
import { FileTypeIcon } from '../FileTypeIcon'
import { JobStatusBadge } from './JobStatusBadge'
import { StageList } from './StageList'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5 truncate text-sm text-ink">{children}</dd>
    </div>
  )
}

interface JobDetailPanelProps {
  jobId: string
  onOpenDocument: (documentId: string) => void
  onChanged: () => void
  onClose?: () => void
}

export function JobDetailPanel({ jobId, onOpenDocument, onChanged, onClose }: JobDetailPanelProps) {
  const { job, loading, error, retry, retrying, retryError } = useJob(jobId, onChanged)

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas text-ink-soft">
            <FileTypeIcon filename={job?.filename ?? ''} className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink" title={job?.filename}>
              {job?.filename ?? (loading ? 'Loading…' : 'Job')}
            </h2>
            <p className="truncate font-mono text-[11px] text-muted">Job {jobId}</p>
          </div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="-mr-1.5 rounded-lg p-1.5 text-muted hover:bg-canvas hover:text-ink"
            aria-label="Close job details"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      {!job && loading && (
        <div role="status" className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
          Loading job…
        </div>
      )}
      {!job && error && (
        <p role="alert" className="m-5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{error}</p>
      )}

      {job && (
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <JobStatusBadge status={job.status} />
            {job.attempts > 1 && <span className="text-xs text-muted">Attempt {job.attempts}</span>}
          </div>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Field label="Customer"><span className="font-mono text-[13px]">{job.customerId}</span></Field>
            <Field label="Loan">{job.loanId ? <span className="font-mono text-[13px]">{job.loanId}</span> : <NotSet />}</Field>
            <Field label="Document type">{job.documentType ? humanize(job.documentType) : <NotSet />}</Field>
            <Field label="Chunks">{job.chunkCount ?? <NotSet />}</Field>
            <Field label="Uploaded">{formatDateTime(job.createdAt)}</Field>
            <Field label="Completed">{job.finishedAt ? formatDateTime(job.finishedAt) : <NotSet />}</Field>
            <Field label="Duration">{formatDuration(job.durationMs)}</Field>
            <Field label="Size">
              {job.sizeBytes < 1024 ? `${job.sizeBytes} B` : `${(job.sizeBytes / 1024).toFixed(1)} KB`}
            </Field>
          </dl>

          {job.status === 'failed' && (
            <div role="alert" className="space-y-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-900">
              <p className="flex gap-2">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span>
                  {job.failedStage && (
                    <span className="font-semibold">Failed at {STAGE_LABELS[job.failedStage] ?? job.failedStage}. </span>
                  )}
                  {job.error ?? 'Processing failed.'}
                </span>
              </p>
              {job.retryable ? (
                <button
                  type="button"
                  onClick={retry}
                  disabled={retrying}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1 font-medium text-red-800 hover:bg-red-50 disabled:opacity-50"
                >
                  <RotateCw className={`h-3.5 w-3.5 ${retrying ? 'animate-spin' : ''}`} aria-hidden />
                  {retrying ? 'Retrying…' : 'Retry processing'}
                </button>
              ) : (
                <p className="text-xs text-red-900/80">
                  Retrying would fail the same way. Fix the file or the customer/loan selection and upload it again.
                </p>
              )}
              {retryError && <p className="text-xs">{retryError}</p>}
            </div>
          )}

          {job.warnings.length > 0 && (
            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-ink">Warnings</h3>
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-soft">
                {job.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </section>
          )}

          <section>
            <h3 className="mb-2 text-xs font-semibold text-ink">Processing stages</h3>
            <StageList stages={job.stages} />
          </section>

          {job.status === 'ready' && (
            <button
              type="button"
              onClick={() => onOpenDocument(job.documentId)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
            >
              <FileSearch className="h-4 w-4" aria-hidden />
              Open in Document Explorer
            </button>
          )}
        </div>
      )}
    </div>
  )
}
