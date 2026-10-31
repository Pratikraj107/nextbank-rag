import type { LucideIcon } from 'lucide-react'
import { Activity, FolderSearch, Landmark, MessageSquareText, ShieldCheck, X } from 'lucide-react'

import type { ConnectionState, View } from '../types'
import { ConnectionStatus } from './ConnectionStatus'

interface NavItem {
  label: string
  icon: LucideIcon
  /** Views that exist; items without one are placeholders. */
  view?: View
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Assistant', icon: MessageSquareText, view: 'assistant' },
  { label: 'Document Explorer', icon: FolderSearch, view: 'documents' },
  { label: 'Activity', icon: Activity, view: 'activity' },
]

interface SidebarProps {
  connection: ConnectionState
  onRetryConnection: () => void
  activeView: View
  onNavigate: (view: View) => void
  /** Present when the sidebar is rendered inside a drawer. */
  onClose?: () => void
}

export function Sidebar({ connection, onRetryConnection, activeView, onNavigate, onClose }: SidebarProps) {
  return (
    <div className="flex h-full w-full flex-col bg-white">
      <div className="flex items-center justify-between gap-3 px-5 pt-5 pb-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-ink text-white shadow-sm">
            <Landmark className="h-[18px] w-[18px]" aria-hidden />
          </div>
          <div className="leading-tight">
            <p className="text-[15px] font-semibold tracking-tight text-ink">NexaBank AI</p>
            <p className="text-xs text-muted">Loan Intelligence</p>
          </div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted hover:bg-canvas hover:text-ink"
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      <nav aria-label="Main" className="px-3">
        <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Workspace
        </p>
        <ul className="space-y-0.5">
          {NAV_ITEMS.map(({ label, icon: Icon, view }) => (
            <li key={label}>
              {!view ? (
                <span
                  aria-disabled="true"
                  title="Not available yet"
                  className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted/80"
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  <span className="flex-1">{label}</span>
                  <span className="rounded-md border border-line px-1.5 py-px text-[10px] font-medium uppercase tracking-wide">
                    Soon
                  </span>
                </span>
              ) : (
                <button
                  type="button"
                  aria-current={activeView === view ? 'page' : undefined}
                  onClick={() => onNavigate(view)}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors ${
                    activeView === view ? 'bg-accent-soft text-accent' : 'text-ink-soft hover:bg-canvas'
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  {label}
                </button>
              )}
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-auto space-y-3 px-4 pb-4">
        <div className="rounded-xl border border-line p-3.5">
          <div className="mb-1.5 flex items-center gap-2 text-sm font-semibold text-ink">
            <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
            Evidence-grounded
          </div>
          <p className="text-xs leading-relaxed text-muted">
            Answers are generated from the loan documents available to the assistant and checked
            against the retrieved evidence. Always verify critical details in the source documents.
          </p>
        </div>

        <ConnectionStatus status={connection} onRetry={onRetryConnection} variant="card" />

        <p className="px-1 pt-1 text-[11px] font-medium uppercase tracking-wider text-muted/80">
          Internal Research Environment
        </p>
      </div>
    </div>
  )
}
