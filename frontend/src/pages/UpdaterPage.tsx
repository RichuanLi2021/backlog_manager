import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import {
  downloadRefreshedFile,
  getSharePointFolder,
  planFileRefresh,
  scanSharePointFile,
  updateSharePointFile,
} from '../api'
import IdentityPrompt from '../components/IdentityPrompt'
import { formatSyncTime, ndpStatusClass } from '../ndp'
import {
  JIRA_FIELD_LABELS,
  type FileProgress,
  type FileUpdatePlan,
  type SharePointFile,
  type SharePointFolder,
  type StatusCount,
  type UserInfo,
} from '../types'

/** Where the file being refreshed lives: the team's SharePoint folder, or an upload. */
type Source = 'sharepoint' | 'upload'

// Older than this, the Jira data a comparison rests on is worth calling out.
const STALE_SYNC_HOURS = 24

// How long after an update to look again, long enough for an AutoSave elsewhere
// to have come through OneDrive if it is going to.
const VERIFY_AFTER_MS = 90_000

function sizeText(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1048576).toFixed(1)} MB`
}

/** One side of the progress panel: each status, the file's count, and Jira's now. */
function ProgressTable({ title, rows, unit }: { title: string; rows: StatusCount[]; unit: string }) {
  if (rows.length === 0) return null
  return (
    <div className="progress-table">
      <div className="progress-title">{title}</div>
      <table className="grid">
        <thead>
          <tr>
            <th>Status</th>
            <th className="numeric">In the file</th>
            <th className="numeric">In Jira now</th>
            <th className="numeric">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const delta = r.now - r.in_file
            return (
              <tr key={r.status}>
                <td>
                  <span className={`badge ${ndpStatusClass(r.status)}`}>{r.status}</span>
                </td>
                <td className="numeric">{r.in_file}</td>
                <td className="numeric">
                  <strong>{r.now}</strong>
                </td>
                <td className={`numeric delta ${delta > 0 ? 'up' : delta < 0 ? 'down' : ''}`}>
                  {delta > 0 ? `+${delta}` : delta < 0 ? `${delta}` : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="muted">Counted in {unit}.</div>
    </div>
  )
}

function syncAgeHours(iso: string | null): number {
  return iso ? (Date.now() - new Date(iso).getTime()) / 3_600_000 : Infinity
}

function SharePointPanel({
  folder,
  kind,
  quarter,
  selected,
  busy,
  onScan,
  onReload,
}: {
  folder: SharePointFolder | null
  kind: string
  quarter: string
  selected: string | null
  busy: boolean
  onScan: (name: string) => void
  onReload: () => void
}) {
  if (!folder) return <div className="muted">Looking for the {quarter} folder...</div>

  if (!folder.found) {
    return (
      <div className="sp-setup">
        <strong>The GLreport folder is not on this PC yet.</strong> One-time setup, about a
        minute:
        <ol>
          <li>
            Open the{' '}
            <a href={folder.web_url} target="_blank" rel="noreferrer">
              {quarter} folder in SharePoint
            </a>{' '}
            and go up to <strong>GL_BL</strong>.
          </li>
          <li>
            Select <strong>GL_BL</strong> and choose <strong>Add shortcut to My files</strong>.
            That covers every quarter, not just this one.
          </li>
          <li>
            Wait until it appears in File Explorer, under{' '}
            <code>OneDrive - TDSYNNEX\Shortcuts</code>,
            then press <strong>Check again</strong>.
          </li>
        </ol>
        <div className="muted">
          Looked in: {folder.searched.join(', ') || 'nowhere configured'}. A different
          location can be set with <code>SHAREPOINT_DIR</code> in <code>backend/.env</code>.
        </div>
        <button onClick={onReload}>Check again</button>
      </div>
    )
  }

  return (
    <div className="sp-files">
      <div className="sp-path">
        <code>{folder.folder}</code>
        <a href={folder.web_url} target="_blank" rel="noreferrer">
          Open in SharePoint
        </a>
        <button
          onClick={onReload}
          disabled={busy}
          title="Re-read the folder and re-scan the file, as SharePoint has it now"
        >
          Refresh
        </button>
      </div>
      {folder.files.length === 0 ? (
        <div className="muted">No workbooks in the {quarter} folder yet.</div>
      ) : (
        folder.files.map((f) => (
          <button
            key={f.name}
            className={`sp-file ${f.name === selected ? 'selected' : ''} ${f.matches_report ? '' : 'other-report'}`}
            onClick={() => onScan(f.name)}
            disabled={busy}
            title={
              f.matches_report
                ? 'Scan this file against the latest Jira data'
                : `Named like a ${f.kind ?? 'different'} report; this page compares against ${kind}`
            }
          >
            <span className="sp-name">{f.name}</span>
            {f.kind && <span className="badge">{f.kind.replace('_', ' + ')}</span>}
            {f.open_here && <span className="badge stale">open in Excel here</span>}
            {f.cloud_only && <span className="badge">in the cloud, downloads on scan</span>}
            <span className="muted">
              saved {formatSyncTime(f.modified)} &middot; {sizeText(f.size)}
            </span>
            {f.name === selected && <span className="sp-scanned">scanned</span>}
          </button>
        ))
      )}
    </div>
  )
}

function ProgressPanel({ progress }: { progress: FileProgress }) {
  return (
    <div className="card progress-panel">
      <div className="notes-head">
        Progress since this file was made
        <span className="muted">
          {progress.backlogs_in_file} backlogs in the file &rarr; {progress.backlogs_now} in
          Jira now
        </span>
      </div>
      <div className="progress-grid">
        <ProgressTable title="Backlog status" rows={progress.backlogs} unit="backlog rows" />
        <ProgressTable title="NDP status" rows={progress.ndps} unit="distinct NDPs" />
      </div>
    </div>
  )
}

const FIELDS = Object.keys(JIRA_FIELD_LABELS)
const ALL_SHEETS = 'ALL'

/** Movement people track week to week, called out separately from other drift. */
const STATUS_FIELDS = new Set(['status', 'ndp_status'])

/** Keep each worksheet's rows together and in tab order, never interleaved. */
function groupBy<T>(rows: T[], key: (row: T) => string): [string, T[]][] {
  const map = new Map<string, T[]>()
  rows.forEach((row) => {
    const at = key(row)
    map.set(at, [...(map.get(at) ?? []), row])
  })
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
}

export default function UpdaterPage() {
  const { kind = '', quarter = '' } = useParams()
  const picker = useRef<HTMLInputElement>(null)

  const [editor, setEditor] = useState<UserInfo | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [over, setOver] = useState(false)

  const [plan, setPlan] = useState<FileUpdatePlan | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set(FIELDS))
  const [addNew, setAddNew] = useState(true)
  const [flagGone, setFlagGone] = useState(true)
  const [sheet, setSheet] = useState(ALL_SHEETS)
  const [busy, setBusy] = useState<'reading' | 'writing' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const [source, setSource] = useState<Source>('sharepoint')
  const [folder, setFolder] = useState<SharePointFolder | null>(null)
  // The SharePoint file the current plan was built from, token and all. The token
  // is what makes the update refuse if someone saved the file after this scan.
  const [scanned, setScanned] = useState<SharePointFile | null>(null)
  // An update waiting on the identity prompt, run as soon as someone is identified.
  const [pendingUpdate, setPendingUpdate] = useState(false)

  const adopt = (result: FileUpdatePlan) => {
    setPlan(result)
    // Only offer the columns this file actually has something stale in; ticking a
    // column with nothing behind it would just be noise.
    setChosen(new Set(Object.keys(result.field_counts)))
    setSheet(ALL_SHEETS)
  }

  const run = async (target: File, user: UserInfo) => {
    setBusy('reading')
    setError(null)
    setSaved(null)
    try {
      adopt(await planFileRefresh(kind, quarter, target, user.email))
    } catch (e) {
      setPlan(null)
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const take = (next: File | null | undefined) => {
    if (!next || !editor) return
    setFile(next)
    run(next, editor)
  }

  const scan = useCallback(
    async (name: string, keepNote = false) => {
      setBusy('reading')
      setError(null)
      if (!keepNote) setSaved(null)
      try {
        const result = await scanSharePointFile(kind, quarter, name)
        setScanned(result.file)
        adopt(result.plan)
      } catch (e) {
        setPlan(null)
        setScanned(null)
        setError((e as Error).message)
      } finally {
        setBusy(null)
      }
    },
    [kind, quarter],
  )

  const loadFolder = useCallback(async () => {
    try {
      const listing = await getSharePointFolder(kind, quarter)
      setFolder(listing)
      return listing
    } catch (e) {
      setError((e as Error).message)
      return null
    }
  }, [kind, quarter])

  // Opening the page scans the newest workbook for this report straight away:
  // "show me where things stand" should not need a click.
  useEffect(() => {
    if (source !== 'sharepoint') return
    let cancelled = false
    loadFolder().then((listing) => {
      const newest = listing?.files.find((f) => f.matches_report)
      if (!cancelled && newest) scan(newest.name)
    })
    return () => {
      cancelled = true
    }
  }, [source, loadFolder, scan])

  const switchSource = (next: Source) => {
    setSource(next)
    setPlan(null)
    setScanned(null)
    setFile(null)
    setSaved(null)
    setError(null)
  }

  const [verifyAt, setVerifyAt] = useState<number | null>(null)
  const [overwritten, setOverwritten] = useState<string | null>(null)

  const verifyStuck = async (name: string) => {
    setVerifyAt(null)
    try {
      const again = await scanSharePointFile(kind, quarter, name)
      const back = again.plan.changes.length + again.plan.new_rows.length
      if (back > 0) {
        setOverwritten(
          `${name} was saved over after the update: ${back} of the changes are gone again. ` +
            'Someone still had it open in Excel (here or elsewhere) and AutoSave wrote their ' +
            'copy back. Ask everyone to close it, then update again.',
        )
        setScanned(again.file)
        adopt(again.plan)
      }
    } catch {
      // A failed check proves nothing either way; the next scan will show the truth.
    }
  }

  /** Re-read the folder and re-scan the file on screen, so both reflect SharePoint now. */
  const refresh = async () => {
    setOverwritten(null)
    const listing = await loadFolder()
    const keep = scanned && listing?.files.some((f) => f.name === scanned.name)
    const target = keep ? scanned!.name : listing?.files.find((f) => f.matches_report)?.name
    if (target) await scan(target)
  }

  const updateOnSharePoint = async (user: UserInfo) => {
    if (!scanned) return
    setBusy('writing')
    setError(null)
    try {
      const result = await updateSharePointFile(kind, quarter, {
        name: scanned.name,
        token: scanned.token,
        author_email: user.email,
        fields: [...chosen],
        add_new: addNew,
        flag_gone: flagGone,
      })
      setSaved(
        `Updated ${result.file.name} on SharePoint: ${result.cells_updated} cells, ` +
          `${result.rows_added} backlogs added, ${result.rows_flagged} flagged. OneDrive is ` +
          `uploading it now. The previous version is in SharePoint's version history, ` +
          `and a copy was kept at ${result.backup}.`,
      )
      await loadFolder()
      // Scan again so the page shows the file as it now is: current, nothing to do.
      await scan(result.file.name, true)
      // Someone with the file open in Excel elsewhere is invisible from this PC, and
      // their AutoSave puts the old content back minutes later. Look again, and say so.
      setVerifyAt(Date.now() + VERIFY_AFTER_MS)
      window.setTimeout(() => verifyStuck(result.file.name), VERIFY_AFTER_MS)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const requestUpdate = () => {
    if (editor) {
      updateOnSharePoint(editor)
    } else {
      setPendingUpdate(true)
      setPromptOpen(true)
    }
  }

  const toggleField = (name: string) =>
    setChosen((prev) => {
      const next = new Set(prev)
      if (!next.delete(name)) next.add(name)
      return next
    })

  const sheets = useMemo(
    () => [...new Set(plan?.changes.map((c) => c.sheet) ?? [])].sort(),
    [plan],
  )

  const visible = useMemo(
    () =>
      (plan?.changes ?? []).filter(
        (c) => chosen.has(c.field) && (sheet === ALL_SHEETS || c.sheet === sheet),
      ),
    [plan, chosen, sheet],
  )

  const download = async () => {
    if (!editor || !file) return
    setBusy('writing')
    setError(null)
    try {
      setSaved(
        await downloadRefreshedFile(
          kind,
          quarter,
          file,
          editor.email,
          [...chosen],
          addNew,
          flagGone,
        ),
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const staleFields = Object.keys(plan?.field_counts ?? {})
  const nothingToDo =
    plan !== null &&
    visible.length === 0 &&
    plan.layout_changes.length === 0 &&
    !(addNew && plan.new_rows.length) &&
    !(flagGone && plan.gone_rows.length)

  return (
    <div className="page">
      <div className="toolbar">
        <strong>
          Spreadsheet updater &middot; {kind.replace('_', ' + ')} &middot; {quarter}
        </strong>
        <span className="muted">
          Bring an exported report back up to date without losing the work done on it.
        </span>
      </div>

      <div className="analyzer">
        <div className="card analyzer-setup">
          <div className="step">
            <span className="step-no">1</span>
            <div>
              <div className="step-title">Who is updating</div>
              {editor ? (
                <div className="edit-bar">
                  <span className="badge editing">
                    {editor.role}: {editor.name || editor.email}
                  </span>
                  <button onClick={() => setPromptOpen(true)}>Change</button>
                </div>
              ) : (
                <>
                  <div className="muted">
                    Only System Engineer, TPM, and Developer members can use this.
                  </div>
                  <button className="primary" onClick={() => setPromptOpen(true)}>
                    Identify me
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="step step-wide">
            <span className="step-no">2</span>
            <div>
              <div className="step-title">The file you have been working in</div>
              <div className="tabs view-tabs">
                <button
                  className={`tab ${source === 'sharepoint' ? 'active' : ''}`}
                  onClick={() => switchSource('sharepoint')}
                  disabled={busy !== null}
                >
                  SharePoint folder
                </button>
                <button
                  className={`tab ${source === 'upload' ? 'active' : ''}`}
                  onClick={() => switchSource('upload')}
                  disabled={busy !== null}
                >
                  Upload a file
                </button>
              </div>

              {source === 'sharepoint' ? (
                <SharePointPanel
                  folder={folder}
                  kind={kind}
                  quarter={quarter}
                  selected={scanned?.name ?? null}
                  busy={busy !== null}
                  onScan={(name) => scan(name)}
                  onReload={refresh}
                />
              ) : (
              <div
                className={`dropzone ${over ? 'over' : ''} ${editor ? '' : 'locked'}`}
                onClick={() => editor && picker.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  if (editor) setOver(true)
                }}
                onDragLeave={() => setOver(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setOver(false)
                  take(e.dataTransfer.files?.[0])
                }}
              >
                {busy === 'reading' ? (
                  <strong>Comparing {file?.name}...</strong>
                ) : (
                  <>
                    <strong>Drop the old exported report here</strong>
                    <span className="muted">
                      or click to choose one &middot; .xlsx or .xlsm
                    </span>
                    {file && <span className="badge">{file.name}</span>}
                  </>
                )}
              </div>
              )}
            </div>
            <input
              ref={picker}
              type="file"
              accept=".xlsx,.xlsm"
              hidden
              onChange={(e) => {
                take(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </div>

          <div className="step">
            <span className="step-no">3</span>
            <div>
              <div className="step-title">
                {source === 'sharepoint' ? 'What changes on SharePoint' : 'What comes back'}
              </div>
              <div className="muted">
                {source === 'sharepoint'
                  ? 'The file is updated where it is, so every link to it keeps working. '
                  : 'The same workbook, '}
                with the Jira columns brought forward. Rank, Developer, UAT ETA, PROD ETA,
                Comments, and any highlighting are left exactly as they are, and an{' '}
                <strong>update log</strong> sheet records every cell that moved.
              </div>
            </div>
          </div>
        </div>

        {error && <div className="error">{error}</div>}
        {overwritten && <div className="error">{overwritten}</div>}
        {source === 'sharepoint' && scanned?.open_here && (
          <div className="error">
            {scanned.name} is open in Excel on this PC. Close it before updating: while it is
            open, AutoSave writes its copy back over the update a few minutes later and the
            changes disappear. Then press <strong>Refresh</strong>.
          </div>
        )}
        {verifyAt && !overwritten && (
          <div className="muted">
            Checking again in a minute or so that nobody's Excel has saved over the update...
          </div>
        )}
        {saved && !error && (
          <div className="notice">
            {source === 'sharepoint' ? saved : `Downloaded ${saved}`}
          </div>
        )}
        {plan && syncAgeHours(plan.last_jira_sync_at) > STALE_SYNC_HOURS && (
          <div className="warning">
            The Jira data this is compared with was last pulled{' '}
            {formatSyncTime(plan.last_jira_sync_at)}, over a day ago. Press{' '}
            <strong>Update from Jira</strong> on the table first, or the file will be brought
            up to that older point rather than to today.
          </div>
        )}

        {plan && (
          <>
            <div className="card analyzer-summary">
              <div className="summary-grid">
                <div>
                  <span className="muted">File</span>
                  <strong>{plan.filename}</strong>
                </div>
                <div>
                  <span className="muted">Jira data from</span>
                  <strong>{formatSyncTime(plan.last_jira_sync_at)}</strong>
                </div>
                <div>
                  <span className="muted">Cells out of date</span>
                  <strong>{plan.changes.length}</strong>
                </div>
                <div>
                  <span className="muted">Raised since</span>
                  <strong>{plan.new_rows.length}</strong>
                </div>
                <div>
                  <span className="muted">No longer returned</span>
                  <strong>{plan.gone_rows.length}</strong>
                </div>
                <div>
                  <span className="muted">Already current</span>
                  <strong>{plan.unchanged_cells}</strong>
                </div>
              </div>

              <div className="summary-notes">
                {plan.sheets.map((s) => (
                  <div key={s.name}>
                    <span className="badge">{s.name}</span>{' '}
                    {s.resolved_to ? (
                      <span className="muted">
                        read as {s.resolved_to} &middot; header on row {s.header_row}{' '}
                        &middot; {s.matched} of {s.rows_in_file} rows matched
                      </span>
                    ) : (
                      <span className="warning-inline">
                        could not be matched to a sheet of {kind}; it will be left alone
                      </span>
                    )}
                  </div>
                ))}
                {plan.sheets_ignored.length > 0 && (
                  <div className="muted">Skipped {plan.sheets_ignored.join(', ')}</div>
                )}
                <div className="muted">
                  Jira data is whatever the last sync pulled. Run{' '}
                  <strong>Update from Jira</strong> on the table first if that timestamp
                  looks old.
                </div>
                {plan.warnings.map((w) => (
                  <div className="warning" key={w}>
                    {w}
                  </div>
                ))}
              </div>
            </div>

            {plan.layout_changes.length > 0 && (
              <div className="card notes-card layout-card">
                <div className="notes-head">
                  <span className="badge tag-status">Layout</span>
                  These tabs will be put in the standard layout
                </div>
                <div className="muted">
                  NA_GL&apos;s columns, Package after Assignee, and Comments split into IT
                  Comment and TPM Comment. Every value, highlight and width moves with its
                  column; nothing is dropped.
                </div>
                <ul>
                  {plan.layout_changes.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            {plan.progress && <ProgressPanel progress={plan.progress} />}

            <div className="table-status analyzer-actions">
              <select value={sheet} onChange={(e) => setSheet(e.target.value)}>
                <option value={ALL_SHEETS}>All sheets</option>
                {sheets.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              {staleFields.length === 0 ? (
                <span className="muted">No Jira column in this file is out of date.</span>
              ) : (
                staleFields.map((name) => (
                  <label className="chip" key={name}>
                    <input
                      type="checkbox"
                      checked={chosen.has(name)}
                      onChange={() => toggleField(name)}
                    />
                    {JIRA_FIELD_LABELS[name] ?? name} ({plan.field_counts[name]})
                  </label>
                ))
              )}
              <label className="chip">
                <input
                  type="checkbox"
                  checked={addNew}
                  onChange={() => setAddNew(!addNew)}
                />
                Append {plan.new_rows.length} new backlog
                {plan.new_rows.length === 1 ? '' : 's'}
              </label>
              <label className="chip">
                <input
                  type="checkbox"
                  checked={flagGone}
                  onChange={() => setFlagGone(!flagGone)}
                />
                Flag {plan.gone_rows.length} dropped
              </label>
              {source === 'sharepoint' ? (
                <button
                  className="primary"
                  style={{ marginLeft: 'auto' }}
                  disabled={busy !== null || nothingToDo || !scanned || scanned.open_here}
                  onClick={requestUpdate}
                  title="Write these changes into the file in SharePoint. Refused if anyone saved it after this scan."
                >
                  {busy === 'writing' ? 'Updating SharePoint...' : 'Update on SharePoint'}
                </button>
              ) : (
                <button
                  className="primary"
                  style={{ marginLeft: 'auto' }}
                  disabled={busy !== null || nothingToDo}
                  onClick={download}
                >
                  {busy === 'writing' ? 'Building...' : 'Download updated workbook'}
                </button>
              )}
            </div>

            {(plan.new_rows.length > 0 || plan.gone_rows.length > 0) && (
              <div className="row-notes">
                {plan.new_rows.length > 0 && (
                  <div className="card notes-card is-new">
                    <div className="notes-head">
                      <span className="badge tag-new">New</span>
                      Raised since this file was exported ({plan.new_rows.length})
                    </div>
                    <div className="muted">
                      Appended at the bottom of the tab they belong to, with the user
                      columns left empty for you to fill in.
                    </div>
                    <div className="notes-scroll">
                      {groupBy(plan.new_rows, (r) => r.sheet).map(([tab, rows]) => (
                        <div key={tab}>
                          <div className="notes-sheet">
                            {tab} ({rows.length})
                          </div>
                          <ul>
                            {rows.map((r) => (
                              <li key={r.key}>
                                <span className="badge tag-new">New</span>{' '}
                                <strong>{r.key}</strong> {r.summary}
                                <span className="badge">{r.status || 'no status'}</span>
                                {r.ndp_status && (
                                  <span className={`badge ${ndpStatusClass(r.ndp_status)}`}>
                                    {r.ndp_status}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {plan.gone_rows.length > 0 && (
                  <div className="card notes-card is-gone">
                    <div className="notes-head">
                      <span className="badge tag-gone">Removed</span>
                      No longer coming back from Jira ({plan.gone_rows.length})
                    </div>
                    <div className="muted">
                      Kept in the file with everything written about them, and marked in
                      an <em>Update Status</em> column.
                    </div>
                    <div className="notes-scroll">
                      {groupBy(plan.gone_rows, (r) => r.sheet).map(([tab, rows]) => (
                        <div key={tab}>
                          <div className="notes-sheet">
                            {tab} ({rows.length})
                          </div>
                          <ul>
                            {rows.map((r) => (
                              <li key={`${r.sheet}:${r.key}`}>
                                <strong>{r.key}</strong>{' '}
                                <span className="muted">
                                  row {r.row} &middot; {r.reason}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {visible.length > 0 && (
              <div className="sheet-groups">
                {groupBy(visible, (c) => c.sheet).map(([tab, rows]) => (
                  <div className="sheet-section" key={tab}>
                    <div className="sheet-head">
                      <span className="badge">{tab}</span>
                      {rows.length} cell{rows.length === 1 ? '' : 's'} to bring forward
                      {rows.some((c) => STATUS_FIELDS.has(c.field)) && (
                        <span className="badge tag-status">
                          {rows.filter((c) => STATUS_FIELDS.has(c.field)).length} status
                          update
                          {rows.filter((c) => STATUS_FIELDS.has(c.field)).length === 1
                            ? ''
                            : 's'}
                        </span>
                      )}
                    </div>
                    <div className="table-wrap">
                      <table className="grid">
                        <thead>
                          <tr>
                            <th>Row</th>
                            <th>Backlog</th>
                            <th>Column</th>
                            <th>Change</th>
                            <th>In your file</th>
                            <th>Now in Jira</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((c) => (
                            <tr key={`${c.row}:${c.field}`}>
                              <td className="numeric">{c.row}</td>
                              <td>{c.key}</td>
                              <td>{c.label}</td>
                              <td>
                                {STATUS_FIELDS.has(c.field) ? (
                                  <span className="badge tag-status">Status Update</span>
                                ) : (
                                  <span className="muted">field update</span>
                                )}
                              </td>
                              <td className="wide change-old">{c.in_file || '—'}</td>
                              <td
                                className={`wide change-new ${
                                  c.field === 'ndp_status' ? ndpStatusClass(c.current) : ''
                                }`}
                              >
                                {c.current || '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {promptOpen && (
        <IdentityPrompt
          action="Update"
          confirmLabel="Continue"
          onCancel={() => {
            setPromptOpen(false)
            setPendingUpdate(false)
          }}
          onIdentified={(user) => {
            setPromptOpen(false)
            setEditor(user)
            if (pendingUpdate) {
              // They pressed Update on SharePoint before saying who they are.
              setPendingUpdate(false)
              updateOnSharePoint(user)
            } else if (source === 'upload' && file) {
              run(file, user)
            }
          }}
        />
      )}
    </div>
  )
}
