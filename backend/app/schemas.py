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
    comments: str = ""


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
    comments: str = ""


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
