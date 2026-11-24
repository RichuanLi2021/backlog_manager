"""Refresh the team's working files where they live, in the GLreport SharePoint.

The same plan and rewrite as the Updater page, with the file read from and written
back to the quarter's SharePoint folder instead of uploaded and downloaded. Scan
first, approve what it shows, then update: the update refuses if the file changed
in between, so what lands is exactly what was approved.
"""
import os
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import REPORT_SPECS, SHAREPOINT_WEB_URL
from ..db import get_db
from ..schemas import (
    SharePointCreateRequest,
    SharePointFile,
    SharePointFolder,
    SharePointScan,
    SharePointScanRequest,
    SharePointUpdateRequest,
    SharePointUpdateResult,
)
from ..services import sharepoint, spreadsheet_updater
from ..services.sharepoint import FileInfo, SharePointError
from ..services.spreadsheet_layout import JIRA_FIELDS, SpreadsheetError
from ..services import excel_export
from ..services.spreadsheet_layout import read_layouts
from .analyzer import _bytes_of, _current, _editor, outside_rows
from .reports import _report_info, _rows

router = APIRouter(prefix="/api/sharepoint", tags=["sharepoint"])


def _scope(kind: str):
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")


def _file(meta: FileInfo, kind: str) -> SharePointFile:
    return SharePointFile(
        name=meta.name,
        size=meta.size,
        modified=meta.modified,
        token=meta.token,
        kind=meta.kind,
        matches_report=meta.kind == kind,
        open_here=meta.open_here,
        cloud_only=meta.cloud_only,
    )


def _fail(exc: Exception):
    if isinstance(exc, SharePointError):
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kind}/{quarter}", response_model=SharePointFolder)
def list_folder(kind: str, quarter: str, db: Session = Depends(get_db)):
    """The quarter's SharePoint folder as this PC sees it, or where it was looked for."""
    _scope(kind)
    where = sharepoint.folder(quarter)
    return SharePointFolder(
        quarter=quarter,
        root_found=sharepoint.root() is not None,
        found=bool(where and where.is_dir()),
        folder=str(where) if where else None,
        searched=[str(p) for p in sharepoint.candidates()],
        web_url=SHAREPOINT_WEB_URL.format(quarter=quarter),
        files=[_file(f, kind) for f in sharepoint.list_workbooks(quarter)],
        last_jira_sync_at=_report_info(db, kind, quarter).last_jira_sync_at,
    )


@router.post("/{kind}/{quarter}/scan", response_model=SharePointScan)
def scan_file(
    kind: str, quarter: str, body: SharePointScanRequest, db: Session = Depends(get_db)
):
    """Where the file stands, where Jira stands now, and every cell between them."""
    _scope(kind)
    try:
        path = sharepoint.locate(quarter, body.name)
        meta = sharepoint.info(path)
        data = sharepoint.read(path)
        current = _current(db, kind, quarter)
        last_sync = _report_info(db, kind, quarter).last_jira_sync_at
        outside, warning = outside_rows(data, path.name, current, kind, quarter, JIRA_FIELDS)
        plan = spreadsheet_updater.plan_update(
            data, path.name, current, kind, quarter, last_sync, JIRA_FIELDS, outside
        )
        if warning:
            plan.warnings.append(warning)
        return SharePointScan(file=_file(meta, kind), plan=plan)
    except (SharePointError, SpreadsheetError) as exc:
        _fail(exc)


@router.post("/{kind}/{quarter}/update", response_model=SharePointUpdateResult)
def update_file(
    kind: str, quarter: str, body: SharePointUpdateRequest, db: Session = Depends(get_db)
):
    """Write the refreshed workbook back over the one in SharePoint."""
    _scope(kind)
    # A shared team file: only the three editing groups may change it.
    _editor(db, body.author_email)
    fields = tuple(body.fields) or JIRA_FIELDS
    unknown = [f for f in fields if f not in JIRA_FIELDS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"not Jira-owned columns: {unknown}")

    try:
        path = sharepoint.locate(quarter, body.name)
        data = sharepoint.read(path)
        current = _current(db, kind, quarter)
        outside, _warning = outside_rows(data, path.name, current, kind, quarter, fields)
        updated, plan = spreadsheet_updater.build_updated_workbook(
            data,
            path.name,
            current,
            kind,
            quarter,
            _report_info(db, kind, quarter).last_jira_sync_at,
            fields,
            add_new=body.add_new,
            flag_gone=body.flag_gone,
            outside=outside,
        )
        new_name = sharepoint.dated_name(path.name, date.today())
        sharepoint.check_rename(path, new_name)
        backup = sharepoint.replace(path, updated, body.token)
        renamed_from = None
        try:
            if new_name != path.name:
                renamed_from, path = path.name, sharepoint.rename(path, new_name)
        except OSError:
            # The update itself has landed; only the name could not change, most likely
            # because OneDrive is still syncing it. The next update tries again.
            renamed_from = None
        return SharePointUpdateResult(
            file=_file(sharepoint.info(path), kind),
            renamed_from=renamed_from,
            cells_updated=len(plan.changes),
            rows_added=len(plan.new_rows) if body.add_new else 0,
            rows_flagged=len(plan.gone_rows) if body.flag_gone else 0,
            backup=str(backup),
        )
    except (SharePointError, SpreadsheetError) as exc:
        _fail(exc)


@router.post("/{kind}/{quarter}/open")
def open_file(kind: str, quarter: str, body: SharePointScanRequest):
    """Open the workbook in desktop Excel on this PC, the one running the platform.

    Opened from the OneDrive-synced folder, so Excel edits the SharePoint file itself,
    with AutoSave and co-authoring, not a downloaded copy.
    """
    _scope(kind)
    try:
        path = sharepoint.locate(quarter, body.name)
    except SharePointError as exc:
        _fail(exc)
    if not hasattr(os, "startfile"):
        raise HTTPException(status_code=501, detail="Opening files is only supported on Windows.")
    try:
        os.startfile(str(path))  # noqa: S606  the path is resolved inside the shared folder
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"{path.name} could not be opened: {exc}") from exc
    return {"opened": path.name}



@router.post("/{kind}/{quarter}/create", response_model=SharePointFile)
def create_report(
    kind: str, quarter: str, body: SharePointCreateRequest, db: Session = Depends(get_db)
):
    """Start the quarter's working file in SharePoint from the platform's report.

    Creates <quarter>/Updated if it is not there yet. The workbook is the standard
    export: every region as a Priority_List tab, from the live Jira data.
    """
    _scope(kind)
    _editor(db, body.author_email)
    rows = _rows(db, kind, quarter, include_archived=False)
    if not rows:
        raise HTTPException(
            status_code=409,
            detail=f"{kind} {quarter} has no backlogs yet. Run Update from Jira first.",
        )
    report = _report_info(db, kind, quarter)
    data = excel_export.build_workbook(
        rows,
        [
            ("Report", f"{kind} - {quarter}"),
            ("View", "Live Jira data"),
            ("Jira last updated", str(report.last_jira_sync_at or "never")),
            ("Rows", str(len(rows))),
        ],
        quarter=quarter,
    )
    try:
        path = sharepoint.write_new(quarter, sharepoint.report_name(kind, quarter, date.today()), data)
    except SharePointError as exc:
        _fail(exc)
    return _file(sharepoint.info(path), kind)


@router.post("/{kind}/{quarter}/import", response_model=SharePointFile)
async def import_report(
    kind: str,
    quarter: str,
    file: UploadFile = File(...),
    author_email: str = Form(...),
    db: Session = Depends(get_db),
):
    """Put a workbook from this PC into the quarter's SharePoint folder, as its working file.

    Saved under the dated name the Updater expects, so it is picked up and scanned like
    any other. Refused if it does not read as a backlog workbook.
    """
    _scope(kind)
    _editor(db, author_email)
    data = await _bytes_of(file)
    try:
        read_layouts(data, file.filename or "upload.xlsx", JIRA_FIELDS)
        path = sharepoint.write_new(quarter, sharepoint.report_name(kind, quarter, date.today()), data)
    except (SharePointError, SpreadsheetError) as exc:
        _fail(exc)
    return _file(sharepoint.info(path), kind)
