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
  /** The IT Comment. Named for the single comment column it was before the split. */
  comments: string
  tpm_comment: string
  package: string
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
  /** The IT Comment. Named for the single comment column it was before the split. */
  comments: string
  tpm_comment: string
  package: string
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

/** green / yellow / red while in the deploy pipeline; see services/ndp_age.py. */
export type NdpAgeLevel = 'green' | 'yellow' | 'red' | 'waiting' | 'done' | 'unknown'

export interface TreeNdp {
  ndp: string
  status: string
  deploy_date: string
  backlogs: TreeBacklog[]
  age_level: NdpAgeLevel
  age_days: number | null
  status_since: string | null
  age_source: string
  live_status: string
}

export interface NdpAgeRules {
  warn_days: number
  flag_days: number
  done_statuses: string[]
  unsubmitted_statuses: string[]
}

export interface NdpAgeRefresh {
  ndps: number
  from_jira: number
  observed: number
  error: string | null
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

export type EditableField =
  | 'rank'
  | 'package'
  | 'developer'
  | 'uat_eta'
  | 'prod_eta'
  | 'comments'
  | 'tpm_comment'

export const FIELD_LABELS: Record<EditableField, string> = {
  rank: 'Rank',
  package: 'Package',
  developer: 'Developer',
  uat_eta: 'UAT ETA',
  prod_eta: 'PROD ETA',
  comments: 'IT Comment',
  tpm_comment: 'TPM Comment',
}

export interface AnalyzedChange {
  field: EditableField
  current: string
  incoming: string
  state: 'added' | 'changed'
}

export interface AnalyzedRow {
  sheet: string
  key: string
  summary: string
  status: string
  archived: boolean
  source_sheet: string
  source_row: number
  changes: AnalyzedChange[]
  unchanged: EditableField[]
}

export interface AnalyzedSheet {
  name: string
  rows_read: number
  matched: number
  target_sheets: string[]
}

export interface IdenticalRow {
  sheet: string
  key: string
  summary: string
  fields: EditableField[]
}

/** What an upload is measured against: live Jira, or one role's latest save. */
export type CompareWith = 'LIVE' | EditableRole

export interface AnalysisResult {
  filename: string
  report_kind: string
  quarter: string
  target_role: EditableRole
  compare_with: CompareWith
  baseline_label: string
  author: UserInfo
  baseline: SnapshotInfo | null
  detected_columns: Record<string, string>
  sheets_read: string[]
  sheets_ignored: string[]
  sheet_summary: AnalyzedSheet[]
  rows_read: number
  keys_matched: number
  unmatched_keys: string[]
  unchanged_cells: number
  rows: AnalyzedRow[]
  identical: IdenticalRow[]
  added_cells: number
  changed_cells: number
  stale_jira_cells: number
  elapsed_ms: number
  warnings: string[]
}

export interface ApplyChange {
  sheet: string
  key: string
  field: EditableField
  value: string
}

/** Jira-owned columns, in the order they appear in the report. */
export const JIRA_FIELD_LABELS: Record<string, string> = {
  status: 'Status',
  ndp: 'NDP',
  ndp_status: 'NDP Status',
  ndp_deploy_date: 'NDP Deploy Date',
  release: 'Release',
  release_title: 'Release Title',
  summary: 'Summary',
  issue_type: 'Issue Type',
  assignee: 'Assignee',
  reporter: 'Reporter',
  priority: 'Priority',
  biz_domain: 'Biz Domain',
  req_qtr: 'Req Qtr',
  labels: 'Labels',
  backlog_source: 'Backlog Source',
  est_h: 'Est h',
  spent_h: 'Spent h',
}

export interface FileFieldChange {
  sheet: string
  row: number
  key: string
  field: string
  label: string
  in_file: string
  current: string
}

export interface FileNewRow {
  sheet: string
  key: string
  summary: string
  status: string
  ndp: string
  ndp_status: string
}

export interface FileGoneRow {
  sheet: string
  row: number
  key: string
  reason: string
}

export interface FileSheetPlan {
  name: string
  resolved_to: string | null
  header_row: number
  rows_in_file: number
  matched: number
  columns: Record<string, string>
}

export interface FileUpdatePlan {
  filename: string
  report_kind: string
  quarter: string
  last_jira_sync_at: string | null
  sheets: FileSheetPlan[]
  sheets_ignored: string[]
  changes: FileFieldChange[]
  field_counts: Record<string, number>
  new_rows: FileNewRow[]
  gone_rows: FileGoneRow[]
  unchanged_cells: number
  warnings: string[]
  /** Status counts, file against Jira now; present when Status was compared. */
  progress: FileProgress | null
  /** One line per tab the standard-layout pass rearranges. */
  layout_changes: string[]
}

export interface StatusCount {
  status: string
  in_file: number
  now: number
}

export interface FileProgress {
  backlogs: StatusCount[]
  ndps: StatusCount[]
  backlogs_in_file: number
  backlogs_now: number
}

export interface SharePointFile {
  name: string
  size: number
  modified: string
  /** Changes whenever the file does; an update is refused if it no longer matches. */
  token: string
  kind: string | null
  matches_report: boolean
  open_here: boolean
  cloud_only: boolean
}

export interface SharePointFolder {
  quarter: string
  found: boolean
  folder: string | null
  searched: string[]
  web_url: string
  files: SharePointFile[]
  last_jira_sync_at: string | null
}

export interface SharePointScan {
  file: SharePointFile
  plan: FileUpdatePlan
}

export interface SharePointUpdateResult {
  file: SharePointFile
  cells_updated: number
  rows_added: number
  rows_flagged: number
  backup: string
}
