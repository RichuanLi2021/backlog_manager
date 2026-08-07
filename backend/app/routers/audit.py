from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, BacklogSnapshot
from ..schemas import AuditEntry

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditEntry])
def get_audit(
    backlog_id: int | None = Query(default=None),
    key: str | None = Query(default=None),
    snapshot_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
):
    if backlog_id is not None:
        snap = db.get(BacklogSnapshot, backlog_id)
        if snap is None:
            raise HTTPException(status_code=404, detail="backlog item not found")
        key = snap.key

    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if key:
        stmt = stmt.where(AuditLog.backlog_key == key)
    if snapshot_id is not None:
        stmt = stmt.where(AuditLog.snapshot_id == snapshot_id)
    return [AuditEntry.model_validate(a, from_attributes=True) for a in db.scalars(stmt)]
