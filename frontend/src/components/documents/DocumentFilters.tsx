import { LoaderCircle, Search, X } from 'lucide-react'

import type { DocumentFacets, FacetValue } from '../../lib/documents'
import { humanize } from '../../lib/sources'

export interface FilterValues {
  search: string
  documentType: string
  customerId: string
  loanId: string
}

interface DocumentFiltersProps {
  values: FilterValues
  facets: DocumentFacets | null
  searchPending: boolean
  onChange: (change: Partial<FilterValues>) => void
  onClear: () => void
}

function FacetSelect({
  id,
  label,
  allLabel,
  value,
  options,
  format = (text) => text,
  onChange,
}: {
  id: string
  label: string
  allLabel: string
  value: string
  options: FacetValue[]
  format?: (value: string) => string
  onChange: (value: string) => void
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-line-strong bg-white px-2.5 text-sm text-ink focus:border-accent/50 focus:ring-4 focus:ring-accent/10 focus:outline-none"
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {format(option.value)} ({option.count})
          </option>
        ))}
      </select>
    </div>
  )
}

export function DocumentFilters({ values, facets, searchPending, onChange, onClear }: DocumentFiltersProps) {
  const hasFilters = Boolean(values.search || values.documentType || values.customerId || values.loanId)

  return (
    <div className="grid gap-3 @md:grid-cols-2 @4xl:grid-cols-[minmax(200px,1.6fr)_repeat(3,minmax(130px,1fr))_auto] @4xl:items-end">
      <div className="min-w-0 @md:col-span-2 @4xl:col-span-1">
        <label htmlFor="document-search" className="mb-1 block text-xs font-medium text-muted">
          Search
        </label>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
          <input
            id="document-search"
            type="search"
            value={values.search}
            onChange={(event) => onChange({ search: event.target.value })}
            placeholder="Filename or source path…"
            maxLength={200}
            className="h-9 w-full rounded-lg border border-line-strong bg-white pr-8 pl-8 text-sm text-ink placeholder:text-muted/80 focus:border-accent/50 focus:ring-4 focus:ring-accent/10 focus:outline-none"
          />
          {searchPending && (
            <LoaderCircle className="absolute top-1/2 right-2.5 h-4 w-4 -translate-y-1/2 animate-spin text-muted" aria-label="Searching" />
          )}
        </div>
      </div>

      <FacetSelect
        id="filter-type"
        label="Document type"
        allLabel="All types"
        value={values.documentType}
        options={facets?.documentTypes ?? []}
        format={humanize}
        onChange={(documentType) => onChange({ documentType })}
      />
      <FacetSelect
        id="filter-customer"
        label="Customer ID"
        allLabel="All customers"
        value={values.customerId}
        options={facets?.customerIds ?? []}
        onChange={(customerId) => onChange({ customerId })}
      />
      <FacetSelect
        id="filter-loan"
        label="Loan ID"
        allLabel="All loans"
        value={values.loanId}
        options={facets?.loanIds ?? []}
        onChange={(loanId) => onChange({ loanId })}
      />

      <button
        type="button"
        onClick={onClear}
        disabled={!hasFilters}
        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 text-sm font-medium text-ink-soft hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50 @md:col-span-2 @4xl:col-span-1"
      >
        <X className="h-4 w-4" aria-hidden />
        Clear filters
      </button>
    </div>
  )
}
