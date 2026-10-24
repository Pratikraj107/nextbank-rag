import type { ApiErrorKind, ChatResponse } from './lib/api'

export interface UserMessage {
  id: string
  role: 'user'
  content: string
  createdAt: number
}

export type AssistantStatus = 'loading' | 'done' | 'error'

export interface AssistantMessage {
  id: string
  role: 'assistant'
  /** The question this message answers, kept so it can be retried. */
  question: string
  status: AssistantStatus
  response: ChatResponse | null
  error: string | null
  errorKind: ApiErrorKind | null
  createdAt: number
}

export type Message = UserMessage | AssistantMessage

export type ConnectionState = 'checking' | 'connected' | 'disconnected'
