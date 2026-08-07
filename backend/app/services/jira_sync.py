"""Fetch Jira data through the jira-rel-review skill and flatten it into snapshot rows.

The skill's build_report_workbook() returns the fully classified data in memory
before any Excel is written, so all region/exclusion/dedupe rules are inherited
rather than reimplemented here.
"""
import json
import sys
import urllib.request
from pathlib import Path

from ..config import REPORT_SPECS, SKILL_DIR

SEARCH_PASSES = 3
REQUEST_TIMEOUT = 60


def _request_json(url, auth_header):
    """Decode Jira responses that are not valid UTF-8.

    Some summaries come back with Windows-1252 bytes (en-dash 0x96); decoding
    those as UTF-8 with errors='replace' turns them into U+FFFD permanently.
    """
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", auth_header[0]: auth_header[1]}
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset()

    for encoding in (charset, "utf-8", "cp1252"):
        if not encoding:
            continue
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def _stabilize(search_all):
    """Run every Jira search several times and union the results.

    Jira intermittently drops trailing results under load, which would otherwise
    show up as backlogs vanishing from a report and being flagged archived. Every
    pass runs even when two agree, because consecutive passes can under-report by
    the same amount; the union means a short pass can only add, never remove.
    """

    def wrapped(base_url, auth_header, jql, fields):
        merged: dict[str, dict] = {}
        for _ in range(SEARCH_PASSES):
            for issue in search_all(base_url, auth_header, jql, fields):
                if issue.get("key"):
                    merged[issue["key"]] = issue
        return list(merged.values())

    return wrapped


def _load_skill():
    skill_dir = str(Path(SKILL_DIR))
    if skill_dir not in sys.path:
        sys.path.insert(0, skill_dir)
    import export_hierarchy
    import export_regions

    # export_regions imported search_all into its own namespace, but every request
    # ultimately routes through export_hierarchy.request_json.
    export_hierarchy.request_json = _request_json
    if not getattr(export_regions.search_all, "_stabilized", False):
        export_regions.search_all = _stabilize(export_regions.search_all)
        export_regions.search_all._stabilized = True
    return export_regions


def split_sheet(sheet: str) -> tuple[str, str]:
    """'NA_AR+GL' -> ('NA', 'AR+GL')"""
    region, _, domain = sheet.partition("_")
    return region, domain


def flatten(combo_data, report_kind: str, quarter: str) -> list[dict]:
    """Turn [(sheet, tree, release_meta, ndp_meta)] into one dict per backlog row."""
    skill = _load_skill()
    rows: list[dict] = []

    for sheet, tree, release_meta, ndp_meta in combo_data:
        region, domain = split_sheet(sheet)
        for rel in skill.sorted_releases(tree):
            rm = release_meta.get(rel, {})
            for ndp in skill.sorted_ndps(tree[rel]):
                nm = ndp_meta.get(ndp, {})
                for r in sorted(tree[rel][ndp], key=lambda x: skill.issue_sort_key(x["key"])):
                    rows.append(
                        {
                            "report_kind": report_kind,
                            "quarter": quarter,
                            "sheet": sheet,
                            "region": region,
                            "domain": domain,
                            "key": r["key"],
                            "release": rel,
                            "release_title": rm.get("title", ""),
                            "ndp": ndp,
                            "ndp_status": nm.get("status", ""),
                            "ndp_deploy_date": nm.get("add", ""),
                            "summary": r.get("summary", ""),
                            "issue_type": r.get("type", ""),
                            "status": r.get("status", ""),
                            "assignee": r.get("assignee", ""),
                            "reporter": r.get("reporter", ""),
                            "priority": r.get("priority", ""),
                            "biz_domain": r.get("biz_domain", "N/A"),
                            "req_qtr": r.get("req_qtr", "N/A"),
                            "labels": r.get("labels", "N/A"),
                            "backlog_source": r.get("backlog_source", ""),
                            "est_h": float(r.get("est") or 0.0),
                            "spent_h": float(r.get("spent") or 0.0),
                        }
                    )
    return rows


def fetch_report(report_kind: str, quarter: str) -> list[dict]:
    """Pull one report kind from Jira and return flat snapshot rows."""
    if report_kind not in REPORT_SPECS:
        raise ValueError(f"unknown report kind: {report_kind}")
    skill = _load_skill()
    skill.load_jira_env()
    if not skill.build_auth_header():
        raise RuntimeError(
            "No Jira credentials. Put JIRA_URL and JIRA_PAT in backend/.env, then restart."
        )
    combo_data, _summary = skill.build_report_workbook(
        quarter, domain_labels=REPORT_SPECS[report_kind]
    )
    return flatten(combo_data, report_kind, quarter)
