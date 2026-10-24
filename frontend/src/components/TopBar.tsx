import { FileText, Menu, SquarePen } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { ConnectionState } from '../types'
import { ConnectionStatus } from './ConnectionStatus'

interface TopBarProps {
  connection: ConnectionState
  onRetryConnection: () => void
  onOpenNavigation: () => void
  onOpenEvidence: () => void
  evidenceCount: number
  canClear: boolean
  onClear: () => void
}

export function TopBar({
  connection,
  onRetryConnection,
  onOpenNavigation,
  onOpenEvidence,
  evidenceCount,
  canClear,
  onClear,
}: TopBarProps) {
  const [confirming, setConfirming] = useState(false)

  // Drop the confirmation prompt if the user does not follow through.
  useEffect(() => {
    if (!confirming) return
    const timer = setTimeout(() => setConfirming(false), 5000)
    return () => clearTimeout(timer)
  }, [confirming])

  return (
    <header className="flex items-center gap-3 border-b border-line bg-white/80 px-4 py-3 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onOpenNavigation}
        className="-ml-1 rounded-lg p-2 text-ink-soft hover:bg-canvas lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="h-5 w-5" />
      </button>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold tracking-tight text-ink sm:text-lg">
          Loan Intelligence Assistant
        </h1>
        <p className="hidden truncate text-sm text-muted sm:block">
          Ask questions about customer and loan documents.
        </p>
        <div className="mt-0.5 md:hidden">
          <ConnectionStatus status={connection} onRetry={onRetryConnection} variant="inline" />
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <div className="hidden md:block">
          <ConnectionStatus status={connection} onRetry={onRetryConnection} />
        </div>

        <button
          type="button"
          onClick={onOpenEvidence}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-sm font-medium text-ink-soft hover:bg-canvas xl:hidden"
          aria-label={`Open evidence panel, ${evidenceCount} source entries`}
        >
          <FileText className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">Evidence</span>
          <span className="rounded-md bg-canvas px-1.5 text-xs tabular-nums">{evidenceCount}</span>
        </button>

        {confirming ? (
          <div className="flex items-center gap-1.5" role="group" aria-label="Confirm clearing the conversation">
            <span className="hidden text-sm text-muted sm:inline">Clear chat?</span>
            <button
              type="button"
              onClick={() => {
                setConfirming(false)
                onClear()
              }}
              className="rounded-lg bg-ink px-2.5 py-1.5 text-sm font-medium text-white hover:bg-ink-soft"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-lg px-2.5 py-1.5 text-sm font-medium text-ink-soft hover:bg-canvas"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={!canClear}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-sm font-medium text-ink-soft hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
          >
            <SquarePen className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">New conversation</span>
            <span className="sr-only sm:hidden">New conversation</span>
          </button>
        )}
      </div>
    </header>
  )
}
