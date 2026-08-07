from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import REPORT_SPECS
from ..db import get_db
from ..models import AuditLog, ReportSnapshot, SnapshotRow, User
from ..schemas import SaveSnapshotRequest, SnapshotInfo

router = APIRouter(prefix="/api", tags=["snapshots"])

EDITABLE_ROLES = ("SE", "TPM", "DEV")
USER_FIELDS = ("developer", "uat_eta", "prod_eta", "comments")


def row_count(db: Session, snapshot_id: int) -> int:
    return (
        db.scalar(
            select(func.count(SnapshotRow.id)).where(SnapshotRow.snapshot_id == snapshot_id)
        )
        or 0
    )


def to_info(db: Session, snap: ReportSnapshot) -> SnapshotInfo:
    return SnapshotInfo(
        id=snap.id,
        report_kind=snap.report_kind,
        quarter=snap.quarter,
        role=snap.role,
        author_email=snap.author_email,
        author_name=snap.author_name,
        label=snap.label,
        based_on_id=snap.based_on_id,
        created_at=snap.created_at,
        row_count=row_count(db, snap.id),
    )


def latest_snapshot(db: Session, kind: str, quarter: str, role: str) -> ReportSnapshot | None:
    return db.scalar(
        select(ReportSnapshot)
        .where(
            ReportSnapshot.report_kind == kind,
            ReportSnapshot.quarter == quarter,
            ReportSnapshot.role == role,
        )
        .order_by(ReportSnapshot.id.desc())
        .limit(1)
    )


def newest_snapshot(db: Session, kind: str, quarter: str) -> ReportSnapshot | None:
    """Most recent save from any role, used to show ranks on the live view."""
    return db.scalar(
        select(ReportSnapshot)
        .where(ReportSnapshot.report_kind == kind, ReportSnapshot.quarter == quarter)
        .order_by(ReportSnapshot.id.desc())
        .limit(1)
    )


def snapshot_values(db: Session, snapshot_id: int) -> dict[tuple[str, str], SnapshotRow]:
    return {
        (r.sheet, r.key): r
        for r in db.scalars(select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id))
    }


@router.get("/reports/{kind}/{quarter}/snapshots", response_model=list[SnapshotInfo])
def list_snapshots(
    kind: str,
    quarter: str,
    role: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    stmt = (
        select(ReportSnapshot)
        .where(ReportSnapshot.report_kind == kind, ReportSnapshot.quarter == quarter)
        .order_by(ReportSnapshot.created_at.desc())
    )
    if role:
        stmt = stmt.where(ReportSnapshot.role == role.upper())
    return [to_info(db, s) for s in db.scalars(stmt)]


@router.post("/reports/{kind}/{quarter}/snapshots", response_model=SnapshotInfo)
def save_snapshot(
    kind: str, quarter: str, body: SaveSnapshotRequest, db: Session = Depends(get_db)
):
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")

    email = body.author_email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        raise HTTPException(status_code=404, detail=f"{body.author_email} is not a known user")
    if user.role not in EDITABLE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{user.email} is in the {user.role} group, which cannot save table changes. "
                "Add this address to the System Engineer, TPM, or Developer group."
            ),
        )

    base = (
        db.get(ReportSnapshot, body.based_on_id)
        if body.based_on_id
        else latest_snapshot(db, kind, quarter, user.role)
    )
    previous = snapshot_values(db, base.id) if base else {}

    snap = ReportSnapshot(
        report_kind=kind,
        quarter=quarter,
        role=user.role,
        author_email=user.email,
        author_name=user.name,
        label=body.label.strip(),
        based_on_id=base.id if base else None,
    )
    db.add(snap)
    db.flush()

    kept = 0
    for row in body.rows:
        has_text = any(getattr(row, f).strip() for f in USER_FIELDS)
        if not has_text and row.rank <= 0:
            continue
        db.add(
            SnapshotRow(
                snapshot_id=snap.id,
                sheet=row.sheet,
                key=row.key,
                rank=row.rank,
                developer=row.developer,
                uat_eta=row.uat_eta,
                prod_eta=row.prod_eta,
                comments=row.comments,
            )
        )
        kept += 1

        old = previous.get((row.sheet, row.key))
        for field in (*USER_FIELDS, "rank"):
            before = getattr(old, field) if old else ("" if field != "rank" else 0)
            after = getattr(row, field)
            if str(before or "") != str(after or ""):
                db.add(
                    AuditLog(
                        actor=user.email,
                        role=user.role,
                        snapshot_id=snap.id,
                        quarter=quarter,
                        report_kind=kind,
                        sheet=row.sheet,
                        backlog_key=row.key,
                        field=field,
                        old_value=str(before or ""),
                        new_value=str(after or ""),
                    )
                )

    db.commit()
    return to_info(db, snap)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotInfo)
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    snap = db.get(ReportSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return to_info(db, snap)


@router.delete("/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    snap = db.get(ReportSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    for row in db.scalars(select(SnapshotRow).where(SnapshotRow.snapshot_id == snapshot_id)):
        db.delete(row)
    db.delete(snap)
    db.commit()
    return {"deleted": snapshot_id}
