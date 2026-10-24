import { LoaderCircle, RotateCw } from 'lucide-react'

import type { ConnectionState } from '../types'

const LABELS: Record<ConnectionState, string> = {
  checking: 'Checking…',
  connected: 'Connected',
  disconnected: 'Disconnected',
}

function StatusDot({ status }: { status: ConnectionState }) {
  if (status === 'checking') {
    return <LoaderCircle aria-hidden className="h-3 w-3 animate-spin text-muted" />
  }

  return (
    <span
      aria-hidden
      className={`h-2 w-2 rounded-full ${
        status === 'connected'
          ? 'bg-emerald-500 ring-4 ring-emerald-500/15'
          : 'bg-red-500 ring-4 ring-red-500/15'
      }`}
    />
  )
}

interface ConnectionStatusProps {
  status: ConnectionState
  onRetry: () => void
  variant?: 'compact' | 'inline' | 'card'
}

export function ConnectionStatus({ status, onRetry, variant = 'compact' }: ConnectionStatusProps) {
  if (variant === 'inline') {
    return (
      <div role="status" aria-live="polite" className="flex items-center gap-1.5 text-xs text-muted">
        <StatusDot status={status} />
        <span>
          <span className="sr-only">Backend: </span>
          {LABELS[status]}
        </span>
        {status === 'disconnected' && (
          <button
            type="button"
            onClick={onRetry}
            className="font-medium text-accent hover:underline"
            aria-label="Retry backend connection check"
          >
            Retry
          </button>
        )}
      </div>
    )
  }

  if (variant === 'compact') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink-soft"
      >
        <StatusDot status={status} />
        <span>
          <span className="sr-only">Backend: </span>
          {LABELS[status]}
        </span>
        {status === 'disconnected' && (
          <button
            type="button"
            onClick={onRetry}
            className="-mr-1 rounded-full p-0.5 text-muted hover:bg-canvas hover:text-ink"
            aria-label="Retry backend connection check"
          >
            <RotateCw className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-line bg-canvas/60 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <div role="status" aria-live="polite" className="flex items-center gap-2.5">
          <StatusDot status={status} />
          <div className="leading-tight">
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted">Backend</p>
            <p className="text-sm font-medium text-ink">{LABELS[status]}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onRetry}
          disabled={status === 'checking'}
          className="rounded-lg p-1.5 text-muted transition-colors hover:bg-white hover:text-ink disabled:opacity-40"
          aria-label="Check backend connection again"
          title="Check again"
        >
          <RotateCw className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
