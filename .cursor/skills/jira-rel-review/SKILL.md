---
name: jira-rel-review
description: Review one or more Jira release tickets, summarize release number, title, total estimate hours, total spent hours, and deploy plan list ordered by ID. Use when the user provides REL keys such as REL-18133, separated by commas, spaces, or lines.
---

# Jira Release Review

Use this skill to review Jira release tickets from a release list.

## Workflow

### Step 1: Require MCP `gateway-atlassian-prod`

- **Data source**: Jira REST API credentials must come from MCP server **`gateway-atlassian-prod`** in `.cursor/mcp.json`.
- Required MCP headers:
  - `X-Atlassian-Jira-Url`
  - `X-Atlassian-Jira-Personal-Token`
- If the MCP server is missing or incomplete, **stop** and tell the user:
  - `Please setup MCP server gateway-atlassian-prod`
- Batch run command:
  - `py jira-rel-review/review_releases.py REL-18133`
- The script reads the same `gateway-atlassian-prod` block from `.cursor/mcp.json` (workspace root or user home).

### Step 2: Normalize release list input

- Accept release keys separated by comma / space / new line.
- Normalize into unique Jira keys, for example:
  - `REL-18133`
  - `REL-19875`

### Step 3: Pull release summary

- Run:
  - `py jira-rel-review/review_releases.py REL-18133,REL-19875`
- If REL count is `<= 9`, script prints release list + deploy plan details to console.
- If REL count is `> 9`, script does **not** print list details and instead prints:
  - `REL count > 9. Skip console list output.`
  - `Please review generated file: <xlsx_path>`

### Step 4: Release and deploy-plan data rules

- Release backlog query logic:
  - `"Snx Release" = "REL-xxxxx"`
- Hours aggregation (Backlog issue type only):
  - `estimate_hours` from `Original Estimate`
  - `spent_hours` from `Time Spent`
  - `remaining_hours = max(estimate_hours - spent_hours, 0)`
- Deploy plan list source:
  - Backlog field `Deploy Plan`
  - Keep unique values and sort by numeric issue part ascending
- Deploy plan fields:
  - `status`
  - `A.D.D - deploy date` from `Actual Deploy Date`

### Step 4b: Bold rules

**Time window rule:** the **7-day window applies to `Verified` only**. `QC Approved`, `IIC Approved`, and `IT Exec Approved` are always bold and always drive background color while they are the NDP's **current** status.

#### Deploy plan table bold (console / markdown)

Wrap the full NDP row as markdown bold when either is true:

1. Current NDP status is `QC Approved`, `IIC Approved`, or `IT Exec Approved`
2. A.D.D is within ±7 calendar days of run date

#### `release_list.ndps-status` cell partial bold (Excel)

- `ndps-status` token format:
  - `NDP-####(Status, MM/DD/YYYY)`
  - tokens joined by `; `
- Bold **only that token** (partial bold inside the cell) when either is true:
  - current status is `QC Approved`, `IIC Approved`, or `IT Exec Approved`
  - status changed to `Verified` within the last 7 days (changelog)
  - A.D.D is within ±7 calendar days of run date

### Step 4c: Cell background color rules (Excel)

#### `release_list.ndps-status`

Aggregate by REL row. Pick **one** cell background using priority below (first match wins across all NDPs on that release):

| Priority | Status | Background | Time rule |
| --- | --- | --- | --- |
| 1 | `QC Approved` | red (`F8CBAD`) | current status |
| 2 | `IIC Approved` | yellow (`FFF2CC`) | current status |
| 3 | `IT Exec Approved` | orange (`FFE699`) | current status |
| 4 | `Verified` | green (`C6EFCE`) | changed to Verified in last 7 days only |

**Priority:** `QC Approved > IIC Approved > IT Exec Approved > Verified`

Example: a release with both `IIC Approved` and `IT Exec Approved` NDPs gets **yellow** (IIC wins).

Implementation reference: `review_releases.py` → `NDP_ALWAYS_HIGHLIGHT_STATUSES`, `NDP_BG_FILL_PRIORITY`, `get_recent_verified_change()`.

#### `release_list.planned_uat`

- If release `status == 40-Active` and `planned_uat` is already past run date, fill `planned_uat` cell **yellow** (`FFF2CC`).

### Step 5: Optional txt table output

- Command:
  - `py jira-rel-review/review_releases.py REL-18133,REL-19875 --table --output-file jira-rel-review/output.txt`
- Output file must be aligned `.txt` table.

### Step 6: Auto Excel output

- Auto-generated file:
  - `jira-rel-review/Skill_jira-rel-review_rel_<REL-or-multi>_as_YYYYMMDD_hhmmss.xlsx`

#### Sheet: `release_list`

Columns:
1. `release`
2. `title`
3. `status`
4. `planned_uat`
5. `IIC` (from Jira `(Snx) IIC`)
6. `SE` (from Jira `(Snx) SE`)
7. `Job Manager` (from Jira `(Snx) Job Manager`)
8. `estimate_hours`
9. `spent_hours`
10. `remaining_hours`
11. `ndps`
12. `ndps-status`

#### Sheet: `ndp_details`

Columns:
1. `release`
2. `release_title`
3. `ndp_key`
4. `ndp_summary`
5. `status`
6. `ndp_submitted_by`
7. `ndp_submit_date`
8. `Planned UAT Date`
9. `actual_deploy_date`
10. `ndp_key(status, actual_deploy_date)`

`ndp_submitted_by` / `ndp_submit_date` come from changelog status transition to `Submitted` (latest Submitted event).

## Date format standard

Use `MM/DD/YYYY` for all date outputs in Excel and display strings:
- `planned_uat`
- `actual_deploy_date`
- `ndp_submit_date`
- token date in `ndps-status`
- token date in `ndp_key(status, actual_deploy_date)`

## Output format (console when REL <= 9)

```markdown
## Release list
| Release | Title | Status | Planned UAT | IIC | SE | Job Manager | Est h | Spent h | Remaining h | NDPs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REL-12345 | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

---

## REL Deploy plan list
Release #: REL-12345
| NDP# | Status | A.D.D date |
| --- | --- | --- |
| **NDP-4940** | **QC Approved** | **N/A** |
| NDP-5596 | Verified | 05/19/2026 |
| **NDP-5401** | **IT Exec Approved** | **N/A** |
| **NDP-4310** | **Verified** | **07/06/2026** |
| NDP-1933 | Closed | N/A |
```

Console bold examples:
- `NDP-4940` — current `QC Approved`
- `NDP-5401` — current `IT Exec Approved`
- `NDP-4310` — `Verified` with A.D.D within ±7 days of run date

## Latest quarter reports (AR / GL / AR_GL)

When the user asks for the **latest report**, always run:

```powershell
py jira-rel-review/update_latest_reports.py --quarter 2026Q3
```

This produces **three fixed workbooks** under `jira-rel-review/Report/` — update in place on every run (never create a new timestamped folder):

| Folder | File | Scope |
| --- | --- | --- |
| `Report/AR_GL/` | `AR_GL_Summary_<quarter>.xlsx` | Comprehensive: NA + LAC, TDS-AR + TDS-GL + TDS-AR+GL |
| `Report/AR/` | `AR_Summary_<quarter>.xlsx` | AR only: NA_AR, LAC_AR |
| `Report/GL/` | `GL_Summary_<quarter>.xlsx` | GL only: NA_GL, LAC_GL |

### Update rules (always follow)

1. **Fixed folders** — `Report/AR_GL`, `Report/AR`, `Report/GL`. One workbook per folder per quarter.
2. **Update in place** — if the workbook already exists, refresh Jira data into it. Do **not** create a new timestamped copy.
3. **Summary timestamp** — every update writes `Last Updated: MM/DD/YYYY HH:MM:SS AM/PM` at the top of the `summary` sheet.
4. **Extra columns** on every mapping sheet (after Jira columns):
   - `Developer` — immediately to the right of `Assignee`; left **empty** on first create; preserved on update.
   - `UAT ETA` — user-editable; preserved on update.
   - `PROD ETA` — user-editable; preserved on update.
   - `Comments` — user-editable; preserved on update.
5. **Jira-sourced columns** (refreshed every run): `Status`, `NDP`, `NDP Status`, `NDP Deploy Date`, `Est h`, `Spent h`, assignee, etc.
6. **Tree sheets** — every mapping sheet gets a paired `<sheet>_tree` tab (RELEASE → NDP → Backlog collapsible outline).
7. **Region classification** — fetch from both NA and LAC JQL, merge, then route each backlog to the correct sheet:
   - **NA**: keys starting with `CISGL`, `CISAR`, or `CIS` (CISGL/CISAR always NA even if LAC-labelled).
   - **LAC**: keys starting with `MCAM`, `WMCC`, or label token `LAC`.
   - Never duplicate a backlog across NA and LAC sheets.
8. **Exclusions** — drop backlogs whose key starts with `KSPE` or whose labels contain `gl-killsp`.
9. **No priority tab** unless the user explicitly asks for one.

### Mapping sheet column order

`Release`, `Release Title`, `NDP`, `NDP Status`, `NDP Deploy Date`, `Backlog Key`, `Summary`, `Issue Type`, `Status`, `Assignee`, `Developer`, `Reporter`, `Priority`, `Biz Domain`, `Req Qtr`, `Labels`, `Backlog Source`, `Est h`, `Spent h`, `UAT ETA`, `PROD ETA`, `Comments`

---

## Region x Domain x Quarter export (recommended for NA / LAC reviews)

Organizes RELEASE -> NDP -> Backlog for the two regions and biz-domain combinations,
filtered by quarter, into one multi-sheet workbook.

- Script: `jira-rel-review/export_regions.py`
- Config: `jira-rel-review/regions.config.json` (field ids/values, editable without code changes)
- Uses the same workspace-root `.env` (`JIRA_URL` + `JIRA_PAT`) and `openpyxl`.

Region scope = a **`base_jql` per region** in `regions.config.json`, taken from each dashboard's
authoritative JQL (via the dashboard's "N filtered issues" -> Issue Navigator). The domain clause
is removed (so the tool can split TDS-AR / TDS-GL) and the quarter value is replaced with a
`{quarter}` placeholder. The tool then ANDs `"(SNX) Biz Domain" in (...)` onto base_jql.

Important: the two dashboards define scope AND quarter differently (this is why a single
field rule can't reproduce them):
- NA (`CIS ALL`, `selectPageId=25900`): `issuetype in (Backlog) and not (status = "100-Done" and
  timespent = 0) and "Request Qtr" ~ {quarter}`. Quarter uses the `~` (contains) operator on
  `Request Qtr` (`customfield_16308`). Not region-scoped.
- LAC (`LAC (MCA) CIS Conversion`, `selectPageId=25816`): project/region scoped
  (`project = MCAM or "Request Region" = LAC and project not in (WBRCC)`), a specific status set,
  and quarter via **`labels = {quarter}`** (NOT Request Qtr).
- Biz Domain = `(SNX) Biz Domain` (`customfield_14900`): `TDS-AR`, `TDS-GL`.
- Release link on backlog = `Snx Release` (`customfield_18613`); Deploy Plan = `customfield_18302`.

Validated 2026Q3 parity: NA -> TDS-AR 48 / TDS-GL 96 / AR+GL 144; LAC -> 3 / 19 / 22.
(The AR+GL sheet is de-duplicated unique issues. Jira's search `total` can transiently
under-report under load; re-run if a combo count looks a few short.)

To adapt to a new quarter just pass `--quarter`; to change scope edit the `base_jql` in the config.

Commands:

```powershell
# Both regions (NA, LAC) x domains (TDS-AR, TDS-GL, TDS-AR+GL) for the quarter
py jira-rel-review/export_regions.py --quarter 2026Q3

# Only NA; only the combined AR+GL view; include all issue types; add tree sheets
py jira-rel-review/export_regions.py --regions NA
py jira-rel-review/export_regions.py --domains "TDS-AR+GL"
py jira-rel-review/export_regions.py --include-issuetype "" --tree
```

Output location (legacy / ad-hoc): pass `--output-file` to override. For routine "latest report" requests, use `update_latest_reports.py` and the fixed `Report/AR_GL`, `Report/AR`, `Report/GL` folders above instead of timestamped folders.

Output workbook:
- Sheet `summary`: one row per Region x Domain combo with #Releases / #NDPs / #Backlogs + the JQL used.
- One sheet per combo (`NA_AR`, `NA_GL`, `NA_AR+GL`, `LAC_AR`, `LAC_GL`, `LAC_AR+GL`) with the
  flat RELEASE -> NDP -> Backlog mapping (adds `Biz Domain` + `Req Qtr` columns).
- With `--tree`, an extra collapsible tree sheet per combo.
- Backlogs with no release/NDP fall under `(no Release)` / `(no NDP)`.

## RELEASE -> NDP -> Backlog hierarchy (single release set / ad-hoc JQL)

Builds the full three-level mapping (each Release contains one or many NDPs; each NDP
contains one or many Backlogs). The linking data lives on each backlog: its "Snx Release"
(-> REL) and its "Deploy Plan" (-> NDP).

- Script: `jira-rel-review/export_hierarchy.py`
- Requires `openpyxl` (`py -m pip install openpyxl`).
- Uses the same workspace-root `.env` (`JIRA_URL` + `JIRA_PAT`).
- Custom fields (`Snx Release`, `Deploy Plan`, `Backlog Source`) resolved by display name.

Commands:

```powershell
# Release-rooted (uses the proven "Snx Release" = REL query)
py jira-rel-review/export_hierarchy.py REL-21631 REL-20814

# Backlog JQL / saved filter (releases + NDPs auto-discovered from the backlogs)
py jira-rel-review/export_hierarchy.py --jql "\"(Snx) Biz Domain\" = \"TDS-GL\""
py jira-rel-review/export_hierarchy.py --filter 12345

# Include all issue types (not just Backlog); custom output path
py jira-rel-review/export_hierarchy.py REL-21631 --include-issuetype "" --output-file jira-rel-review/hierarchy.xlsx
```

Output (`Skill_jira-rel-review_hierarchy_<tag>_as_YYYYMMDD_hhmmss.xlsx`):
- Sheet `tree`: collapsible outline, RELEASE (level 0) > NDP (level 1) > Backlog (level 2).
- Sheet `mapping`: flat, one row per backlog with `Release, Release Title, NDP, NDP Status,
  NDP Deploy Date, Backlog Key, Summary, Issue Type, Status, Assignee, Reporter, Priority,
  Backlog Source, Est h, Spent h` (auto-filter + frozen header).
- Backlogs with no Deploy Plan are grouped under `(no NDP)`.
- Also prints the tree to the console.

## Backlog -> NDP export (flat, backlog-centric mode)

Use this mode to replace the manual "board filter -> export Excel" workflow. It lists
every backlog from a JQL / saved board filter and associates each with its Deploy Plan (NDP).

- Script: `jira-rel-review/export_backlogs.py`
- Requires `openpyxl` (`py -m pip install openpyxl`).
- Uses the same workspace-root `.env` (`JIRA_URL` + `JIRA_PAT`).
- Custom fields (`Backlog Source`, `Deploy Plan`) are resolved by display name at runtime.

Commands:

```powershell
# By saved board/filter id
py jira-rel-review/export_backlogs.py --filter 12345

# By raw JQL
py jira-rel-review/export_backlogs.py --jql "\"(Snx) Biz Domain\" = \"TDS-GL\""

# Custom output + include all issue types (not just Backlog)
py jira-rel-review/export_backlogs.py --filter 12345 --include-issuetype "" --output-file jira-rel-review/backlogs.xlsx
```

Behavior:
- Default restricts to `issuetype = Backlog` (override with `--include-issuetype`).
- Paginates all results (100 per page).
- Fetches each NDP once for status + Actual Deploy Date (skip with `--no-ndp-details`).
- Output sheet `backlogs` columns: `Issue Type`, `Issue Key`, `Summary`, `Status`,
  `Assignee`, `Reporter`, `Priority`, `Backlog Source`, `NDP`, `NDP Status`, `NDP Deploy Date`.
- Rows sorted by NDP then issue key; header styled; auto-filter + frozen header.
- Auto output name: `jira-rel-review/Skill_jira-rel-review_backlogs_as_YYYYMMDD_hhmmss.xlsx`.

## Checklist before submitting

- [ ] MCP server `gateway-atlassian-prod` exists and is readable from `.cursor/mcp.json`.
- [ ] `release_list` has columns through `ndps-status` including `IIC/SE/Job Manager` and `remaining_hours`.
- [ ] `remaining_hours` is floored at `0`.
- [ ] `ndps-status` uses token format `NDP-####(Status, MM/DD/YYYY)`.
- [ ] `QC Approved` / `IIC Approved` / `IT Exec Approved` tokens are bold whenever current status matches (no 7-day limit).
- [ ] `Verified` token bold and green cell background only when status changed to Verified in last 7 days (or A.D.D ±7 days for token bold).
- [ ] `ndps-status` cell background follows priority `QC Approved > IIC Approved > IT Exec Approved > Verified`.
- [ ] `ndps-status` token bold is partial (only matched NDP token in the cell, via Excel rich text).
- [ ] `ndp_details` includes `ndp_submitted_by`, `ndp_submit_date`, `Planned UAT Date`.
- [ ] Latest-report run uses `update_latest_reports.py` and updates `Report/AR_GL`, `Report/AR`, `Report/GL` in place.
- [ ] `summary` sheet shows `Last Updated` timestamp after every refresh.
- [ ] Mapping sheets include `Developer` (right of Assignee), `UAT ETA`, `PROD ETA`, `Comments`; manual columns preserved on update.
