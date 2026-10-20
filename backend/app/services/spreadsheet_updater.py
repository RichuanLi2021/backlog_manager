"""Refresh a circulated backlog workbook from the platform, in place.

Direction: platform -> file. A report exported weeks ago still carries the ranking,
comments and highlighting people built on top of it, but its Jira columns have gone
stale: statuses moved on, NDPs were approved, backlogs were raised or dropped. This
rewrites only the Jira-owned cells of the file people are already working in, adds
the backlogs raised since, flags the ones Jira no longer returns, and leaves every
other cell — values, fills, fonts, widths, formulas — exactly as it was.

Two passes over the same bytes: one with `data_only=True` to read what the cells
currently say, one with `data_only=False` to write without flattening formulas.
"""

from __future__ import annotations

from collections import Counter
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from ..schemas import (
    BacklogRow,
    FileFieldChange,
    FileGoneRow,
    FileNewRow,
    FileProgress,
    FileSheetPlan,
    FileUpdatePlan,
    StatusCount,
)
from .excel_export import NDP_FILLS
from .spreadsheet_layout import (
    ALL_ALIASES,
    JIRA_FIELDS,
    USER_FIELDS,
    SheetLayout,
    SpreadsheetError,
    _norm,
    read_layouts,
    resolve_sheet,
    same_value,
    text_of,
)

# Column headers written when a row has to be added or flagged, and when the file
# turns out to have no column for a field at all.
MARKER_HEADER = "Update Status"
LOG_SHEET = "update log"

NUMERIC = {"est_h", "spent_h"}
INTEGER = {"rank"}

FIELD_LABELS = {
    "release": "Release",
    "release_title": "Release Title",
    "ndp": "NDP",
    "ndp_status": "NDP Status",
    "ndp_deploy_date": "NDP Deploy Date",
    "summary": "Summary",
    "issue_type": "Issue Type",
    "status": "Status",
    "assignee": "Assignee",
    "reporter": "Reporter",
    "priority": "Priority",
    "biz_domain": "Biz Domain",
    "req_qtr": "Req Qtr",
    "labels": "Labels",
    "backlog_source": "Backlog Source",
    "est_h": "Est h",
    "spent_h": "Spent h",
    "rank": "Rank",
    "developer": "Developer",
    "uat_eta": "UAT ETA",
    "prod_eta": "PROD ETA",
    "comments": "Comments",
}

# Timestamp labels the skill and this platform write into their `about` sheets.
STAMP_LABELS = {"jiralastupdated", "lastupdated", "lastjirasync"}


@dataclass
class Target:
    """One worksheet of the file, tied to the report sheet it stands for."""

    layout: SheetLayout
    sheet: str | None
    rows: dict[str, BacklogRow] = field(default_factory=dict)


def _platform_text(row: BacklogRow, name: str) -> str:
    value = getattr(row, name)
    if name in INTEGER:
        return str(int(value)) if int(value or 0) else ""
    if name in NUMERIC:
        number = float(value or 0)
        return str(int(number)) if number.is_integer() else str(number)
    return str(value or "")


def _targets(layout, current: list[BacklogRow]) -> list[Target]:
    by_key: dict[str, set[str]] = {}
    for row in current:
        by_key.setdefault(row.key.upper(), set()).add(row.sheet)
    sheets = {_norm(row.sheet): row.sheet for row in current}
    indexed: dict[str, dict[str, BacklogRow]] = {}
    for row in current:
        indexed.setdefault(row.sheet, {})[row.key.upper()] = row

    out = []
    for sheet_layout in layout.sheets:
        resolved = resolve_sheet(sheet_layout, sheets, by_key)
        out.append(Target(sheet_layout, resolved, indexed.get(resolved or "", {})))
    return out


def _plan_sheet(
    target: Target, fields: tuple[str, ...], plan: FileUpdatePlan
) -> tuple[int, list[str]]:
    """Collect the changes, additions and removals one worksheet would receive."""
    unchanged = 0
    seen: set[str] = set()
    sheet_layout = target.layout
    readable = {f: c for f, c in sheet_layout.columns.items() if f in fields}

    for key, row_number in sheet_layout.keys:
        seen.add(key)
        live = target.rows.get(key)
        if live is None:
            plan.gone_rows.append(
                FileGoneRow(
                    sheet=sheet_layout.name,
                    row=row_number,
                    key=key,
                    reason="not in this report any more",
                )
            )
            continue
        if live.archived:
            plan.gone_rows.append(
                FileGoneRow(
                    sheet=sheet_layout.name,
                    row=row_number,
                    key=key,
                    reason="archived - Jira stopped returning it",
                )
            )
        for name, column in readable.items():
            in_file = text_of(sheet_layout.value(row_number, column))
            live_text = _platform_text(live, name)
            if same_value(name, in_file, live_text):
                unchanged += 1
                continue
            plan.changes.append(
                FileFieldChange(
                    sheet=sheet_layout.name,
                    row=row_number,
                    key=key,
                    field=name,
                    label=text_of(sheet_layout.value(sheet_layout.header_row, column))
                    or FIELD_LABELS.get(name, name),
                    in_file=in_file,
                    current=live_text,
                )
            )

    added = [k for k in target.rows if k not in seen and not target.rows[k].archived]
    for key in sorted(added):
        live = target.rows[key]
        plan.new_rows.append(
            FileNewRow(
                sheet=sheet_layout.name,
                key=live.key,
                summary=live.summary,
                status=live.status,
                ndp=live.ndp,
                ndp_status=live.ndp_status,
            )
        )
    return unchanged, sorted(added)


def _plan_from(
    layout,
    filename: str,
    current: list[BacklogRow],
    kind: str,
    quarter: str,
    last_sync: datetime | None,
    fields: tuple[str, ...],
) -> tuple[FileUpdatePlan, list[Target]]:
    plan = FileUpdatePlan(
        filename=filename,
        report_kind=kind,
        quarter=quarter,
        last_jira_sync_at=last_sync,
        sheets=[],
        sheets_ignored=layout.ignored,
        changes=[],
        field_counts={},
        new_rows=[],
        gone_rows=[],
        unchanged_cells=0,
        warnings=list(layout.warnings),
    )

    targets = _targets(layout, current)
    for target in targets:
        sheet_layout = target.layout
        if target.sheet is None:
            plan.warnings.append(
                f"'{sheet_layout.name}' could not be matched to a region sheet of "
                f"{kind}. Rename the worksheet to a sheet name such as NA_GL, or check "
                "you picked the right report."
            )
            plan.sheets.append(
                FileSheetPlan(
                    name=sheet_layout.name,
                    resolved_to=None,
                    header_row=sheet_layout.header_row,
                    rows_in_file=len(sheet_layout.keys),
                    matched=0,
                    columns={},
                )
            )
            continue

        unchanged, _ = _plan_sheet(target, fields, plan)
        plan.unchanged_cells += unchanged
        plan.sheets.append(
            FileSheetPlan(
                name=sheet_layout.name,
                resolved_to=target.sheet,
                header_row=sheet_layout.header_row,
                rows_in_file=len(sheet_layout.keys),
                matched=sum(1 for k, _ in sheet_layout.keys if k in target.rows),
                columns={
                    FIELD_LABELS.get(f, f): text_of(
                        sheet_layout.value(sheet_layout.header_row, c)
                    )
                    for f, c in sorted(sheet_layout.columns.items())
                    if f in JIRA_FIELDS
                },
            )
        )

    missing = [f for f in fields if not any(f in s.columns for s in layout.sheets)]
    if missing:
        plan.warnings.append(
            "The file has no column for "
            + ", ".join(FIELD_LABELS.get(f, f) for f in missing)
            + ", so those cannot be refreshed."
        )

    for change in plan.changes:
        plan.field_counts[change.field] = plan.field_counts.get(change.field, 0) + 1
    plan.changes.sort(key=lambda c: (c.sheet, c.row, c.field))
    if "status" in fields:
        plan.progress = progress(layout, current)
    return plan, targets


def plan_update(
    data: bytes,
    filename: str,
    current: list[BacklogRow],
    kind: str,
    quarter: str,
    last_sync: datetime | None,
    fields: tuple[str, ...] = JIRA_FIELDS,
) -> FileUpdatePlan:
    """Report what refreshing this file from the platform would change, without writing."""
    layout = read_layouts(data, filename, fields, ALL_ALIASES)
    plan, _ = _plan_from(layout, filename, current, kind, quarter, last_sync, fields)
    return plan


def _marker_column(ws, sheet_layout: SheetLayout) -> int:
    """Find or create the column the updater writes its per-row notes into."""
    header_row = sheet_layout.header_row
    for cell in ws[header_row]:
        if text_of(cell.value).strip().lower() == MARKER_HEADER.lower():
            return cell.column
    column = max(ws.max_column, *sheet_layout.columns.values(), sheet_layout.key_column) + 1
    head = ws.cell(row=header_row, column=column)
    head.value = MARKER_HEADER
    reference = ws.cell(row=header_row, column=sheet_layout.key_column)
    head._style = copy(reference._style)
    ws.column_dimensions[get_column_letter(column)].width = 26
    return column


def _write_cell(ws, row: int, column: int, name: str, value: str):
    cell = ws.cell(row=row, column=column)
    if name in NUMERIC:
        cell.value = float(value or 0)
    elif name in INTEGER:
        cell.value = int(value) if value else None
    else:
        # A field Jira no longer has a value for should leave a blank cell, not an
        # empty string, so filters and COUNTA in the file behave as people expect.
        cell.value = value or None
    if name == "ndp_status":
        fill = NDP_FILLS.get(value.strip())
        if fill:
            cell.fill = copy(fill)
    return cell


def _restamp(ws):
    """Keep an `about` or `summary` sheet's timestamp honest after a refresh."""
    for row in ws.iter_rows(min_col=1, max_col=1):
        for cell in row:
            if _norm(cell.value) in STAMP_LABELS:
                ws.cell(row=cell.row, column=2).value = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )


def build_updated_workbook(
    data: bytes,
    filename: str,
    current: list[BacklogRow],
    kind: str,
    quarter: str,
    last_sync: datetime | None,
    fields: tuple[str, ...] = JIRA_FIELDS,
    add_new: bool = True,
    flag_gone: bool = True,
) -> tuple[bytes, FileUpdatePlan]:
    """Write the refreshed workbook, returning the bytes and what was done to it."""
    layout = read_layouts(data, filename, fields, ALL_ALIASES)
    plan, targets = _plan_from(layout, filename, current, kind, quarter, last_sync, fields)
    try:
        wb = load_workbook(BytesIO(data))
    except Exception as exc:  # already parsed once, so this is not a bad upload
        raise SpreadsheetError(f"{filename} could not be reopened for writing: {exc}") from exc

    log: list[tuple] = []
    for target in targets:
        sheet_layout = target.layout
        if target.sheet is None:
            continue
        ws = wb[sheet_layout.name]
        writable = {f: c for f, c in sheet_layout.columns.items() if f in fields}
        marker = None

        gone_here = {
            g.row: g.reason for g in plan.gone_rows if g.sheet == sheet_layout.name
        }
        for key, row_number in sheet_layout.keys:
            live = target.rows.get(key)
            if live is None:
                if flag_gone:
                    marker = marker or _marker_column(ws, sheet_layout)
                    ws.cell(row=row_number, column=marker).value = gone_here.get(row_number, "")
                continue
            if live.archived and flag_gone:
                marker = marker or _marker_column(ws, sheet_layout)
                ws.cell(row=row_number, column=marker).value = gone_here.get(row_number, "")
            for name, column in writable.items():
                in_file = text_of(sheet_layout.value(row_number, column))
                live_text = _platform_text(live, name)
                if same_value(name, in_file, live_text):
                    continue
                _write_cell(ws, row_number, column, name, live_text)
                log.append((sheet_layout.name, key, FIELD_LABELS.get(name, name), in_file, live_text))

        if add_new:
            new_keys = [n.key.upper() for n in plan.new_rows if n.sheet == sheet_layout.name]
            if new_keys:
                marker = marker or _marker_column(ws, sheet_layout)
                style_row = max((r for _, r in sheet_layout.keys), default=sheet_layout.header_row)
                at = ws.max_row + 1
                for key in new_keys:
                    live = target.rows[key]
                    _clone_row(ws, style_row, at, sheet_layout, live, writable, marker)
                    log.append((sheet_layout.name, live.key, "(row added)", "", live.status))
                    at += 1

    for ws in wb.worksheets:
        if _norm(ws.title) in {"about", "summary"}:
            _restamp(ws)

    _write_log(wb, plan, log, kind, quarter, last_sync)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue(), plan


def _clone_row(ws, style_row: int, at: int, sheet_layout, live, writable, marker: int):
    """Append one backlog, borrowing the styling of the last row already there."""
    width = max(ws.max_column, marker)
    for column in range(1, width + 1):
        cell = ws.cell(row=at, column=column)
        cell._style = copy(ws.cell(row=style_row, column=column)._style)
        cell.value = None
    ws.cell(row=at, column=sheet_layout.key_column).value = live.key
    for name, column in writable.items():
        _write_cell(ws, at, column, name, _platform_text(live, name))
    # User columns are left empty on purpose: nobody has ranked or commented on a
    # backlog that did not exist when the file was shared.
    for name, column in sheet_layout.columns.items():
        if name in USER_FIELDS:
            ws.cell(row=at, column=column).value = None
    ws.cell(row=at, column=marker).value = "new since this file was exported"


def _write_log(wb, plan: FileUpdatePlan, log: list[tuple], kind, quarter, last_sync):
    if LOG_SHEET in wb.sheetnames:
        del wb[LOG_SHEET]
    ws = wb.create_sheet(LOG_SHEET)
    bold = Font(bold=True)
    for label, value in [
        ("Source file", plan.filename),
        ("Report", f"{kind} - {quarter}"),
        ("Jira last updated", str(last_sync or "never")),
        ("Refreshed", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Cells updated", str(len(log))),
        ("Backlogs added", str(len(plan.new_rows))),
        ("Backlogs flagged", str(len(plan.gone_rows))),
    ]:
        ws.append([label, value])
        ws.cell(row=ws.max_row, column=1).font = bold
    ws.append([])
    ws.append(["Sheet", "Backlog", "Field", "Was", "Now"])
    for cell in ws[ws.max_row]:
        cell.font = bold
    for entry in log:
        ws.append(list(entry))
    for column, width in zip("ABCDE", (16, 16, 20, 46, 46)):
        ws.column_dimensions[column].width = width


def _status_key(status: str) -> tuple:
    """Order statuses the way the workflow runs: '20-...' before '100-...'."""
    head = status.split("-", 1)[0]
    return (0, int(head), status) if head.isdigit() else (1, 0, status)


def progress(layout, current: list[BacklogRow]) -> FileProgress:
    """How many backlogs and NDPs sit in each status, in the file and in Jira now.

    "Now" covers the same report sheets the file covers, including backlogs raised
    since it was exported, so the two columns describe the same piece of work. A
    backlog Jira has dropped still counts in the file and not now.

    Counted once per report sheet: a working file often repeats a region sheet in a
    reordered priority-list tab, and those are the same backlogs, not twice as many.
    """
    file_status: dict[tuple[str, str], str] = {}  # (report sheet, key) -> status
    covered: set[str] = set()
    file_ndps: dict[str, str] = {}
    now_ndps: dict[str, str] = {}

    for target in _targets(layout, current):
        if target.sheet is None:
            continue
        sheet = target.layout
        status_col = sheet.columns.get("status")
        ndp_col = sheet.columns.get("ndp")
        ndp_status_col = sheet.columns.get("ndp_status")
        for key, row in sheet.keys:
            if status_col:
                file_status[(target.sheet, key)] = (
                    text_of(sheet.value(row, status_col)) or "(blank)"
                )
            if ndp_col and ndp_status_col:
                ndp = text_of(sheet.value(row, ndp_col))
                if ndp.startswith("NDP-"):
                    file_ndps[ndp] = text_of(sheet.value(row, ndp_status_col)) or "(blank)"
        covered.add(target.sheet)

    now_backlogs: Counter[str] = Counter()
    for row in current:
        if row.sheet not in covered or row.archived:
            continue
        now_backlogs[row.status or "(blank)"] += 1
        if row.ndp.startswith("NDP-"):
            now_ndps[row.ndp] = row.ndp_status or "(blank)"
    file_backlogs = Counter(file_status.values())

    def table(before: Counter, after: Counter) -> list[StatusCount]:
        return [
            StatusCount(status=s, in_file=before.get(s, 0), now=after.get(s, 0))
            for s in sorted(set(before) | set(after), key=_status_key)
        ]

    return FileProgress(
        backlogs=table(file_backlogs, now_backlogs),
        ndps=table(Counter(file_ndps.values()), Counter(now_ndps.values())),
        backlogs_in_file=sum(file_backlogs.values()),
        backlogs_now=sum(now_backlogs.values()),
    )
