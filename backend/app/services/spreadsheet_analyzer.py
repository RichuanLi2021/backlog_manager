"""Read a backlog workbook someone else edited and diff it against a report view.

Direction: file -> platform. Only the columns people are allowed to edit are read;
Jira-owned columns in the file are passed over, because Jira stays the source of
truth for them and an old copy must not be able to roll them back. The reverse trip,
refreshing a circulated file from the platform, lives in `spreadsheet_updater.py`.

Where the table is and which column is which is worked out by `spreadsheet_layout`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import AnalyzedChange, AnalyzedRow, BacklogRow, IdenticalRow
from .spreadsheet_layout import (
    USER_ALIASES,
    USER_FIELDS,
    SheetLayout,
    SpreadsheetError,
    _norm,
    rank_of,
    read_layouts,
    same_value,
    text_of,
)

# Kept for callers that predate the split into layout + analyzer.
AnalyzerError = SpreadsheetError


@dataclass
class ParsedRow:
    source_sheet: str
    source_row: int
    key: str
    values: dict[str, str]


@dataclass
class ParsedWorkbook:
    rows: list[ParsedRow] = field(default_factory=list)
    sheets_read: list[str] = field(default_factory=list)
    sheets_ignored: list[str] = field(default_factory=list)
    detected_columns: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    rows: list[AnalyzedRow] = field(default_factory=list)
    # Rows the file speaks about that the baseline already agrees with, kept so the
    # preview can show that the comparison ran rather than an empty screen.
    identical: list[IdenticalRow] = field(default_factory=list)
    matched_keys: set[str] = field(default_factory=set)
    unmatched_keys: list[str] = field(default_factory=list)
    unchanged_cells: int = 0
    warnings: list[str] = field(default_factory=list)
    # Per worksheet of the file, so the preview can show that every tab was read
    # rather than leaving people to guess which ones counted.
    matched_by_sheet: dict[str, set[str]] = field(default_factory=dict)
    targets_by_sheet: dict[str, set[str]] = field(default_factory=dict)


def _headers(parsed: ParsedWorkbook, sheet: SheetLayout, editable: dict[str, int]):
    """Record the spelling each recognized column arrived under, for the preview."""
    for name, column in {**editable, "key": sheet.key_column}.items():
        label = text_of(sheet.value(sheet.header_row, column))
        seen = parsed.detected_columns.setdefault(name, [])
        if label and label not in seen:
            seen.append(label)


def parse_workbook(data: bytes, filename: str) -> ParsedWorkbook:
    """Pull backlog keys and user-editable values out of an arbitrary .xlsx."""
    layout = read_layouts(data, filename, USER_FIELDS, USER_ALIASES)

    parsed = ParsedWorkbook(sheets_ignored=layout.ignored, warnings=layout.warnings)
    for sheet in layout.sheets:
        editable = {f: c for f, c in sheet.columns.items() if f in USER_FIELDS}
        if not editable:
            parsed.sheets_ignored.append(
                f"{sheet.name} (no Rank / Developer / UAT ETA / PROD ETA / Comments column)"
            )
            continue
        _headers(parsed, sheet, editable)
        parsed.sheets_read.append(sheet.name)
        for key, row in sheet.keys:
            values = {
                f: text_of(sheet.value(row, c))
                for f, c in editable.items()
                if text_of(sheet.value(row, c))
            }
            if values:
                parsed.rows.append(ParsedRow(sheet.name, row, key, values))

    if not parsed.sheets_read:
        raise SpreadsheetError(
            f"No editable columns were found in {filename}. Every worksheet was skipped: "
            f"{'; '.join(parsed.sheets_ignored)}. The file needs a Backlog Key column plus "
            "at least one of Rank, Developer, UAT ETA, PROD ETA or Comments."
        )
    return parsed


def compare(parsed: ParsedWorkbook, current: list[BacklogRow]) -> Comparison:
    """Diff the parsed file against the view the changes would be saved into.

    A worksheet named after a region sheet pins its rows to that sheet. Otherwise the
    key decides, and when a key lives in more than one sheet (`NA_AR` and `NA_AR+GL`
    both hold it) the text fields go to each of them while ranking is held back,
    because rank is only meaningful within one sheet.
    """
    by_key: dict[str, list[BacklogRow]] = {}
    for row in current:
        by_key.setdefault(row.key.upper(), []).append(row)
    sheets = {_norm(row.sheet): row.sheet for row in current}

    result = Comparison()
    taken: dict[tuple[str, str], str] = {}
    ambiguous: set[str] = set()

    for parsed_row in parsed.rows:
        candidates = by_key.get(parsed_row.key)
        if not candidates:
            if parsed_row.key not in result.unmatched_keys:
                result.unmatched_keys.append(parsed_row.key)
            continue
        result.matched_keys.add(parsed_row.key)
        result.matched_by_sheet.setdefault(parsed_row.source_sheet, set()).add(parsed_row.key)

        named = sheets.get(_norm(parsed_row.source_sheet))
        targets = [c for c in candidates if c.sheet == named] if named else []
        if not targets:
            targets = candidates
        rank_allowed = len(targets) == 1

        for target in targets:
            result.targets_by_sheet.setdefault(parsed_row.source_sheet, set()).add(target.sheet)
            spot = (target.sheet, target.key)
            if spot in taken and taken[spot] != parsed_row.source_sheet:
                result.warnings.append(
                    f"{target.key} appears in both '{taken[spot]}' and "
                    f"'{parsed_row.source_sheet}'; the later sheet was used."
                )
            taken[spot] = parsed_row.source_sheet

            changes: list[AnalyzedChange] = []
            agreed: list[str] = []
            for name in USER_FIELDS:
                incoming = parsed_row.values.get(name, "")
                if not incoming:
                    continue
                if name == "rank":
                    if not rank_allowed:
                        ambiguous.add(parsed_row.source_sheet)
                        continue
                    incoming = str(rank_of(incoming))
                    if incoming == "0":
                        continue
                present = str(getattr(target, name) or "")
                if same_value(name, present, incoming):
                    result.unchanged_cells += 1
                    agreed.append(name)
                    continue
                changes.append(
                    AnalyzedChange(
                        field=name,
                        current=present,
                        incoming=incoming,
                        state="changed" if present.strip() else "added",
                    )
                )
            if changes:
                result.rows.append(
                    AnalyzedRow(
                        sheet=target.sheet,
                        key=target.key,
                        summary=target.summary,
                        status=target.status,
                        archived=target.archived,
                        source_sheet=parsed_row.source_sheet,
                        source_row=parsed_row.source_row,
                        changes=changes,
                        unchanged=agreed,
                    )
                )
            elif agreed:
                result.identical.append(
                    IdenticalRow(
                        sheet=target.sheet,
                        key=target.key,
                        summary=target.summary,
                        fields=agreed,
                    )
                )

    for sheet_name in sorted(ambiguous):
        result.warnings.append(
            f"Ranking from '{sheet_name}' was skipped: its rows match more than one "
            "region sheet, and rank is only meaningful inside a single sheet. Rename "
            "the worksheet to a region sheet such as NA_GL to import its order."
        )
    result.rows.sort(key=lambda r: (r.sheet, r.key))
    result.identical.sort(key=lambda r: (r.sheet, r.key))
    return result
