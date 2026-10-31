import { CircleAlert, CircleCheck, FileSearch, FileUp, LoaderCircle, Menu, RotateCw } from 'lucide-react'
import { useCallback, useState } from 'react'

import { useDocumentList } from '../../hooks/useDocuments'
import { useUpload } from '../../hooks/useUpload'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { Drawer } from '../Drawer'
import { DocumentDetailPanel } from './DocumentDetailPanel'
import { DocumentFilters, type FilterValues } from './DocumentFilters'
import { DocumentTable, Pagination } from './DocumentTable'
import { UploadPanel } from './UploadPanel'

const PAGE_SIZE = 20
const NO_FILTERS: FilterValues = { search: '', documentType: '', customerId: '', loanId: '' }

interface DocumentExplorerProps {
  selectedId: string | null
  onSelect: (id: string | null) => void
  onAsk: (question: string) => void
  onOpenNavigation: () => void
}

export function DocumentExplorer({ selectedId, onSelect, onAsk, onOpenNavigation }: DocumentExplorerProps) {
  const [filters, setFilters] = useState<FilterValues>(NO_FILTERS)
  const [page, setPage] = useState(1)
  const showsDetailColumn = useMediaQuery('(min-width: 1280px)')

  const list = useDocumentList({ ...filters, page, pageSize: PAGE_SIZE })
  const data = list.data
  const hasFilters = Boolean(filters.search || filters.documentType || filters.customerId || filters.loanId)

  const changeFilters = useCallback((change: Partial<FilterValues>) => {
    setFilters((previous) => ({ ...previous, ...change }))
    setPage(1)
  }, [])

  const clearFilters = useCallback(() => {
    setFilters(NO_FILTERS)
    setPage(1)
  }, [])

  const closeDetail = useCallback(() => onSelect(null), [onSelect])

  // Upload state lives here, not in the panel, so closing the panel does
  // not stop tracking the job. A ready job refreshes the list.
  const [uploadOpen, setUploadOpen] = useState(false)
  const refreshList = list.retry
  const uploader = useUpload(useCallback(() => refreshList(), [refreshList]))
  const job = uploader.state.job

  const openUploadedDocument = useCallback(
    (documentId: string) => {
      setUploadOpen(false)
      onSelect(documentId)
    },
    [onSelect],
  )

  let body
  if (!data && list.loading) {
    body = (
      <div role="status" className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
        Loading documents…
      </div>
    )
  } else if (list.error && !data) {
    body = <ListError message={list.error} onRetry={list.retry} />
  } else if (data && data.items.length === 0) {
    body = (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-muted">
        <FileSearch className="h-6 w-6" aria-hidden />
        {hasFilters ? (
          <>
            <p>No documents match these filters.</p>
            <button
              type="button"
              onClick={clearFilters}
              className="rounded-lg border border-line bg-white px-3 py-1.5 font-medium text-ink-soft hover:bg-canvas"
            >
              Clear filters
            </button>
          </>
        ) : (
          <p>No documents have been ingested yet. Run ingestion and chunking, then reload this page.</p>
        )}
      </div>
    )
  } else if (data) {
    body = (
      <div className={`min-h-0 flex-1 overflow-y-auto transition-opacity ${list.loading ? 'opacity-60' : ''}`}>
        {list.error && (
          <div className="px-4 pt-3">
            <ListError message={list.error} onRetry={list.retry} compact />
          </div>
        )}
        <DocumentTable items={data.items} selectedId={selectedId} onSelect={onSelect} />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      {/* A size container: filters and table columns adapt to the space left by the detail panel. */}
      <section aria-labelledby="explorer-title" className="@container flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex items-start gap-3 border-b border-line bg-white/80 px-4 py-3 backdrop-blur sm:px-6">
          <button
            type="button"
            onClick={onOpenNavigation}
            className="-ml-1 rounded-lg p-2 text-ink-soft hover:bg-canvas lg:hidden"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 id="explorer-title" className="truncate text-[15px] font-semibold tracking-tight text-ink sm:text-lg">
              Document Explorer
            </h1>
            <p className="hidden truncate text-sm text-muted sm:block">
              Browse the loan and customer documents ingested into NexaBank AI.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {uploader.state.phase !== 'idle' && !uploadOpen && (
              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                className="inline-flex max-w-[220px] items-center gap-1.5 rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink-soft hover:bg-canvas"
                aria-label="Show upload status"
              >
                {job?.status === 'ready' ? (
                  <CircleCheck className="h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden />
                ) : job?.status === 'failed' ? (
                  <CircleAlert className="h-3.5 w-3.5 shrink-0 text-red-600" aria-hidden />
                ) : (
                  <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" aria-hidden />
                )}
                <span className="truncate">
                  {job ? `${job.filename}: ${job.status}` : `Uploading ${uploader.state.filename ?? ''}`}
                </span>
              </button>
            )}
            {data && (
              <span className="hidden rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink-soft tabular-nums sm:inline">
                {data.libraryTotal} {data.libraryTotal === 1 ? 'document' : 'documents'}
              </span>
            )}
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
            >
              <FileUp className="h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Upload document</span>
              <span className="sr-only sm:hidden">Upload document</span>
            </button>
          </div>
        </header>

        <div className="border-b border-line px-4 py-3 sm:px-6">
          <DocumentFilters
            values={filters}
            facets={data?.facets ?? null}
            searchPending={list.searchPending}
            onChange={changeFilters}
            onClear={clearFilters}
          />
        </div>

        {body}

        {data && data.total > 0 && (
          <div className="border-t border-line px-4 py-2.5 sm:px-6">
            <Pagination
              page={data.page}
              pageSize={data.pageSize}
              total={data.total}
              totalPages={data.totalPages}
              onPage={setPage}
            />
          </div>
        )}
      </section>

      {showsDetailColumn && (
        <aside aria-label="Document details" className="w-[460px] shrink-0 border-l border-line">
          {selectedId ? (
            <DocumentDetailPanel key={selectedId} documentId={selectedId} onAsk={onAsk} onClose={closeDetail} />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 bg-white px-8 text-center text-sm text-muted">
              <FileSearch className="h-6 w-6" aria-hidden />
              Select a document to see its extracted text, chunks and fields.
            </div>
          )}
        </aside>
      )}

      <Drawer
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        side="right"
        label="Upload document"
        widthClassName="w-[94vw] max-w-[480px]"
      >
        <UploadPanel
          upload={uploader.state}
          busy={uploader.busy}
          onStart={uploader.start}
          onRetry={uploader.retry}
          onResume={uploader.resume}
          onReset={uploader.reset}
          onOpenDocument={openUploadedDocument}
          onClose={() => setUploadOpen(false)}
        />
      </Drawer>

      <Drawer
        open={!uploadOpen && !showsDetailColumn && selectedId !== null}
        onClose={closeDetail}
        side="right"
        label="Document details"
        widthClassName="w-[94vw] max-w-[560px]"
      >
        {selectedId && (
          <DocumentDetailPanel key={selectedId} documentId={selectedId} onAsk={onAsk} onClose={closeDetail} />
        )}
      </Drawer>
    </div>
  )
}

function ListError({ message, onRetry, compact = false }: { message: string; onRetry: () => void; compact?: boolean }) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50/70 px-4 py-3 text-sm text-red-900 ${
        compact ? '' : 'mx-auto mt-10 max-w-md'
      }`}
    >
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden />
      <div className="space-y-2">
        <p>{message}</p>
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1 font-medium text-red-800 hover:bg-red-50"
        >
          <RotateCw className="h-3.5 w-3.5" aria-hidden />
          Retry
        </button>
      </div>
    </div>
  )
}
