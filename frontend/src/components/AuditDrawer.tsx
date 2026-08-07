import { useEffect, useState } from 'react'

import { getAudit } from '../api'
import type { AuditEntry, BacklogRow } from '../types'

export default function AuditDrawer({ row, onClose }: { row: BacklogRow; onClose: () => void }) {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getAudit(row.id)
      .then(setEntries)
      .catch((e) => setError((e as Error).message))
  }, [row.id])

  return (
    <aside className="drawer">
      <div className="toolbar">
        <h3>{row.key} history</h3>
        <div className="spacer" />
        <button onClick={onClose}>Close</button>
      </div>
      <p className="muted">{row.summary}</p>
      {error && <div className="error">{error}</div>}
      {entries.length === 0 && !error && <p className="muted">No edits recorded yet.</p>}
      <table>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td className="muted">{new Date(e.changed_at).toLocaleString()}</td>
              <td>
                <strong>{e.field}</strong>
                <div className="muted">
                  {e.old_value || '(empty)'} &rarr; {e.new_value || '(empty)'}
                </div>
                <div className="muted">
                  {e.role ? `${e.role} - ` : ''}
                  {e.actor} &middot; {e.sheet}
                  {e.snapshot_id ? ` \u00b7 snapshot ${e.snapshot_id}` : ''}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </aside>
  )
}
