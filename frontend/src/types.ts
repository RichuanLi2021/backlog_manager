export type ReportKind = 'AR_GL' | 'AR' | 'GL'

export interface ReportInfo {
  kind: string
  quarter: string
  last_jira_sync_at: string | null
  last_sync_status: string
  last_sync_error: string | null
  item_count: number
}

export interface BacklogRow {
  id: number
  sheet: string
  region: string
  domain: string
  key: string
  release: string
  release_title: string
  ndp: string
  ndp_status: string
  ndp_deploy_date: string
  summary: string
  issue_type: string
  status: string
  assignee: string
  reporter: string
  priority: string
  biz_domain: string
  req_qtr: string
  labels: string
  backlog_source: string
  est_h: number
  spent_h: number
  archived: boolean
  rank: number
  developer: string
  uat_eta: string
  prod_eta: string
  comments: string
}

export type Role = 'SE' | 'TPM' | 'DEV'
export type EditableRole = Role
export type ViewMode = 'LIVE' | EditableRole

export const ROLE_LABELS: Record<Role, string> = {
  SE: 'System Engineer',
  TPM: 'TPM',
  DEV: 'Developer',
}

export interface UserInfo {
  id: number
  email: string
  name: string
  role: Role
}

export interface SnapshotInfo {
  id: number
  report_kind: string
  quarter: string
  role: EditableRole
  author_email: string
  author_name: string
  label: string
  based_on_id: number | null
  created_at: string
  row_count: number
}

export interface SnapshotRowInput {
  sheet: string
  key: string
  rank: number
  developer: string
  uat_eta: string
  prod_eta: string
  comments: string
}

export interface ReportDetail {
  report: ReportInfo
  sheets: string[]
  items: BacklogRow[]
  snapshot: SnapshotInfo | null
}

export interface SyncStatus {
  id: number
  quarter: string
  report_kind: string
  state: 'running' | 'done' | 'failed'
  message: string
  started_at: string
  finished_at: string | null
  estimate_seconds: number
  elapsed_seconds: number
}

export interface TreeBacklog {
  id: number
  key: string
  summary: string
  status: string
  assignee: string
  developer: string
  est_h: number
  spent_h: number
}

export interface TreeNdp {
  ndp: string
  status: string
  deploy_date: string
  backlogs: TreeBacklog[]
}

export interface TreeRelease {
  release: string
  title: string
  ndps: TreeNdp[]
}

export interface TreeSheet {
  sheet: string
  releases: TreeRelease[]
}

export interface AuditEntry {
  id: number
  actor: string
  role: string
  snapshot_id: number | null
  backlog_key: string
  report_kind: string
  sheet: string
  field: string
  old_value: string
  new_value: string
  changed_at: string
}

export type EditableField = 'rank' | 'developer' | 'uat_eta' | 'prod_eta' | 'comments'
