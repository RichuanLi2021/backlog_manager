"""Both spreadsheet round trips: reading a circulated file, and refreshing one.

`/analyze` and `/analyze/apply` go file -> platform: read someone else's edits and
save the accepted ones as a snapshot. `/refresh-file` and its `/download` go the
other way: rewrite the stale Jira columns of a file people are already working in.

Each direction previews before it commits. Nothing is written to the database, and
no workbook is returned, until the second call says which parts were accepted.
"""

import json
from datetime import datetime
from time import perf_counter

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import REPORT_SPECS
from ..db import get_db
from ..models import AuditLog, ReportSnapshot, SnapshotRow, User
from ..schemas import (
    AnalysisResult,
    AnalyzedSheet,
    ApplyAnalysisRequest,
    ApplyChange,
    BacklogRow,
    FileUpdatePlan,
    SnapshotInfo,
    UserInfo,
)
from ..services import spreadsheet_analyzer, spreadsheet_updater
from ..services.spreadsheet_analyzer import USER_FIELDS, AnalyzerError
from ..services.spreadsheet_layout import JIRA_FIELDS
from .reports import _report_info, _rows
from .snapshots import EDITABLE_ROLES, latest_snapshot, to_info

router = APIRouter(prefix="/api", tags=["analyzer"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

FIELD_LABELS = {
    "rank": "Rank",
    "developer": "Developer",
    "uat_eta": "UAT ETA",
    "prod_eta": "PROD ETA",
    "comments": "IT Comment",
    "tpm_comment": "TPM Comment",
    "package": "Package",
}


def _editor(db: Session, author_email: str) -> User:
    """Only members of the three editing groups may upload or apply a workbook."""
    email = (author_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="author_email is required")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"{author_email} is not in the System Engineer, TPM, or Developer "
                "groups. Ask an admin to add you on the Users page."
            ),
        )
    if user.role not in EDITABLE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{user.email} is in the {user.role} group, which cannot import a "
                "spreadsheet. Only System Engineer, TPM, and Developer members can."
            ),
        )
    return user


def _target(role: str) -> str:
    value = (role or "").strip().upper()
    if value not in EDITABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"target_role must be one of {', '.join(EDITABLE_ROLES)}",
        )
    return value


def _scope(kind: str):
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")


async def _bytes_of(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{file.filename} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    return data


def _current(db: Session, kind: str, quarter: str, snapshot=None):
    rows = _rows(db, kind, quarter, include_archived=True, snapshot=snapshot)
    if not rows:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{kind} {quarter} has no backlog rows yet. Click Update from Jira "
                "first, so the spreadsheet has something to be compared against."
            ),
        )
    return rows


LIVE = "LIVE"


def _baseline(db: Session, kind: str, quarter: str, compare_with: str, fallback: str):
    """Which state the upload is measured against: a role's latest save, or live Jira."""
    choice = (compare_with or fallback).strip().upper()
    if choice in ("", "LATEST", "REPORT"):
        choice = LIVE
    if choice != LIVE and choice not in EDITABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"compare_with must be {LIVE} or one of {', '.join(EDITABLE_ROLES)}",
        )
    if choice == LIVE:
        return LIVE, None, "Latest backlog report (live Jira)"

    snapshot = latest_snapshot(db, kind, quarter, choice)
    if snapshot is None:
        return (
            choice,
            None,
            f"{choice} View - nothing saved yet, so every value in the file is new",
        )
    label = (
        f"{choice} View - saved {snapshot.created_at:%Y-%m-%d %H:%M} by "
        f"{snapshot.author_name or snapshot.author_email}"
    )
    return choice, snapshot, label


def _stale_jira_cells(data: bytes, name: str, current, kind: str, quarter: str) -> int:
    """How far the file's Jira columns have drifted, to point at the Updater."""
    try:
        plan = spreadsheet_updater.plan_update(data, name, current, kind, quarter, None)
    except Exception:  # the file may carry no Jira columns at all
        return 0
    return len(plan.changes)


@router.post("/reports/{kind}/{quarter}/analyze", response_model=AnalysisResult)
async def analyze_spreadsheet(
    kind: str,
    quarter: str,
    file: UploadFile = File(...),
    author_email: str = Form(...),
    target_role: str = Form(...),
    compare_with: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """Read an uploaded workbook and diff it against the state it is measured from."""
    started = perf_counter()
    _scope(kind)
    user = _editor(db, author_email)
    role = _target(target_role)
    data = await _bytes_of(file)
    name = file.filename or "upload.xlsx"

    try:
        parsed = spreadsheet_analyzer.parse_workbook(data, name)
    except AnalyzerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    choice, baseline, label = _baseline(db, kind, quarter, compare_with, role)
    current = _current(db, kind, quarter, baseline)
    result = spreadsheet_analyzer.compare(parsed, current)

    return AnalysisResult(
        filename=name,
        report_kind=kind,
        quarter=quarter,
        target_role=role,
        compare_with=choice,
        baseline_label=label,
        author=UserInfo.model_validate(user, from_attributes=True),
        baseline=to_info(db, baseline) if baseline else None,
        detected_columns={
            FIELD_LABELS.get(f, f): " / ".join(labels)
            for f, labels in parsed.detected_columns.items()
            if f != "key"
        },
        sheets_read=parsed.sheets_read,
        sheets_ignored=parsed.sheets_ignored,
        sheet_summary=[
            AnalyzedSheet(
                name=tab,
                rows_read=sum(1 for r in parsed.rows if r.source_sheet == tab),
                matched=len(result.matched_by_sheet.get(tab, ())),
                target_sheets=sorted(result.targets_by_sheet.get(tab, ())),
            )
            for tab in parsed.sheets_read
        ],
        rows_read=len(parsed.rows),
        keys_matched=len(result.matched_keys),
        unmatched_keys=result.unmatched_keys,
        unchanged_cells=result.unchanged_cells,
        rows=result.rows,
        identical=result.identical,
        added_cells=sum(1 for r in result.rows for c in r.changes if c.state == "added"),
        changed_cells=sum(1 for r in result.rows for c in r.changes if c.state == "changed"),
        stale_jira_cells=_stale_jira_cells(data, name, current, kind, quarter),
        elapsed_ms=int((perf_counter() - started) * 1000),
        warnings=parsed.warnings + result.warnings,
    )


def _accepted(changes: list[ApplyChange]) -> dict[tuple[str, str], dict[str, str | int]]:
    """The subset of the diff the reviewer kept, keyed by the row it belongs to."""
    out: dict[tuple[str, str], dict[str, str | int]] = {}
    for change in changes:
        if change.field not in USER_FIELDS:
            raise HTTPException(status_code=400, detail=f"unknown field: {change.field}")
        value: str | int = change.value
        if change.field == "rank":
            try:
                value = max(0, int(float(change.value)))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"{change.key}: rank '{change.value}' is not a number.",
                ) from None
        out.setdefault((change.sheet, change.key), {})[change.field] = value
    if not out:
        raise HTTPException(status_code=400, detail="No changes were selected.")
    return out


def _base_snapshot(db: Session, kind: str, quarter: str, role: str, based_on_id: int | None):
    if based_on_id is None:
        return latest_snapshot(db, kind, quarter, role)
    base = db.get(ReportSnapshot, based_on_id)
    if base is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    if (base.report_kind, base.quarter, base.role) != (kind, quarter, role):
        raise HTTPException(
            status_code=400,
            detail=(
                f"snapshot {base.id} belongs to {base.report_kind} {base.quarter} "
                f"{base.role}, not {kind} {quarter} {role}."
            ),
        )
    return base


def _merged(db: Session, kind: str, quarter: str, base, accepted) -> list[BacklogRow]:
    """The target view with the accepted values laid over it — the agreed outcome.

    The same rows drive both destinations: the snapshot written to the database and
    the workbook handed back to whoever uploaded it, so the file and the view cannot
    end up disagreeing about what was decided.
    """
    rows = _rows(db, kind, quarter, include_archived=True, snapshot=base)
    known = {(row.sheet, row.key) for row in rows}
    unknown = sorted({f"{s}/{k}" for s, k in accepted if (s, k) not in known})
    if unknown:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(unknown)} row(s) are no longer in this report: "
                f"{', '.join(unknown[:5])}. Re-run the analysis and try again."
            ),
        )
    for row in rows:
        for name, value in accepted.get((row.sheet, row.key), {}).items():
            setattr(row, name, value)
    return rows


@router.post("/reports/{kind}/{quarter}/analyze/apply", response_model=SnapshotInfo)
def apply_analysis(
    kind: str, quarter: str, body: ApplyAnalysisRequest, db: Session = Depends(get_db)
):
    """Save the accepted changes as a new snapshot of the chosen role's view."""
    _scope(kind)
    user = _editor(db, body.author_email)
    role = _target(body.target_role)

    accepted = _accepted(body.changes)
    base = _base_snapshot(db, kind, quarter, role, body.based_on_id)
    # The whole view is rewritten, so the snapshot stays complete on its own: rows the
    # upload never touched keep the values and order the target view already had.
    current = _rows(db, kind, quarter, include_archived=True, snapshot=base)
    known = {(row.sheet, row.key) for row in current}
    unknown = sorted({f"{s}/{k}" for s, k in accepted if (s, k) not in known})
    if unknown:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(unknown)} row(s) are no longer in this report: "
                f"{', '.join(unknown[:5])}. Re-run the analysis and try again."
            ),
        )

    snap = ReportSnapshot(
        report_kind=kind,
        quarter=quarter,
        role=role,
        author_email=user.email,
        author_name=user.name,
        label=body.label.strip(),
        based_on_id=base.id if base else None,
    )
    db.add(snap)
    db.flush()

    for row in current:
        applied = accepted.get((row.sheet, row.key), {})
        for field_name, value in applied.items():
            before = str(getattr(row, field_name) or "")
            setattr(row, field_name, value)
            db.add(
                AuditLog(
                    actor=user.email,
                    role=user.role,
                    snapshot_id=snap.id,
                    quarter=quarter,
                    report_kind=kind,
                    sheet=row.sheet,
                    backlog_key=row.key,
                    field=field_name,
                    old_value=before,
                    new_value=str(value),
                )
            )
        has_text = any(str(getattr(row, f) or "").strip() for f in USER_FIELDS if f != "rank")
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
                tpm_comment=row.tpm_comment,
                package=row.package,
            )
        )

    db.commit()
    return to_info(db, snap)


def _writeback(
    db: Session, kind: str, quarter: str, author_email: str, target_role: str, changes: str
):
    """Shared setup for previewing and downloading the reviewer's own file, updated."""
    _scope(kind)
    _editor(db, author_email)
    role = _target(target_role)
    try:
        raw = json.loads(changes or "[]")
        parsed = [ApplyChange.model_validate(item) for item in raw]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"changes is not valid: {exc}") from exc

    accepted = _accepted(parsed)
    base = _base_snapshot(db, kind, quarter, role, None)
    return role, _merged(db, kind, quarter, base, accepted)


@router.post("/reports/{kind}/{quarter}/analyze/file-preview", response_model=FileUpdatePlan)
async def preview_updated_file(
    kind: str,
    quarter: str,
    file: UploadFile = File(...),
    author_email: str = Form(...),
    target_role: str = Form(...),
    changes: str = Form(default="[]"),
    db: Session = Depends(get_db),
):
    """What the uploaded workbook itself would look like once the changes are applied."""
    data = await _bytes_of(file)
    role, merged = _writeback(db, kind, quarter, author_email, target_role, changes)
    try:
        return spreadsheet_updater.plan_update(
            data,
            file.filename or "upload.xlsx",
            merged,
            kind,
            quarter,
            None,
            USER_FIELDS,
        )
    except AnalyzerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reports/{kind}/{quarter}/analyze/file-download")
async def download_updated_file(
    kind: str,
    quarter: str,
    file: UploadFile = File(...),
    author_email: str = Form(...),
    target_role: str = Form(...),
    changes: str = Form(default="[]"),
    db: Session = Depends(get_db),
):
    """The uploaded workbook with its user columns set to the agreed outcome."""
    data = await _bytes_of(file)
    name = file.filename or "upload.xlsx"
    role, merged = _writeback(db, kind, quarter, author_email, target_role, changes)
    try:
        updated, _plan = spreadsheet_updater.build_updated_workbook(
            data,
            name,
            merged,
            kind,
            quarter,
            None,
            USER_FIELDS,
            # Adding or flagging rows is the Updater's job; this only settles the
            # columns people type into, so the file keeps exactly the rows it had.
            add_new=False,
            flag_gone=False,
        )
    except AnalyzerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stem = name.rsplit(".", 1)[0] or "backlog"
    filename = f"{stem}_{role}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return Response(
        content=updated,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fields(selected: str | None) -> tuple[str, ...]:
    """Which Jira columns to refresh. Empty means all of them."""
    if not selected or not selected.strip():
        return JIRA_FIELDS
    names = tuple(f.strip() for f in selected.split(",") if f.strip())
    unknown = [f for f in names if f not in JIRA_FIELDS]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"not Jira-owned columns: {', '.join(unknown)}"
        )
    return names


@router.post("/reports/{kind}/{quarter}/refresh-file", response_model=FileUpdatePlan)
async def plan_file_refresh(
    kind: str,
    quarter: str,
    file: UploadFile = File(...),
    author_email: str = Form(...),
    fields: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """Report what refreshing an old exported workbook would change inside it."""
    _scope(kind)
    _editor(db, author_email)
    data = await _bytes_of(file)
    report = _report_info(db, kind, quarter)

    try:
        return spreadsheet_updater.plan_update(
            data,
            file.filename or "upload.xlsx",
            _current(db, kind, quarter),
            kind,
            quarter,
            report.last_jira_sync_at,
            _fields(fields),
        )
    except AnalyzerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reports/{kind}/{quarter}/refresh-file/download")
async def download_refreshed_file(
    kind: str,
    quarter: str,
    file: UploadFile = File(...),
    author_email: str = Form(...),
    fields: str = Form(default=""),
    add_new: bool = Form(default=True),
    flag_gone: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    """Return the same workbook with its Jira columns brought up to date."""
    _scope(kind)
    _editor(db, author_email)
    data = await _bytes_of(file)
    report = _report_info(db, kind, quarter)
    name = file.filename or "upload.xlsx"

    try:
        updated, _plan = spreadsheet_updater.build_updated_workbook(
            data,
            name,
            _current(db, kind, quarter),
            kind,
            quarter,
            report.last_jira_sync_at,
            _fields(fields),
            add_new=add_new,
            flag_gone=flag_gone,
        )
    except AnalyzerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stem = name.rsplit(".", 1)[0] or "backlog"
    filename = f"{stem}_updated_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return Response(
        content=updated,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
