import { useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { downloadRefreshedFile, planFileRefresh } from '../api'
import IdentityPrompt from '../components/IdentityPrompt'
import { formatSyncTime, ndpStatusClass } from '../ndp'
import { JIRA_FIELD_LABELS, type FileUpdatePlan, type UserInfo } from '../types'

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

  const run = async (target: File, user: UserInfo) => {
    setBusy('reading')
    setError(null)
    setSaved(null)
    try {
      const result = await planFileRefresh(kind, quarter, target, user.email)
      setPlan(result)
      // Only offer the columns this file actually has something stale in; ticking a
      // column with nothing behind it would just be noise.
      setChosen(new Set(Object.keys(result.field_counts)))
      setSheet(ALL_SHEETS)
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

          <div className="step">
            <span className="step-no">2</span>
            <div>
              <div className="step-title">The file you have been working in</div>
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
              <div className="step-title">What comes back</div>
              <div className="muted">
                The same workbook, with the Jira columns brought forward. Rank, Developer,
                UAT ETA, PROD ETA, Comments, and any highlighting you added are left
                exactly as they are, and an <strong>update log</strong> sheet records
                every cell that moved.
              </div>
            </div>
          </div>
        </div>

        {error && <div className="error">{error}</div>}
        {saved && !error && <div className="notice">Downloaded {saved}</div>}

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
              <button
                className="primary"
                style={{ marginLeft: 'auto' }}
                disabled={busy !== null || nothingToDo}
                onClick={download}
              >
                {busy === 'writing' ? 'Building...' : 'Download updated workbook'}
              </button>
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
          onCancel={() => setPromptOpen(false)}
          onIdentified={(user) => {
            setPromptOpen(false)
            setEditor(user)
            if (file) run(file, user)
          }}
        />
      )}
    </div>
  )
}
