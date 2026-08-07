"""End-to-end check of the role-based snapshot workflow.

Adds users to each group, identifies them the way the Edit prompt does, saves a
snapshot as SE, re-runs a live Jira sync, and confirms the snapshot is unchanged
and still separate from the live view.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import ADMIN_KEY  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services import jira_sync, merge  # noqa: E402

API = "http://127.0.0.1:8000/api"
KIND, QUARTER, SHEET = "GL", "2026Q3", "NA_GL"

USERS = [
    {"email": "se.tester@tdsynnex.com", "name": "SE Tester", "role": "SE"},
    {"email": "tpm.tester@tdsynnex.com", "name": "TPM Tester", "role": "TPM"},
    {"email": "dev.tester@tdsynnex.com", "name": "Dev Tester", "role": "DEV"},
]

EDITS = {
    "developer": "Snapshot Test Dev",
    "uat_eta": "09/15/2026",
    "prod_eta": "10/01/2026",
    "comments": "Saved by test_snapshots.py",
}


def call(method, path, body=None, admin=True):
    headers = {"Content-Type": "application/json"}
    if admin:
        headers["X-Admin-Key"] = ADMIN_KEY
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            if "json" not in (r.headers.get("Content-Type") or ""):
                return {"__bytes__": len(payload)}
            return json.loads(payload.decode())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "detail": json.loads(e.read().decode()).get("detail")}


def rows_for(query=""):
    data = call("GET", f"/reports/{KIND}/{QUARTER}{query}")
    return [r for r in data["items"] if r["sheet"] == SHEET], data.get("snapshot")


def main():
    failures = []

    locked = call("POST", "/users", USERS[0], admin=False)
    if locked.get("__error__") not in (403, 503):
        failures.append(f"group changes should need the admin passphrase, got {locked}")
    print(f"add without passphrase -> {locked.get('__error__')}")

    for u in USERS:
        call("POST", "/users", u)
    print(f"users in groups: {[(u['email'], u['role']) for u in call('GET', '/users')]}")

    by_name = call("POST", "/users/identify", {"identifier": "SE Tester"})
    by_email = call("POST", "/users/identify", {"identifier": "SE.Tester@tdsynnex.com"})
    if by_name.get("role") != "SE" or by_email.get("role") != "SE":
        failures.append(f"identify failed: {by_name}, {by_email}")
    unknown = call("POST", "/users/identify", {"identifier": "nobody@example.com"})
    if unknown.get("__error__") != 404:
        failures.append(f"unknown user should 404, got {unknown}")
    print(f"identify by name -> {by_name.get('role')}, by email -> {by_email.get('role')}, unknown -> 404")

    live, _ = rows_for()
    if len(live) < 3:
        print("no live rows; run a sync first")
        return 1
    if any(r["developer"] or r["comments"] for r in live):
        failures.append("live view should have no user text")
    if any(r["rank"] <= 0 for r in live):
        failures.append("live view should fall back to a default ranking")

    target = live[0]
    keys = [r["key"] for r in live]
    reordered = [keys[2], *[k for k in keys if k != keys[2]]]
    payload = {
        "author_email": "se.tester@tdsynnex.com",
        "label": "test run",
        "rows": [
            {
                "sheet": SHEET,
                "key": key,
                "rank": i + 1,
                **(EDITS if key == target["key"] else {}),
            }
            for i, key in enumerate(reordered)
        ],
    }
    saved = call("POST", f"/reports/{KIND}/{QUARTER}/snapshots", payload)
    print(f"saved snapshot {saved['id']} as {saved['role']} by {saved['author_name']} ({saved['row_count']} rows)")

    # Ranks are typed by hand as well as dragged, so repeats have to survive.
    dupe = call(
        "POST",
        f"/reports/{KIND}/{QUARTER}/snapshots",
        {
            "author_email": "tpm.tester@tdsynnex.com",
            "label": "duplicate ranks",
            "rows": [{"sheet": SHEET, "key": k, "rank": 7} for k in keys[:3]],
        },
    )
    dupe_rows, _ = rows_for(f"?snapshot_id={dupe['id']}")
    got_ranks = sorted(r["rank"] for r in dupe_rows if r["key"] in keys[:3])
    if got_ranks != [7, 7, 7]:
        failures.append(f"duplicate ranks not kept: {got_ranks}")
    print(f"duplicate ranks stored as {got_ranks}")
    call("DELETE", f"/snapshots/{dupe['id']}")

    denied = call(
        "POST",
        f"/reports/{KIND}/{QUARTER}/snapshots",
        {"author_email": "nobody@example.com", "rows": []},
    )
    if denied.get("__error__") != 404:
        failures.append(f"unknown author should be rejected, got {denied}")

    se_rows, info = rows_for(f"?role=SE")
    got = {k: next(r for r in se_rows if r["key"] == target["key"])[k] for k in EDITS}
    if got != EDITS:
        failures.append(f"SE view lost edits: {got}")
    if se_rows[0]["key"] != keys[2]:
        failures.append(f"SE view rank order wrong: {se_rows[0]['key']} != {keys[2]}")

    live_after, _ = rows_for()
    if any(r["developer"] or r["comments"] for r in live_after):
        failures.append("live view was polluted by the snapshot")

    print("re-syncing from Jira...")
    db = SessionLocal()
    stats = merge.apply_snapshot(db, KIND, QUARTER, jira_sync.fetch_report(KIND, QUARTER))
    db.close()
    print(f"sync: {stats}")

    se_after, _ = rows_for(f"?snapshot_id={saved['id']}")
    got2 = {k: next(r for r in se_after if r["key"] == target["key"])[k] for k in EDITS}
    if got2 != EDITS:
        failures.append(f"snapshot did not survive refresh: {got2}")
    if se_after[0]["key"] != keys[2]:
        failures.append("rank order did not survive refresh")

    audit = call("GET", f"/audit?snapshot_id={saved['id']}")
    if len(audit) < len(EDITS):
        failures.append(f"expected >= {len(EDITS)} audit rows, got {len(audit)}")
    print(f"audit rows for snapshot: {len(audit)}; roles: {sorted({a['role'] for a in audit})}")

    snaps = call("GET", f"/reports/{KIND}/{QUARTER}/snapshots?role=SE")
    print(f"SE snapshots available: {[(s['id'], s['created_at']) for s in snaps]}")

    export = call("GET", f"/reports/{KIND}/{QUARTER}/export?snapshot_id={saved['id']}")
    if not export.get("__bytes__"):
        failures.append(f"export failed: {export}")
    print(f"export produced {export.get('__bytes__')} bytes")

    # Leave the database as it was found.
    call("DELETE", f"/snapshots/{saved['id']}")
    test_emails = {u["email"] for u in USERS}
    for u in call("GET", "/users"):
        if u["email"] in test_emails:
            call("DELETE", f"/users/{u['id']}")
    print("cleaned up test users and the test snapshot")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: role snapshots save, load, and survive a Jira refresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
