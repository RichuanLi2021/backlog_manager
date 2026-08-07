import { useEffect, useState } from 'react'

import { addUser, deleteUser, getAdminState, listUsers } from '../api'
import { ROLE_LABELS, type Role, type UserInfo } from '../types'

const GROUPS: { role: Role; label: string; hint: string }[] = [
  { role: 'SE', label: 'System Engineer', hint: 'Saves changes as "Save as SE"' },
  { role: 'TPM', label: 'TPM', hint: 'Saves changes as "Save as TPM"' },
  { role: 'DEV', label: 'Developer', hint: 'Saves changes as "Save as DEV"' },
]

export default function UsersPage() {
  const [users, setUsers] = useState<UserInfo[]>([])
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('SE')
  const [error, setError] = useState<string | null>(null)

  // The passphrase is held in memory only, so it is gone when the tab closes.
  const [adminKey, setAdminKey] = useState('')
  const [keyConfigured, setKeyConfigured] = useState(true)
  const [unlocking, setUnlocking] = useState(false)
  const [typedKey, setTypedKey] = useState('')

  const unlocked = adminKey !== ''

  const load = () =>
    listUsers()
      .then(setUsers)
      .catch((e) => setError((e as Error).message))

  useEffect(() => {
    load()
    getAdminState()
      .then((s) => setKeyConfigured(s.configured))
      .catch(() => setKeyConfigured(false))
  }, [])

  const unlock = async () => {
    setError(null)
    try {
      const state = await getAdminState(typedKey)
      if (!state.unlocked) {
        setError('Wrong admin passphrase.')
        return
      }
      setAdminKey(typedKey)
      setTypedKey('')
      setUnlocking(false)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const submit = async () => {
    setError(null)
    try {
      await addUser(email.trim(), name.trim(), role, adminKey)
      setEmail('')
      setName('')
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const remove = async (user: UserInfo) => {
    if (!window.confirm(`Remove ${user.email} from ${ROLE_LABELS[user.role]}?`)) return
    try {
      await deleteUser(user.id, adminKey)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <strong>Users and groups</strong>
        <span className="muted">
          Group membership decides which Save button a person sees when they edit a table.
        </span>
        <div className="admin-lock">
          {unlocked ? (
            <>
              <span className="badge editing">Admin unlocked</span>
              <button onClick={() => setAdminKey('')}>Lock</button>
            </>
          ) : unlocking ? (
            <>
              <input
                autoFocus
                type="password"
                placeholder="Admin passphrase"
                value={typedKey}
                onChange={(e) => setTypedKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') unlock()
                  if (e.key === 'Escape') setUnlocking(false)
                }}
              />
              <button className="primary" onClick={unlock} disabled={!typedKey}>
                Unlock
              </button>
              <button onClick={() => setUnlocking(false)}>Cancel</button>
            </>
          ) : (
            <button onClick={() => setUnlocking(true)} disabled={!keyConfigured}>
              Unlock admin
            </button>
          )}
        </div>
      </div>

      {!keyConfigured && (
        <div className="error">
          No admin passphrase is set, so groups cannot be changed. Add ADMIN_KEY=... to
          backlog_manager/backend/.env and restart the API.
        </div>
      )}

      {unlocked ? (
        <div className="card" style={{ padding: 14 }}>
          <div className="toolbar">
            <input
              placeholder="name@tdsynnex.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ minWidth: 260 }}
            />
            <input
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ minWidth: 200 }}
            />
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {GROUPS.map((g) => (
                <option key={g.role} value={g.role}>
                  {g.label}
                </option>
              ))}
            </select>
            <button className="primary" onClick={submit} disabled={!email.trim()}>
              Add to group
            </button>
          </div>
        </div>
      ) : (
        keyConfigured && (
          <div className="muted">
            This list is read-only. Click "Unlock admin" and enter the passphrase to add or
            remove members.
          </div>
        )
      )}

      {error && <div className="error">{error}</div>}

      <div className="group-grid">
        {GROUPS.map((g) => {
          const members = users.filter((u) => u.role === g.role)
          return (
            <div className="card report-card" key={g.role}>
              <h2>{g.label}</h2>
              <div className="meta">{g.hint}</div>
              {members.length === 0 && <div className="muted">No members yet.</div>}
              {members.map((u) => (
                <div className="member" key={u.id}>
                  <div>
                    <strong>{u.name || u.email}</strong>
                    {u.name && <div className="muted">{u.email}</div>}
                  </div>
                  {unlocked && <button onClick={() => remove(u)}>Remove</button>}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
