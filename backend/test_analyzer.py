"""Checks for the spreadsheet analyzer, run against workbooks built in memory.

No server, no Jira, no database: `parse_workbook` and `compare` are the parts that
have to cope with whatever layout a circulated copy comes back in, so they are
exercised directly with renamed headers, junk rows, and unknown keys.
"""
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.schemas import BacklogRow  # noqa: E402
from app.services.spreadsheet_analyzer import (  # noqa: E402
    AnalyzerError,
    compare,
    parse_workbook,
)

failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)
    return condition


def book(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def row(sheet, key, **over) -> BacklogRow:
    base = dict(
        id=abs(hash((sheet, key))) % 10000,
        sheet=sheet,
        region=sheet.split("_")[0],
        domain=sheet.split("_")[1],
        key=key,
        release="R1",
        release_title="Release one",
        ndp="NDP-1",
        ndp_status="Verified",
        ndp_deploy_date="2026-09-01",
        summary=f"Summary for {key}",
        issue_type="Story",
        status="20-RequirementCompleted",
        assignee="A Person",
        reporter="B Person",
        priority="Medium",
        biz_domain="GL",
        req_qtr="2026Q3",
        labels="",
        backlog_source="",
        est_h=0.0,
        spent_h=0.0,
        archived=False,
        rank=0,
        developer="",
        uat_eta="",
        prod_eta="",
        comments="",
    )
    return BacklogRow(**{**base, **over})


def test_renamed_headers_and_junk_rows():
    """Headers get renamed and a title block gets pasted above them; both survive."""
    data = book(
        {
            "NA_GL": [
                ["GL backlog review - do not distribute"],
                ["Owner: someone else", None, None],
                [],
                ["#", "Backlog", "Summary", "Dev Owner", "UAT", "Go-Live", "Remarks"],
                [3, "CISGL-1", "ignored", "Ann Lee", datetime(2026, 9, 15), "2026-10-01", " Needs   sign-off "],
                [1, "CISGL-2", "ignored", "", None, None, "Blocked on vendor"],
                [None, "not-a-key", "junk", "X", "", "", ""],
            ]
        }
    )
    parsed = parse_workbook(data, "review.xlsx")
    check(parsed.sheets_read == ["NA_GL"], f"sheet not read: {parsed.sheets_read}")
    check(len(parsed.rows) == 2, f"expected 2 data rows, got {len(parsed.rows)}")
    check(
        set(parsed.detected_columns) == {"key", "rank", "developer", "uat_eta", "prod_eta", "comments"},
        f"columns missed: {parsed.detected_columns}",
    )
    first = parsed.rows[0]
    check(first.key == "CISGL-1", f"key wrong: {first.key}")
    check(first.values["uat_eta"] == "2026-09-15", f"date not normalized: {first.values}")
    check(first.values["rank"] == "3", f"rank not read as int: {first.values}")

    current = [
        row("NA_GL", "CISGL-1", rank=1, developer="ann lee", comments="Needs sign-off"),
        row("NA_GL", "CISGL-2", rank=2),
    ]
    result = compare(parsed, current)
    changed = {(r.key, c.field): c for r in result.rows for c in r.changes}
    # "ann lee" vs "Ann Lee" and the double-spaced comment are the same value.
    check(("CISGL-1", "developer") not in changed, "casing counted as a change")
    check(("CISGL-1", "comments") not in changed, "whitespace counted as a change")
    check(result.unchanged_cells == 2, f"unchanged not counted: {result.unchanged_cells}")
    check(changed[("CISGL-1", "uat_eta")].state == "added", "new value not marked added")
    check(changed[("CISGL-1", "rank")].current == "1", "current rank not reported")
    check(changed[("CISGL-1", "rank")].incoming == "3", "incoming rank not reported")
    check(changed[("CISGL-2", "comments")].state == "added", "CISGL-2 comment missed")
    check(("CISGL-2", "rank") in changed, "CISGL-2 rank change missed")
    print(f"renamed headers: {len(parsed.rows)} rows read, {len(changed)} cells differ")


def test_blank_cells_never_clear_a_value():
    data = book({"NA_GL": [["Key", "Developer", "Comments"], ["CISGL-1", "", ""]]})
    parsed = parse_workbook(data, "blanks.xlsx")
    result = compare(parsed, [row("NA_GL", "CISGL-1", developer="Keep Me", comments="Keep this")])
    check(result.rows == [], f"blank cells proposed a change: {result.rows}")
    print("blank cells: nothing proposed, existing values kept")


def test_unmatched_keys_and_skipped_sheets():
    data = book(
        {
            "about": [["Report", "GL"], ["Exported", "yesterday"]],
            "NA_GL_tree": [["Backlog Key", "Comments"], ["CISGL-1", "from the tree"]],
            "NA_GL": [["Backlog Key", "Comments"], ["CISGL-1", "real"], ["KSPE-9", "excluded"]],
        }
    )
    parsed = parse_workbook(data, "mixed.xlsx")
    check(parsed.sheets_read == ["NA_GL"], f"wrong sheets read: {parsed.sheets_read}")
    check(len(parsed.sheets_ignored) == 2, f"skip list wrong: {parsed.sheets_ignored}")
    result = compare(parsed, [row("NA_GL", "CISGL-1")])
    check(result.unmatched_keys == ["KSPE-9"], f"unmatched wrong: {result.unmatched_keys}")
    check(len(result.rows) == 1, f"expected 1 changed row, got {len(result.rows)}")
    print(f"skipped sheets: {parsed.sheets_ignored}; unmatched: {result.unmatched_keys}")


def test_sheet_resolution_across_overlapping_sheets():
    """A key lives in both NA_GL and NA_AR+GL, so the worksheet name has to decide."""
    current = [row("NA_GL", "CISGL-1"), row("NA_AR+GL", "CISGL-1")]

    named = parse_workbook(
        book({"NA AR + GL": [["Key", "Rank", "Comments"], ["CISGL-1", 4, "ranked here"]]}),
        "named.xlsx",
    )
    result = compare(named, current)
    check([r.sheet for r in result.rows] == ["NA_AR+GL"], f"sheet not pinned: {result.rows}")
    check(
        {c.field for c in result.rows[0].changes} == {"rank", "comments"},
        "rank withheld from a named sheet",
    )

    anonymous = parse_workbook(
        book({"Sheet1": [["Key", "Rank", "Comments"], ["CISGL-1", 4, "everywhere"]]}),
        "anon.xlsx",
    )
    result = compare(anonymous, current)
    check(
        sorted(r.sheet for r in result.rows) == ["NA_AR+GL", "NA_GL"],
        f"text should reach both sheets: {[r.sheet for r in result.rows]}",
    )
    check(
        all(c.field == "comments" for r in result.rows for c in r.changes),
        "rank applied to an ambiguous sheet",
    )
    check(any("Ranking from 'Sheet1'" in w for w in result.warnings), "no warning about rank")
    print("sheet resolution: named sheet keeps rank, ambiguous sheet does not")


def test_unreadable_files_explain_themselves():
    for data, name, hint in [
        (b"not a workbook", "notes.xlsx", "could not be read"),
        (b"\xd0\xcf\x11\xe0", "old.xls", ".xls format"),
        (book({"NA_GL": [["Release", "Status"], ["R1", "Open"]]}), "nokeys.xlsx", "No backlog rows"),
    ]:
        try:
            parse_workbook(data, name)
            failures.append(f"{name} should have been rejected")
        except AnalyzerError as exc:
            check(hint in str(exc), f"{name}: unhelpful message: {exc}")
    print("bad files: rejected with an actionable message")


def main():
    for test in (
        test_renamed_headers_and_junk_rows,
        test_blank_cells_never_clear_a_value,
        test_unmatched_keys_and_skipped_sheets,
        test_sheet_resolution_across_overlapping_sheets,
        test_unreadable_files_explain_themselves,
    ):
        try:
            test()
        except Exception as exc:  # a crash is a failure, not a stack trace
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: the analyzer reads renamed layouts and proposes only real changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
