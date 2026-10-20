import type {
  AnalysisResult,
  ApplyChange,
  // FileUpdatePlan is reused for the write-back preview: same shape, other direction.
  AuditEntry,
  BacklogRow,
  CompareWith,
  EditableRole,
  FileUpdatePlan,
  NdpAgeRefresh,
  NdpAgeRules,
  SharePointFolder,
  SharePointScan,
  SharePointUpdateResult,
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

// Multipart, so the browser has to set Content-Type itself with the part boundary.
async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, { method: 'POST', body: form })
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

export const addQuarter = (quarter: string) =>
  request<string[]>('/quarters', { method: 'POST', body: JSON.stringify({ quarter }) })

export const deleteQuarter = (quarter: string) =>
  request<string[]>(`/quarters/${encodeURIComponent(quarter)}`, { method: 'DELETE' })

/** 2026Q3 -> 2026Q4, 2026Q4 -> 2027Q1. Empty when the name is not a quarter. */
export function nextQuarter(quarter: string): string {
  const parts = /^(\d{4})Q([1-4])$/.exec(quarter)
  if (!parts) return ''
  const year = Number(parts[1])
  const number = Number(parts[2])
  return number === 4 ? `${year + 1}Q1` : `${year}Q${number + 1}`
}

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

export const getNdpAgeRules = () => request<NdpAgeRules>('/ndp-age-rules')

/** Re-read NDP status dates from Jira: seconds, not the minutes of a full sync. */
export const refreshNdpAges = (kind: string, quarter: string) =>
  request<NdpAgeRefresh>(`/reports/${kind}/${quarter}/ndp-ages`, { method: 'POST' })

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

export function analyzeSpreadsheet(
  kind: string,
  quarter: string,
  file: File,
  authorEmail: string,
  targetRole: EditableRole,
  compareWith: CompareWith,
) {
  const form = new FormData()
  form.append('file', file)
  form.append('author_email', authorEmail)
  form.append('target_role', targetRole)
  form.append('compare_with', compareWith)
  return upload<AnalysisResult>(`/reports/${kind}/${quarter}/analyze`, form)
}

export const applyAnalysis = (
  kind: string,
  quarter: string,
  body: {
    author_email: string
    target_role: EditableRole
    label?: string
    based_on_id?: number | null
    changes: ApplyChange[]
  },
) =>
  request<SnapshotInfo>(`/reports/${kind}/${quarter}/analyze/apply`, {
    method: 'POST',
    body: JSON.stringify(body),
  })

export function planFileRefresh(
  kind: string,
  quarter: string,
  file: File,
  authorEmail: string,
) {
  const form = new FormData()
  form.append('file', file)
  form.append('author_email', authorEmail)
  return upload<FileUpdatePlan>(`/reports/${kind}/${quarter}/refresh-file`, form)
}

/** Posts a form and hands the workbook that comes back to the browser to save. */
async function saveResponse(path: string, form: FormData): Promise<string> {
  const res = await fetch(`/api${path}`, { method: 'POST', body: form })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText}`)
  }

  const disposition = res.headers.get('Content-Disposition') ?? ''
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? 'backlog_updated.xlsx'
  const url = URL.createObjectURL(await res.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return name
}

export function downloadRefreshedFile(
  kind: string,
  quarter: string,
  file: File,
  authorEmail: string,
  fields: string[],
  addNew: boolean,
  flagGone: boolean,
): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  form.append('author_email', authorEmail)
  form.append('fields', fields.join(','))
  form.append('add_new', String(addNew))
  form.append('flag_gone', String(flagGone))
  return saveResponse(`/reports/${kind}/${quarter}/refresh-file/download`, form)
}

function writebackForm(
  file: File,
  authorEmail: string,
  targetRole: EditableRole,
  changes: ApplyChange[],
): FormData {
  const form = new FormData()
  form.append('file', file)
  form.append('author_email', authorEmail)
  form.append('target_role', targetRole)
  form.append('changes', JSON.stringify(changes))
  return form
}

/** What the uploaded workbook itself would look like once the changes are applied. */
export const previewUpdatedFile = (
  kind: string,
  quarter: string,
  file: File,
  authorEmail: string,
  targetRole: EditableRole,
  changes: ApplyChange[],
) =>
  upload<FileUpdatePlan>(
    `/reports/${kind}/${quarter}/analyze/file-preview`,
    writebackForm(file, authorEmail, targetRole, changes),
  )

export const downloadUpdatedFile = (
  kind: string,
  quarter: string,
  file: File,
  authorEmail: string,
  targetRole: EditableRole,
  changes: ApplyChange[],
) =>
  saveResponse(
    `/reports/${kind}/${quarter}/analyze/file-download`,
    writebackForm(file, authorEmail, targetRole, changes),
  )

export const getSharePointFolder = (kind: string, quarter: string) =>
  request<SharePointFolder>(`/sharepoint/${kind}/${quarter}`)

export const scanSharePointFile = (kind: string, quarter: string, name: string) =>
  request<SharePointScan>(`/sharepoint/${kind}/${quarter}/scan`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })

export const updateSharePointFile = (
  kind: string,
  quarter: string,
  body: {
    name: string
    token: string
    author_email: string
    fields: string[]
    add_new: boolean
    flag_gone: boolean
  },
) =>
  request<SharePointUpdateResult>(`/sharepoint/${kind}/${quarter}/update`, {
    method: 'POST',
    body: JSON.stringify(body),
  })

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
