"""Refresh the team's working files where they live, in the GLreport SharePoint.

The same plan and rewrite as the Updater page, with the file read from and written
back to the quarter's SharePoint folder instead of uploaded and downloaded. Scan
first, approve what it shows, then update: the update refuses if the file changed
in between, so what lands is exactly what was approved.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import REPORT_SPECS, SHAREPOINT_WEB_URL
from ..db import get_db
from ..schemas import (
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
from .analyzer import _current, _editor
from .reports import _report_info

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
        return SharePointScan(
            file=_file(meta, kind),
            plan=spreadsheet_updater.plan_update(
                data, path.name, current, kind, quarter, last_sync
            ),
        )
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
        updated, plan = spreadsheet_updater.build_updated_workbook(
            data,
            path.name,
            _current(db, kind, quarter),
            kind,
            quarter,
            _report_info(db, kind, quarter).last_jira_sync_at,
            fields,
            add_new=body.add_new,
            flag_gone=body.flag_gone,
        )
        backup = sharepoint.replace(path, updated, body.token)
        return SharePointUpdateResult(
            file=_file(sharepoint.info(path), kind),
            cells_updated=len(plan.changes),
            rows_added=len(plan.new_rows) if body.add_new else 0,
            rows_flagged=len(plan.gone_rows) if body.flag_gone else 0,
            backup=str(backup),
        )
    except (SharePointError, SpreadsheetError) as exc:
        _fail(exc)
