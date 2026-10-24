import { useCallback, useRef, useState } from 'react'

import { ApiError, sendChat } from '../lib/api'
import type { AssistantMessage, Message } from '../types'

const UNREACHABLE_MESSAGE =
  'Unable to reach the NexaBank assistant. Check that the backend is running and try again.'

function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return 'Something went wrong while contacting the assistant. Try again.'
  }

  switch (error.kind) {
    case 'network':
      return UNREACHABLE_MESSAGE
    case 'timeout':
      return 'The assistant took too long to respond, so the request was stopped. Try again.'
    case 'malformed':
      return 'The assistant returned a response this app could not read. Try again or check the backend logs.'
    default:
      return error.message
  }
}

interface UseChatOptions {
  /** Called when a request fails in a way that suggests the backend is down. */
  onConnectionProblem: () => void
}

export interface ChatState {
  messages: Message[]
  isLoading: boolean
  send: (question: string) => boolean
  retry: (assistantId: string) => void
  clear: () => void
}

export function useChat({ onConnectionProblem }: UseChatOptions): ChatState {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const inFlightRef = useRef<AbortController | null>(null)

  const updateAssistant = useCallback(
    (id: string, patch: Partial<AssistantMessage>) => {
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id && message.role === 'assistant'
            ? { ...message, ...patch }
            : message,
        ),
      )
    },
    [],
  )

  const run = useCallback(
    async (assistantId: string, question: string) => {
      const controller = new AbortController()
      inFlightRef.current = controller
      setIsLoading(true)

      try {
        const response = await sendChat(question, controller.signal)
        updateAssistant(assistantId, { status: 'done', response, error: null, errorKind: null })
      } catch (error) {
        if (error instanceof ApiError && error.kind === 'aborted') return

        if (error instanceof ApiError && (error.kind === 'network' || error.kind === 'timeout')) {
          onConnectionProblem()
        }

        updateAssistant(assistantId, {
          status: 'error',
          response: null,
          error: describeError(error),
          errorKind: error instanceof ApiError ? error.kind : null,
        })
      } finally {
        if (inFlightRef.current === controller) {
          inFlightRef.current = null
          setIsLoading(false)
        }
      }
    },
    [onConnectionProblem, updateAssistant],
  )

  const send = useCallback(
    (rawQuestion: string): boolean => {
      const question = rawQuestion.trim()

      // Reject empty questions and duplicate submissions.
      if (!question || inFlightRef.current) return false

      const now = Date.now()
      const assistantId = crypto.randomUUID()

      setMessages((previous) => [
        ...previous,
        { id: crypto.randomUUID(), role: 'user', content: question, createdAt: now },
        {
          id: assistantId,
          role: 'assistant',
          question,
          status: 'loading',
          response: null,
          error: null,
          errorKind: null,
          createdAt: now,
        },
      ])

      void run(assistantId, question)
      return true
    },
    [run],
  )

  const retry = useCallback(
    (assistantId: string) => {
      if (inFlightRef.current) return

      const target = messages.find(
        (message): message is AssistantMessage =>
          message.id === assistantId && message.role === 'assistant',
      )

      if (!target) return

      updateAssistant(assistantId, { status: 'loading', error: null, errorKind: null })
      void run(assistantId, target.question)
    },
    [messages, run, updateAssistant],
  )

  const clear = useCallback(() => {
    inFlightRef.current?.abort()
    inFlightRef.current = null
    setIsLoading(false)
    setMessages([])
  }, [])

  return { messages, isLoading, send, retry, clear }
}
