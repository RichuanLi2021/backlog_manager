import { useCallback, useEffect, useRef, useState } from 'react'

import { getSyncStatus, refreshReport } from './api'
import type { SyncStatus } from './types'

const POLL_MS = 3000

/**
 * Watches the background Jira sync. A sync only ever starts from `start()`;
 * `onFinished` fires only for a job this component actually watched running, so
 * opening or switching reports never re-pulls data on its own.
 */
export function useSync(kind: string | undefined, onFinished?: () => void) {
  const [status, setStatus] = useState<SyncStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const watching = useRef(false)
  const finishedRef = useRef(onFinished)
  finishedRef.current = onFinished

  const poll = useCallback(async () => {
    try {
      const s = await getSyncStatus(kind)
      setStatus(s)
      if (s?.state === 'running') {
        watching.current = true
        timer.current = window.setTimeout(poll, POLL_MS)
      } else if (watching.current) {
        watching.current = false
        if (s?.state === 'done') finishedRef.current?.()
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }, [kind])

  useEffect(() => {
    poll()
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [poll])

  const start = useCallback(
    async (targetKind: string, quarter: string) => {
      setError(null)
      try {
        const s = await refreshReport(targetKind, quarter)
        setStatus(s)
        watching.current = true
        timer.current = window.setTimeout(poll, POLL_MS)
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [poll],
  )

  return { status, error, start, running: status?.state === 'running' }
}
