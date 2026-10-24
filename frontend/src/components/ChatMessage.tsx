import { CircleAlert, Landmark, RotateCw, TriangleAlert, WifiOff } from 'lucide-react'

import type { ChatResponse } from '../lib/api'
import type { AssistantMessage, Message } from '../types'
import { AnswerText } from './AnswerText'
import { ValidationStatus } from './ValidationStatus'

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/** Notice shown above answers that need extra care. The answer itself is never hidden. */
function ResponseNotice({ response }: { response: ChatResponse }) {
  if (response.search_mode === 'conflict') {
    return (
      <div className="flex gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>
          <span className="font-semibold">Identifier conflict.</span> The customer and loan
          identifiers in the question do not match. Verify them before relying on any result.
        </p>
      </div>
    )
  }

  if (response.search_mode !== 'exact' && response.evidence_validation_passed !== true) {
    return (
      <div className="flex gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>
          <span className="font-semibold">Requires review.</span>{' '}
          {response.evidence_validation_passed === false
            ? 'This response could not be verified against the retrieved evidence.'
            : 'The backend did not report an evidence validation result.'}{' '}
          Check the source documents before relying on it.
        </p>
      </div>
    )
  }

  return null
}

function AssistantAvatar() {
  return (
    <div
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-line bg-white text-ink shadow-sm"
    >
      <Landmark className="h-4 w-4" />
    </div>
  )
}

interface AssistantBodyProps {
  message: AssistantMessage
  isBusy: boolean
  onRetry: (id: string) => void
  onCitation: (messageId: string, index: number) => void
  onShowSources: (messageId: string) => void
}

function AssistantBody({ message, isBusy, onRetry, onCitation, onShowSources }: AssistantBodyProps) {
  if (message.status === 'loading') {
    return (
      <div role="status" className="flex items-center gap-3 py-1.5 text-sm text-muted">
        <span className="flex items-center gap-1" aria-hidden>
          {[0, 1, 2].map((dot) => (
            <span
              key={dot}
              className="typing-dot h-1.5 w-1.5 rounded-full bg-accent"
              style={{ animationDelay: `${dot * 0.15}s` }}
            />
          ))}
        </span>
        Searching documents and validating evidence…
      </div>
    )
  }

  if (message.status === 'error') {
    const unreachable = message.errorKind === 'network' || message.errorKind === 'timeout'
    const Icon = unreachable ? WifiOff : CircleAlert

    return (
      <div role="alert" className="rounded-xl border border-red-200 bg-red-50/70 px-4 py-3">
        <div className="flex gap-2.5">
          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden />
          <div className="min-w-0 space-y-2.5">
            <p className="text-sm text-red-900">{message.error}</p>
            <button
              type="button"
              onClick={() => onRetry(message.id)}
              disabled={isBusy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-sm font-medium text-red-800 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCw className="h-3.5 w-3.5" aria-hidden />
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  const response = message.response

  if (!response) return null

  return (
    <div className="space-y-3">
      <ResponseNotice response={response} />
      <AnswerText
        text={response.answer || 'The assistant returned an empty answer.'}
        sourceCount={response.sources.length}
        onCitation={(index) => onCitation(message.id, index)}
      />
      <ValidationStatus response={response} onShowSources={() => onShowSources(message.id)} />
    </div>
  )
}

interface ChatMessageProps {
  message: Message
  isBusy: boolean
  onRetry: (id: string) => void
  onCitation: (messageId: string, index: number) => void
  onShowSources: (messageId: string) => void
}

export function ChatMessage({ message, ...handlers }: ChatMessageProps) {
  if (message.role === 'user') {
    return (
      <article aria-label="Your question" className="flex justify-end">
        <div
          className="max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-white shadow-sm [overflow-wrap:anywhere] sm:max-w-[75%]"
          title={formatTime(message.createdAt)}
        >
          {message.content}
        </div>
      </article>
    )
  }

  return (
    <article aria-label="Assistant response" className="flex gap-3">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 pt-1">
        <p className="mb-1.5 text-xs font-medium text-muted">
          NexaBank AI
          {message.status === 'done' && (
            <span className="font-normal"> · {formatTime(message.createdAt)}</span>
          )}
        </p>
        <AssistantBody message={message} {...handlers} />
      </div>
    </article>
  )
}
