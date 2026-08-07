# Backlog Report Platform

A centralized web platform for SE, TPM, and DEV stakeholders to view, prioritize, and collaborate on Jira backlog reports — built on top of the existing **`jira-rel-review`** skill.

---

## Problem Statement

Today, backlog reporting is done via locally generated Excel files. This creates three recurring pain points:

| # | Pain Point | Impact |
|---|-----------|--------|
| 1 | **No centralized report** | Everyone generates their own Excel copy. Changes are not reflected in real time. People switch between versions and it is hard to track who has what. |
| 2 | **No flexibility to rank** | Reports mirror Jira query order. Once generated, teams cannot drag-and-drop to reprioritize by business need, or add custom comments/columns easily. |
| 3 | **Report falls behind** | Backlogs change weekly (new items, status moves, NDP updates). Local Excel files go stale immediately; other stakeholders never see the update unless someone re-sends a file. |

---

## Solution

A shared web application where:

- **Jira is the source of truth for status** (backlog status, NDP status, release status, hours).
- **The platform is the source of truth for collaboration** (rank/priority, comments, UAT ETA, PROD ETA, Developer assignment).
- Anyone with permission can click **"Update from Jira"** to refresh status fields while preserving user-edited fields.
- All stakeholders see the same live view — no more emailing Excel files.

```
┌─────────────┐     "Update"      ┌──────────────────┐     jira-rel-review     ┌──────┐
│  Web UI     │ ────────────────► │  Backend API     │ ──────────────────────► │ Jira │
│  drag/drop  │ ◄──────────────── │  + database      │ ◄────────────────────── │      │
│  comments   │   merged view     └──────────────────┘                         └──────┘
└─────────────┘
```

---

## Existing Skill (Foundation)

The platform wraps the existing Python skill at `jira-rel-review/`:

| Script | Purpose |
|--------|---------|
| `update_latest_reports.py` | Entry point — refreshes all three quarter reports |
| `export_regions.py` | Fetches Jira data, classifies NA/LAC, builds workbook |
| `export_hierarchy.py` | Jira API helpers, tree builder, field resolution |
| `regions.config.json` | Region JQL, domain filters, quarter config |

### Current report layout (Excel, to be replaced by web UI)

```
Report/
  AR_GL/AR_GL_Summary_<quarter>.xlsx   ← comprehensive (NA + LAC, AR + GL)
  AR/AR_Summary_<quarter>.xlsx          ← AR only
  GL/GL_Summary_<quarter>.xlsx          ← GL only
```

Each workbook contains:
- `summary` sheet with **Last Updated** timestamp
- Mapping sheets: `NA_AR`, `NA_GL`, `LAC_AR`, `LAC_GL`, etc.
- Tree sheets: `NA_GL_tree`, etc. (RELEASE → NDP → Backlog hierarchy)

### Mapping sheet columns (current)

```
Release | Release Title | NDP | NDP Status | NDP Deploy Date |
Backlog Key | Summary | Issue Type | Status | Assignee | Developer |
Reporter | Priority | Biz Domain | Req Qtr | Labels | Backlog Source |
Est h | Spent h | UAT ETA | PROD ETA | Comments
```

**Jira-sourced** (overwritten on every refresh): Status, NDP, NDP Status, NDP Deploy Date, Est h, Spent h, Assignee, etc.

**User-editable** (preserved on refresh): Developer, UAT ETA, PROD ETA, Comments, **Rank** (new in platform).

### Region classification rules (backend must enforce)

| Region | Rule |
|--------|------|
| **NA** | Key starts with `CISGL`, `CISAR`, or `CIS` (CISGL/CISAR always NA, even if LAC-labelled) |
| **LAC** | Key starts with `MCAM`, `WMCC`, or has label token `LAC` |
| **Exclude** | Key starts with `KSPE`, or label contains `gl-killsp` |

Fetch from both NA and LAC JQL, merge, dedupe, then route each backlog to the correct region sheet. Never duplicate across NA/LAC.

### Jira credentials

```
JIRA_URL=https://jira.synnex.com
JIRA_PAT=<personal access token>
```

Stored in `.env` at workspace root. PAT must live on the server only — never exposed to the browser.

---

## Status: built and running

The platform runs locally today: FastAPI + SQLite behind a React + Vite UI, pulling live
Jira data through the `jira-rel-review` skill. Start with [Running it](#running-it), then
[Editing workflow](#editing-workflow-roles-and-snapshots).

---

## MVP Scope (Phase 1)

### Features

1. **Report views** — AR_GL, AR, GL for configured quarter (default `2026Q3`)
2. **Flat backlog table** — sortable, searchable grid per region/domain sheet, with a
   dropdown to view one backlog status at a time
3. **Tree view** — RELEASE → NDP → Backlog collapsible hierarchy
4. **"Update from Jira" button** — runs the skill server-side as a background job with a
   duration estimate; only ever refreshes Jira columns
5. **Drag-and-drop ranking** — per sheet, inside a snapshot
6. **Inline editing** — Developer, UAT ETA, PROD ETA, Comments
7. **Groups** — System Engineer, TPM, Developer; membership decides the Save button, and
   changing membership needs the admin passphrase
8. **Role snapshots** — SE / TPM / DEV views, each with full save history by date and time
9. **Audit log** — who changed which field, from what to what, in which snapshot
10. **Excel export** — the visible view, styled like the skill's workbooks

### Refresh rules

```
For each backlog key in the report:
  IF key exists in Jira response:
    overwrite  → Status, NDP, NDP Status, NDP Deploy Date, Est h, Spent h,
                  Assignee, Summary, Priority, Release, Release Title, etc.
  IF key is new in Jira (not in DB):
    insert
  IF key missing from Jira twice in a row:
    mark as archived / show stale badge

Snapshots are never read or written by a refresh, so user values cannot be lost.
```

### Out of scope for MVP (Phase 2)

- Custom columns per team
- Manual rows (backlogs not yet in Jira)
- Push notifications on NDP status change
- Multi-quarter comparison

---

## Tech Stack (as built)

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Backend** | Python FastAPI | Reuses the existing `jira-rel-review` Python scripts directly |
| **Database** | SQLite via SQLAlchemy | Local file; Postgres is a connection-string change |
| **Frontend** | React + TanStack Table v9 + `@dnd-kit` | Spreadsheet-like grid with drag-and-drop |
| **Identity** | Name/email checked against group lists | No passwords; enough to attribute a save |
| **Hosting** | Your machine | Jira PAT stays server-side |

---

## Data Model (as built)

```
Report
  kind (AR_GL | AR | GL), quarter, last_jira_sync_at, last_sync_status, last_sync_error

BacklogSnapshot            -- Jira-owned, rewritten every sync, no user input
  report_kind, quarter, sheet, region, domain
  key                      -- e.g. CISGL-2412 (unique per report + sheet)
  release, release_title, ndp, ndp_status, ndp_deploy_date, summary, issue_type,
  status, assignee, reporter, priority, biz_domain, req_qtr, labels,
  backlog_source, est_h, spent_h
  archived, missing_streak, last_seen_at

User
  email (unique), name, role (SE | TPM | DEV | ADMIN)

ReportSnapshot             -- one save by one person
  report_kind, quarter, role, author_email, author_name, label,
  based_on_id, created_at

SnapshotRow                -- user values inside that save
  snapshot_id, sheet, key, rank, developer, uat_eta, prod_eta, comments

AuditLog
  actor, role, snapshot_id, quarter, report_kind, sheet,
  backlog_key, field, old_value, new_value, changed_at

SyncJob
  quarter, report_kind, state (running | done | failed), message,
  started_at, finished_at
```

---

## API Endpoints

```
GET    /api/reports                            List reports for a quarter
GET    /api/quarters                           Quarters present in the database
GET    /api/reports/:kind/:quarter             Live view; add ?role= or ?snapshot_id=
GET    /api/reports/:kind/:quarter/tree        RELEASE -> NDP -> Backlog hierarchy
GET    /api/reports/:kind/:quarter/export      Download the view as .xlsx (?sheet=, ?status=)
POST   /api/reports/:kind/:quarter/refresh     Start a Jira sync (kind=ALL for all three)
GET    /api/sync/status?kind=GL                Job state, elapsed, and duration estimate

GET    /api/reports/:kind/:quarter/snapshots   Saves, optionally ?role=SE
POST   /api/reports/:kind/:quarter/snapshots   Save the current table as the author's role
GET    /api/snapshots/:id                      One snapshot's metadata
DELETE /api/snapshots/:id                      Remove a snapshot

GET    /api/users                              Group membership (open to everyone)
GET    /api/users/admin                        Is a passphrase set, and is this one right
POST   /api/users                              Add or move someone (needs X-Admin-Key)
DELETE /api/users/:id                          Remove from groups (needs X-Admin-Key)
POST   /api/users/identify                     Resolve a name or email to a role

GET    /api/audit?backlog_id=:id               Change history for one backlog
```

---

## Frontend Pages

| Page | Description |
|------|-------------|
| `/reports` | Report picker: AR_GL / AR / GL |
| `/reports/:kind/:quarter` | Main view: region tabs on top, then search, views, and update |
| `/reports/:kind/:quarter/tree` | Read-only RELEASE → NDP → Backlog tracker, filtered by NDP status |
| `/admin/users` | Group membership for System Engineer / TPM / Developer |

### Main view layout

```
NA_AR | NA_GL | NA_AR+GL | LAC_AR | LAC_GL | LAC_AR+GL      <- region tabs
[ search ] [ Edit ]           Live | SE View | TPM View | DEV View   [ Update from Jira ]
                              Snapshot: 08/06/2026 06:15 PM ...      Last updated: ...
[ All statuses (95) v ]                                        [ Export to Excel ]
```

The status dropdown narrows the table to one backlog status. Each entry carries its count
for the region sheet you are on, ordered by the number in the status name, so the row
count is part of the control rather than a separate label. The choice narrows the export
too, so a download matches what is on screen. Reordering is suspended while a single
status is selected, because ranking is decided across the whole sheet.

### Main table interactions

- Read-only until you click Edit and are matched to a group
- Drag the handle to reorder, or type a number straight into the Rank cell; repeated
  numbers are allowed, and ties fall back to release, NDP, then key order
- Changed cells are highlighted until saved
- Click a cell to edit Developer / UAT ETA / PROD ETA / Comments
- Click a backlog key for its change history
- Search box and status dropdown filter the current sheet; searching, sorting, or picking
  a single status suspends reordering
- **Export to Excel** downloads exactly what the current view holds: the visible region
  sheet, in its saved order, with the user columns from the selected snapshot, NDP status
  cells colored with the skill's palette, and an `about` tab recording the source

### Tree page

The tree is a status tracker only, so it has no role views and nothing is editable there.
It always shows live Jira data. Above the tree sit status tabs — All statuses, Open, N/A,
IT Leader Approved, IIC Approved, QC Approved, Verified, and whatever else Jira returns —
so you can look at one status at a time or all of them together. Counts follow the region
sheet you are on.
- NDP status color-coded with the skill's palette (QC Approved red, IIC yellow, and so on)

---

## Project Structure

```
backlog_manager/
  backend/
    app/
      main.py              FastAPI entry + CORS
      config.py            paths, report specs, default quarter
      db.py                SQLAlchemy engine/session
      models.py            Report, BacklogSnapshot, User, ReportSnapshot, SnapshotRow, AuditLog, SyncJob
      schemas.py           Pydantic response models
      routers/             reports.py, snapshots.py, users.py, audit.py
      services/
        jira_sync.py       calls the skill, stabilizes search, flattens to rows
        merge.py           writes Jira rows only; never touches snapshots
        excel_export.py    builds the .xlsx download
    .env                   ADMIN_KEY, never committed
    verify_parity.py       counts vs Excel + internal invariants
    test_snapshots.py      groups, identity, and snapshots surviving a refresh
    db_info.py             where the database is and what is in it
    requirements.txt
  scripts/
    setup.ps1              installs dependencies, builds the UI, creates backend/.env
    start.ps1              runs UI + API together on one port
  frontend/
    src/
      pages/               ReportsPage, ReportPage, TreePage, UsersPage
      components/          BacklogTable, EditableCell, IdentityPrompt, UpdateButton, AuditDrawer
      api.ts, types.ts, useSync.ts, ndp.ts, styles.css
    package.json
  .cursor/skills/jira-rel-review/   the skill (Cursor loads it, backend imports it)
  README.md
  .env.example
```

---

## Editing workflow (roles and snapshots)

The live table is always the untouched Jira pull. Edits never change it; they are saved
as **snapshots** owned by the editor's group, so SE, TPM, and DEV each keep their own
history of the same backlog.

```mermaid
flowchart LR
  Live["Live (Jira) view"] --> Edit["Click Edit"]
  Edit --> Who["Enter name or TD SYNNEX email"]
  Who --> Role["Edit as SE / TPM / DEV: name"]
  Role --> Change["Drag to rank, fill Developer / ETAs / Comments"]
  Change --> Save["Save as SE / TPM / DEV"]
  Save --> Views["SE View / TPM View / DEV View"]
  Views --> History["Pick any earlier snapshot by date and time"]
```

1. **Groups first.** Open **Users** in the top nav and add each person's TD SYNNEX email
   to System Engineer, TPM, or Developer. Nobody can edit until they are in a group.
   Everyone can read the group list, but adding and removing members requires clicking
   **Unlock admin** and entering the passphrase from `backend/.env` (see below). The
   passphrase is held in memory only, so closing the tab locks it again.
2. **Edit.** The Edit button sits under the search bar. It asks
   `Please enter your name or TD SYNNEX email address:`, matches the entry against the
   groups, and confirms with `Edit as SE: <name>` before unlocking the table. An
   unrecognized entry is refused with a message pointing at the Users page.
3. **Change.** While editing, the drag handle reorders rows and the Developer, UAT ETA,
   PROD ETA, and Comments cells accept input. Changed cells are highlighted and counted;
   nothing is written to the server yet.
4. **Save.** The button reads `Save as SE`, `Save as TPM`, or `Save as DEV` according to
   the editor's group. Saving writes one snapshot and one audit row per changed field.
5. **Review.** The view tabs sit to the right of the search bar: Live (Jira), SE View,
   TPM View, DEV View. Each role view has a snapshot picker listing every save by date,
   time, and author, so any earlier state can be traced back.

Jira columns always show current data even inside a role view; only the user columns and
the row order come from the snapshot. That means a snapshot cannot go stale on status.

Ranking is per sheet, so `NA_GL` is ordered independently from `LAC_GL`. The live view
keeps its own text columns empty but still shows the ranking from the most recent save of
any role, so priority order is never lost. Where nothing has been ranked yet, rows are
numbered by their position in Jira order rather than shown as zero.

## Resolved questions

| # | Question | Decision |
|---|----------|----------|
| 1 | Hosting | Runs as one process on a laptop today; the same build can be hosted internally later. |
| 2 | Auth | No login. Editors type a name or email checked against the group lists; group management is gated by one shared passphrase. |
| 3 | Who can click "Update" | Anyone. It only refreshes Jira data and cannot touch snapshots. |
| 4 | Ranking scope | Per sheet, inside a snapshot. |
| 5 | MVP users | Small team; add each member on the Users page. |
| 6 | Quarter handling | Switchable. Quarter is part of every route and API call; default `2026Q3`. |

---

## Running it

Prerequisites: **Python 3.11+** and **Node 20+**, plus a Jira personal access token.
On Windows, `py` and `npm` must work from PowerShell.

```powershell
git clone <this repo>
cd backlog_manager

# Installs Python packages, builds the UI, and creates backend\.env
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# Paste your Jira token into backend\.env  ->  JIRA_PAT=...

powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

`start.ps1` serves the UI and the API together on <http://127.0.0.1:8000/> and opens your
browser. Use `-Port 9000` for a different port, or `-Share` to let others on your network
reach it. Stop with Ctrl+C.

First run: the report tables are empty until you press **Update from Jira**. To edit
anything, add yourself on the **Users** page first, which needs the `ADMIN_KEY` that
`setup.ps1` generated into `backend\.env`.

Every install keeps its own database, so snapshots are not shared between machines until
the app is hosted somewhere central.

### Working on the code

Run the two processes separately to get hot reload. Vite proxies `/api` to the backend,
and the backend skips serving the built UI whenever it is started this way.

```powershell
cd backend; py -m uvicorn app.main:app --reload    # API on 8000
cd frontend; npm run dev                           # UI on 5173
```

**Update from Jira** runs as a background job. The button shows `Updating...` and, in the
same spot as the timestamp, an estimate such as `About 1m 20s left (est. 2m 15s)` derived
from how long recent syncs of the same scope actually took. Nothing else blocks while it
runs, and data is never re-pulled just because you opened or switched a report. Only the
button starts a sync.

### Where the data lives

Everything is in one SQLite file, `backend/backlog.db` by default: Jira rows, snapshots,
groups, the audit trail, and sync history. Any SQLite client opens it — in DBeaver, create
a SQLite connection and point Path at that file. Read it freely while the app runs, but
stop the app before writing to it.

Keep that file out of OneDrive, Dropbox, or any synced folder. Sync tools copy the file
while SQLite is writing to it, which causes locking errors and can corrupt the database.
If the repo itself lives in a synced folder, set an unsynced path instead:

```
# backend/.env
DATABASE_URL=sqlite:///C:/backlog_manager/backlog.db
```

`py db_info.py` from `backend` prints the current file, its size, and the row count of
every table.

### Verification scripts

```powershell
cd backend
py verify_parity.py 2026Q3    # per-sheet counts vs the skill's Excel + internal invariants
py test_snapshots.py          # groups, identity check, and snapshots surviving a Jira refresh
```

`verify_parity.py` also asserts invariants the Excel files cannot: `NA_AR+GL` must equal
`NA_AR` united with `NA_GL`, and each sheet must be identical across the reports
containing it.

---

## How the sync works

`backend/app/services/jira_sync.py` imports the skill's `build_report_workbook()`, which
returns the classified data in memory before any Excel is written, so the region,
exclusion, and dedupe rules are inherited rather than reimplemented. Two behaviors are
wrapped on top of it for the platform:

- **Stabilized search.** Jira intermittently drops trailing results under load. Two
  consecutive runs a minute apart returned 87 and 86 rows for the same query. Each search
  is repeated until two passes agree and results are unioned, so a short pass can only
  add rows, never remove them. Without this, a transient under-fetch would flag live
  backlogs as archived.
- **Response decoding.** Some Jira summaries contain Windows-1252 bytes (en-dash `0x96`)
  that are invalid UTF-8. The response charset is honored with a cp1252 fallback instead
  of substituting replacement characters.

Persistence keeps Jira data and user data in separate tables (`backlog_snapshots` vs
`report_snapshots` / `snapshot_rows`), so a sync physically cannot overwrite user input.
A key that Jira omits is only marked `archived`, and only after two consecutive syncs
omit it, because a single short response would otherwise flag live backlogs as stale.

---

## Success Criteria

- [x] All three reports (AR_GL, AR, GL) viewable in browser without Excel
- [x] "Update from Jira" refreshes status within one click
- [x] User fields (rank, developer, UAT ETA, PROD ETA, comments) survive a Jira refresh
- [x] Drag-and-drop ranking works per sheet
- [x] Tree view shows RELEASE → NDP → Backlog hierarchy
- [x] Region rules enforced (CISGL → NA, MCAM → LAC, KSPE excluded)
- [x] Editing requires group membership; the Save button names the editor's role
- [x] SE / TPM / DEV views with a full snapshot history by date and time
- [x] Audit log captures all user edits with role and snapshot
