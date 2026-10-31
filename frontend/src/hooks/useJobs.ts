import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../lib/api'
import { getJob, isTerminal, listJobs, retryJob, type IngestionJob, type JobPage, type JobQuery } from '../lib/uploads'
import { describeLoadError } from './useDocuments'

// Refresh while something on screen is still queued or processing.
const ACTIVE_POLL_MS = 2500

const isAbort = (error: unknown) => error instanceof ApiError && error.kind === 'aborted'

interface Keyed<T> {
  key: string
  value: T | null
  error: string | null
}

/** One page of jobs; re-polls while any job on it is still running. */
export function useJobList(query: JobQuery) {
  const [tick, setTick] = useState(0)
  const [result, setResult] = useState<Keyed<JobPage> | null>(null)
  const { status, customerId, documentType, page, pageSize } = query
  const key = JSON.stringify([status, customerId, documentType, page, pageSize, tick])

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined

    listJobs({ status, customerId, documentType, page, pageSize }, controller.signal)
      .then((value) => {
        setResult({ key, value, error: null })
        if (value.items.some((job) => !isTerminal(job.status))) {
          timer = setTimeout(() => setTick((t) => t + 1), ACTIVE_POLL_MS)
        }
      })
      .catch((error: unknown) => {
        if (!isAbort(error)) {
          setResult((previous) => ({ key, value: previous?.value ?? null, error: describeLoadError(error) }))
        }
      })

    return () => {
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [key, status, customerId, documentType, page, pageSize])

  const refresh = useCallback(() => setTick((t) => t + 1), [])
  const current = result?.key === key

  return {
    data: result?.value ?? null,
    loading: !current,
    error: current ? (result?.error ?? null) : null,
    refresh,
  }
}

/** One job, kept up to date while it is running; supports retry. */
export function useJob(jobId: string | null, onChange?: () => void) {
  const [tick, setTick] = useState(0)
  const [result, setResult] = useState<Keyed<IngestionJob> | null>(null)
  const [retryError, setRetryError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const key = jobId ? `${jobId}#${tick}` : null

  useEffect(() => {
    if (!jobId || key === null) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined

    getJob(jobId, controller.signal)
      .then((value) => {
        setResult({ key, value, error: null })
        if (!isTerminal(value.status)) timer = setTimeout(() => setTick((t) => t + 1), ACTIVE_POLL_MS)
      })
      .catch((error: unknown) => {
        if (!isAbort(error)) setResult({ key, value: null, error: describeLoadError(error) })
      })

    return () => {
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [jobId, key])

  const retry = useCallback(() => {
    if (!jobId || retrying) return
    setRetrying(true)
    setRetryError(null)
    retryJob(jobId)
      .then(() => {
        setTick((t) => t + 1)
        onChange?.()
      })
      .catch((error: unknown) => setRetryError(describeLoadError(error)))
      .finally(() => setRetrying(false))
  }, [jobId, retrying, onChange])

  const sameJob = result !== null && jobId !== null && result.key.startsWith(`${jobId}#`)

  return {
    // Keep showing the last state of this job while the next poll loads.
    job: sameJob ? result.value : null,
    loading: !sameJob,
    error: result?.key === key ? result.error : null,
    retry,
    retrying,
    retryError,
  }
}
