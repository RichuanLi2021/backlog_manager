import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { exportUrl, getReport, listSnapshots, saveSnapshot } from '../api'
import AuditDrawer from '../components/AuditDrawer'
import BacklogTable from '../components/BacklogTable'
import IdentityPrompt from '../components/IdentityPrompt'
import UpdateButton from '../components/UpdateButton'
import { NDP_LEGEND, formatSyncTime } from '../ndp'
import {
  type BacklogRow,
  type EditableField,
  type ReportDetail,
  type SnapshotInfo,
  type UserInfo,
  type ViewMode,
} from '../types'
import { useSync } from '../useSync'

const ALL_STATUS = 'ALL'
const NO_STATUS = 'N/A'

// Statuses read like "20-RequirementCompleted", so order by the leading number
// rather than alphabetically, which would put 100-Done before 10-Placeholder.
function statusRank(status: string): [number, string] {
  const lead = Number.parseInt(status, 10)
  return [Number.isNaN(lead) ? Number.MAX_SAFE_INTEGER : lead, status]
}

const VIEWS: { id: ViewMode; label: string }[] = [
  { id: 'LIVE', label: 'Live (Jira)' },
  { id: 'SE', label: 'SE View' },
  { id: 'TPM', label: 'TPM View' },
  { id: 'DEV', label: 'DEV View' },
]

export default function ReportPage() {
  const { kind = '', quarter = '' } = useParams()

  const [view, setView] = useState<ViewMode>('LIVE')
  const [snapshotId, setSnapshotId] = useState<number | null>(null)
  // Tagged with the view it belongs to: a list from the previous view must not be
  // read as "this view has no snapshots" while the new request is still in flight.
  const [snapshots, setSnapshots] = useState<{ view: ViewMode; items: SnapshotInfo[] }>({
    view: 'LIVE',
    items: [],
  })
  const [detail, setDetail] = useState<ReportDetail | null>(null)
  const [rows, setRows] = useState<BacklogRow[]>([])
  const [sheet, setSheet] = useState('')
  const [status, setStatus] = useState(ALL_STATUS)
  const [globalFilter, setGlobalFilter] = useState('')
  const [error, setError] = useState<string | null>(null)

  const [editor, setEditor] = useState<UserInfo | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveNote, setSaveNote] = useState<string | null>(null)
  const [auditRow, setAuditRow] = useState<BacklogRow | null>(null)

  const editing = editor !== null

  const load = useCallback(
    async (targetView: ViewMode, targetSnapshot: number | null) => {
      try {
        const d = await getReport(kind, quarter, targetView, targetSnapshot)
        setDetail(d)
        setRows(d.items)
        setDirty(new Set())
        setSheet((current) =>
          current && d.sheets.includes(current) ? current : (d.sheets[0] ?? ''),
        )
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [kind, quarter],
  )

  const loadSnapshots = useCallback(
    async (targetView: ViewMode) => {
      if (targetView === 'LIVE') {
        setSnapshots({ view: 'LIVE', items: [] })
        return
      }
      try {
        const items = await listSnapshots(kind, quarter, targetView)
        setSnapshots({ view: targetView, items })
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [kind, quarter],
  )

  const sync = useSync(kind, () => load(view, snapshotId))

  useEffect(() => {
    load(view, snapshotId)
  }, [load, view, snapshotId])

  useEffect(() => {
    loadSnapshots(view)
  }, [loadSnapshots, view])

  const switchView = (next: ViewMode) => {
    if (editing && !window.confirm('Discard the changes you have not saved yet?')) return
    setEditor(null)
    setView(next)
    setSnapshotId(null)
    setSaveNote(null)
  }

  const sheetRows = useMemo(() => rows.filter((r) => r.sheet === sheet), [rows, sheet])

  const statusCounts = useMemo(() => {
    const map = new Map<string, number>()
    sheetRows.forEach((r) => {
      const key = r.status?.trim() || NO_STATUS
      map.set(key, (map.get(key) ?? 0) + 1)
    })
    return new Map([...map].sort((a, b) => {
      const [an, at] = statusRank(a[0])
      const [bn, bt] = statusRank(b[0])
      return an - bn || at.localeCompare(bt)
    }))
  }, [sheetRows])

  useEffect(() => {
    if (status !== ALL_STATUS && !statusCounts.has(status)) setStatus(ALL_STATUS)
  }, [status, statusCounts])

  const visibleRows = useMemo(
    () =>
      status === ALL_STATUS
        ? sheetRows
        : sheetRows.filter((r) => (r.status?.trim() || NO_STATUS) === status),
    [sheetRows, status],
  )

  // Null until this view's own list has arrived, so nothing is claimed too early.
  const snapshotList = snapshots.view === view ? snapshots.items : null

  const handleEdit = (row: BacklogRow, field: EditableField, value: string) => {
    // Rank is a number and may repeat; anything unparseable clears it back to 0.
    const next = field === 'rank' ? Math.max(0, Math.trunc(Number(value)) || 0) : value
    setRows((prev) =>
      prev.map((r) => (r.sheet === row.sheet && r.key === row.key ? { ...r, [field]: next } : r)),
    )
    setDirty((prev) => new Set(prev).add(`${row.sheet}:${row.key}:${field}`))
  }

  const handleReorder = (keys: string[]) => {
    const position = new Map(keys.map((k, i) => [k, i + 1]))
    setRows((prev) => {
      const moved = new Map(prev.filter((r) => r.sheet === sheet).map((r) => [r.key, r]))
      const ordered = keys
        .map((k) => moved.get(k))
        .filter((r): r is BacklogRow => Boolean(r))
        .map((r) => ({ ...r, rank: position.get(r.key)! }))
      // Drop the reordered rows back into the slots this sheet already occupied.
      let i = 0
      return prev.map((r) => (r.sheet === sheet ? (ordered[i++] ?? r) : r))
    })
    setDirty((prev) => {
      const next = new Set(prev)
      keys.forEach((k) => next.add(`${sheet}:${k}:rank`))
      return next
    })
  }

  const handleSave = async () => {
    if (!editor) return
    setSaving(true)
    setError(null)
    try {
      const saved = await saveSnapshot(kind, quarter, {
        author_email: editor.email,
        based_on_id: detail?.snapshot?.id ?? null,
        rows: rows.map((r) => ({
          sheet: r.sheet,
          key: r.key,
          rank: r.rank,
          developer: r.developer,
          uat_eta: r.uat_eta,
          prod_eta: r.prod_eta,
          comments: r.comments,
        })),
      })
      setEditor(null)
      setSaveNote(
        `Saved as ${saved.role} by ${saved.author_name || saved.author_email} at ${formatSyncTime(saved.created_at)}`,
      )
      setView(saved.role)
      setSnapshotId(saved.id)
      await loadSnapshots(saved.role)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const cancelEdit = () => {
    setEditor(null)
    load(view, snapshotId)
  }

  const dirtyCount = dirty.size
  const activeSnapshot = detail?.snapshot ?? null

  return (
    <div className="page">
      <div className="toolbar">
        <strong>
          {kind.replace('_', ' + ')} &middot; {quarter}
        </strong>
        <div className="legend">
          {NDP_LEGEND.map((l) => (
            <span key={l.label}>
              <span className={`swatch ${l.cls}`} />
              {l.label}
            </span>
          ))}
        </div>
      </div>

      <div className="tabs sheet-tabs">
        {detail?.sheets.map((s) => (
          <button
            key={s}
            className={`tab ${s === sheet ? 'active' : ''}`}
            onClick={() => setSheet(s)}
          >
            {s}
            <span className="count">{rows.filter((r) => r.sheet === s).length}</span>
          </button>
        ))}
      </div>

      <div className="control-bar">
        <div className="control-left">
          <input
            className="search"
            placeholder="Search this sheet..."
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
          />
          {!editing ? (
            <button onClick={() => setPromptOpen(true)}>Edit</button>
          ) : (
            <div className="edit-bar">
              <span className="badge editing">
                Edit as {editor!.role}: {editor!.name || editor!.email}
              </span>
              <button className="primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving...' : `Save as ${editor!.role}`}
              </button>
              <button onClick={cancelEdit} disabled={saving}>
                Cancel
              </button>
              <span className="muted">
                {dirtyCount ? `${dirtyCount} unsaved change${dirtyCount > 1 ? 's' : ''}` : 'No changes yet'}
              </span>
            </div>
          )}
        </div>

        <div className="control-right">
          <div className="view-block">
            <div className="tabs view-tabs">
              {VIEWS.map((v) => (
                <button
                  key={v.id}
                  className={`tab ${v.id === view ? 'active' : ''}`}
                  onClick={() => switchView(v.id)}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </div>

          <UpdateButton
            lastSync={detail?.report.last_jira_sync_at ?? null}
            status={sync.status}
            error={sync.error}
            warning={detail?.report.last_sync_error ?? null}
            onClick={() => sync.start(kind, quarter)}
          />
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {saveNote && !error && <div className="notice">{saveNote}</div>}

      {view !== 'LIVE' && snapshotList && (
        <div className="snapshot-picker">
          {snapshotList.length === 0 ? (
            <span className="muted">
              No {view} snapshot yet. Click Edit, then Save as {view}.
            </span>
          ) : (
            <label className="muted">
              <span>Snapshot</span>
              <select
                value={activeSnapshot?.id ?? snapshotList[0]?.id ?? ''}
                onChange={(e) => setSnapshotId(Number(e.target.value))}
              >
                {snapshotList.map((s) => (
                  <option key={s.id} value={s.id}>
                    {formatSyncTime(s.created_at)} - {s.author_name || s.author_email}
                    {s.label ? ` - ${s.label}` : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      <BacklogTable
        rows={visibleRows}
        editing={editing}
        dirty={dirty}
        allowReorder={status === ALL_STATUS}
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        onEdit={handleEdit}
        onReorder={handleReorder}
        onShowAudit={setAuditRow}
        statusControl={
          <select
            className="status-select"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value={ALL_STATUS}>All statuses ({sheetRows.length})</option>
            {[...statusCounts].map(([s, count]) => (
              <option key={s} value={s}>
                {s} ({count})
              </option>
            ))}
          </select>
        }
        exportHref={exportUrl(
          kind,
          quarter,
          view,
          activeSnapshot?.id ?? null,
          sheet,
          status === ALL_STATUS ? undefined : status,
        )}
        exportLabel={`Download ${sheet}${status === ALL_STATUS ? '' : ` (${status})`} as it stands in the ${view === 'LIVE' ? 'live' : view} view`}
      />

      {promptOpen && (
        <IdentityPrompt
          onCancel={() => setPromptOpen(false)}
          onIdentified={(user) => {
            setPromptOpen(false)
            setEditor(user)
            setSaveNote(null)
          }}
        />
      )}

      {auditRow && <AuditDrawer row={auditRow} onClose={() => setAuditRow(null)} />}
    </div>
  )
}
