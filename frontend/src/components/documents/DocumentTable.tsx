import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { KeyboardEvent } from 'react'

import type { DocumentSummary } from '../../lib/documents'
import { humanize } from '../../lib/sources'
import { FileTypeIcon } from '../FileTypeIcon'

export function NotSet() {
  return <span className="text-muted/80 italic">Not set</span>
}

function Mono({ value }: { value: string | null }) {
  return value ? <span className="font-mono text-xs text-ink">{value}</span> : <NotSet />
}

interface DocumentTableProps {
  items: DocumentSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
}

export function DocumentTable({ items, selectedId, onSelect }: DocumentTableProps) {
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
          <th scope="col" className="w-auto px-4 py-2.5 font-medium">File</th>
          <th scope="col" className="hidden w-[22%] px-3 py-2.5 font-medium @2xl:table-cell">Type</th>
          <th scope="col" className="hidden w-[17%] px-3 py-2.5 font-medium @lg:table-cell">Customer</th>
          <th scope="col" className="hidden w-[17%] px-3 py-2.5 font-medium @lg:table-cell">Loan</th>
          <th scope="col" className="hidden w-[9%] px-3 py-2.5 font-medium @5xl:table-cell">Format</th>
          <th scope="col" className="hidden w-[9%] px-3 py-2.5 text-right font-medium @4xl:table-cell">Chunks</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => {
          const selected = item.id === selectedId
          return (
            <tr
              key={item.id}
              tabIndex={0}
              aria-selected={selected}
              onClick={() => onSelect(item.id)}
              onKeyDown={(event) => onKeyDown(event, item.id)}
              className={`cursor-pointer border-b border-line/70 transition-colors outline-none focus-visible:bg-accent-soft/60 ${
                selected ? 'bg-accent-soft' : 'hover:bg-white'
              }`}
            >
              <td className="px-4 py-3 align-top">
                <div className="flex min-w-0 items-start gap-3">
                  <div
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${
                      selected ? 'border-accent/30 bg-white text-accent' : 'border-line bg-white text-ink-soft'
                    }`}
                  >
                    <FileTypeIcon filename={item.filename} sourceType={item.sourceType} />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink" title={item.filename}>
                      {item.filename}
                      {item.rowNumber !== null && (
                        <span className="font-normal text-muted"> · row {item.rowNumber}</span>
                      )}
                    </p>
                    <p className="truncate text-xs text-muted" title={item.source}>
                      {item.source}
                    </p>
                    {/* Compact metadata where columns are hidden. */}
                    <p className="mt-1 truncate text-xs text-ink-soft @2xl:hidden">
                      {item.documentType ? humanize(item.documentType) : 'Type not set'}
                      <span className="@lg:hidden">
                        {' · '}
                        {item.customerId ?? 'no customer'} · {item.loanId ?? 'no loan'}
                      </span>
                    </p>
                  </div>
                </div>
              </td>
              <td className="hidden px-3 py-3 align-top @2xl:table-cell">
                {item.documentType ? (
                  <span className="inline-flex max-w-full truncate rounded-md bg-white px-2 py-0.5 text-xs font-medium text-ink-soft ring-1 ring-line">
                    {humanize(item.documentType)}
                  </span>
                ) : (
                  <NotSet />
                )}
              </td>
              <td className="hidden px-3 py-3 align-top @lg:table-cell"><Mono value={item.customerId} /></td>
              <td className="hidden px-3 py-3 align-top @lg:table-cell"><Mono value={item.loanId} /></td>
              <td className="hidden px-3 py-3 align-top text-xs text-ink-soft uppercase @5xl:table-cell">
                {item.sourceType ?? <NotSet />}
              </td>
              <td className="hidden px-3 py-3 text-right align-top text-xs text-ink-soft tabular-nums @4xl:table-cell">
                {item.chunkCount}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  totalPages: number
  onPage: (page: number) => void
}

export function Pagination({ page, pageSize, total, totalPages, onPage }: PaginationProps) {
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)

  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-sm text-muted">
      <p aria-live="polite">
        {total === 0 ? 'No documents' : `Showing ${first}–${last} of ${total}`}
      </p>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          className="rounded-lg border border-line bg-white p-1.5 text-ink-soft hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="min-w-[72px] text-center tabular-nums">
          Page {Math.min(page, totalPages)} of {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
          className="rounded-lg border border-line bg-white p-1.5 text-ink-soft hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </nav>
  )
}
