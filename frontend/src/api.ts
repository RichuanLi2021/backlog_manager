import type {
  AuditEntry,
  BacklogRow,
  EditableRole,
  ReportDetail,
  ReportInfo,
  Role,
  SnapshotInfo,
  SnapshotRowInput,
  SyncStatus,
  TreeSheet,
  UserInfo,
  ViewMode,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

function viewQuery(view: ViewMode, snapshotId: number | null): string {
  if (snapshotId != null) return `?snapshot_id=${snapshotId}`
  return view === 'LIVE' ? '' : `?role=${view}`
}

export const listReports = (quarter: string) =>
  request<ReportInfo[]>(`/reports?quarter=${encodeURIComponent(quarter)}`)

export const listQuarters = () => request<string[]>('/quarters')

export const getReport = (
  kind: string,
  quarter: string,
  view: ViewMode = 'LIVE',
  snapshotId: number | null = null,
) => request<ReportDetail>(`/reports/${kind}/${quarter}${viewQuery(view, snapshotId)}`)

export const getTree = (
  kind: string,
  quarter: string,
  view: ViewMode = 'LIVE',
  snapshotId: number | null = null,
) => request<TreeSheet[]>(`/reports/${kind}/${quarter}/tree${viewQuery(view, snapshotId)}`)

export const refreshReport = (kind: string, quarter: string) =>
  request<SyncStatus>(`/reports/${kind}/${quarter}/refresh`, { method: 'POST' })

export function exportUrl(
  kind: string,
  quarter: string,
  view: ViewMode,
  snapshotId: number | null,
  sheet?: string,
  status?: string,
): string {
  const params = new URLSearchParams()
  if (snapshotId != null) params.set('snapshot_id', String(snapshotId))
  else if (view !== 'LIVE') params.set('role', view)
  if (sheet) params.set('sheet', sheet)
  if (status) params.set('status', status)
  return `/api/reports/${kind}/${quarter}/export?${params.toString()}`
}

export const getSyncStatus = (kind?: string) =>
  request<SyncStatus | null>(`/sync/status${kind ? `?kind=${kind}` : ''}`)

export const listSnapshots = (kind: string, quarter: string, role?: EditableRole) =>
  request<SnapshotInfo[]>(
    `/reports/${kind}/${quarter}/snapshots${role ? `?role=${role}` : ''}`,
  )

export const saveSnapshot = (
  kind: string,
  quarter: string,
  body: {
    author_email: string
    label?: string
    based_on_id?: number | null
    rows: SnapshotRowInput[]
  },
) =>
  request<SnapshotInfo>(`/reports/${kind}/${quarter}/snapshots`, {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const deleteSnapshot = (id: number) =>
  request<{ deleted: number }>(`/snapshots/${id}`, { method: 'DELETE' })

export const identifyUser = (identifier: string) =>
  request<UserInfo>('/users/identify', {
    method: 'POST',
    body: JSON.stringify({ identifier }),
  })

export const listUsers = () => request<UserInfo[]>('/users')

export const getAdminState = (key = '') =>
  request<{ configured: boolean; unlocked: boolean }>('/users/admin', {
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': key },
  })

export const addUser = (email: string, name: string, role: Role, key: string) =>
  request<UserInfo>('/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': key },
    body: JSON.stringify({ email, name, role }),
  })

export const deleteUser = (id: number, key: string) =>
  request<{ deleted: number }>(`/users/${id}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': key },
  })

export const getAudit = (backlogId: number) =>
  request<AuditEntry[]>(`/audit?backlog_id=${backlogId}`)

export type { BacklogRow }
