"""Work out where the data is inside a backlog workbook nobody kept to a template.

Copies of the report circulate by email and come back with the columns renamed, a
title block pasted on top, and the sheets reordered. Both spreadsheet features need
the same answer first — which row is the header, which column holds the backlog key,
and which column is which field — so that reading lives here once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

# What the platform lets people edit, and therefore never overwrites from Jira.
# "comments" is the IT Comment. A legacy "Comments" column lands there too, which
# is where the team decided pre-split comments belong.
USER_FIELDS = ("rank", "package", "developer", "uat_eta", "prod_eta", "comments", "tpm_comment")

# What Jira owns. Refreshing a circulated file rewrites these and nothing else.
JIRA_FIELDS = (
    "release",
    "release_title",
    "ndp",
    "ndp_status",
    "ndp_deploy_date",
    "summary",
    "issue_type",
    "status",
    "assignee",
    "reporter",
    "priority",
    "biz_domain",
    "req_qtr",
    "labels",
    "backlog_source",
    "est_h",
    "spent_h",
)

# Header spellings seen in copies that have been passed around and renamed. Keys are
# compared after _norm(), so "UAT ETA", "uat_eta" and "Uat-Eta" all arrive as "uateta".
USER_ALIASES: dict[str, set[str]] = {
    "key": {
        "backlogkey", "key", "issuekey", "issue", "jirakey", "jiraid",
        "backlog", "backlogid", "backlogno", "ticket", "ticketid",
    },
    "rank": {
        "rank", "ranking", "order", "priorityrank", "priorityorder", "rankorder",
        "seq", "sequence", "no", "num", "sortorder",
    },
    "developer": {
        "developer", "dev", "devs", "assigneddev", "devowner", "devassignee",
        "devname", "owner", "resource",
    },
    "uat_eta": {"uateta", "uat", "uatdate", "uattargetdate", "uatplan", "situat", "sit"},
    "prod_eta": {
        "prodeta", "prod", "proddate", "production", "productioneta", "productiondate",
        "golive", "golivedate", "golivedt",
    },
    "comments": {
        "itcomment", "itcomments", "itnote", "itnotes",
        "comments", "comment", "remark", "remarks", "note", "notes", "feedback",
    },
    "tpm_comment": {"tpmcomment", "tpmcomments", "tpmnote", "tpmnotes", "tpmremark", "tpmremarks"},
    "package": {"package", "packages", "pkg", "module"},
}

JIRA_ALIASES: dict[str, set[str]] = {
    "release": {"release", "releasekey", "fixversion"},
    "release_title": {"releasetitle", "releasename", "releasesummary"},
    "ndp": {"ndp", "ndpkey", "ndpid"},
    "ndp_status": {"ndpstatus", "ndpstate"},
    "ndp_deploy_date": {"ndpdeploydate", "ndpdeploy", "ndpdate", "deploydate"},
    "summary": {"summary", "title", "backlogsummary", "description"},
    "issue_type": {"issuetype", "type"},
    "status": {"status", "backlogstatus", "jirastatus", "currentstatus"},
    "assignee": {"assignee", "assignedto"},
    "reporter": {"reporter", "requester", "requestedby"},
    "priority": {"priority", "jirapriority"},
    "biz_domain": {"bizdomain", "businessdomain", "domain"},
    "req_qtr": {"reqqtr", "requestquarter", "requestedquarter", "requiredquarter"},
    "labels": {"labels", "label"},
    "backlog_source": {"backlogsource", "source"},
    "est_h": {"esth", "esthours", "estimatedhours", "estimateh", "originalestimate", "estimate"},
    "spent_h": {"spenth", "spenthours", "timespent", "loggedhours", "actualhours"},
}

ALL_ALIASES: dict[str, set[str]] = {**USER_ALIASES, **JIRA_ALIASES}

# Headers _norm() would erase, because they carry no letters or digits at all.
SYMBOL_ALIASES = {"#": "rank", "##": "rank", "no.": "rank", "#no": "rank"}

# Sheets in the skill's workbooks that hold no editable mapping rows. Tree sheets do
# carry backlog keys, but as a hierarchy, so reading them would double-count.
SKIP_SHEETS = {"about", "summary", "legend", "info", "notes", "readme", "cover", "updatelog"}

KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{1,7}$")

HEADER_SCAN_ROWS = 15
MAX_ROWS = 20000


class SpreadsheetError(ValueError):
    """A problem with the uploaded file that the person who uploaded it can fix."""


def _norm(value: object) -> str:
    """Fold a header or sheet name to letters and digits, so styling cannot matter."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def match_field(header: object, aliases: dict[str, set[str]]) -> str | None:
    symbol = str(header or "").strip().lower()
    if symbol in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[symbol]
    key = _norm(header)
    if not key:
        return None
    for name, spellings in aliases.items():
        if key in spellings:
            return name
    return None


def text_of(value: object) -> str:
    """Cell value as the platform stores it: dates as dates, whole floats as ints."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.hour or value.minute or value.second:
            return value.strftime("%Y-%m-%d %H:%M")
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def rank_of(value: str) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def same_value(name: str, left: str, right: str) -> bool:
    """Cosmetic differences are not edits: whitespace and casing are ignored."""
    if name in ("rank", "est_h", "spent_h"):
        try:
            return float(left or 0) == float(right or 0)
        except (TypeError, ValueError):
            pass
    return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()


@dataclass
class SheetLayout:
    name: str
    header_row: int  # 1-based, as Excel numbers rows
    key_column: int  # 1-based
    columns: dict[str, int] = field(default_factory=dict)  # field -> 1-based column
    keys: list[tuple[str, int]] = field(default_factory=list)  # (key, row), file order
    grid: list[tuple] = field(default_factory=list)  # raw values, row 1 at index 0

    def value(self, row: int, column: int) -> object:
        """Cell value by Excel coordinates, or None past the end of the sheet."""
        if row - 1 >= len(self.grid):
            return None
        cells = self.grid[row - 1]
        return cells[column - 1] if column <= len(cells) else None


@dataclass
class WorkbookLayout:
    sheets: list[SheetLayout] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _score_header(row: tuple, aliases: dict[str, set[str]]) -> dict[str, int]:
    """Column number per field for one candidate header row."""
    found: dict[str, int] = {}
    for column, cell in enumerate(row, start=1):
        matched = match_field(cell, aliases)
        if matched and matched not in found:
            found[matched] = column
    return found


def _find_key_column(grid: list[tuple], start: int) -> int | None:
    """Column whose values look like CISGL-2412, used when no header names the key."""
    width = max((len(r) for r in grid[start:]), default=0)
    best, best_hits = None, 0
    for column in range(width):
        hits = sum(
            1
            for row in grid[start:]
            if column < len(row) and KEY_PATTERN.match(text_of(row[column]).upper())
        )
        if hits > best_hits:
            best, best_hits = column + 1, hits
    return best if best_hits >= 3 else None


def read_layouts(
    data: bytes,
    filename: str,
    wanted: tuple[str, ...],
    aliases: dict[str, set[str]] = ALL_ALIASES,
) -> WorkbookLayout:
    """Locate the table on every worksheet that carries at least one wanted field."""
    if filename.lower().endswith(".xls"):
        raise SpreadsheetError(
            f"{filename} is in the old .xls format. Open it in Excel and save it as "
            ".xlsx, then upload again."
        )
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise SpreadsheetError(
            f"{filename} could not be read as an Excel workbook ({exc}). Upload an "
            ".xlsx or .xlsm file exported from this platform or from the report."
        ) from exc

    layout = WorkbookLayout()
    try:
        for ws in wb.worksheets:
            name = ws.title
            folded = _norm(name)
            if folded in SKIP_SHEETS or folded.endswith("tree"):
                layout.ignored.append(f"{name} (not a mapping sheet)")
                continue

            grid = []
            for index, values in enumerate(ws.iter_rows(values_only=True)):
                if index >= MAX_ROWS:
                    layout.warnings.append(f"{name}: only the first {MAX_ROWS} rows were read.")
                    break
                grid.append(values)
            if not grid:
                layout.ignored.append(f"{name} (empty)")
                continue

            header_index, columns = -1, {}
            for index, row in enumerate(grid[:HEADER_SCAN_ROWS]):
                found = _score_header(row, aliases)
                if len(found) > len(columns):
                    header_index, columns = index, found
            if not columns:
                layout.ignored.append(f"{name} (no recognizable headers)")
                continue

            key_column = columns.get("key") or _find_key_column(grid, header_index + 1)
            if key_column is None:
                layout.ignored.append(f"{name} (no backlog key column)")
                continue
            if not any(f in columns for f in wanted):
                layout.ignored.append(f"{name} (none of the columns this needs)")
                continue

            keys = []
            for offset, row in enumerate(grid[header_index + 1 :], start=header_index + 2):
                if key_column > len(row):
                    continue
                value = text_of(row[key_column - 1]).upper()
                if KEY_PATTERN.match(value):
                    keys.append((value, offset))

            layout.sheets.append(
                SheetLayout(
                    name=name,
                    header_row=header_index + 1,
                    key_column=key_column,
                    columns={f: c for f, c in columns.items() if f != "key"},
                    keys=keys,
                    grid=grid,
                )
            )
    finally:
        wb.close()

    if not layout.sheets:
        detail = "; ".join(layout.ignored) or "the workbook has no worksheets"
        raise SpreadsheetError(
            f"No backlog rows were found in {filename}. Every worksheet was skipped: "
            f"{detail}. The file needs a Backlog Key column plus at least one of the "
            "columns this step reads."
        )
    return layout


def report_sheet_key(title: object) -> str:
    """Fold a tab name to the region sheet it stands for.

    'Q4_NA_GL_Priority_List' and 'NA_GL' both give 'nagl': the priority-list tab is
    the team's working copy of that region sheet, under the quarter's prefix.
    """
    key = _norm(title)
    key = re.sub(r"^q[1-4](?=na|lac)", "", key)
    return re.sub(r"prioritylist$", "", key)


def is_priority_tab(title: object) -> bool:
    return _norm(title).endswith("prioritylist")


def resolve_sheet(
    layout: SheetLayout, sheets: dict[str, str], by_key: dict[str, set[str]]
) -> str | None:
    """Which report sheet a worksheet stands for: its name if that is recognizable,
    otherwise whichever sheet holds the most of the keys it lists."""
    named = sheets.get(report_sheet_key(layout.name))
    if named:
        return named
    scores: dict[str, int] = {}
    for key, _ in layout.keys:
        for sheet in by_key.get(key, ()):
            scores[sheet] = scores.get(sheet, 0) + 1
    if not scores:
        return None
    best = max(scores.values())
    winners = sorted(s for s, n in scores.items() if n == best)
    return winners[0] if len(winners) == 1 else None
