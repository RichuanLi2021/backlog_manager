import { useEffect, useState } from 'react'

interface Props {
  value: string
  editing: boolean
  changed?: boolean
  numeric?: boolean
  onCommit: (next: string) => void
}

export default function EditableCell({ value, editing, changed, numeric, onCommit }: Props) {
  const [active, setActive] = useState(false)
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    if (!active) setDraft(value)
  }, [value, active])

  useEffect(() => {
    if (!editing) setActive(false)
  }, [editing])

  const commit = () => {
    setActive(false)
    if (draft !== value) onCommit(draft)
  }

  const className = [editing ? 'editable' : '', changed ? 'changed' : '', numeric ? 'numeric' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <td
      className={className || undefined}
      onClick={() => editing && setActive(true)}
      title={editing ? value || 'Click to edit' : value}
    >
      {active ? (
        <input
          autoFocus
          type={numeric ? 'number' : 'text'}
          min={numeric ? 0 : undefined}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') {
              setDraft(value)
              setActive(false)
            }
          }}
        />
      ) : (
        value || '\u00a0'
      )}
    </td>
  )
}
