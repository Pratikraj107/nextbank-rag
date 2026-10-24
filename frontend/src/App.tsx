import { useCallback, useMemo, useState } from 'react'

import { ChatView } from './components/ChatView'
import { Drawer } from './components/Drawer'
import { Sidebar } from './components/Sidebar'
import { SourcePanel } from './components/SourcePanel'
import { TopBar } from './components/TopBar'
import { useChat } from './hooks/useChat'
import { useHealth } from './hooks/useHealth'
import { useMediaQuery } from './hooks/useMediaQuery'
import type { AssistantMessage } from './types'

interface EvidenceSelection {
  messageId: string
  activeIndex: number | null
  /** Incremented on each selection so repeated clicks re-scroll. */
  token: number
}

export default function App() {
  const health = useHealth()
  const chat = useChat({ onConnectionProblem: health.recheck })
  const showsEvidenceColumn = useMediaQuery('(min-width: 1280px)')

  const [navigationOpen, setNavigationOpen] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [selection, setSelection] = useState<EvidenceSelection | null>(null)

  const completedAnswers = useMemo(
    () =>
      chat.messages.filter(
        (message): message is AssistantMessage =>
          message.role === 'assistant' && message.status === 'done',
      ),
    [chat.messages],
  )

  // Show the evidence the user selected, otherwise the most recent answer's.
  const latestAnswer = completedAnswers.at(-1) ?? null
  const evidenceMessage =
    completedAnswers.find((message) => message.id === selection?.messageId) ?? latestAnswer
  const activeIndex = evidenceMessage && selection?.messageId === evidenceMessage.id ? selection.activeIndex : null

  const selectEvidence = useCallback(
    (messageId: string, index: number | null) => {
      setSelection((previous) => ({ messageId, activeIndex: index, token: (previous?.token ?? 0) + 1 }))
      if (!showsEvidenceColumn) setEvidenceOpen(true)
    },
    [showsEvidenceColumn],
  )

  const handleSend = useCallback(
    (question: string) => {
      const accepted = chat.send(question)
      // A new answer should take over the evidence panel when it arrives.
      if (accepted) setSelection(null)
      return accepted
    },
    [chat],
  )

  const handleClear = useCallback(() => {
    chat.clear()
    setSelection(null)
    setEvidenceOpen(false)
  }, [chat])

  const closeNavigation = useCallback(() => setNavigationOpen(false), [])
  const closeEvidence = useCallback(() => setEvidenceOpen(false), [])

  const sourcePanelProps = {
    message: evidenceMessage,
    activeIndex,
    focusToken: selection?.token ?? 0,
    isUpdating: chat.isLoading,
  }

  return (
    <div className="flex h-full overflow-hidden">
      <aside className="hidden w-[256px] shrink-0 border-r border-line lg:block" aria-label="Sidebar">
        <Sidebar connection={health.status} onRetryConnection={health.recheck} />
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <TopBar
          connection={health.status}
          onRetryConnection={health.recheck}
          onOpenNavigation={() => setNavigationOpen(true)}
          onOpenEvidence={() => setEvidenceOpen(true)}
          evidenceCount={evidenceMessage?.response?.sources.length ?? 0}
          canClear={chat.messages.length > 0}
          onClear={handleClear}
        />
        <ChatView
          messages={chat.messages}
          isLoading={chat.isLoading}
          onSend={handleSend}
          onRetry={chat.retry}
          onCitation={selectEvidence}
          onShowSources={(messageId) => selectEvidence(messageId, null)}
        />
      </main>

      {showsEvidenceColumn && (
        <aside className="w-[328px] shrink-0 border-l border-line bg-white" aria-label="Evidence panel">
          <SourcePanel {...sourcePanelProps} />
        </aside>
      )}

      <Drawer open={navigationOpen} onClose={closeNavigation} side="left" label="Navigation">
        <Sidebar connection={health.status} onRetryConnection={health.recheck} onClose={closeNavigation} />
      </Drawer>

      <Drawer
        open={evidenceOpen && !showsEvidenceColumn}
        onClose={closeEvidence}
        side="right"
        label="Evidence"
      >
        <SourcePanel {...sourcePanelProps} onClose={closeEvidence} />
      </Drawer>
    </div>
  )
}
