import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listQuarters, listReports } from '../api'
import UpdateButton from '../components/UpdateButton'
import { formatSyncTime } from '../ndp'
import type { ReportInfo } from '../types'
import { useSync } from '../useSync'

const DESCRIPTIONS: Record<string, string> = {
  AR_GL: 'Comprehensive: NA + LAC, AR + GL',
  AR: 'AR only: NA_AR, LAC_AR',
  GL: 'GL only: NA_GL, LAC_GL',
}

export default function ReportsPage() {
  const [quarters, setQuarters] = useState<string[]>([])
  const [quarter, setQuarter] = useState('')
  const [reports, setReports] = useState<ReportInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (q: string) => {
    if (!q) return
    try {
      setReports(await listReports(q))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  const sync = useSync(undefined, () => load(quarter))

  useEffect(() => {
    listQuarters()
      .then((qs) => {
        setQuarters(qs)
        setQuarter((current) => current || qs[0] || '')
      })
      .catch((e) => setError((e as Error).message))
  }, [])

  useEffect(() => {
    load(quarter)
  }, [quarter, load])

  return (
    <div className="page">
      <div className="toolbar">
        <label>
          Quarter{' '}
          <select value={quarter} onChange={(e) => setQuarter(e.target.value)}>
            {quarters.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        <UpdateButton
          lastSync={reports.find((r) => r.last_jira_sync_at)?.last_jira_sync_at ?? null}
          status={sync.status}
          error={sync.error}
          onClick={() => sync.start('ALL', quarter)}
        />
      </div>

      {error && <div className="error">{error}</div>}

      <div className="report-picker">
        {reports.map((r) => (
          <div className="card report-card" key={r.kind}>
            <h2>{r.kind.replace('_', ' + ')}</h2>
            <div className="meta">{DESCRIPTIONS[r.kind]}</div>
            <div className="meta">
              {r.item_count} rows &middot; updated {formatSyncTime(r.last_jira_sync_at)}
            </div>
            {r.last_sync_status === 'failed' && (
              <div className="error">{r.last_sync_error}</div>
            )}
            <div className="actions">
              <Link to={`/reports/${r.kind}/${r.quarter}`}>
                <button>Open table</button>
              </Link>
              <Link to={`/reports/${r.kind}/${r.quarter}/tree`}>
                <button>Tree view</button>
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
