"""Opening, using and removing a quarter, against a running API.

A quarter is created empty and only fills up when someone runs Update from Jira,
so the checks here are that it appears at once, that all three reports exist and
are empty, that every page and download works before any sync, and that it can be
taken back off the list while it is still untouched.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import DEFAULT_QUARTER  # noqa: E402

# Set BACKLOG_API when the app is served somewhere other than the default port.
API = os.getenv("BACKLOG_API", "http://127.0.0.1:8000").rstrip("/") + "/api"
KINDS = ("AR_GL", "AR", "GL")
# Far enough out that a real quarter is never borrowed for the test.
NEW = "2099Q4"

failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)
    return condition


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return payload if raw else json.loads(payload.decode())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "detail": json.loads(e.read().decode()).get("detail")}


def main():
    if NEW in call("GET", "/quarters"):
        call("DELETE", f"/quarters/{NEW}")

    before = call("GET", "/quarters")
    print(f"quarters before: {before}")

    for bad in ("2026", "26Q4", "2026Q5", "next quarter", ""):
        refused = call("POST", "/quarters", {"quarter": bad})
        if refused.get("__error__") != 400:
            failures.append(f"'{bad}' should be refused as a quarter name, got {refused}")
    print("bad names refused: 2026, 26Q4, 2026Q5, 'next quarter', empty")

    # Lower case and stray spaces are the same quarter, not a different one.
    after = call("POST", "/quarters", {"quarter": " 2099q4 "})
    if "__error__" in after:
        print(f"could not add {NEW}: {after}")
        return 1
    check(NEW in after, f"{NEW} is not on the list after adding it: {after}")
    check(after == sorted(set(before) | {NEW}, reverse=True),
          f"quarter list is wrong after adding: {after}")
    print(f"added -> {after}")

    again = call("POST", "/quarters", {"quarter": NEW})
    check(again.get("__error__") == 409, f"adding {NEW} twice should conflict, got {again}")

    reports = call("GET", f"/reports?quarter={NEW}")
    check([r["kind"] for r in reports] == list(KINDS),
          f"expected all three reports, got {[r['kind'] for r in reports]}")
    check(all(r["item_count"] == 0 for r in reports), f"a new quarter should be empty: {reports}")
    check(all(r["last_sync_status"] == "never" for r in reports),
          f"a new quarter should never have synced: {reports}")
    print(f"three reports exist and are empty: "
          f"{[(r['kind'], r['item_count'], r['last_sync_status']) for r in reports]}")

    # Every page has to survive an empty quarter rather than erroring.
    for kind in KINDS:
        detail = call("GET", f"/reports/{kind}/{NEW}")
        check(detail.get("items") == [], f"{kind}: expected no rows, got {detail}")
        check(detail.get("sheets") == [], f"{kind}: expected no sheets, got {detail}")
        tree = call("GET", f"/reports/{kind}/{NEW}/tree")
        check(tree == [], f"{kind}: expected an empty tree, got {tree}")
        snaps = call("GET", f"/reports/{kind}/{NEW}/snapshots")
        check(snaps == [], f"{kind}: expected no snapshots, got {snaps}")
        export = call("GET", f"/reports/{kind}/{NEW}/export", raw=True)
        check(isinstance(export, dict) and export.get("__error__") == 404,
              f"{kind}: exporting an empty quarter should 404, got {type(export)}")
    print("table, tree, snapshots and export all behave on an empty quarter")

    # The default quarter is the floor of the list and cannot be taken away.
    kept = call("DELETE", f"/quarters/{DEFAULT_QUARTER}")
    check(kept.get("__error__") == 409,
          f"the default quarter should not be removable, got {kept}")

    left = call("DELETE", f"/quarters/{NEW}")
    check(NEW not in left, f"{NEW} should be gone, got {left}")
    check(left == before, f"the list should be back as it was: {left} != {before}")
    print(f"removed -> {left}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: a quarter opens empty, works everywhere, and can be taken back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
