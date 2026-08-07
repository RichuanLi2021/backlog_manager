import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { getTree } from '../api'
import { NDP_LEGEND, ndpStatusClass } from '../ndp'
import type { TreeNdp, TreeRelease, TreeSheet } from '../types'

const ALL = 'ALL'
const NO_STATUS = 'N/A'

// Statuses the team watches most, in the order they appear on the deploy plan.
// Anything Jira returns outside this list is appended alphabetically.
const STATUS_ORDER = [
  'Open',
  'In Progress',
  'IT Leader Approved',
  'IT Exec Approved',
  'IIC Approved',
  'QC Approved',
  'Verified',
  'Closed',
  NO_STATUS,
]

function statusOf(ndp: TreeNdp): string {
  return ndp.status?.trim() || NO_STATUS
}

function statusRank(status: string): number {
  const index = STATUS_ORDER.indexOf(status)
  return index === -1 ? STATUS_ORDER.length : index
}

function filterReleases(releases: TreeRelease[], status: string): TreeRelease[] {
  if (status === ALL) return releases
  return releases
    .map((r) => ({ ...r, ndps: r.ndps.filter((n) => statusOf(n) === status) }))
    .filter((r) => r.ndps.length > 0)
}

function ReleaseNode({ release }: { release: TreeRelease }) {
  const [open, setOpen] = useState(true)
  const backlogCount = release.ndps.reduce((n, d) => n + d.backlogs.length, 0)

  return (
    <div className="tree-node">
      <div className="tree-row" onClick={() => setOpen(!open)}>
        <span className="toggle">{open ? '\u25be' : '\u25b8'}</span>
        <span className="key">{release.release}</span>
        <span className="title">{release.title}</span>
        <span className="badge">
          {release.ndps.length} NDP / {backlogCount} backlog
        </span>
      </div>
      {open && release.ndps.map((ndp) => <NdpNode key={ndp.ndp} ndp={ndp} />)}
    </div>
  )
}

function NdpNode({ ndp }: { ndp: TreeNdp }) {
  const [open, setOpen] = useState(true)

  return (
    <div className="tree-node">
      <div className="tree-row" onClick={() => setOpen(!open)}>
        <span className="toggle">{open ? '\u25be' : '\u25b8'}</span>
        <span className="key">{ndp.ndp}</span>
        <span className={`badge ${ndpStatusClass(ndp.status)}`}>{statusOf(ndp)}</span>
        <span className="muted">{ndp.deploy_date}</span>
      </div>
      {open &&
        ndp.backlogs.map((b) => (
          <div className="tree-node" key={b.id}>
            <div className="tree-row">
              <span className="toggle" />
              <span className="key">{b.key}</span>
              <span className="title">{b.summary}</span>
              <span className="badge">{b.status}</span>
              <span className="muted">
                {b.developer || b.assignee} &middot; {b.spent_h}/{b.est_h}h
              </span>
            </div>
          </div>
        ))}
    </div>
  )
}

export default function TreePage() {
  const { kind = '', quarter = '' } = useParams()
  const [sheets, setSheets] = useState<TreeSheet[]>([])
  const [active, setActive] = useState('')
  const [status, setStatus] = useState(ALL)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getTree(kind, quarter)
      .then((data) => {
        setSheets(data)
        setActive((current) =>
          current && data.some((s) => s.sheet === current) ? current : (data[0]?.sheet ?? ''),
        )
      })
      .catch((e) => setError((e as Error).message))
  }, [kind, quarter])

  const sheet = sheets.find((s) => s.sheet === active)

  // Tabs stay stable across sheets; the counts follow the sheet you are on.
  const statuses = useMemo(() => {
    const seen = new Set<string>()
    sheets.forEach((s) => s.releases.forEach((r) => r.ndps.forEach((n) => seen.add(statusOf(n)))))
    return [...seen].sort((a, b) => statusRank(a) - statusRank(b) || a.localeCompare(b))
  }, [sheets])

  const counts = useMemo(() => {
    const map = new Map<string, number>()
    sheet?.releases.forEach((r) =>
      r.ndps.forEach((n) => {
        const key = statusOf(n)
        map.set(key, (map.get(key) ?? 0) + 1)
      }),
    )
    return map
  }, [sheet])

  const releases = useMemo(
    () => filterReleases(sheet?.releases ?? [], status),
    [sheet, status],
  )

  const totalNdps = [...counts.values()].reduce((a, b) => a + b, 0)

  return (
    <div className="page">
      <div className="toolbar">
        <strong>
          {kind.replace('_', ' + ')} &middot; {quarter} &middot; RELEASE &rarr; NDP &rarr; Backlog
        </strong>
        <div className="legend">
          {NDP_LEGEND.map((l) => (
            <span key={l.label}>
              <span className={`swatch ${l.cls}`} />
              {l.label}
            </span>
          ))}
        </div>
        <div className="spacer" />
        <span className="muted">Read-only status tracker on live Jira data</span>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="tabs sheet-tabs">
        {sheets.map((s) => (
          <button
            key={s.sheet}
            className={`tab ${s.sheet === active ? 'active' : ''}`}
            onClick={() => setActive(s.sheet)}
          >
            {s.sheet}
            <span className="count">{s.releases.length}</span>
          </button>
        ))}
      </div>

      <div className="tabs status-tabs">
        <button
          className={`tab ${status === ALL ? 'active' : ''}`}
          onClick={() => setStatus(ALL)}
        >
          All statuses
          <span className="count">{totalNdps}</span>
        </button>
        {statuses.map((s) => (
          <button
            key={s}
            className={`tab ${s === status ? 'active' : ''} ${ndpStatusClass(s)}`}
            onClick={() => setStatus(s)}
            disabled={!counts.get(s)}
          >
            {s}
            <span className="count">{counts.get(s) ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="tree card">
        {releases.length === 0 ? (
          <div className="muted">
            No NDP with status {status === ALL ? 'at all' : status} in {active}.
          </div>
        ) : (
          releases.map((r) => <ReleaseNode key={r.release} release={r} />)
        )}
      </div>
    </div>
  )
}
