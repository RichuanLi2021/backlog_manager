import { useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { analyzeSpreadsheet, applyAnalysis } from '../api'
import IdentityPrompt from '../components/IdentityPrompt'
import { formatSyncTime } from '../ndp'
import {
  FIELD_LABELS,
  type AnalysisResult,
  type AnalyzedChange,
  type AnalyzedRow,
  type CompareWith,
  type EditableField,
  type EditableRole,
  type SnapshotInfo,
  type UserInfo,
} from '../types'

const ROLES: EditableRole[] = ['SE', 'TPM', 'DEV']
const FIELDS = Object.keys(FIELD_LABELS) as EditableField[]
const ALL_SHEETS = 'ALL'

const BASELINES: { id: CompareWith; label: string; hint: string }[] = [
  {
    id: 'LIVE',
    label: 'Latest backlog report',
    hint: 'The live Jira pull, with no snapshot over it. Everything the file says shows as incoming.',
  },
  { id: 'SE', label: 'SE View', hint: "The System Engineer group's most recent save." },
  { id: 'TPM', label: 'TPM View', hint: "The TPM group's most recent save." },
  { id: 'DEV', label: 'DEV View', hint: "The Developer group's most recent save." },
]

type Filter = 'CHANGES' | 'IDENTICAL'

const cellId = (row: AnalyzedRow, change: AnalyzedChange) =>
  `${row.sheet}:${row.key}:${change.field}`

/** Keep each region sheet's rows together and in tab order, never interleaved. */
function groupBy<T>(rows: T[], key: (row: T) => string): [string, T[]][] {
  const map = new Map<string, T[]>()
  rows.forEach((row) => {
    const at = key(row)
    map.set(at, [...(map.get(at) ?? []), row])
  })
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
}

export default function AnalyzerPage() {
  const { kind = '', quarter = '' } = useParams()
  const picker = useRef<HTMLInputElement>(null)

  const [editor, setEditor] = useState<UserInfo | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  const [role, setRole] = useState<EditableRole>('SE')
  const [baseline, setBaseline] = useState<CompareWith>('LIVE')
  const [file, setFile] = useState<File | null>(null)
  const [over, setOver] = useState(false)

  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [sheet, setSheet] = useState(ALL_SHEETS)
  const [fields, setFields] = useState<Set<EditableField>>(new Set(FIELDS))
  const [filter, setFilter] = useState<Filter>('CHANGES')
  const [busy, setBusy] = useState<'reading' | 'saving' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<SnapshotInfo | null>(null)

  const run = async (
    target: File,
    targetRole: EditableRole,
    compare: CompareWith,
    user: UserInfo,
  ) => {
    setBusy('reading')
    setError(null)
    setSaved(null)
    try {
      const analysis = await analyzeSpreadsheet(
        kind,
        quarter,
        target,
        user.email,
        targetRole,
        compare,
      )
      setResult(analysis)
      // Everything that differs starts accepted; the review is about taking things
      // out, not hunting for what to put in.
      setSelected(
        new Set(analysis.rows.flatMap((r) => r.changes.map((c) => cellId(r, c)))),
      )
      setFields(new Set(FIELDS))
      setSheet(ALL_SHEETS)
      setFilter(analysis.rows.length === 0 ? 'IDENTICAL' : 'CHANGES')
    } catch (e) {
      setResult(null)
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const take = (next: File | null | undefined) => {
    if (!next || !editor) return
    setFile(next)
    run(next, role, baseline, editor)
  }

  const rerun = (targetRole: EditableRole, compare: CompareWith) => {
    setRole(targetRole)
    setBaseline(compare)
    if (file && editor) run(file, targetRole, compare, editor)
  }

  const visibleRows = useMemo(() => {
    if (!result) return []
    return result.rows
      .filter((r) => sheet === ALL_SHEETS || r.sheet === sheet)
      .map((r) => ({ ...r, changes: r.changes.filter((c) => fields.has(c.field)) }))
      .filter((r) => r.changes.length > 0)
  }, [result, sheet, fields])

  const visibleIdentical = useMemo(
    () =>
      (result?.identical ?? []).filter((r) => sheet === ALL_SHEETS || r.sheet === sheet),
    [result, sheet],
  )

  const sheets = useMemo(
    () =>
      [
        ...new Set([
          ...(result?.rows ?? []).map((r) => r.sheet),
          ...(result?.identical ?? []).map((r) => r.sheet),
        ]),
      ].sort(),
    [result],
  )

  const setMany = (ids: string[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)))
      return next
    })

  const toggleField = (name: EditableField) =>
    setFields((prev) => {
      const next = new Set(prev)
      if (!next.delete(name)) next.add(name)
      return next
    })

  const accepted = useMemo(
    () =>
      (result?.rows ?? []).flatMap((r) =>
        r.changes.filter((c) => selected.has(cellId(r, c))).map((c) => ({ row: r, change: c })),
      ),
    [result, selected],
  )

  const save = async () => {
    if (!editor || !result) return
    setBusy('saving')
    setError(null)
    try {
      const snapshot = await applyAnalysis(kind, quarter, {
        author_email: editor.email,
        target_role: result.target_role,
        label: `Imported from ${result.filename}`,
        // Only reuse the compared snapshot when it is the one being written into;
        // otherwise the backend starts from the target role's own latest save.
        based_on_id:
          result.compare_with === result.target_role ? (result.baseline?.id ?? null) : null,
        changes: accepted.map(({ row, change }) => ({
          sheet: row.sheet,
          key: row.key,
          field: change.field,
          value: change.incoming,
        })),
      })
      setSaved(snapshot)
      setResult(null)
      setFile(null)
      setSelected(new Set())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const fieldCounts = useMemo(() => {
    const map = new Map<EditableField, number>()
    ;(result?.rows ?? []).forEach((r) =>
      r.changes.forEach((c) => map.set(c.field, (map.get(c.field) ?? 0) + 1)),
    )
    return map
  }, [result])

  return (
    <div className="page">
      <div className="toolbar">
        <strong>
          Spreadsheet analyzer &middot; {kind.replace('_', ' + ')} &middot; {quarter}
        </strong>
        <span className="muted">
          Read a circulated Excel copy, see exactly what it would change, and keep the
          parts you want.
        </span>
      </div>

      <div className="analyzer">
        <div className="card analyzer-setup">
          <div className="step">
            <span className="step-no">1</span>
            <div>
              <div className="step-title">Who is importing</div>
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
                    Only System Engineer, TPM, and Developer members can import a file.
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
              <div className="step-title">Compare against</div>
              <div className="tabs view-tabs">
                {BASELINES.map((b) => (
                  <button
                    key={b.id}
                    className={`tab ${b.id === baseline ? 'active' : ''}`}
                    disabled={!editor || busy !== null}
                    title={b.hint}
                    onClick={() => rerun(role, b.id)}
                  >
                    {b.label}
                  </button>
                ))}
              </div>
              <div className="muted">
                {BASELINES.find((b) => b.id === baseline)?.hint}
              </div>
            </div>
          </div>

          <div className="step">
            <span className="step-no">3</span>
            <div>
              <div className="step-title">Save into</div>
              <div className="tabs view-tabs">
                {ROLES.map((r) => (
                  <button
                    key={r}
                    className={`tab ${r === role ? 'active' : ''}`}
                    disabled={!editor || busy !== null}
                    onClick={() => rerun(r, baseline)}
                  >
                    {r} View
                  </button>
                ))}
              </div>
              <div className="muted">
                Written as a new {role} snapshot under your name. Rows the file says
                nothing about keep whatever the {role} view already had.
              </div>
            </div>
          </div>

          <div className="step">
            <span className="step-no">4</span>
            <div>
              <div className="step-title">The file</div>
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
                    <strong>Drop an Excel file here</strong>
                    <span className="muted">
                      or click to choose one &middot; .xlsx or .xlsm
                    </span>
                    {file && <span className="badge">{file.name}</span>}
                  </>
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
          </div>
        </div>

        {error && <div className="error">{error}</div>}

        {saved && (
          <div className="notice">
            Saved as a {saved.role} snapshot at {formatSyncTime(saved.created_at)} with{' '}
            {saved.row_count} rows.{' '}
            <Link to={`/reports/${kind}/${quarter}`}>Open the table</Link> and pick{' '}
            {saved.role} View to see it.
          </div>
        )}

        {result && (
          <>
            <div className="card diff-summary">
              <div className="diff-stats">
                <span className="stat add">+{result.added_cells} added</span>
                <span className="stat mod">~{result.changed_cells} changed</span>
                <span className="stat same">{result.unchanged_cells} identical</span>
                {result.unmatched_keys.length > 0 && (
                  <span className="stat gone">
                    {result.unmatched_keys.length} not in the report
                  </span>
                )}
                <span className="muted">
                  {result.filename} &middot; {result.rows_read} rows read &middot;{' '}
                  {result.keys_matched} backlogs matched &middot; compared in{' '}
                  {result.elapsed_ms} ms
                </span>
              </div>

              <div className="diff-base">
                <span className="muted">Compared against</span>{' '}
                <strong>{result.baseline_label}</strong>
                <span className="muted"> &rarr; saving into </span>
                <strong>{result.target_role} View</strong>
              </div>

              <div className="summary-notes">
                <div>
                  <span className="muted">Columns recognized: </span>
                  {Object.entries(result.detected_columns).map(([f, header]) => (
                    <span className="badge" key={f}>
                      {header} &rarr; {f}
                    </span>
                  ))}
                </div>
                <div>
                  <span className="muted">Worksheets read: </span>
                  {result.sheet_summary.map((s) => (
                    <span className="badge" key={s.name}>
                      {s.name}: {s.matched}/{s.rows_read} rows
                      {s.target_sheets.length > 0 && ` → ${s.target_sheets.join(', ')}`}
                    </span>
                  ))}
                  {result.sheet_summary.length === 0 && 'none'}
                  {result.sheets_ignored.length > 0 && (
                    <span className="muted">
                      {' '}
                      &middot; skipped {result.sheets_ignored.join(', ')}
                    </span>
                  )}
                </div>
                {result.sheet_summary.length === 1 && (
                  <div className="muted">
                    This file has one worksheet, so only {result.sheet_summary[0].name} is
                    compared. Use <strong>Export all sheets</strong> on the table to get a
                    workbook holding every region tab.
                  </div>
                )}
                {result.unmatched_keys.length > 0 && (
                  <div className="muted">
                    Not in this report, so left out:{' '}
                    {result.unmatched_keys.slice(0, 12).join(', ')}
                    {result.unmatched_keys.length > 12 ? ', ...' : ''}
                  </div>
                )}
                {result.stale_jira_cells > 0 && (
                  <div className="warning">
                    {result.stale_jira_cells} Jira cells in this file are out of date
                    (status, NDP, hours). This page only imports what people typed —{' '}
                    <Link to={`/reports/${kind}/${quarter}/update-file`}>
                      open the Updater
                    </Link>{' '}
                    to write the current Jira data back into the file itself.
                  </div>
                )}
                <div className="muted">
                  Empty cells in the file are ignored, so an upload never clears a value
                  someone already entered.
                </div>
                {result.warnings.map((w) => (
                  <div className="warning" key={w}>
                    {w}
                  </div>
                ))}
              </div>
            </div>

            <div className="table-status analyzer-actions">
              <div className="tabs view-tabs">
                <button
                  className={`tab ${filter === 'CHANGES' ? 'active' : ''}`}
                  onClick={() => setFilter('CHANGES')}
                >
                  Incoming changes ({result.rows.length})
                </button>
                <button
                  className={`tab ${filter === 'IDENTICAL' ? 'active' : ''}`}
                  onClick={() => setFilter('IDENTICAL')}
                >
                  Already identical ({result.identical.length})
                </button>
              </div>

              {sheets.length > 1 && (
                <select value={sheet} onChange={(e) => setSheet(e.target.value)}>
                  <option value={ALL_SHEETS}>All sheets</option>
                  {sheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              )}

              {filter === 'CHANGES' &&
                FIELDS.filter((f) => fieldCounts.has(f)).map((f) => (
                  <label className="chip" key={f}>
                    <input
                      type="checkbox"
                      checked={fields.has(f)}
                      onChange={() => toggleField(f)}
                    />
                    {FIELD_LABELS[f]} ({fieldCounts.get(f)})
                  </label>
                ))}

              {filter === 'CHANGES' && (
                <>
                  <button
                    onClick={() =>
                      setMany(
                        visibleRows.flatMap((r) => r.changes.map((c) => cellId(r, c))),
                        true,
                      )
                    }
                  >
                    Keep all shown
                  </button>
                  <button
                    onClick={() =>
                      setMany(
                        visibleRows.flatMap((r) => r.changes.map((c) => cellId(r, c))),
                        false,
                      )
                    }
                  >
                    Discard all shown
                  </button>
                  <button
                    className="primary"
                    style={{ marginLeft: 'auto' }}
                    disabled={busy !== null || accepted.length === 0}
                    onClick={save}
                  >
                    {busy === 'saving'
                      ? 'Saving...'
                      : `Apply ${accepted.length} change${accepted.length === 1 ? '' : 's'} to ${result.target_role} View`}
                  </button>
                </>
              )}
            </div>

            {filter === 'CHANGES' ? (
              visibleRows.length === 0 ? (
                <div className="card" style={{ padding: 16 }}>
                  <strong>No differences to show.</strong>{' '}
                  <span className="muted">
                    {result.rows.length === 0
                      ? `Every value ${result.filename} fills in already matches ${result.baseline_label}. Switch the comparison above to measure it against something else.`
                      : 'The column filters above are hiding all of them.'}
                  </span>
                </div>
              ) : (
                <div className="sheet-groups">
                  {groupBy(visibleRows, (r) => r.sheet).map(([tab, tabRows]) => {
                    const tabIds = tabRows.flatMap((r) =>
                      r.changes.map((c) => cellId(r, c)),
                    )
                    const tabKept = tabIds.filter((id) => selected.has(id)).length
                    return (
                      <div key={tab}>
                        <div className="sheet-head standalone">
                          <input
                            type="checkbox"
                            checked={tabKept === tabIds.length}
                            ref={(el) => {
                              if (el)
                                el.indeterminate = tabKept > 0 && tabKept < tabIds.length
                            }}
                            onChange={() => setMany(tabIds, tabKept !== tabIds.length)}
                          />
                          <span className="badge">{tab}</span>
                          {tabRows.length} backlog{tabRows.length === 1 ? '' : 's'},{' '}
                          {tabIds.length} change{tabIds.length === 1 ? '' : 's'}
                          <span className="muted">{tabKept} kept</span>
                        </div>
                        <div className="diff-list">
                          {tabRows.map((row) => (
                            <DiffCard
                              key={`${row.sheet}:${row.key}`}
                              row={row}
                              selected={selected}
                              setMany={setMany}
                            />
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            ) : visibleIdentical.length === 0 ? (
              <div className="card" style={{ padding: 16 }}>
                <strong>Nothing matched exactly.</strong>{' '}
                <span className="muted">
                  Every row the file fills in differs from {result.baseline_label}.
                </span>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="grid">
                  <thead>
                    <tr>
                      <th>Sheet</th>
                      <th>Backlog</th>
                      <th>Summary</th>
                      <th>Columns that already agree</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleIdentical.map((r) => (
                      <tr key={`${r.sheet}:${r.key}`}>
                        <td>{r.sheet}</td>
                        <td>{r.key}</td>
                        <td className="wide" title={r.summary}>
                          {r.summary}
                        </td>
                        <td>{r.fields.map((f) => FIELD_LABELS[f]).join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {promptOpen && (
        <IdentityPrompt
          action="Import"
          confirmLabel="Continue"
          onCancel={() => setPromptOpen(false)}
          onIdentified={(user) => {
            setPromptOpen(false)
            setEditor(user)
            setRole(user.role)
            if (file) run(file, user.role, baseline, user)
          }}
        />
      )}
    </div>
  )
}

/** One backlog's incoming changes, laid out like a commit hunk. */
function DiffCard({
  row,
  selected,
  setMany,
}: {
  row: AnalyzedRow
  selected: Set<string>
  setMany: (ids: string[], on: boolean) => void
}) {
  const ids = row.changes.map((c) => cellId(row, c))
  const kept = ids.filter((id) => selected.has(id)).length

  return (
    <div className="diff-row">
      <div className="diff-head">
        <input
          type="checkbox"
          checked={kept === ids.length}
          ref={(el) => {
            if (el) el.indeterminate = kept > 0 && kept < ids.length
          }}
          onChange={() => setMany(ids, kept !== ids.length)}
        />
        <strong>{row.key}</strong>
        {row.status && <span className="badge">{row.status}</span>}
        {row.archived && <span className="badge stale">stale</span>}
        <span className="diff-title" title={row.summary}>
          {row.summary}
        </span>
        <span className="muted diff-origin">
          {row.source_sheet} row {row.source_row}
        </span>
      </div>

      {row.changes.map((change) => {
        const id = cellId(row, change)
        const on = selected.has(id)
        return (
          <div className={`diff-field ${on ? '' : 'skipped'}`} key={change.field}>
            <input type="checkbox" checked={on} onChange={() => setMany([id], !on)} />
            <span className="diff-name">
              {FIELD_LABELS[change.field]}
              <span className={`tag ${change.state}`}>{change.state}</span>
            </span>
            <div className="diff-values">
              <div className="diff-line old">
                <span className="mark">&minus;</span>
                <span>{change.current || <em>empty</em>}</span>
              </div>
              <div className="diff-line new">
                <span className="mark">+</span>
                <span>{change.incoming}</span>
              </div>
            </div>
          </div>
        )
      })}

      {row.unchanged.length > 0 && (
        <div className="diff-context">
          unchanged here: {row.unchanged.map((f) => FIELD_LABELS[f]).join(', ')}
        </div>
      )}
    </div>
  )
}
