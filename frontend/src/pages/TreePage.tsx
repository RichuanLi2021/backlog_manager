import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { getNdpAgeRules, getTree, refreshNdpAges } from '../api'
import { NDP_LEGEND, formatSyncTime, ndpStatusClass } from '../ndp'
import type { NdpAgeLevel, NdpAgeRules, TreeNdp, TreeRelease, TreeSheet } from '../types'

const ALL = 'ALL'
const NO_STATUS = 'N/A'

// Statuses the team watches most, in the order they appear on the deploy plan.
// Anything Jira returns outside this list is appended alphabetically.
const STATUS_ORDER = [
  'Open',
  'Submitted',
  'In Progress',
  'QC Approved',
  'IIC Approved',
  'IT Leader Approved',
  'IT Exec Approved',
  'Verified',
  'Closed',
  NO_STATUS,
]

// The levels a person acts on, worst first. waiting/done/unknown are shown, not counted.
const AGE_LEVELS: NdpAgeLevel[] = ['red', 'yellow', 'green']

type LevelFilter = NdpAgeLevel | typeof ALL

function statusOf(ndp: TreeNdp): string {
  return ndp.status?.trim() || NO_STATUS
}

function statusRank(status: string): number {
  const index = STATUS_ORDER.indexOf(status)
  return index === -1 ? STATUS_ORDER.length : index
}

function daysText(days: number | null): string {
  if (days == null) return ''
  if (days < 1) return 'today'
  const whole = Math.floor(days)
  return `${whole} day${whole === 1 ? '' : 's'}`
}

function ageTitle(ndp: TreeNdp): string {
  if (!ndp.status_since) return ''
  const since = new Date(ndp.status_since).toLocaleString()
  const how =
    ndp.age_source === 'jira'
      ? 'from the Jira changelog'
      : 'Jira could not be asked, so this counts from the first sync that saw it'
  return `${statusOf(ndp)} since ${since} (${ndp.age_days} days), ${how}`
}

function filterReleases(
  releases: TreeRelease[],
  status: string,
  level: LevelFilter,
): TreeRelease[] {
  return releases
    .map((r) => ({
      ...r,
      ndps: r.ndps.filter(
        (n) =>
          (status === ALL || statusOf(n) === status) && (level === ALL || n.age_level === level),
      ),
    }))
    .filter((r) => r.ndps.length > 0)
}

function AgePill({ ndp }: { ndp: TreeNdp }) {
  if (ndp.live_status) {
    return (
      <span
        className="age-pill stale-status"
        title="Jira has moved this NDP on since the report was last synced. Press Update from Jira on the table."
      >
        Jira now: {ndp.live_status}
      </span>
    )
  }
  // A "+" marks an observed date: the NDP has been there at least this long.
  const atLeast = ndp.age_source === 'observed' ? '+' : ''
  switch (ndp.age_level) {
    case 'red':
      return (
        <span className="age-pill red" title={ageTitle(ndp)}>
          &#9873; Flagged &middot; {daysText(ndp.age_days)}
          {atLeast} in {statusOf(ndp)}
        </span>
      )
    case 'yellow':
    case 'green':
      return (
        <span className={`age-pill ${ndp.age_level}`} title={ageTitle(ndp)}>
          {daysText(ndp.age_days)}
          {atLeast} in {statusOf(ndp)}
        </span>
      )
    case 'waiting':
      return (
        <span
          className="age-pill waiting"
          title={`${ageTitle(ndp)}. Not submitted for deployment yet, so never flagged.`}
        >
          {daysText(ndp.age_days)}
          {atLeast} in {statusOf(ndp)}
        </span>
      )
    default:
      return null
  }
}

function ReleaseNode({ release }: { release: TreeRelease }) {
  const [open, setOpen] = useState(true)
  const backlogCount = release.ndps.reduce((n, d) => n + d.backlogs.length, 0)
  const flagged = release.ndps.filter((n) => n.age_level === 'red').length

  return (
    <div className="tree-node">
      <div className="tree-row" onClick={() => setOpen(!open)}>
        <span className="toggle">{open ? '▾' : '▸'}</span>
        <span className="key">{release.release}</span>
        <span className="title">{release.title}</span>
        {flagged > 0 && <span className="age-pill red">&#9873; {flagged} flagged</span>}
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
      <div className={`tree-row ndp-row age-${ndp.age_level}`} onClick={() => setOpen(!open)}>
        <span className="toggle">{open ? '▾' : '▸'}</span>
        <span className="key">{ndp.ndp}</span>
        <span className={`badge ${ndpStatusClass(ndp.status)}`}>{statusOf(ndp)}</span>
        <AgePill ndp={ndp} />
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
  const [level, setLevel] = useState<LevelFilter>(ALL)
  const [rules, setRules] = useState<NdpAgeRules | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshNote, setRefreshNote] = useState<string | null>(null)

  const load = useCallback(
    () =>
      getTree(kind, quarter)
        .then((data) => {
          setSheets(data)
          setActive((current) =>
            current && data.some((s) => s.sheet === current) ? current : (data[0]?.sheet ?? ''),
          )
        })
        .catch((e) => setError((e as Error).message)),
    [kind, quarter],
  )

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    getNdpAgeRules()
      .then(setRules)
      .catch(() => setRules(null))
  }, [])

  const refresh = async () => {
    setRefreshing(true)
    setError(null)
    try {
      const result = await refreshNdpAges(kind, quarter)
      setRefreshNote(
        result.error
          ? `Jira could not be asked (${result.error}); ages are approximate.`
          : `Checked ${result.from_jira} NDPs against Jira at ${formatSyncTime(new Date().toISOString())}.`,
      )
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRefreshing(false)
    }
  }

  const sheet = sheets.find((s) => s.sheet === active)

  // One NDP can sit under several releases; count each once per sheet.
  const sheetNdps = useMemo(() => {
    const byKey = new Map<string, TreeNdp>()
    sheet?.releases.forEach((r) => r.ndps.forEach((n) => byKey.set(n.ndp, n)))
    return [...byKey.values()]
  }, [sheet])

  // Tabs stay stable across sheets; the counts follow the sheet you are on.
  const statuses = useMemo(() => {
    const seen = new Set<string>()
    sheets.forEach((s) => s.releases.forEach((r) => r.ndps.forEach((n) => seen.add(statusOf(n)))))
    return [...seen].sort((a, b) => statusRank(a) - statusRank(b) || a.localeCompare(b))
  }, [sheets])

  const counts = useMemo(() => {
    const map = new Map<string, number>()
    sheetNdps.forEach((n) => map.set(statusOf(n), (map.get(statusOf(n)) ?? 0) + 1))
    return map
  }, [sheetNdps])

  const levelCounts = useMemo(() => {
    const map = new Map<NdpAgeLevel, number>()
    sheetNdps.forEach((n) => map.set(n.age_level, (map.get(n.age_level) ?? 0) + 1))
    return map
  }, [sheetNdps])

  const releases = useMemo(
    () => filterReleases(sheet?.releases ?? [], status, level),
    [sheet, status, level],
  )

  const staleStatuses = sheetNdps.filter((n) => n.live_status).length
  // In-flight NDPs with no date at all mean ages have never been loaded for them.
  const unaged = sheetNdps.filter(
    (n) => n.age_level === 'unknown' && !n.live_status && n.ndp.startsWith('NDP-'),
  ).length

  const warn = rules?.warn_days ?? 7
  const flag = rules?.flag_days ?? 14
  const levelText: Record<string, string> = {
    red: `flagged, over ${flag} days in one status`,
    yellow: `at risk, ${warn} to ${flag} days`,
    green: `on track, within ${warn} days`,
  }

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
        {refreshNote && <span className="muted">{refreshNote}</span>}
        <button
          onClick={refresh}
          disabled={refreshing}
          title="Re-read when each NDP entered its status from the Jira changelog. Takes a few seconds."
        >
          {refreshing ? 'Checking Jira...' : 'Refresh NDP ages'}
        </button>
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

      <div className="age-summary">
        <span className="age-summary-title">Time in current status</span>
        {AGE_LEVELS.map((l) => (
          <button
            key={l}
            className={`age-filter ${l} ${level === l ? 'active' : ''}`}
            onClick={() => setLevel(level === l ? ALL : l)}
            disabled={!levelCounts.get(l)}
            title={level === l ? 'Show every NDP again' : 'Show only these NDPs'}
          >
            <strong>{levelCounts.get(l) ?? 0}</strong> {levelText[l]}
          </button>
        ))}
        <span className="muted">
          {levelCounts.get('waiting') ?? 0} not yet submitted &middot;{' '}
          {levelCounts.get('done') ?? 0} finished
        </span>
        {level !== ALL && <button onClick={() => setLevel(ALL)}>Show all</button>}
      </div>

      {unaged > 0 && (
        <div className="warning">
          {unaged} NDP{unaged === 1 ? ' has' : 's have'} no status date yet. Press{' '}
          <strong>Refresh NDP ages</strong> to read {unaged === 1 ? 'it' : 'them'} from Jira.
        </div>
      )}
      {staleStatuses > 0 && (
        <div className="warning">
          Jira has moved {staleStatuses} NDP{staleStatuses === 1 ? '' : 's'} on since this
          report was last synced, so {staleStatuses === 1 ? 'it is' : 'they are'} not aged. Run{' '}
          <strong>Update from Jira</strong> on the table to bring the statuses forward.
        </div>
      )}

      <div className="tabs status-tabs">
        <button
          className={`tab ${status === ALL ? 'active' : ''}`}
          onClick={() => setStatus(ALL)}
        >
          All statuses
          <span className="count">{sheetNdps.length}</span>
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
            No NDP
            {status === ALL ? '' : ` with status ${status}`}
            {level === ALL ? '' : ` that is ${level}`} in {active}.
          </div>
        ) : (
          releases.map((r) => <ReleaseNode key={r.release} release={r} />)
        )}
      </div>
    </div>
  )
}
