import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../lib/api'
import {
  getDocument,
  getDocumentChunks,
  listDocuments,
  type DocumentChunk,
  type DocumentDetail,
  type DocumentPage,
  type DocumentQuery,
} from '../lib/documents'

const SEARCH_DEBOUNCE_MS = 300

export function describeLoadError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'network') {
      return 'Unable to reach the NexaBank API. Check that the backend is running.'
    }
    if (error.kind === 'timeout') return 'The request took too long. Try again.'
    if (error.status === 404) return 'This document no longer exists in the library.'
    return error.message
  }
  return 'Something went wrong while loading documents.'
}

const isAbort = (error: unknown) => error instanceof ApiError && error.kind === 'aborted'

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}

/**
 * Results are stored with the key of the request that produced them.
 * "Loading" is derived (no result for the current key yet), and a late
 * response for an old key can never be shown for a newer request.
 */
interface Keyed<T> {
  key: string
  value: T | null
  error: string | null
}

/** Load one page of documents; superseded requests are aborted. */
export function useDocumentList(query: DocumentQuery) {
  const search = useDebounced(query.search, SEARCH_DEBOUNCE_MS)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Keyed<DocumentPage> | null>(null)

  const { documentType, customerId, loanId, page, pageSize } = query
  const key = JSON.stringify([search, documentType, customerId, loanId, page, pageSize, attempt])

  useEffect(() => {
    const controller = new AbortController()

    listDocuments({ search, documentType, customerId, loanId, page, pageSize }, controller.signal)
      .then((value) => setResult({ key, value, error: null }))
      .catch((error: unknown) => {
        if (isAbort(error)) return
        // Keep the previous page visible behind the error.
        setResult((previous) => ({ key, value: previous?.value ?? null, error: describeLoadError(error) }))
      })

    return () => controller.abort()
  }, [key, search, documentType, customerId, loanId, page, pageSize])

  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  const current = result?.key === key

  return {
    // The last loaded page stays visible while the next one loads.
    data: result?.value ?? null,
    loading: !current,
    error: current ? (result?.error ?? null) : null,
    retry,
    searchPending: search !== query.search,
  }
}

interface Loadable<T> {
  value: T | null
  loading: boolean
  error: string | null
}

function useKeyedLoad<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
): Loadable<T> {
  const [result, setResult] = useState<Keyed<T> | null>(null)

  useEffect(() => {
    if (key === null) return
    const controller = new AbortController()

    load(controller.signal)
      .then((value) => setResult({ key, value, error: null }))
      .catch((error: unknown) => {
        if (!isAbort(error)) setResult({ key, value: null, error: describeLoadError(error) })
      })

    return () => controller.abort()
  }, [key, load])

  if (key === null) return { value: null, loading: false, error: null }
  if (result?.key !== key) return { value: null, loading: true, error: null }
  return { value: result.value, loading: false, error: result.error }
}

/** Load a document and its chunks in parallel; switching documents aborts the old requests. */
export function useDocumentDetail(documentId: string | null) {
  const [attempt, setAttempt] = useState(0)
  const key = documentId ? `${documentId}#${attempt}` : null

  // Stable loaders, so the requests re-run only when the key changes.
  const loadDetail = useCallback(
    (signal: AbortSignal) => getDocument(documentId as string, signal),
    [documentId],
  )
  const loadChunks = useCallback(
    (signal: AbortSignal) => getDocumentChunks(documentId as string, signal),
    [documentId],
  )

  const detail = useKeyedLoad<DocumentDetail>(key, loadDetail)
  const chunks = useKeyedLoad<DocumentChunk[]>(key, loadChunks)

  const retry = useCallback(() => setAttempt((value) => value + 1), [])

  return { detail, chunks, retry }
}
