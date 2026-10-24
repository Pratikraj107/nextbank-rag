import { FileSpreadsheet, FileText, Globe, Mail } from 'lucide-react'
import { forwardRef } from 'react'

import { humanize, type SourceGroup } from '../lib/sources'

function FileIcon({ filename }: { filename: string }) {
  const extension = filename.split('.').at(-1)?.toLowerCase()
  const className = 'h-4 w-4'

  switch (extension) {
    case 'csv':
      return <FileSpreadsheet className={className} aria-hidden />
    case 'eml':
      return <Mail className={className} aria-hidden />
    case 'html':
    case 'htm':
      return <Globe className={className} aria-hidden />
    default:
      return <FileText className={className} aria-hidden />
  }
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd className="truncate font-mono text-xs text-ink" title={value}>
        {value}
      </dd>
    </div>
  )
}

interface SourceCardProps {
  group: SourceGroup
  /** Whether citation labels (S1, S2…) apply to these entries. */
  showLabels: boolean
  highlighted: boolean
  activeIndex: number | null
}

export const SourceCard = forwardRef<HTMLLIElement, SourceCardProps>(function SourceCard(
  { group, showLabels, highlighted, activeIndex },
  ref,
) {
  const chunkIndexes = group.entries
    .map((entry) => entry.chunkIndex)
    .filter((value): value is number => value !== null)

  return (
    <li
      ref={ref}
      className={`rounded-xl border bg-white p-3.5 transition-[box-shadow,border-color] duration-300 ${
        highlighted
          ? 'border-accent/60 shadow-[0_0_0_4px_rgba(42,91,215,0.12)]'
          : 'border-line shadow-[0_1px_2px_rgba(15,27,61,0.04)]'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas text-ink-soft">
          <FileIcon filename={group.filename} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink [overflow-wrap:anywhere]" title={group.source}>
            {group.filename}
          </p>
          {group.folder && (
            <p className="truncate text-xs text-muted" title={group.source}>
              {group.folder}
            </p>
          )}
        </div>
      </div>

      {group.documentType && (
        <span className="mt-3 inline-flex rounded-md bg-canvas px-2 py-0.5 text-xs font-medium text-ink-soft">
          {humanize(group.documentType)}
        </span>
      )}

      {(group.customerId || group.loanId) && (
        <dl className="mt-3 grid grid-cols-2 gap-3">
          {group.customerId && <Field label="Customer" value={group.customerId} />}
          {group.loanId && <Field label="Loan" value={group.loanId} />}
        </dl>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-3 text-xs text-muted">
        <span>
          {group.entries.length} {group.entries.length === 1 ? 'entry' : 'entries'} returned
          {chunkIndexes.length > 0 &&
            ` · ${chunkIndexes.length === 1 ? 'chunk' : 'chunks'} ${chunkIndexes.join(', ')}`}
        </span>
        {showLabels && (
          <span className="ml-auto flex flex-wrap gap-1">
            {group.entries.map((entry) => (
              <span
                key={entry.label}
                className={`rounded px-1.5 py-px text-[11px] font-semibold tabular-nums ${
                  entry.index === activeIndex ? 'bg-accent text-white' : 'bg-accent-soft text-accent'
                }`}
              >
                {entry.label}
              </span>
            ))}
          </span>
        )}
      </div>
    </li>
  )
})
