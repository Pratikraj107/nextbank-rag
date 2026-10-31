import { useCallback, useEffect, useMemo, useState } from 'react'

import { ActivityCenter } from './components/activity/ActivityCenter'
import { ChatView } from './components/ChatView'
import { DocumentExplorer } from './components/documents/DocumentExplorer'
import { Drawer } from './components/Drawer'
import { Sidebar } from './components/Sidebar'
import { SourcePanel } from './components/SourcePanel'
import { TopBar } from './components/TopBar'
import { useChat } from './hooks/useChat'
import { useHealth } from './hooks/useHealth'
import { useMediaQuery } from './hooks/useMediaQuery'
import type { AssistantMessage, ComposerDraft, View } from './types'

interface Location {
  view: View
  documentId: string | null
  jobId: string | null
}

// The current view (and selected document or job) live in the URL hash, so a
// refresh or a shared link reopens the same place:
//   #/documents?doc=doc_…    #/activity?job=<32 hex characters>
function readLocation(): Location {
  const hash = window.location.hash
  const params = new URLSearchParams(hash.split('?')[1] ?? '')
  if (hash.startsWith('#/documents')) {
    const documentId = params.get('doc')
    return { view: 'documents', documentId: documentId && /^doc_[0-9a-f]{16}$/.test(documentId) ? documentId : null, jobId: null }
  }
  if (hash.startsWith('#/activity')) {
    const jobId = params.get('job')
    return { view: 'activity', documentId: null, jobId: jobId && /^[0-9a-f]{32}$/.test(jobId) ? jobId : null }
  }
  return { view: 'assistant', documentId: null, jobId: null }
}

function writeLocation(location: Location, replace: boolean) {
  const hash =
    location.view === 'documents'
      ? `#/documents${location.documentId ? `?doc=${location.documentId}` : ''}`
      : location.view === 'activity'
        ? `#/activity${location.jobId ? `?job=${location.jobId}` : ''}`
        : '#/'
  if (hash === window.location.hash) return
  if (replace) window.history.replaceState(null, '', hash)
  else window.history.pushState(null, '', hash)
}

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

  const [location, setLocation] = useState<Location>(readLocation)
  const [draft, setDraft] = useState<ComposerDraft | null>(null)
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

  // Back/forward buttons.
  useEffect(() => {
    const onPopState = () => setLocation(readLocation())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = useCallback((view: View) => {
    setNavigationOpen(false)
    setLocation((current) => {
      const next = {
        view,
        documentId: view === 'documents' ? current.documentId : null,
        jobId: view === 'activity' ? current.jobId : null,
      }
      writeLocation(next, false)
      return next
    })
  }, [])

  const selectDocument = useCallback((documentId: string | null) => {
    const next: Location = { view: 'documents', documentId, jobId: null }
    writeLocation(next, true)
    setLocation(next)
  }, [])

  const selectJob = useCallback((jobId: string | null) => {
    const next: Location = { view: 'activity', documentId: null, jobId }
    writeLocation(next, true)
    setLocation(next)
  }, [])

  // From a job to its document: a new history entry, so Back returns to the job.
  const openDocumentFromJob = useCallback((documentId: string) => {
    const next: Location = { view: 'documents', documentId, jobId: null }
    writeLocation(next, false)
    setLocation(next)
  }, [])

  // "Ask about this document": switch to the chat with an editable question.
  const askAboutDocument = useCallback(
    (question: string) => {
      setDraft((previous) => ({ text: question, nonce: (previous?.nonce ?? 0) + 1 }))
      navigate('assistant')
    },
    [navigate],
  )

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
        <Sidebar
          connection={health.status}
          onRetryConnection={health.recheck}
          activeView={location.view}
          onNavigate={navigate}
        />
      </aside>

      {location.view === 'activity' ? (
        <main className="flex min-w-0 flex-1">
          <ActivityCenter
            selectedJobId={location.jobId}
            onSelectJob={selectJob}
            onOpenDocument={openDocumentFromJob}
            onGoToDocuments={() => navigate('documents')}
            onOpenNavigation={() => setNavigationOpen(true)}
          />
        </main>
      ) : location.view === 'documents' ? (
        <main className="flex min-w-0 flex-1">
          <DocumentExplorer
            selectedId={location.documentId}
            onSelect={selectDocument}
            onAsk={askAboutDocument}
            onOpenNavigation={() => setNavigationOpen(true)}
          />
        </main>
      ) : (
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
          draft={draft}
        />
      </main>
      )}

      {location.view === 'assistant' && showsEvidenceColumn && (
        <aside className="w-[328px] shrink-0 border-l border-line bg-white" aria-label="Evidence panel">
          <SourcePanel {...sourcePanelProps} />
        </aside>
      )}

      <Drawer open={navigationOpen} onClose={closeNavigation} side="left" label="Navigation">
        <Sidebar
          connection={health.status}
          onRetryConnection={health.recheck}
          activeView={location.view}
          onNavigate={navigate}
          onClose={closeNavigation}
        />
      </Drawer>

      <Drawer
        open={location.view === 'assistant' && evidenceOpen && !showsEvidenceColumn}
        onClose={closeEvidence}
        side="right"
        label="Evidence"
      >
        <SourcePanel {...sourcePanelProps} onClose={closeEvidence} />
      </Drawer>
    </div>
  )
}
