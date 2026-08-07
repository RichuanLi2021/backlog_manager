import { useEffect, useState } from 'react'

import { formatDuration, formatSyncTime } from '../ndp'
import type { SyncStatus } from '../types'

interface Props {
  lastSync: string | null
  status: SyncStatus | null
  error: string | null
  warning?: string | null
  onClick: () => void
}

export default function UpdateButton({ lastSync, status, error, warning, onClick }: Props) {
  const running = status?.state === 'running'
  const [tick, setTick] = useState(0)

  // Local ticker so the estimate counts down between the 3s status polls.
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => setTick((t) => t + 1), 1000)
    return () => window.clearInterval(id)
  }, [running, status?.id])

  useEffect(() => {
    setTick(0)
  }, [status?.elapsed_seconds])

  const elapsed = (status?.elapsed_seconds ?? 0) + tick
  const estimate = status?.estimate_seconds ?? 0
  const remaining = Math.max(0, estimate - elapsed)

  return (
    <div className="update-block">
      <button className="primary" onClick={onClick} disabled={running}>
        {running ? 'Updating...' : 'Update from Jira'}
      </button>

      {running ? (
        <>
          <span className="muted timestamp">
            {remaining > 0
              ? `About ${formatDuration(remaining)} left (est. ${formatDuration(estimate)})`
              : `Taking longer than the usual ${formatDuration(estimate)}`}
          </span>
          <span className="muted timestamp">Runs in the background, you can keep working</span>
        </>
      ) : (
        <span className="muted timestamp">Last updated: {formatSyncTime(lastSync)}</span>
      )}

      {status?.state === 'failed' && (
        <span className="error timestamp">Sync failed: {status.message}</span>
      )}
      {!running && warning && <span className="error timestamp">{warning}</span>}
      {error && <span className="error timestamp">{error}</span>}
    </div>
  )
}
