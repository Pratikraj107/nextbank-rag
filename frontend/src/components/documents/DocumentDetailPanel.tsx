import { Check, CircleAlert, Copy, LoaderCircle, MessageSquareText, RotateCw, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { useDocumentDetail } from '../../hooks/useDocuments'
import { questionAbout, type DocumentChunk } from '../../lib/documents'
import { humanize } from '../../lib/sources'
import { FileTypeIcon } from '../FileTypeIcon'
import { NotSet } from './DocumentTable'

type Tab = 'text' | 'chunks' | 'fields'

// ------------------------------------------------------------
// Small building blocks
// ------------------------------------------------------------

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5 truncate text-sm text-ink">{children}</dd>
    </div>
  )
}

function Mono({ value }: { value: string | null }) {
  return value ? <span className="font-mono text-[13px]" title={value}>{value}</span> : <NotSet />
}

function PanelState({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center text-sm text-muted">
      {icon}
      {children}
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <PanelState icon={<CircleAlert className="h-5 w-5 text-red-600" aria-hidden />}>
      <p role="alert" className="text-red-900">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1 font-medium text-ink-soft hover:bg-canvas"
      >
        <RotateCw className="h-3.5 w-3.5" aria-hidden />
        Retry
      </button>
    </PanelState>
  )
}

function Loading({ label }: { label: string }) {
  return (
    <PanelState icon={<LoaderCircle className="h-5 w-5 animate-spin" aria-hidden />}>
      <p role="status">{label}</p>
    </PanelState>
  )
}

function formatValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <NotSet />
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : <NotSet />
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function KeyValueList({ entries }: { entries: [string, unknown][] }) {
  return (
    <dl className="divide-y divide-line/70 rounded-lg border border-line">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[minmax(110px,40%)_1fr] gap-3 px-3 py-2 text-sm">
          <dt className="text-muted">{humanize(key)}</dt>
          <dd className="min-w-0 text-ink [overflow-wrap:anywhere]">{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    if (state === 'idle') return
    const timer = setTimeout(() => setState('idle'), 1800)
    return () => clearTimeout(timer)
  }, [state])

  const copy = () => {
    if (!navigator.clipboard) {
      setState('failed')
      return
    }
    navigator.clipboard.writeText(text).then(
      () => setState('copied'),
      () => setState('failed'),
    )
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-muted hover:bg-canvas hover:text-ink"
    >
      {state === 'copied' ? <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
      <span aria-live="polite">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy'}</span>
    </button>
  )
}

// ------------------------------------------------------------
// Tabs
// ------------------------------------------------------------

function TextTab({ content }: { content: string }) {
  if (!content.trim()) {
    return <PanelState icon={null}>No text was extracted from this doc.</PanelState>
  }
  return (
    // Rendered as plain text; React escapes it, so markup in documents is never interpreted.
    <pre className="rounded-lg border border-line bg-canvas/50 p-4 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">
      {content}
    </pre>
  )
}

function ChunksTab({ chunks, loading, error, onRetry }: {
  chunks: DocumentChunk[] | null
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  if (loading) return <Loading label="Loading chunks…" />
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (!chunks?.length) {
    return (
      <PanelState icon={null}>
        This document has no chunks, so it is not searchable by the assistant until chunking is re-run.
      </PanelState>
    )
  }

  return (
    <ol className="space-y-3">
      {chunks.map((chunk) => (
        <li key={chunk.chunkId ?? chunk.chunkIndex} className="rounded-lg border border-line">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70 px-3 py-1.5">
            <span className="text-xs font-semibold text-ink">Chunk {chunk.chunkIndex}</span>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
              {chunk.documentType && <span>{humanize(chunk.documentType)}</span>}
              <span className="font-mono">{chunk.customerId ?? 'no customer'}</span>
              <span className="font-mono">{chunk.loanId ?? 'no loan'}</span>
              <CopyButton text={chunk.content} />
            </span>
          </div>
          <pre className="px-3 py-2.5 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">
            {chunk.content}
          </pre>
        </li>
      ))}
    </ol>
  )
}

function FieldsTab({ metadata }: { metadata: Record<string, unknown> }) {
  const { classification, email, record, upload } = metadata
  const sections: ReactNode[] = []

  // Structured fields get their own sections; row_number is shown in the header.
  const extractedEntries = Object.entries(metadata).filter(
    ([key]) => !['classification', 'email', 'record', 'row_number', 'upload'].includes(key),
  )
  if (extractedEntries.length) {
    sections.push(
      <section key="extracted">
        <h4 className="mb-2 text-xs font-semibold text-ink">Fields extracted during ingestion</h4>
        <KeyValueList entries={extractedEntries} />
      </section>,
    )
  }

  if (record && typeof record === 'object') {
    sections.push(
      <section key="record">
        <h4 className="mb-2 text-xs font-semibold text-ink">CSV record</h4>
        <KeyValueList entries={Object.entries(record as Record<string, unknown>)} />
      </section>,
    )
  }

  if (email && typeof email === 'object') {
    sections.push(
      <section key="email">
        <h4 className="mb-2 text-xs font-semibold text-ink">Email headers</h4>
        <KeyValueList entries={Object.entries(email as Record<string, unknown>)} />
      </section>,
    )
  }

  if (upload && typeof upload === 'object') {
    sections.push(
      <section key="upload">
        <h4 className="mb-2 text-xs font-semibold text-ink">Upload</h4>
        <KeyValueList entries={Object.entries(upload as Record<string, unknown>)} />
      </section>,
    )
  }

  if (classification && typeof classification === 'object') {
    sections.push(
      <section key="classification">
        <h4 className="mb-2 text-xs font-semibold text-ink">Automatic classification</h4>
        <KeyValueList entries={Object.entries(classification as Record<string, unknown>)} />
      </section>,
    )
  }

  if (!sections.length) {
    return <PanelState icon={null}>No fields were extracted for this doc.</PanelState>
  }

  return <div className="space-y-5">{sections}</div>
}

// ------------------------------------------------------------
// Panel
// ------------------------------------------------------------

interface DocumentDetailPanelProps {
  documentId: string
  onAsk: (question: string) => void
  onClose?: () => void
}

export function DocumentDetailPanel({ documentId, onAsk, onClose }: DocumentDetailPanelProps) {
  const { detail, chunks, retry } = useDocumentDetail(documentId)
  const [tab, setTab] = useState<Tab>('text')
  const doc = detail.value

  const tabs: { id: Tab; label: string }[] = [
    { id: 'text', label: 'Extracted text' },
    { id: 'chunks', label: chunks.value ? `Chunks (${chunks.value.length})` : 'Chunks' },
    { id: 'fields', label: 'Fields' },
  ]

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas text-ink-soft">
            <FileTypeIcon filename={doc?.filename ?? ''} sourceType={doc?.sourceType} className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink" title={doc?.filename}>
              {doc ? doc.filename : detail.loading ? 'Loading…' : 'Document'}
              {doc?.rowNumber != null && <span className="font-normal text-muted"> · row {doc.rowNumber}</span>}
            </h2>
            {doc && (
              <p className="truncate text-xs text-muted" title={doc.source}>
                {doc.source}
              </p>
            )}
          </div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="-mr-1.5 rounded-lg p-1.5 text-muted hover:bg-canvas hover:text-ink"
            aria-label="Close document"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      {detail.loading && <Loading label="Loading document…" />}
      {detail.error && <ErrorState message={detail.error} onRetry={retry} />}

      {doc && (
        <>
          <div className="space-y-4 border-b border-line px-5 py-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
              <Field label="Type">{doc.documentType ? humanize(doc.documentType) : <NotSet />}</Field>
              <Field label="Customer"><Mono value={doc.customerId} /></Field>
              <Field label="Loan"><Mono value={doc.loanId} /></Field>
              <Field label="Format">{doc.sourceType ? doc.sourceType.toUpperCase() : <NotSet />}</Field>
            </dl>
            <div>
              <button
                type="button"
                onClick={() => onAsk(questionAbout(doc))}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
              >
                <MessageSquareText className="h-4 w-4" aria-hidden />
                Ask about this document
              </button>
              <p className="mt-1.5 text-xs text-muted">
                Opens the assistant with an editable question. The assistant searches all ingested
                documents; it is not limited to this one.
              </p>
            </div>
          </div>

          <div role="tablist" aria-label="Document views" className="flex gap-1 border-b border-line px-4">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                id={`tab-${item.id}`}
                aria-selected={tab === item.id}
                aria-controls={`panel-${item.id}`}
                onClick={() => setTab(item.id)}
                className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  tab === item.id ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
            className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
          >
            {tab === 'text' && <TextTab content={doc.content} />}
            {tab === 'chunks' && (
              <ChunksTab chunks={chunks.value} loading={chunks.loading} error={chunks.error} onRetry={retry} />
            )}
            {tab === 'fields' && <FieldsTab metadata={doc.metadata} />}
          </div>
        </>
      )}
    </div>
  )
}
