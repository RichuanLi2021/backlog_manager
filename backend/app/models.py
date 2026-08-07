from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("kind", "quarter", name="uq_report_kind_quarter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    quarter: Mapped[str] = mapped_column(String(16), index=True)
    last_jira_sync_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_sync_status: Mapped[str] = mapped_column(String(32), default="never")
    last_sync_error: Mapped[str | None] = mapped_column(Text, default=None)


class BacklogSnapshot(Base):
    """Jira-owned data. Rewritten on every sync; holds no user input."""

    __tablename__ = "backlog_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "report_kind", "quarter", "sheet", "key", name="uq_snapshot_scope_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_kind: Mapped[str] = mapped_column(String(16), index=True)
    quarter: Mapped[str] = mapped_column(String(16), index=True)
    sheet: Mapped[str] = mapped_column(String(32), index=True)
    region: Mapped[str] = mapped_column(String(8))
    domain: Mapped[str] = mapped_column(String(16))

    key: Mapped[str] = mapped_column(String(32), index=True)
    release: Mapped[str] = mapped_column(String(64), default="")
    release_title: Mapped[str] = mapped_column(Text, default="")
    ndp: Mapped[str] = mapped_column(String(64), default="")
    ndp_status: Mapped[str] = mapped_column(String(64), default="")
    ndp_deploy_date: Mapped[str] = mapped_column(String(32), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    issue_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(64), default="")
    assignee: Mapped[str] = mapped_column(String(128), default="")
    reporter: Mapped[str] = mapped_column(String(128), default="")
    priority: Mapped[str] = mapped_column(String(32), default="")
    biz_domain: Mapped[str] = mapped_column(String(64), default="")
    req_qtr: Mapped[str] = mapped_column(String(64), default="")
    labels: Mapped[str] = mapped_column(Text, default="")
    backlog_source: Mapped[str] = mapped_column(String(128), default="")
    est_h: Mapped[float] = mapped_column(Float, default=0.0)
    spent_h: Mapped[float] = mapped_column(Float, default=0.0)

    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Consecutive syncs in which Jira did not return this key. Archiving waits for
    # two so a single incomplete Jira response cannot flag live backlogs as stale.
    missing_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class User(Base):
    """Membership of the three editing groups, plus admins."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(8), index=True)  # SE | TPM | DEV | ADMIN
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ReportSnapshot(Base):
    """One saved table state, owned by the role of the person who saved it."""

    __tablename__ = "report_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_kind: Mapped[str] = mapped_column(String(16), index=True)
    quarter: Mapped[str] = mapped_column(String(16), index=True)
    role: Mapped[str] = mapped_column(String(8), index=True)  # SE | TPM | DEV
    author_email: Mapped[str] = mapped_column(String(200))
    author_name: Mapped[str] = mapped_column(String(200), default="")
    label: Mapped[str] = mapped_column(Text, default="")
    based_on_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class SnapshotRow(Base):
    """User-entered values for one backlog inside one snapshot."""

    __tablename__ = "snapshot_rows"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "sheet", "key", name="uq_snapshot_row"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("report_snapshots.id", ondelete="CASCADE"), index=True
    )
    sheet: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(32), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    developer: Mapped[str] = mapped_column(Text, default="")
    uat_eta: Mapped[str] = mapped_column(Text, default="")
    prod_eta: Mapped[str] = mapped_column(Text, default="")
    comments: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(8), default="")
    snapshot_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    quarter: Mapped[str] = mapped_column(String(16))
    report_kind: Mapped[str] = mapped_column(String(16), default="")
    sheet: Mapped[str] = mapped_column(String(32), default="")
    backlog_key: Mapped[str] = mapped_column(String(32), index=True)
    field: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quarter: Mapped[str] = mapped_column(String(16))
    report_kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), default="running")  # running|done|failed
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
