"""Fetch Jira data through the jira-rel-review skill and flatten it into snapshot rows.

The skill's build_report_workbook() returns the fully classified data in memory
before any Excel is written, so all region/exclusion/dedupe rules are inherited
rather than reimplemented here.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from ..config import REPORT_SPECS, SKILL_DIR
from .exclusions import excluded_release

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
    rows = flatten(combo_data, report_kind, quarter)
    return [r for r in rows if not excluded_release(r["release_title"])]


# Keys per changelog search. Keeps each JQL `key in (...)` well under URL limits.
NDP_BATCH = 50


def _jira_time(value: str) -> datetime:
    """Jira's '2026-10-19T01:18:10.157-0700' as a local naive datetime, like the DB."""
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, pattern).astimezone().replace(tzinfo=None)
        except ValueError:
            continue
    raise ValueError(f"unrecognised Jira timestamp: {value!r}")


def _entered_current_status(issue: dict) -> datetime:
    """When this issue moved into the status it is in now.

    The latest changelog entry that set the status to its current value. An issue
    that has never been transitioned has been in its first status since creation.
    """
    fields = issue.get("fields") or {}
    current = ((fields.get("status") or {}).get("name")) or ""
    moves = [
        _jira_time(history["created"])
        for history in (issue.get("changelog") or {}).get("histories") or []
        for item in history.get("items") or []
        if item.get("field") == "status" and item.get("toString") == current
    ]
    return max(moves) if moves else _jira_time(fields["created"])


def fetch_ndp_status_since(keys: list[str]) -> dict[str, tuple[str, datetime]]:
    """Current status of each NDP and the moment it entered that status.

    One JQL search per batch with the changelog expanded, so a report's worth of
    NDPs costs a request or two rather than one each. Keys Jira does not return
    (deleted, or not visible to this PAT) are simply absent from the result.
    """
    keys = sorted({k for k in keys if k and k.startswith("NDP-")})
    if not keys:
        return {}
    skill = _load_skill()
    skill.load_jira_env()
    hierarchy = sys.modules["export_hierarchy"]
    auth = skill.build_auth_header()
    base = (os.getenv("JIRA_URL") or os.getenv("JIRA_SERVER_URL") or "").strip().rstrip("/")
    if not auth or not base:
        raise RuntimeError("No Jira credentials. Put JIRA_URL and JIRA_PAT in backend/.env.")

    found: dict[str, tuple[str, datetime]] = {}
    for start in range(0, len(keys), NDP_BATCH):
        batch = keys[start : start + NDP_BATCH]
        query = urllib.parse.urlencode(
            {
                "jql": f"key in ({','.join(batch)})",
                "fields": "status,created",
                "expand": "changelog",
                "maxResults": len(batch),
            }
        )
        for issue in hierarchy.api_get(base, auth, f"search?{query}").get("issues") or []:
            changelog = issue.get("changelog") or {}
            # A search can cap the changelog it inlines. The newest entries are the
            # ones dropped, and those are exactly the ones needed, so fetch whole.
            if changelog.get("total", 0) > len(changelog.get("histories") or []):
                issue = hierarchy.api_get(
                    base, auth, f"issue/{issue['key']}?fields=status,created&expand=changelog"
                )
            status = (((issue.get("fields") or {}).get("status") or {}).get("name")) or ""
            found[issue["key"]] = (status, _entered_current_status(issue))
    return found


def fetch_by_keys(keys: list[str], report_kind: str, quarter: str) -> dict[str, dict]:
    """Current Jira state of specific backlogs, as the same flat rows a sync makes.

    For backlogs a team still tracks that the report leaves out, chiefly 100-Done with
    no hours logged: a backlog that finishes drops out of the report exactly when its
    status is worth refreshing.
    Same fields, same record builder and the same release / NDP
    enrichment as a sync; only the JQL differs, `key in (...)`.

    Excluded projects and releases are left out, as everywhere else. Keys Jira does not
    return (deleted, or not visible to this PAT) are absent from the result.
    """
    keys = sorted({k for k in keys if k})
    if not keys:
        return {}
    skill = _load_skill()
    hierarchy = sys.modules["export_hierarchy"]
    skill.load_jira_env()
    cfg = skill.load_config()
    base = (os.getenv("JIRA_URL") or os.getenv("JIRA_SERVER_URL") or "").strip().rstrip("/")
    auth = skill.build_auth_header()
    if not auth or not base:
        raise RuntimeError("No Jira credentials. Put JIRA_URL and JIRA_PAT in backend/.env.")

    source_name = cfg.get("backlog_source_field_name", "backlog source").lower()
    backlog_source = hierarchy.resolve_field_ids(base, auth, {source_name}).get(source_name)
    release_field, deploy_field = cfg.get("snx_release_field"), cfg.get("deploy_plan_field")
    fields = [
        "summary", "issuetype", "status", "assignee", "reporter", "priority",
        "labels", "timeoriginalestimate", "timespent", "timetracking",
        deploy_field, release_field,
    ]
    extra = {"labels": "labels"}
    for name, field_id in (("biz_domain", cfg.get("biz_domain_field")),
                           ("req_qtr", cfg.get("req_qtr_field"))):
        if field_id:
            extra[name] = field_id
            fields.append(field_id)
    if backlog_source:
        fields.append(backlog_source)

    records = []
    for start in range(0, len(keys), NDP_BATCH):
        jql = f"key in ({','.join(keys[start : start + NDP_BATCH])})"
        for issue in skill.search_all(base, auth, jql, fields):
            record = hierarchy.record_from_issue(
                issue, None, release_field, deploy_field, backlog_source, extra_fields=extra,
            )
            # Excluded projects stay excluded, even when a file still lists them.
            if not skill.should_exclude_record(record):
                records.append(record)
    tree = hierarchy.build_tree(records)
    release_meta, ndp_meta = hierarchy.enrich_metadata(base, auth, tree)
    rows = flatten([("OUTSIDE_REPORT", tree, release_meta, ndp_meta)], report_kind, quarter)
    return {r["key"]: r for r in rows if not excluded_release(r["release_title"])}
