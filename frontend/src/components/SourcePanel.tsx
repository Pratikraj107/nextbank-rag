import { FileSearch, LoaderCircle, X } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'

import { groupSources } from '../lib/sources'
import type { AssistantMessage } from '../types'
import { SourceCard } from './SourceCard'

interface SourcePanelProps {
  /** The completed assistant message whose evidence is shown. */
  message: AssistantMessage | null
  /** Index into that message's sources selected through a citation. */
  activeIndex: number | null
  /** Changes on every citation click so repeated clicks scroll again. */
  focusToken: number
  /** A newer question is still being answered. */
  isUpdating: boolean
  onClose?: () => void
}

function EmptyState({ children }: { children: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-line bg-canvas text-muted">
        <FileSearch className="h-5 w-5" aria-hidden />
      </div>
      <p className="max-w-[220px] text-sm leading-relaxed text-muted">{children}</p>
    </div>
  )
}

export function SourcePanel({ message, activeIndex, focusToken, isUpdating, onClose }: SourcePanelProps) {
  const response = message?.response ?? null
  const sources = useMemo(() => response?.sources ?? [], [response])
  const groups = useMemo(() => groupSources(sources), [sources])
  const showLabels = response?.search_mode === 'semantic'
  const cardRefs = useRef(new Map<string, HTMLLIElement>())

  const activeGroupKey =
    activeIndex === null
      ? null
      : (groups.find((group) => group.entries.some((entry) => entry.index === activeIndex))?.key ?? null)

  useEffect(() => {
    if (!activeGroupKey) return
    cardRefs.current.get(activeGroupKey)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeGroupKey, focusToken])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">Evidence</h2>
          <p className="mt-0.5 text-xs text-muted">
            {response
              ? `${sources.length} source ${sources.length === 1 ? 'entry' : 'entries'} · ${groups.length} ${
                  groups.length === 1 ? 'document' : 'documents'
                }`
              : 'Sources for the latest answer'}
          </p>
        </div>
        <div className="flex items-center gap-1">
          {isUpdating && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted" role="status">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
              Updating
            </span>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="-mr-1.5 rounded-lg p-1.5 text-muted hover:bg-canvas hover:text-ink"
              aria-label="Close evidence panel"
            >
              <X className="h-5 w-5" />
            </button>
          )}
        </div>
      </div>

      {!message || !response ? (
        <EmptyState>Evidence will appear here after your first question.</EmptyState>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <p className="mb-3 line-clamp-2 px-1 text-xs text-muted" title={message.question}>
            For: <span className="text-ink-soft">{message.question}</span>
          </p>

          {groups.length === 0 ? (
            <div className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-sm text-muted">
              No source entries were returned for this response.
            </div>
          ) : (
            <ul className="space-y-2.5">
              {groups.map((group) => (
                <SourceCard
                  key={group.key}
                  ref={(node) => {
                    if (node) cardRefs.current.set(group.key, node)
                    else cardRefs.current.delete(group.key)
                  }}
                  group={group}
                  showLabels={showLabels}
                  highlighted={group.key === activeGroupKey}
                  activeIndex={activeIndex}
                />
              ))}
            </ul>
          )}

          {showLabels && groups.length > 0 && (
            <p className="mt-4 px-1 text-[11px] leading-relaxed text-muted">
              Citation labels follow the order of the returned source entries. Several labels can
              point to different chunks of the same document.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
