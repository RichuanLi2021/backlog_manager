import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import (
    DEFAULT_QUARTER,
    NDP_AGE_FLAG_DAYS,
    NDP_AGE_WARN_DAYS,
    NDP_DONE_STATUSES,
    NDP_UNSUBMITTED_STATUSES,
    REPORT_SPECS,
)
from ..db import SessionLocal, get_db
from ..models import BacklogSnapshot, NdpState, Report, ReportSnapshot, SyncJob
from ..schemas import (
    BacklogRow,
    NdpAgeRefresh,
    NdpAgeRules,
    ReportDetail,
    QuarterCreate,
    ReportInfo,
    SyncStatus,
    TreeBacklog,
    TreeNdp,
    TreeRelease,
    TreeSheet,
)
from ..services import excel_export, jira_sync, merge, ndp_age
from .snapshots import latest_snapshot, newest_snapshot, snapshot_values, to_info

router = APIRouter(prefix="/api", tags=["reports"])

SHEET_ORDER = ["NA_AR", "NA_GL", "NA_AR+GL", "LAC_AR", "LAC_GL", "LAC_AR+GL"]

# The name is substituted into the skill's JQL, where NA matches it against
# "Request Qtr" and LAC against a label, so it has to be written their way.
QUARTER_PATTERN = re.compile(r"^\d{4}Q[1-4]$")

# Used until a report has been synced before and can be timed from history.
DEFAULT_ESTIMATES = {"ALL": 150, "AR_GL": 95, "AR": 30, "GL": 45}


def estimate_for(db: Session, report_kind: str) -> int:
    """Average duration of recent successful syncs of the same scope."""
    rows = db.execute(
        select(SyncJob.started_at, SyncJob.finished_at)
        .where(SyncJob.report_kind == report_kind, SyncJob.state == "done")
        .order_by(SyncJob.id.desc())
        .limit(5)
    ).all()
    durations = [(f - s).total_seconds() for s, f in rows if f and s]
    if durations:
        return int(sum(durations) / len(durations))
    return DEFAULT_ESTIMATES.get(report_kind, 60)


def job_status(db: Session, job: SyncJob) -> SyncStatus:
    status = SyncStatus.model_validate(job, from_attributes=True)
    status.estimate_seconds = estimate_for(db, job.report_kind)
    end = job.finished_at or datetime.now()
    status.elapsed_seconds = max(0, int((end - job.started_at).total_seconds()))
    return status


def sheet_sort_key(sheet: str) -> tuple[int, str]:
    return (SHEET_ORDER.index(sheet) if sheet in SHEET_ORDER else len(SHEET_ORDER), sheet)


def _report_info(db: Session, kind: str, quarter: str) -> ReportInfo:
    report = db.scalar(select(Report).where(Report.kind == kind, Report.quarter == quarter))
    count = db.scalar(
        select(func.count(BacklogSnapshot.id)).where(
            BacklogSnapshot.report_kind == kind, BacklogSnapshot.quarter == quarter
        )
    )
    return ReportInfo(
        kind=kind,
        quarter=quarter,
        last_jira_sync_at=report.last_jira_sync_at if report else None,
        last_sync_status=report.last_sync_status if report else "never",
        last_sync_error=report.last_sync_error if report else None,
        item_count=count or 0,
    )


@router.get("/reports", response_model=list[ReportInfo])
def list_reports(
    quarter: str = Query(default=DEFAULT_QUARTER), db: Session = Depends(get_db)
):
    return [_report_info(db, kind, quarter) for kind in REPORT_SPECS]


@router.get("/quarters", response_model=list[str])
def list_quarters(db: Session = Depends(get_db)):
    # Reports are included so a quarter that has been opened but never synced still
    # shows up; without it a new quarter would be invisible until it had rows.
    known = set(db.scalars(select(BacklogSnapshot.quarter).distinct()))
    known.update(db.scalars(select(Report.quarter).distinct()))
    known.add(DEFAULT_QUARTER)
    return sorted(known, reverse=True)


def _clean_quarter(value: str) -> str:
    quarter = "".join(value.split()).upper()
    if not QUARTER_PATTERN.match(quarter):
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{value}' is not a quarter name. Use four digits, Q, then 1-4, "
                "for example 2026Q4. The name goes straight into the Jira query, "
                "so it has to match the way Request Qtr and the LAC labels are written."
            ),
        )
    return quarter


@router.post("/quarters", response_model=list[str])
def add_quarter(body: QuarterCreate, db: Session = Depends(get_db)):
    """Open an empty quarter. It stays empty until someone runs Update from Jira."""
    quarter = _clean_quarter(body.quarter)
    if quarter in list_quarters(db):
        raise HTTPException(status_code=409, detail=f"{quarter} is already on the list.")

    for kind in REPORT_SPECS:
        db.add(Report(kind=kind, quarter=quarter))
    db.commit()
    return list_quarters(db)


@router.delete("/quarters/{quarter}", response_model=list[str])
def delete_quarter(quarter: str, db: Session = Depends(get_db)):
    """Undo an opened quarter, but only while nothing has been put in it."""
    quarter = _clean_quarter(quarter)
    if quarter == DEFAULT_QUARTER:
        raise HTTPException(
            status_code=409,
            detail=f"{quarter} is the default quarter and is always on the list.",
        )

    rows = db.scalar(
        select(func.count(BacklogSnapshot.id)).where(BacklogSnapshot.quarter == quarter)
    )
    saves = db.scalar(
        select(func.count(ReportSnapshot.id)).where(ReportSnapshot.quarter == quarter)
    )
    if rows or saves:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{quarter} holds {rows} backlog row(s) and {saves} save(s), so it is "
                "not empty. Only a quarter nothing has been put in can be removed."
            ),
        )

    for report in db.scalars(select(Report).where(Report.quarter == quarter)):
        db.delete(report)
    db.commit()
    return list_quarters(db)


def _rows(
    db: Session,
    kind: str,
    quarter: str,
    include_archived: bool,
    snapshot: ReportSnapshot | None = None,
) -> list[BacklogRow]:
    """Live Jira rows, optionally overlaid with the user values from one snapshot."""
    stmt = select(BacklogSnapshot).where(
        BacklogSnapshot.report_kind == kind, BacklogSnapshot.quarter == quarter
    )
    if not include_archived:
        stmt = stmt.where(BacklogSnapshot.archived.is_(False))
    snapshots = list(db.scalars(stmt))

    saved = snapshot_values(db, snapshot.id) if snapshot else {}

    # The live view keeps its own columns empty, but still shows the ranking people
    # last agreed on, so priority order is not lost when nobody picks a snapshot.
    if snapshot:
        ranks = saved
    else:
        newest = newest_snapshot(db, kind, quarter)
        ranks = snapshot_values(db, newest.id) if newest else {}

    rows = []
    for s in snapshots:
        ov = saved.get((s.sheet, s.key))
        rows.append(
            BacklogRow(
                id=s.id,
                sheet=s.sheet,
                region=s.region,
                domain=s.domain,
                key=s.key,
                release=s.release,
                release_title=s.release_title,
                ndp=s.ndp,
                ndp_status=s.ndp_status,
                ndp_deploy_date=s.ndp_deploy_date,
                summary=s.summary,
                issue_type=s.issue_type,
                status=s.status,
                assignee=s.assignee,
                reporter=s.reporter,
                priority=s.priority,
                biz_domain=s.biz_domain,
                req_qtr=s.req_qtr,
                labels=s.labels,
                backlog_source=s.backlog_source,
                est_h=s.est_h,
                spent_h=s.spent_h,
                archived=s.archived,
                rank=(ranks.get((s.sheet, s.key)).rank if ranks.get((s.sheet, s.key)) else 0),
                developer=ov.developer if ov else "",
                uat_eta=ov.uat_eta if ov else "",
                prod_eta=ov.prod_eta if ov else "",
                comments=ov.comments if ov else "",
            )
        )
    # Unranked rows (rank 0) fall to the bottom in Jira order.
    rows.sort(key=lambda r: (sheet_sort_key(r.sheet), r.rank == 0, r.rank, r.release, r.ndp, r.key))

    # A row nobody has ranked shows its position instead of a meaningless 0.
    position = {}
    for row in rows:
        position[row.sheet] = position.get(row.sheet, 0) + 1
        if row.rank == 0:
            row.rank = position[row.sheet]
    return rows


@router.get("/reports/{kind}/{quarter}", response_model=ReportDetail)
def get_report(
    kind: str,
    quarter: str,
    include_archived: bool = Query(default=True),
    snapshot_id: int | None = Query(default=None),
    role: str | None = Query(default=None, description="Load this role's latest snapshot"),
    db: Session = Depends(get_db),
):
    """Without snapshot_id or role this returns the untouched Jira view."""
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")

    snapshot = None
    if snapshot_id is not None:
        snapshot = db.get(ReportSnapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="snapshot not found")
    elif role:
        snapshot = latest_snapshot(db, kind, quarter, role.upper())

    rows = _rows(db, kind, quarter, include_archived, snapshot)
    sheets = sorted({r.sheet for r in rows}, key=sheet_sort_key)
    return ReportDetail(
        report=_report_info(db, kind, quarter),
        sheets=sheets,
        items=rows,
        snapshot=to_info(db, snapshot) if snapshot else None,
    )


@router.get("/reports/{kind}/{quarter}/export")
def export_report(
    kind: str,
    quarter: str,
    include_archived: bool = Query(default=True),
    sheet: str | None = Query(default=None, description="Export one region sheet only"),
    status: str | None = Query(default=None, description="Export one backlog status only"),
    snapshot_id: int | None = Query(default=None),
    role: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Download the current view as an Excel workbook, one worksheet per sheet."""
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")

    snapshot = None
    if snapshot_id is not None:
        snapshot = db.get(ReportSnapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="snapshot not found")
    elif role and role.upper() != "LIVE":
        snapshot = latest_snapshot(db, kind, quarter, role.upper())

    rows = _rows(db, kind, quarter, include_archived, snapshot)
    if sheet:
        rows = [r for r in rows if r.sheet == sheet]
    if status:
        rows = [r for r in rows if (r.status.strip() or "N/A") == status]
    if not rows:
        raise HTTPException(status_code=404, detail="nothing to export")

    report = _report_info(db, kind, quarter)
    view = (
        f"{snapshot.role} snapshot saved {snapshot.created_at:%Y-%m-%d %H:%M:%S} by "
        f"{snapshot.author_name or snapshot.author_email}"
        if snapshot
        else "Live Jira data"
    )
    data = excel_export.build_workbook(
        rows,
        [
            ("Report", f"{kind} - {quarter}"),
            ("View", view),
            ("Status filter", status or "all"),
            ("Jira last updated", str(report.last_jira_sync_at or "never")),
            ("Rows", str(len(rows))),
        ],
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    tag = snapshot.role if snapshot else "Live"
    scope = f"_{sheet.replace('+', '')}" if sheet else ""
    if status:
        scope += f"_{status.replace('/', '-')}"
    filename = f"{kind}_{quarter}{scope}_{tag}_{stamp}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/{kind}/{quarter}/tree", response_model=list[TreeSheet])
def get_tree(
    kind: str,
    quarter: str,
    snapshot_id: int | None = Query(default=None),
    role: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")

    snapshot = (
        db.get(ReportSnapshot, snapshot_id)
        if snapshot_id is not None
        else (latest_snapshot(db, kind, quarter, role.upper()) if role else None)
    )
    rows = _rows(db, kind, quarter, include_archived=False, snapshot=snapshot)
    states = {
        s.ndp: s
        for s in db.scalars(select(NdpState).where(NdpState.ndp.in_({r.ndp for r in rows})))
    }
    now = datetime.now()

    out: list[TreeSheet] = []
    for sheet in sorted({r.sheet for r in rows}, key=sheet_sort_key):
        sheet_rows = [r for r in rows if r.sheet == sheet]
        releases: list[TreeRelease] = []
        for release in sorted({r.release for r in sheet_rows}):
            rel_rows = [r for r in sheet_rows if r.release == release]
            ndps: list[TreeNdp] = []
            for ndp in sorted({r.ndp for r in rel_rows}):
                ndp_rows = [r for r in rel_rows if r.ndp == ndp]
                age = ndp_age.age_of(ndp_rows[0].ndp_status, states.get(ndp), now)
                ndps.append(
                    TreeNdp(
                        ndp=ndp,
                        status=ndp_rows[0].ndp_status,
                        deploy_date=ndp_rows[0].ndp_deploy_date,
                        age_level=age.level,
                        age_days=age.days,
                        status_since=age.since,
                        age_source=age.source,
                        live_status=(
                            states[ndp].status
                            if ndp in states and states[ndp].status != ndp_rows[0].ndp_status
                            else ""
                        ),
                        backlogs=[
                            TreeBacklog(
                                id=r.id,
                                key=r.key,
                                summary=r.summary,
                                status=r.status,
                                assignee=r.assignee,
                                developer=r.developer,
                                est_h=r.est_h,
                                spent_h=r.spent_h,
                            )
                            for r in ndp_rows
                        ],
                    )
                )
            releases.append(
                TreeRelease(release=release, title=rel_rows[0].release_title, ndps=ndps)
            )
        out.append(TreeSheet(sheet=sheet, releases=releases))
    return out


def _run_sync(job_id: int, kinds: list[str], quarter: str):
    db = SessionLocal()
    try:
        job = db.get(SyncJob, job_id)
        done = []
        ndp_statuses: dict[str, str] = {}
        for kind in kinds:
            job.message = f"Fetching {kind} from Jira..."
            db.commit()
            rows = jira_sync.fetch_report(kind, quarter)
            stats = merge.apply_snapshot(db, kind, quarter, rows)
            ndp_statuses.update({r["ndp"]: r["ndp_status"] for r in rows})
            note = (
                f" - incomplete Jira response, {stats['missing']} rows kept"
                if stats["suspect"]
                else f" ({stats['archived']} archived)"
            )
            done.append(f"{kind}: {stats['total']} rows{note}")
        # Ages are a nice-to-have on top of the sync, never a reason to fail it.
        job.message = "Checking how long each NDP has been in its status..."
        db.commit()
        aged = ndp_age.refresh(db, ndp_statuses)
        if aged["error"]:
            done.append(f"NDP ages approximate ({aged['error']})")
        job.state = "done"
        job.message = "; ".join(done)
        job.finished_at = datetime.now()
        db.commit()
    except Exception as exc:  # surfaced to the UI via /api/sync/status
        db.rollback()
        job = db.get(SyncJob, job_id)
        job.state = "failed"
        job.message = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now()
        for kind in kinds:
            report = db.scalar(
                select(Report).where(Report.kind == kind, Report.quarter == quarter)
            )
            if report is not None:
                report.last_sync_status = "failed"
                report.last_sync_error = job.message
        db.commit()
    finally:
        db.close()


@router.post("/reports/{kind}/{quarter}/refresh", response_model=SyncStatus)
def refresh_report(
    kind: str,
    quarter: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger a Jira sync. Use kind=ALL to refresh all three reports."""
    kinds = list(REPORT_SPECS) if kind.upper() == "ALL" else [kind]
    if any(k not in REPORT_SPECS for k in kinds):
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")

    running = db.scalar(select(SyncJob).where(SyncJob.state == "running"))
    if running is not None:
        raise HTTPException(status_code=409, detail=f"sync already running (job {running.id})")

    job = SyncJob(quarter=quarter, report_kind=kind.upper(), message="Queued")
    db.add(job)
    db.commit()
    background.add_task(_run_sync, job.id, kinds, quarter)
    return job_status(db, job)


@router.get("/sync/status", response_model=SyncStatus | None)
def sync_status(
    kind: str | None = Query(default=None, description="Only jobs covering this report"),
    db: Session = Depends(get_db),
):
    stmt = select(SyncJob).order_by(SyncJob.id.desc())
    if kind:
        stmt = stmt.where(SyncJob.report_kind.in_([kind.upper(), "ALL"]))
    job = db.scalar(stmt.limit(1))
    return job_status(db, job) if job else None


@router.post("/reports/{kind}/{quarter}/ndp-ages", response_model=NdpAgeRefresh)
def refresh_ndp_ages(kind: str, quarter: str, db: Session = Depends(get_db)):
    """Re-read NDP status dates from Jira without a full report sync.

    One changelog search for this report's NDPs, a second or two, against the ~2
    minutes of Update from Jira. Statuses come from the last sync; only the dates
    are refreshed, so run Update from Jira first if statuses themselves look stale.
    """
    if kind not in REPORT_SPECS:
        raise HTTPException(status_code=404, detail=f"unknown report kind: {kind}")
    statuses = {
        ndp: status
        for ndp, status in db.execute(
            select(BacklogSnapshot.ndp, BacklogSnapshot.ndp_status)
            .where(
                BacklogSnapshot.report_kind == kind,
                BacklogSnapshot.quarter == quarter,
                BacklogSnapshot.archived.is_(False),
            )
            .distinct()
        )
    }
    result = ndp_age.refresh(db, statuses)
    return NdpAgeRefresh(
        ndps=result["jira"] + result["observed"],
        from_jira=result["jira"],
        observed=result["observed"],
        error=result["error"],
    )


@router.get("/ndp-age-rules", response_model=NdpAgeRules)
def ndp_age_rules():
    """The thresholds behind the colours, so the legend can never disagree with them."""
    return NdpAgeRules(
        warn_days=NDP_AGE_WARN_DAYS,
        flag_days=NDP_AGE_FLAG_DAYS,
        done_statuses=sorted(NDP_DONE_STATUSES),
        unsubmitted_statuses=sorted(NDP_UNSUBMITTED_STATUSES),
    )
