"""Persist Jira rows without ever touching user-owned data.

A sync only writes BacklogSnapshot. Overrides and ranks live in separate tables,
so preserving user input is structural rather than a conditional we could get wrong.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BacklogSnapshot, Report

# Jira intermittently returns short result sets, so a key must be absent from this
# many consecutive syncs before it counts as genuinely removed from the backlog.
ARCHIVE_AFTER_MISSING_SYNCS = 2

SNAPSHOT_FIELDS = [
    "region", "domain", "release", "release_title", "ndp", "ndp_status",
    "ndp_deploy_date", "summary", "issue_type", "status", "assignee", "reporter",
    "priority", "biz_domain", "req_qtr", "labels", "backlog_source", "est_h", "spent_h",
]


def apply_snapshot(db: Session, report_kind: str, quarter: str, rows: list[dict]) -> dict:
    """Upsert rows and archive keys Jira has omitted two syncs in a row."""
    now = datetime.now()

    existing = {
        (s.sheet, s.key): s
        for s in db.scalars(
            select(BacklogSnapshot).where(
                BacklogSnapshot.report_kind == report_kind,
                BacklogSnapshot.quarter == quarter,
            )
        )
    }

    seen: set[tuple[str, str]] = set()
    inserted = updated = 0

    for row in rows:
        ident = (row["sheet"], row["key"])
        seen.add(ident)
        snap = existing.get(ident)
        if snap is None:
            snap = BacklogSnapshot(
                report_kind=report_kind, quarter=quarter, sheet=row["sheet"], key=row["key"]
            )
            db.add(snap)
            inserted += 1
        else:
            updated += 1
        for field in SNAPSHOT_FIELDS:
            setattr(snap, field, row[field])
        snap.archived = False
        snap.missing_streak = 0
        snap.last_seen_at = now

    missing = [ident for ident in existing if ident not in seen]
    archived = 0
    for ident in missing:
        snap = existing[ident]
        snap.missing_streak = (snap.missing_streak or 0) + 1
        if snap.missing_streak >= ARCHIVE_AFTER_MISSING_SYNCS and not snap.archived:
            snap.archived = True
            archived += 1

    pending = [i for i in missing if not existing[i].archived]
    suspect = bool(pending)

    report = db.scalar(
        select(Report).where(Report.kind == report_kind, Report.quarter == quarter)
    )
    if report is None:
        report = Report(kind=report_kind, quarter=quarter)
        db.add(report)
    report.last_jira_sync_at = now
    report.last_sync_status = "partial" if suspect else "ok"
    report.last_sync_error = (
        f"Jira did not return {len(pending)} previously known row(s). They are kept "
        "for now and will be archived only if the next update also omits them."
        if suspect
        else None
    )

    db.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "archived": archived,
        "total": len(rows),
        "suspect": suspect,
        "missing": len(pending),
    }
