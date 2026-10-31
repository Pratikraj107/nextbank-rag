import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../lib/api'
import { getJob, isTerminal, retryJob, uploadDocument, type IngestionJob } from '../lib/uploads'

const FAST_POLL_MS = 1000
const SLOW_POLL_MS = 2500
const FAST_POLLS = 30
const MAX_POLL_ERRORS = 5

export type UploadPhase = 'idle' | 'uploading' | 'tracking'

export interface UploadState {
  phase: UploadPhase
  /** Upload progress, 0–1, while phase is "uploading". */
  progress: number
  filename: string | null
  job: IngestionJob | null
  /** The same file was already uploaded for this customer and loan. */
  duplicate: boolean
  error: string | null
}

const INITIAL: UploadState = {
  phase: 'idle', progress: 0, filename: null, job: null, duplicate: false, error: null,
}

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'network') return 'Unable to reach the NexaBank API. Check that the backend is running.'
    if (error.kind === 'timeout') return 'The server took too long to respond.'
    return error.message
  }
  return 'Something went wrong during the upload.'
}

/**
 * Upload one document, then poll its ingestion job until it is ready or
 * failed. `onReady` runs once when a job reaches "ready".
 */
export function useUpload(onReady: (job: IngestionJob) => void) {
  const [state, setState] = useState<UploadState>(INITIAL)
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onReadyRef = useRef(onReady)

  useEffect(() => {
    onReadyRef.current = onReady
  }, [onReady])

  const stop = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  useEffect(() => stop, [stop])

  const track = useCallback(
    (job: IngestionJob) => {
      stop()
      const abort = new AbortController()
      controller.current = abort
      let polls = 0
      let errors = 0

      const settle = (current: IngestionJob) => {
        setState((previous) => ({ ...previous, phase: 'tracking', job: current, error: null }))
        if (current.status === 'ready') onReadyRef.current(current)
      }

      const schedule = () => {
        timer.current = setTimeout(poll, polls < FAST_POLLS ? FAST_POLL_MS : SLOW_POLL_MS)
      }

      const poll = () => {
        polls += 1
        getJob(job.jobId, abort.signal)
          .then((current) => {
            errors = 0
            if (isTerminal(current.status)) {
              settle(current)
            } else {
              setState((previous) => ({ ...previous, job: current, error: null }))
              schedule()
            }
          })
          .catch((error: unknown) => {
            if (error instanceof ApiError && error.kind === 'aborted') return
            errors += 1
            if (errors >= MAX_POLL_ERRORS) {
              setState((previous) => ({
                ...previous,
                error: `Lost contact while checking progress: ${message(error)}`,
              }))
              return
            }
            schedule()
          })
      }

      if (isTerminal(job.status)) settle(job)
      else schedule()
    },
    [stop],
  )

  const busy =
    state.phase === 'uploading' ||
    (state.phase === 'tracking' && state.job !== null && !isTerminal(state.job.status))

  const start = useCallback(
    (file: File, customerId: string, loanId: string | null) => {
      if (busy) return
      stop()
      const abort = new AbortController()
      controller.current = abort
      setState({ ...INITIAL, phase: 'uploading', filename: file.name })

      uploadDocument(
        file,
        customerId,
        loanId,
        (progress) => setState((previous) => ({ ...previous, progress })),
        abort.signal,
      )
        .then(({ job, duplicate }) => {
          setState((previous) => ({ ...previous, phase: 'tracking', progress: 1, job, duplicate }))
          track(job)
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.kind === 'aborted') return
          setState((previous) => ({ ...previous, phase: 'idle', error: message(error) }))
        })
    },
    [busy, stop, track],
  )

  const retry = useCallback(() => {
    const job = state.job
    if (!job || job.status !== 'failed') return
    setState((previous) => ({ ...previous, error: null }))
    retryJob(job.jobId)
      .then((current) => {
        setState((previous) => ({ ...previous, job: current }))
        track(current)
      })
      .catch((error: unknown) => setState((previous) => ({ ...previous, error: message(error) })))
  }, [state.job, track])

  /** Re-check a job after polling gave up because of connection errors. */
  const resume = useCallback(() => {
    if (state.job) track(state.job)
  }, [state.job, track])

  const reset = useCallback(() => {
    stop()
    setState(INITIAL)
  }, [stop])

  return { state, busy, start, retry, resume, reset }
}
