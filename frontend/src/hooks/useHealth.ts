import { useCallback, useEffect, useRef, useState } from 'react'

import { checkHealth } from '../lib/api'
import type { ConnectionState } from '../types'

const POLL_INTERVAL_MS = 30_000

export interface HealthState {
  status: ConnectionState
  recheck: () => void
}

/** Track backend availability through real `GET /health` requests. */
export function useHealth(): HealthState {
  const [status, setStatus] = useState<ConnectionState>('checking')
  const controllerRef = useRef<AbortController | null>(null)

  const probe = useCallback(() => {
    controllerRef.current?.abort()

    const controller = new AbortController()
    controllerRef.current = controller

    checkHealth(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setStatus('connected')
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('disconnected')
      })
  }, [])

  // Explicit rechecks show a "Checking…" state; background polling does not.
  const recheck = useCallback(() => {
    setStatus('checking')
    probe()
  }, [probe])

  useEffect(() => {
    probe()
    const timer = setInterval(probe, POLL_INTERVAL_MS)

    return () => {
      clearInterval(timer)
      controllerRef.current?.abort()
    }
  }, [probe])

  return { status, recheck }
}
