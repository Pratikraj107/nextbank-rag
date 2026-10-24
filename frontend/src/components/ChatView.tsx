import { Landmark } from 'lucide-react'
import { useEffect, useRef } from 'react'

import type { Message } from '../types'
import { ChatMessage } from './ChatMessage'
import { MessageComposer } from './MessageComposer'
import { SuggestedQuestions } from './SuggestedQuestions'

function WelcomeState({ isLoading, onSend }: { isLoading: boolean; onSend: (question: string) => boolean }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10 sm:px-6 sm:py-14">
      <div className="space-y-4">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink text-white shadow-sm">
          <Landmark className="h-5 w-5" aria-hidden />
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-[28px]">
            Ask questions across loan documents.
            <span className="block text-muted">Get evidence-backed answers.</span>
          </h2>
          <p className="max-w-2xl text-[15px] leading-relaxed text-ink-soft">
            Ask a question about a loan or customer. NexaBank AI retrieves relevant documents and
            checks whether the evidence supports its response.
          </p>
        </div>
      </div>

      <SuggestedQuestions disabled={isLoading} onSelect={(question) => onSend(question)} />
    </div>
  )
}

interface ChatViewProps {
  messages: Message[]
  isLoading: boolean
  onSend: (question: string) => boolean
  onRetry: (id: string) => void
  onCitation: (messageId: string, index: number) => void
  onShowSources: (messageId: string) => void
}

export function ChatView({ messages, isLoading, onSend, onRetry, onCitation, onShowSources }: ChatViewProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const lastMessage = messages.at(-1)
  const scrollKey = lastMessage
    ? `${lastMessage.id}:${lastMessage.role === 'assistant' ? lastMessage.status : ''}`
    : ''

  // Keep the newest message in view as the conversation grows or a response arrives.
  useEffect(() => {
    if (scrollKey) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [scrollKey])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <WelcomeState isLoading={isLoading} onSend={onSend} />
        ) : (
          <div
            role="log"
            aria-live="polite"
            aria-label="Conversation"
            className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 py-8 sm:px-6"
          >
            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                isBusy={isLoading}
                onRetry={onRetry}
                onCitation={onCitation}
                onShowSources={onShowSources}
              />
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <div className="border-t border-line/70 bg-canvas/90 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl px-4 pt-3 pb-4 sm:px-6">
          <MessageComposer isLoading={isLoading} onSend={onSend} />
          <p className="mt-2 text-center text-xs text-muted">
            AI-generated responses are decision-support only. Verify critical information against
            the source documents.
          </p>
        </div>
      </div>
    </div>
  )
}
