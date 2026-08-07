import { useState } from 'react'

import { identifyUser } from '../api'
import { ROLE_LABELS, type UserInfo } from '../types'

interface Props {
  onIdentified: (user: UserInfo) => void
  onCancel: () => void
}

export default function IdentityPrompt({ onIdentified, onCancel }: Props) {
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [confirmed, setConfirmed] = useState<UserInfo | null>(null)

  const submit = async () => {
    if (!value.trim()) return
    setChecking(true)
    setError(null)
    try {
      setConfirmed(await identifyUser(value.trim()))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  if (confirmed) {
    return (
      <div className="modal-backdrop" onClick={onCancel}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h3>
            Edit as {confirmed.role}: {confirmed.name || confirmed.email}
          </h3>
          <p className="muted">
            Recognized as {ROLE_LABELS[confirmed.role]}. Your changes will be saved as a{' '}
            {confirmed.role} snapshot.
          </p>
          <div className="modal-actions">
            <button onClick={onCancel}>Cancel</button>
            <button className="primary" autoFocus onClick={() => onIdentified(confirmed)}>
              Start editing
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Please enter your name or TD SYNNEX email address:</h3>
        <input
          autoFocus
          value={value}
          placeholder="name@tdsynnex.com"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
            if (e.key === 'Escape') onCancel()
          }}
        />
        {error && <div className="error">{error}</div>}
        <div className="modal-actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={submit} disabled={checking || !value.trim()}>
            {checking ? 'Checking...' : 'Continue'}
          </button>
        </div>
      </div>
    </div>
  )
}
