// Client for the NexaBank FastAPI backend (src/api/main.py).

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL
).replace(/\/+$/, '')

const HEALTH_TIMEOUT_MS = 5_000
// One question can run retrieval and several LLM calls (answer,
// evidence validation, and a possible retry), so allow plenty of time.
const CHAT_TIMEOUT_MS = 180_000
// Document browsing only reads cached data, so it should answer quickly.
const READ_TIMEOUT_MS = 15_000

// ------------------------------------------------------------
// Types mirroring the backend schema
// ------------------------------------------------------------

export interface ChatRequest {
  question: string
}

/** Mirrors `SourceResponse`. Optional fields are normalised to null. */
export interface ChatSource {
  source: string
  document_type: string | null
  customer_id: string | null
  loan_id: string | null
  chunk_index: number | null
}

/**
 * Mirrors `ChatResponse`. Fields the backend fails to send are
 * normalised to null so the UI never assumes a passing status.
 */
export interface ChatResponse {
  answer: string
  sources: ChatSource[]
  search_mode: string | null
  attempts: number | null
  basic_validation_passed: boolean | null
  evidence_validation_passed: boolean | null
}

export interface HealthResponse {
  status: string
  service: string | null
}

// ------------------------------------------------------------
// Errors
// ------------------------------------------------------------

export type ApiErrorKind = 'network' | 'timeout' | 'http' | 'malformed' | 'aborted'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number | null

  constructor(kind: ApiErrorKind, message: string, status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

// ------------------------------------------------------------
// Response parsing
// ------------------------------------------------------------

type JsonRecord = Record<string, unknown>

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

export function optionalNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function optionalBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

export function malformed(detail: string): ApiError {
  return new ApiError('malformed', `Malformed response from the assistant: ${detail}`)
}

function parseSource(value: unknown): ChatSource {
  if (!isRecord(value)) {
    throw malformed('a source entry is not an object.')
  }

  return {
    source: optionalString(value.source) ?? 'Unknown',
    document_type: optionalString(value.document_type),
    customer_id: optionalString(value.customer_id),
    loan_id: optionalString(value.loan_id),
    chunk_index: optionalNumber(value.chunk_index),
  }
}

export function parseChatResponse(value: unknown): ChatResponse {
  if (!isRecord(value)) {
    throw malformed('expected a JSON object.')
  }

  if (typeof value.answer !== 'string') {
    throw malformed('the "answer" field is missing.')
  }

  const rawSources = value.sources ?? []

  if (!Array.isArray(rawSources)) {
    throw malformed('the "sources" field is not a list.')
  }

  return {
    answer: value.answer,
    sources: rawSources.map(parseSource),
    search_mode: optionalString(value.search_mode),
    attempts: optionalNumber(value.attempts),
    basic_validation_passed: optionalBoolean(value.basic_validation_passed),
    evidence_validation_passed: optionalBoolean(value.evidence_validation_passed),
  }
}

// ------------------------------------------------------------
// Transport
// ------------------------------------------------------------

async function request(
  path: string,
  init: RequestInit,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<Response> {
  const controller = new AbortController()
  let timedOut = false

  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  const forwardAbort = () => controller.abort()
  signal?.addEventListener('abort', forwardAbort, { once: true })

  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
    })
  } catch {
    if (timedOut) {
      throw new ApiError('timeout', 'The request timed out.')
    }

    if (signal?.aborted) {
      throw new ApiError('aborted', 'The request was cancelled.')
    }

    throw new ApiError('network', 'The backend could not be reached.')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', forwardAbort)
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw malformed('the body is not valid JSON.')
  }
}

/** Build a user-safe message from a non-2xx response. */
interface ErrorWording {
  rejected: string
  failed: string
}

const CHAT_WORDING: ErrorWording = {
  rejected: 'The question was not accepted. Make sure it is between 1 and 2,000 characters.',
  failed: 'The assistant returned an error',
}

const READ_WORDING: ErrorWording = {
  rejected: 'The request was not accepted. Check the search and filter values.',
  failed: 'The server returned an error',
}

async function httpError(response: Response, wording: ErrorWording = CHAT_WORDING): Promise<ApiError> {
  let detail: unknown = null

  try {
    const body: unknown = await response.json()
    detail = isRecord(body) ? body.detail : null
  } catch {
    // Non-JSON error bodies are not shown to the user.
  }

  if (response.status === 422) {
    return new ApiError('http', wording.rejected, response.status)
  }

  // FastAPI's own `detail` strings are short and user-facing; anything
  // else (objects, long traces) is replaced with a generic message.
  if (typeof detail === 'string' && detail.length <= 300) {
    return new ApiError('http', detail, response.status)
  }

  return new ApiError(
    'http',
    `${wording.failed} (HTTP ${response.status}).`,
    response.status,
  )
}

// ------------------------------------------------------------
// Endpoints
// ------------------------------------------------------------

export async function checkHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await request('/health', { method: 'GET' }, HEALTH_TIMEOUT_MS, signal)

  if (!response.ok) {
    throw await httpError(response)
  }

  const body = await readJson(response)

  if (!isRecord(body) || body.status !== 'ok') {
    throw malformed('the health check did not report status "ok".')
  }

  return {
    status: body.status,
    service: optionalString(body.service),
  }
}

export async function sendChat(question: string, signal?: AbortSignal): Promise<ChatResponse> {
  const payload: ChatRequest = { question }

  const response = await request(
    '/api/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    CHAT_TIMEOUT_MS,
    signal,
  )

  if (!response.ok) {
    throw await httpError(response)
  }

  return parseChatResponse(await readJson(response))
}

/** GET a JSON resource; throws ApiError on network, HTTP or parse failure. */
export async function getJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await request(path, { method: 'GET' }, READ_TIMEOUT_MS, signal)

  if (!response.ok) {
    throw await httpError(response, READ_WORDING)
  }

  return readJson(response)
}

/** POST without a body (e.g. to trigger an action); returns the JSON response. */
export async function postJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await request(path, { method: 'POST' }, READ_TIMEOUT_MS, signal)

  if (!response.ok) {
    throw await httpError(response, READ_WORDING)
  }

  return readJson(response)
}
