import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { addQuarter, deleteQuarter, listQuarters, listReports, nextQuarter } from '../api'
import UpdateButton from '../components/UpdateButton'
import { formatSyncTime } from '../ndp'
import type { ReportInfo } from '../types'
import { useSync } from '../useSync'

const DESCRIPTIONS: Record<string, string> = {
  AR_GL: 'Comprehensive: NA + LAC, AR + GL',
  AR: 'AR only: NA_AR, LAC_AR',
  GL: 'GL only: NA_GL, LAC_GL',
}

// Sentinel value for the extra <option>; never a real quarter name.
const ADD = '__add__'

export default function ReportsPage() {
  const [quarters, setQuarters] = useState<string[]>([])
  const [quarter, setQuarter] = useState('')
  const [reports, setReports] = useState<ReportInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  const [adding, setAdding] = useState<string | null>(null)
  const [addError, setAddError] = useState<string | null>(null)
  const [working, setWorking] = useState(false)

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

  const create = async () => {
    const name = (adding ?? '').trim()
    if (!name) return
    setWorking(true)
    setAddError(null)
    try {
      setQuarters(await addQuarter(name))
      setQuarter(name.toUpperCase())
      setAdding(null)
    } catch (e) {
      setAddError((e as Error).message)
    } finally {
      setWorking(false)
    }
  }

  const remove = async () => {
    if (!window.confirm(`Remove ${quarter}? It holds no backlogs and no saves.`)) return
    setError(null)
    try {
      const left = await deleteQuarter(quarter)
      setQuarters(left)
      setQuarter(left[0] ?? '')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Only an untouched quarter can be taken back off the list, which is the way out
  // of a mistyped name before anything has been synced into it.
  const empty = reports.length > 0 && reports.every((r) => r.item_count === 0)
  const removable = empty && quarters.length > 1

  return (
    <div className="page">
      <div className="toolbar">
        <label>
          Quarter{' '}
          <select
            value={quarter}
            onChange={(e) => {
              if (e.target.value === ADD) {
                setAdding(nextQuarter(quarter) || '')
                setAddError(null)
              } else {
                setQuarter(e.target.value)
              }
            }}
          >
            {quarters.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
            <option value={ADD}>+ Add quarter...</option>
          </select>
        </label>
        {removable && (
          <button onClick={remove} title={`${quarter} is empty, so it can be removed`}>
            Remove {quarter}
          </button>
        )}
        <div className="spacer" />
        <UpdateButton
          lastSync={reports.find((r) => r.last_jira_sync_at)?.last_jira_sync_at ?? null}
          status={sync.status}
          error={sync.error}
          onClick={() => sync.start('ALL', quarter)}
        />
      </div>

      {error && <div className="error">{error}</div>}

      {empty && (
        <div className="notice">
          {quarter} is open but empty. Press <strong>Update from Jira</strong> to pull the{' '}
          {quarter} backlogs into all three reports.
        </div>
      )}

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

      {adding !== null && (
        <div className="modal-backdrop" onClick={() => setAdding(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Add a quarter</h3>
            <p className="muted">
              Opens {quarter ? `the quarter after ${quarter}` : 'a new quarter'} with the
              same AR + GL, AR and GL reports, all empty. The name is used as-is in the
              Jira query, so write it the way Request Qtr and the LAC labels are written.
            </p>
            <input
              autoFocus
              value={adding}
              placeholder="2026Q4"
              onChange={(e) => setAdding(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') create()
                if (e.key === 'Escape') setAdding(null)
              }}
            />
            {addError && <div className="error">{addError}</div>}
            <div className="modal-actions">
              <button onClick={() => setAdding(null)}>Cancel</button>
              <button
                className="primary"
                onClick={create}
                disabled={working || !adding.trim()}
              >
                {working ? 'Adding...' : 'Add quarter'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
