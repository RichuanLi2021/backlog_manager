#!/usr/bin/env python3
"""
Review one or more Jira release tickets and summarize:
- release key
- title
- total estimate hours
- total spent hours
- deploy plan list ordered by linked issue ID

Input separators supported:
- comma
- spaces
- new lines

Examples:
  py jira-rel-review/review_releases.py REL-18133
  py jira-rel-review/review_releases.py REL-18133,REL-19875
  py jira-rel-review/review_releases.py REL-18133 REL-19875
  echo REL-18133 REL-19875 | py jira-rel-review/review_releases.py
"""
import base64
import argparse
import json
import os
import re
import sys
from datetime import date
import urllib.parse
import urllib.error
import urllib.request


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(WORKSPACE_ROOT, ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1].replace('\\"', '"')
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1].replace("\\'", "'")
            os.environ[k] = v


def build_auth_header():
    pat = os.getenv("JIRA_PAT", "").strip()
    email = os.getenv("JIRA_EMAIL", "").strip()
    token = os.getenv("JIRA_API_TOKEN", "").strip()
    if pat:
        return ("Authorization", f"Bearer {pat}")
    if email and token:
        b64 = base64.b64encode(f"{email}:{token}".encode()).decode()
        return ("Authorization", f"Basic {b64}")
    return None


def request_json(url, auth_header):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", auth_header[0]: auth_header[1]},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_issue(base_url, auth_header, key):
    last_err = None
    for ver in ("2", "3"):
        url = f"{base_url}/rest/api/{ver}/issue/{key}"
        try:
            return request_json(url, auth_header)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404 and ver == "2":
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError(f"Failed to fetch {key}")


def fetch_issue_fields(base_url, auth_header, key, fields=None):
    field_q = f"?fields={','.join(fields)}" if fields else ""
    last_err = None
    for ver in ("2", "3"):
        url = f"{base_url}/rest/api/{ver}/issue/{key}{field_q}"
        try:
            return request_json(url, auth_header)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404 and ver == "2":
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError(f"Failed to fetch {key}")


def search_by_snx_release(base_url, auth_header, release_key):
    jql = f'"Snx Release" = "{release_key}"'
    q = urllib.parse.quote(jql, safe="")
    fields = ",".join(
        [
            "summary",
            "status",
            "issuetype",
            "timeoriginalestimate",
            "timespent",
            "timetracking",
            "customfield_18302",
            "customfield_12107",
        ]
    )
    for ver in ("2", "3"):
        url = f"{base_url}/rest/api/{ver}/search?jql={q}&maxResults=500&fields={fields}"
        try:
            return request_json(url, auth_header)
        except urllib.error.HTTPError as e:
            if e.code == 404 and ver == "2":
                continue
            raise
    raise RuntimeError(f"Failed to search Snx Release for {release_key}")


def parse_release_keys(argv):
    raw = " ".join(argv[1:]).strip()
    if not raw and not sys.stdin.isatty():
        raw = sys.stdin.read()
    tokens = re.split(r"[\s,]+", raw.strip())
    keys = []
    for t in tokens:
        t = t.strip().upper()
        if t and re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", t):
            keys.append(t)
    return list(dict.fromkeys(keys))


def seconds_to_hours(seconds):
    if not seconds:
        return 0.0
    return round(float(seconds) / 3600.0, 2)


def issue_sort_key(key):
    m = re.fullmatch(r"([A-Z][A-Z0-9]+)-(\d+)", key or "")
    if not m:
        return (key or "", 0)
    return (m.group(1), int(m.group(2)))


def deploy_plan_sort_key(key):
    m = re.fullmatch(r"([A-Z][A-Z0-9]+)-(\d+)", key or "")
    if not m:
        return (key or "", 0)
    return (m.group(1), int(m.group(2)))


def format_add(value):
    if not value:
        return "N/A"
    text = str(value)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", text)
    if not m:
        return text
    months = {
        "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
        "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
        "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
    }
    return f"{m.group(3)}/{months.get(m.group(2), m.group(2))}/{m.group(1)}"


# NDP lines are wrapped in markdown **bold** when status matches or A.D.D is near today.
NDP_BOLD_STATUSES = frozenset({"IIC Approved", "QC Approved"})
NDP_ADD_DAY_WINDOW = 7


def parse_add_date(value):
    """Parse Jira Actual Deploy Date (often ISO YYYY-MM-DD...) to a date, or None."""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def ndp_line_should_bold(status, add_raw, today=None):
    """
    True if deploy plan line should be **bold**:
    - NDP status is IIC Approved or QC Approved, OR
    - Actual Deploy Date is present and within NDP_ADD_DAY_WINDOW calendar days of today (inclusive).
    """
    today = today or date.today()
    st = (status or "").strip()
    if st in NDP_BOLD_STATUSES:
        return True
    d = parse_add_date(add_raw)
    if d is None:
        return False
    return abs((d - today).days) <= NDP_ADD_DAY_WINDOW


def md_bold(text):
    return f"**{text}**"


def deploy_plan_rows(deploy_plans):
    rows = []
    for plan in deploy_plans:
        row = [plan["key"], plan["status"], plan["add"]]
        if ndp_line_should_bold(plan["status"], plan.get("add_raw")):
            row = [md_bold(str(c)) for c in row]
        rows.append(row)
    return rows


def render_table(headers, rows):
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))
    sep = " | "
    header_line = sep.join(str(h).ljust(widths[idx]) for idx, h in enumerate(headers))
    rule_line = "-+-".join("-" * widths[idx] for idx in range(len(headers)))
    body_lines = [
        sep.join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([header_line, rule_line] + body_lines)


def build_release_data(issue, related_issues, base_url, auth_header):
    fields = issue.get("fields") or {}
    backlog_issues = [
        i for i in related_issues if ((i.get("fields") or {}).get("issuetype") or {}).get("name") == "Backlog"
    ]
    release_est = round(
        sum(
            seconds_to_hours(
                (i.get("fields") or {}).get("timeoriginalestimate")
                or (((i.get("fields") or {}).get("timetracking") or {}).get("originalEstimateSeconds"))
            )
            for i in backlog_issues
        ),
        2,
    )
    release_spent = round(
        sum(
            seconds_to_hours(
                (i.get("fields") or {}).get("timespent")
                or (((i.get("fields") or {}).get("timetracking") or {}).get("timeSpentSeconds"))
            )
            for i in backlog_issues
        ),
        2,
    )
    deploy_plan_keys = sorted(
        {
            (((i.get("fields") or {}).get("customfield_18302") or {}).get("key"))
            for i in backlog_issues
            if ((i.get("fields") or {}).get("customfield_18302") or {}).get("key")
        },
        key=deploy_plan_sort_key,
    )
    deploy_plans = []
    for key in deploy_plan_keys:
        try:
            ndp = fetch_issue_fields(
                base_url,
                auth_header,
                key,
                fields=["summary", "status", "customfield_20411"],
            )
            nf = ndp.get("fields") or {}
            add_raw = nf.get("customfield_20411")
            deploy_plans.append(
                {
                    "key": key,
                    "summary": nf.get("summary") or "N/A",
                    "status": ((nf.get("status") or {}).get("name")) or "N/A",
                    "add": format_add(add_raw),
                    "add_raw": add_raw,
                }
            )
        except Exception:
            deploy_plans.append(
                {
                    "key": key,
                    "summary": "N/A",
                    "status": "N/A",
                    "add": "N/A",
                    "add_raw": None,
                }
            )

    return {
        "release": issue.get("key") or "N/A",
        "title": fields.get("summary") or "N/A",
        "status": ((fields.get("status") or {}).get("name")) or "N/A",
        "planned_uat": format_add(fields.get("customfield_14602")),
        "estimate_hours": release_est,
        "spent_hours": release_spent,
        "deploy_plans": deploy_plans,
    }


def render_release(release_data):
    lines = [
        "## REL Deploy plan list",
        f"Release #: {release_data['release']}",
    ]
    deploy_plans = release_data["deploy_plans"]
    if not deploy_plans:
        lines.append("N/A")
    else:
        lines.append(render_table(["NDP#", "Status", "A.D.D date"], deploy_plan_rows(deploy_plans)))
    return "\n".join(lines)


def render_release_table(release_data, base_url, auth_header):
    deploy_plan_keys = [p["key"] for p in release_data["deploy_plans"]]
    summary_rows = [[
        release_data["release"],
        release_data["title"],
        release_data["status"],
        release_data["planned_uat"],
        release_data["estimate_hours"],
        release_data["spent_hours"],
    ]]
    deploy_rows = []
    for key in deploy_plan_keys:
        try:
            ndp = fetch_issue_fields(base_url, auth_header, key, fields=["status", "customfield_20411"])
            nf = ndp.get("fields") or {}
            st = ((nf.get("status") or {}).get("name")) or "N/A"
            add_raw = nf.get("customfield_20411")
            add_fmt = format_add(add_raw)
            row = [key, st, add_fmt]
            if ndp_line_should_bold(st, add_raw):
                row = [md_bold(str(c)) for c in row]
            deploy_rows.append(row)
        except Exception:
            deploy_rows.append([key, "N/A", "N/A"])

    parts = [
        f"Release: {release_data['release']}",
        render_table(
            ["Release #", "Title", "Status", "Planned UAT Date", "Total Estimate Hours", "Total Spent Hours"],
            summary_rows,
        ),
        "",
        "Deploy Plan List",
    ]
    if deploy_rows:
        parts.append(render_table(["Deploy Plan", "Status", "A.D.D - deploy date"], deploy_rows))
    else:
        parts.append("N/A")
    return "\n".join(parts)


def render_release_summary_table(release_data_list):
    headers = ["Release", "Title", "Status", "Planned UAT", "Est h", "Spent h", "NDPs"]
    lines = [
        "## Release list",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for item in release_data_list:
        ndps = "N/A" if item.get("error") else str(len(item.get("deploy_plans") or []))
        row = [
            item.get("release", "N/A"),
            item.get("title", "N/A"),
            item.get("status", "N/A"),
            item.get("planned_uat", "N/A"),
            str(item.get("estimate_hours", "N/A")),
            str(item.get("spent_hours", "N/A")),
            ndps,
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Review Jira release tickets.")
    parser.add_argument("items", nargs="*", help="Release keys separated by spaces/commas")
    parser.add_argument("--table", action="store_true", help="Render plain text table layout")
    parser.add_argument("--output-file", help="Write output to a txt file")
    args = parser.parse_args()

    keys = parse_release_keys(["prog"] + args.items)
    if not keys and not sys.stdin.isatty():
        keys = parse_release_keys(["prog", sys.stdin.read()])
    if not keys:
        print(
            "Usage: py jira-rel-review/review_releases.py REL-123,REL-456 [--table] [--output-file out.txt]",
            file=sys.stderr,
        )
        sys.exit(1)

    load_dotenv(ENV_PATH)
    base_url = (os.getenv("JIRA_URL") or os.getenv("JIRA_SERVER_URL") or "").strip().rstrip("/")
    auth_header = build_auth_header()
    if not base_url or not auth_header:
        print(
            "FAILED: set JIRA_URL and JIRA_PAT (or JIRA_EMAIL + JIRA_API_TOKEN) in workspace .env",
            file=sys.stderr,
        )
        sys.exit(1)

    details = []
    summary = []
    for key in keys:
        try:
            issue = fetch_issue(base_url, auth_header, key)
            related = (search_by_snx_release(base_url, auth_header, key) or {}).get("issues") or []
            release_data = build_release_data(issue, related, base_url, auth_header)
            summary.append(release_data)
            if args.table:
                details.append(render_release_table(release_data, base_url, auth_header))
            else:
                details.append(render_release(release_data))
        except Exception as e:
            summary.append(
                {
                    "release": key,
                    "title": "N/A",
                    "status": "FAILED",
                    "planned_uat": "N/A",
                    "estimate_hours": "N/A",
                    "spent_hours": "N/A",
                    "deploy_plans": [],
                    "error": str(e),
                }
            )
            details.append(
                "\n".join(
                    [
                        "## Release review",
                        f"- Release #: {key}",
                        "- Result: FAILED",
                        f"- Error: {e}",
                        "- Deploy plan list: N/A",
                    ]
                )
            )
    final_text = "\n\n".join(
        [
            render_release_summary_table(summary),
            "\n\n---\n\n".join(details),
        ]
    )
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(final_text)
    else:
        print(final_text)


if __name__ == "__main__":
    main()
