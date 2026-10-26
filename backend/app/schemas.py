from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Role = Literal["SE", "TPM", "DEV", "ADMIN"]
EditableRole = Literal["SE", "TPM", "DEV"]


class ReportInfo(BaseModel):
    kind: str
    quarter: str
    last_jira_sync_at: datetime | None = None
    last_sync_status: str = "never"
    last_sync_error: str | None = None
    item_count: int = 0


class BacklogRow(BaseModel):
    id: int
    sheet: str
    region: str
    domain: str
    key: str
    release: str
    release_title: str
    ndp: str
    ndp_status: str
    ndp_deploy_date: str
    summary: str
    issue_type: str
    status: str
    assignee: str
    reporter: str
    priority: str
    biz_domain: str
    req_qtr: str
    labels: str
    backlog_source: str
    est_h: float
    spent_h: float
    archived: bool
    rank: int = 0
    developer: str = ""
    uat_eta: str = ""
    prod_eta: str = ""
    comments: str = ""  # the IT Comment
    tpm_comment: str = ""
    package: str = ""


class SnapshotInfo(BaseModel):
    id: int
    report_kind: str
    quarter: str
    role: str
    author_email: str
    author_name: str
    label: str
    based_on_id: int | None = None
    created_at: datetime
    row_count: int = 0


class ReportDetail(BaseModel):
    report: ReportInfo
    sheets: list[str]
    items: list[BacklogRow]
    snapshot: SnapshotInfo | None = None


class SnapshotRowInput(BaseModel):
    sheet: str
    key: str
    rank: int = 0
    developer: str = ""
    uat_eta: str = ""
    prod_eta: str = ""
    comments: str = ""  # the IT Comment
    tpm_comment: str = ""
    package: str = ""


class SaveSnapshotRequest(BaseModel):
    author_email: str
    label: str = ""
    based_on_id: int | None = None
    rows: list[SnapshotRowInput]


class UserInfo(BaseModel):
    id: int
    email: str
    name: str
    role: str


class UserCreate(BaseModel):
    email: str
    name: str = ""
    role: Role


class IdentifyRequest(BaseModel):
    identifier: str


class QuarterCreate(BaseModel):
    quarter: str


class AnalyzedChange(BaseModel):
    """One user-editable cell the uploaded file disagrees with."""

    field: str
    current: str
    incoming: str
    state: Literal["added", "changed"]


class AnalyzedRow(BaseModel):
    sheet: str
    key: str
    summary: str = ""
    status: str = ""
    archived: bool = False
    source_sheet: str = ""
    source_row: int = 0
    changes: list[AnalyzedChange]
    # Fields the file also filled in that already agree, kept so the diff can show
    # why a row is only partly highlighted.
    unchanged: list[str] = []


class AnalyzedSheet(BaseModel):
    """Coverage of one worksheet of the upload, so no tab is silently skipped."""

    name: str
    rows_read: int
    matched: int
    target_sheets: list[str]


class IdenticalRow(BaseModel):
    """A row the file has an opinion on that the baseline already agrees with."""

    sheet: str
    key: str
    summary: str = ""
    fields: list[str]


class AnalysisResult(BaseModel):
    """Preview of what an uploaded workbook would change, before anything is saved."""

    filename: str
    report_kind: str
    quarter: str
    target_role: EditableRole
    compare_with: str
    baseline_label: str
    author: UserInfo
    baseline: SnapshotInfo | None = None
    detected_columns: dict[str, str]
    sheets_read: list[str]
    sheets_ignored: list[str]
    sheet_summary: list[AnalyzedSheet]
    rows_read: int
    keys_matched: int
    unmatched_keys: list[str]
    unchanged_cells: int
    rows: list[AnalyzedRow]
    identical: list[IdenticalRow]
    added_cells: int = 0
    changed_cells: int = 0
    stale_jira_cells: int = 0
    elapsed_ms: int = 0
    warnings: list[str]


class FileFieldChange(BaseModel):
    """One Jira-owned cell in the uploaded file that has gone stale."""

    sheet: str
    row: int
    key: str
    field: str
    label: str
    in_file: str
    current: str


class FileNewRow(BaseModel):
    sheet: str
    key: str
    summary: str = ""
    status: str = ""
    ndp: str = ""
    ndp_status: str = ""


class FileGoneRow(BaseModel):
    sheet: str
    row: int
    key: str
    reason: str


class FileSheetPlan(BaseModel):
    name: str
    resolved_to: str | None = None
    header_row: int
    rows_in_file: int
    matched: int
    columns: dict[str, str]


class StatusCount(BaseModel):
    status: str
    in_file: int
    now: int


class FileProgress(BaseModel):
    """Where a file says things stand, against where Jira says they stand now."""

    backlogs: list[StatusCount]
    ndps: list[StatusCount]
    backlogs_in_file: int
    backlogs_now: int


class FileUpdatePlan(BaseModel):
    """What refreshing a circulated workbook from the platform would do to it."""

    filename: str
    report_kind: str
    quarter: str
    last_jira_sync_at: datetime | None = None
    sheets: list[FileSheetPlan]
    sheets_ignored: list[str]
    changes: list[FileFieldChange]
    field_counts: dict[str, int]
    new_rows: list[FileNewRow]
    gone_rows: list[FileGoneRow]
    unchanged_cells: int
    warnings: list[str]
    # Status counts, file against Jira now. Only filled when Status is being compared.
    progress: FileProgress | None = None
    # One line per tab the standard-layout pass rearranges, e.g. Comments -> IT Comment.
    layout_changes: list[str] = []


class SharePointFile(BaseModel):
    name: str
    size: int
    modified: datetime
    token: str
    kind: str | None = None
    matches_report: bool = False
    open_here: bool = False
    cloud_only: bool = False


class SharePointFolder(BaseModel):
    quarter: str
    found: bool
    folder: str | None = None
    searched: list[str]
    web_url: str
    files: list[SharePointFile]
    last_jira_sync_at: datetime | None = None


class SharePointScanRequest(BaseModel):
    name: str


class SharePointScan(BaseModel):
    file: SharePointFile
    plan: FileUpdatePlan


class SharePointUpdateRequest(BaseModel):
    name: str
    token: str
    author_email: str
    fields: list[str] = []
    add_new: bool = True
    flag_gone: bool = True


class SharePointUpdateResult(BaseModel):
    file: SharePointFile
    cells_updated: int
    rows_added: int
    rows_flagged: int
    backup: str


class ApplyChange(BaseModel):
    sheet: str
    key: str
    field: str
    value: str


class ApplyAnalysisRequest(BaseModel):
    author_email: str
    target_role: EditableRole
    label: str = ""
    based_on_id: int | None = None
    changes: list[ApplyChange]


class TreeBacklog(BaseModel):
    id: int
    key: str
    summary: str
    status: str
    assignee: str
    developer: str
    est_h: float
    spent_h: float


class TreeNdp(BaseModel):
    ndp: str
    status: str
    deploy_date: str
    backlogs: list[TreeBacklog]
    # How long the NDP has been in `status`: see services/ndp_age.py for the levels.
    age_level: str = "unknown"
    age_days: float | None = None
    status_since: datetime | None = None
    age_source: str = ""
    # Set when Jira has moved the NDP on since this report was last synced, so the
    # tree can say "Jira now: Verified" instead of a bare unknown.
    live_status: str = ""


class NdpAgeRules(BaseModel):
    warn_days: float
    flag_days: float
    done_statuses: list[str]
    unsubmitted_statuses: list[str]


class NdpAgeRefresh(BaseModel):
    ndps: int
    from_jira: int
    observed: int
    error: str | None = None


class TreeRelease(BaseModel):
    release: str
    title: str
    ndps: list[TreeNdp]


class TreeSheet(BaseModel):
    sheet: str
    releases: list[TreeRelease]


class SyncStatus(BaseModel):
    id: int
    quarter: str
    report_kind: str
    state: str
    message: str
    started_at: datetime
    finished_at: datetime | None = None
    estimate_seconds: int = 0
    elapsed_seconds: int = 0


class AuditEntry(BaseModel):
    id: int
    actor: str
    role: str
    snapshot_id: int | None = None
    backlog_key: str
    report_kind: str
    sheet: str
    field: str
    old_value: str
    new_value: str
    changed_at: datetime
