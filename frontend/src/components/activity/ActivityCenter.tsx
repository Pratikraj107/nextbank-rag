import { CircleAlert, FileUp, History, LoaderCircle, Menu, RotateCw, X } from 'lucide-react'
import { useCallback, useState, type KeyboardEvent } from 'react'

import { useJobList } from '../../hooks/useJobs'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { formatDateTime, formatDuration } from '../../lib/format'
import { humanize } from '../../lib/sources'
import { STAGE_LABELS, type FacetValue, type IngestionJob } from '../../lib/uploads'
import { Pagination } from '../documents/DocumentTable'
import { Drawer } from '../Drawer'
import { FileTypeIcon } from '../FileTypeIcon'
import { JobDetailPanel } from './JobDetailPanel'
import { JobStatusBadge } from './JobStatusBadge'

const PAGE_SIZE = 20
const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Queued', processing: 'Processing', ready: 'Ready', failed: 'Failed',
}

interface Filters {
  status: string
  customerId: string
  documentType: string
}

const NO_FILTERS: Filters = { status: '', customerId: '', documentType: '' }

function FilterSelect({ id, label, allLabel, value, options, format, onChange }: {
  id: string
  label: string
  allLabel: string
  value: string
  options: FacetValue[]
  format: (value: string) => string
  onChange: (value: string) => void
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted">{label}</label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-line-strong bg-white px-2.5 text-sm text-ink focus:border-accent/50 focus:ring-4 focus:ring-accent/10 focus:outline-none"
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{format(option.value)} ({option.count})</option>
        ))}
      </select>
    </div>
  )
}

function JobTable({ jobs, selectedId, onSelect }: {
  jobs: IngestionJob[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const onKeyDown = (event: KeyboardEvent, id: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(id)
    }
  }

  return (
    <table className="w-full table-fixed text-left text-sm">
      <thead className="sticky top-0 z-10 bg-canvas/95 text-xs font-medium text-muted backdrop-blur">
        <tr className="border-b border-line">
          <th scope="col" className="px-4 py-2.5 font-medium">File</th>
          <th scope="col" className="hidden w-[18%] px-3 py-2.5 font-medium @lg:table-cell">Customer</th>
          <th scope="col" className="hidden w-[22%] px-3 py-2.5 font-medium @3xl:table-cell">Uploaded</th>
          <th scope="col" className="hidden w-[12%] px-3 py-2.5 font-medium @2xl:table-cell">Duration</th>
          <th scope="col" className="w-[26%] px-3 py-2.5 font-medium @lg:w-[20%]">Status</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => {
          const selected = job.jobId === selectedId
          return (
            <tr
              key={job.jobId}
              tabIndex={0}
              aria-selected={selected}
              onClick={() => onSelect(job.jobId)}
              onKeyDown={(event) => onKeyDown(event, job.jobId)}
              className={`cursor-pointer border-b border-line/70 outline-none focus-visible:bg-accent-soft/60 ${
                selected ? 'bg-accent-soft' : 'hover:bg-white'
              }`}
            >
              <td className="px-4 py-3 align-top">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line bg-white text-ink-soft">
                    <FileTypeIcon filename={job.filename} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink" title={job.filename}>{job.filename}</p>
                    <p className="truncate text-xs text-muted">
                      {job.documentType ? humanize(job.documentType) : 'Type not determined yet'}
                      <span className="@lg:hidden"> · {job.customerId}</span>
                    </p>
                  </div>
                </div>
              </td>
              <td className="hidden px-3 py-3 align-top @lg:table-cell">
                <p className="font-mono text-xs text-ink">{job.customerId}</p>
                {job.loanId && <p className="font-mono text-[11px] text-muted">{job.loanId}</p>}
              </td>
              <td className="hidden px-3 py-3 align-top text-xs text-ink-soft @3xl:table-cell">
                {formatDateTime(job.createdAt)}
              </td>
              <td className="hidden px-3 py-3 align-top text-xs text-ink-soft tabular-nums @2xl:table-cell">
                {formatDuration(job.durationMs)}
              </td>
              <td className="px-3 py-3 align-top">
                <JobStatusBadge status={job.status} />
                {job.status === 'failed' && job.failedStage && (
                  <p className="mt-1 truncate text-[11px] text-red-800">at {STAGE_LABELS[job.failedStage] ?? job.failedStage}</p>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

interface ActivityCenterProps {
  selectedJobId: string | null
  onSelectJob: (jobId: string | null) => void
  onOpenDocument: (documentId: string) => void
  onGoToDocuments: () => void
  onOpenNavigation: () => void
}

export function ActivityCenter({
  selectedJobId,
  onSelectJob,
  onOpenDocument,
  onGoToDocuments,
  onOpenNavigation,
}: ActivityCenterProps) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [page, setPage] = useState(1)
  const showsDetailColumn = useMediaQuery('(min-width: 1280px)')
  const list = useJobList({ ...filters, page, pageSize: PAGE_SIZE })
  const data = list.data
  const hasFilters = Boolean(filters.status || filters.customerId || filters.documentType)
  const totalJobs = data?.facets.statuses.reduce((sum, facet) => sum + facet.count, 0) ?? 0

  const change = (patch: Partial<Filters>) => {
    setFilters((previous) => ({ ...previous, ...patch }))
    setPage(1)
  }

  const closeDetail = useCallback(() => onSelectJob(null), [onSelectJob])

  let body
  if (!data && list.loading) {
    body = (
      <div role="status" className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
        Loading activity…
      </div>
    )
  } else if (!data && list.error) {
    body = (
      <div role="alert" className="mx-auto mt-10 flex max-w-md gap-2.5 rounded-xl border border-red-200 bg-red-50/70 px-4 py-3 text-sm text-red-900">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden />
        <div className="space-y-2">
          <p>{list.error}</p>
          <button type="button" onClick={list.refresh} className="font-medium underline">Try again</button>
        </div>
      </div>
    )
  } else if (data && data.items.length === 0) {
    body = (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-muted">
        <History className="h-6 w-6" aria-hidden />
        {hasFilters ? (
          <>
            <p>No jobs match these filters.</p>
            <button type="button" onClick={() => change(NO_FILTERS)} className="rounded-lg border border-line bg-white px-3 py-1.5 font-medium text-ink-soft hover:bg-canvas">
              Clear filters
            </button>
          </>
        ) : (
          <>
            <p>No documents have been uploaded yet.</p>
            <button type="button" onClick={onGoToDocuments} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 font-medium text-white hover:bg-accent-hover">
              <FileUp className="h-4 w-4" aria-hidden />
              Upload from Document Explorer
            </button>
          </>
        )}
      </div>
    )
  } else if (data) {
    body = (
      <div className={`min-h-0 flex-1 overflow-y-auto ${list.loading ? 'opacity-90' : ''}`}>
        {list.error && <p role="alert" className="mx-4 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{list.error}</p>}
        <JobTable jobs={data.items} selectedId={selectedJobId} onSelect={onSelectJob} />
      </div>
    )
  }

  const detail = selectedJobId && (
    <JobDetailPanel
      key={selectedJobId}
      jobId={selectedJobId}
      onOpenDocument={onOpenDocument}
      onChanged={list.refresh}
      onClose={closeDetail}
    />
  )

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <section aria-labelledby="activity-title" className="@container flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex items-start gap-3 border-b border-line bg-white/80 px-4 py-3 backdrop-blur sm:px-6">
          <button type="button" onClick={onOpenNavigation} className="-ml-1 rounded-lg p-2 text-ink-soft hover:bg-canvas lg:hidden" aria-label="Open navigation">
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 id="activity-title" className="truncate text-[15px] font-semibold tracking-tight text-ink sm:text-lg">Activity</h1>
            <p className="hidden truncate text-sm text-muted sm:block">Processing status of uploaded documents.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {data && (
              <span className="hidden rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink-soft tabular-nums sm:inline">
                {totalJobs} {totalJobs === 1 ? 'job' : 'jobs'}
              </span>
            )}
            <button
              type="button"
              onClick={list.refresh}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-sm font-medium text-ink-soft hover:bg-canvas"
              aria-label="Refresh jobs"
            >
              <RotateCw className={`h-4 w-4 ${list.loading && data ? 'animate-spin' : ''}`} aria-hidden />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </header>

        <div className="grid gap-3 border-b border-line px-4 py-3 sm:px-6 @md:grid-cols-2 @3xl:grid-cols-[repeat(3,minmax(140px,1fr))_auto] @3xl:items-end">
          <FilterSelect id="job-status" label="Status" allLabel="All statuses" value={filters.status}
            options={data?.facets.statuses ?? []} format={(v) => STATUS_LABELS[v] ?? v} onChange={(status) => change({ status })} />
          <FilterSelect id="job-customer" label="Customer ID" allLabel="All customers" value={filters.customerId}
            options={data?.facets.customerIds ?? []} format={(v) => v} onChange={(customerId) => change({ customerId })} />
          <FilterSelect id="job-type" label="Document type" allLabel="All types" value={filters.documentType}
            options={data?.facets.documentTypes ?? []} format={humanize} onChange={(documentType) => change({ documentType })} />
          <button
            type="button"
            onClick={() => change(NO_FILTERS)}
            disabled={!hasFilters}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 text-sm font-medium text-ink-soft hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50 @md:col-span-2 @3xl:col-span-1"
          >
            <X className="h-4 w-4" aria-hidden />
            Clear filters
          </button>
        </div>

        {body}

        {data && data.total > 0 && (
          <div className="border-t border-line px-4 py-2.5 sm:px-6">
            <Pagination page={data.page} pageSize={data.pageSize} total={data.total} totalPages={data.totalPages} onPage={setPage} />
          </div>
        )}
      </section>

      {showsDetailColumn && (
        <aside aria-label="Job details" className="w-[420px] shrink-0 border-l border-line">
          {detail || (
            <div className="flex h-full flex-col items-center justify-center gap-3 bg-white px-8 text-center text-sm text-muted">
              <History className="h-6 w-6" aria-hidden />
              Select a job to see its processing stages.
            </div>
          )}
        </aside>
      )}

      <Drawer
        open={!showsDetailColumn && selectedJobId !== null}
        onClose={closeDetail}
        side="right"
        label="Job details"
        widthClassName="w-[94vw] max-w-[480px]"
      >
        {detail}
      </Drawer>
    </div>
  )
}
