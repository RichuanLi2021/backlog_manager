import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = BACKEND_DIR.parent


def _load_env_file(path: Path):
    """Read KEY=VALUE lines without overriding variables already in the environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Backend-only settings. Jira credentials are loaded separately by the skill.
_load_env_file(BACKEND_DIR / ".env")

SKILL_DIR = Path(
    os.getenv("JIRA_REL_REVIEW_DIR", WORKSPACE_ROOT / ".cursor" / "skills" / "jira-rel-review")
)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'backlog.db'}")

# Built UI, served by this process so the whole app is one address.
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", WORKSPACE_ROOT / "frontend" / "dist"))

DEFAULT_QUARTER = os.getenv("DEFAULT_QUARTER", "2026Q3")

# Shared passphrase that unlocks group management. Everyone can read the group
# list; only someone holding this can add or remove members.
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()

REPORT_SPECS = {
    "AR_GL": ["TDS-AR", "TDS-GL", "TDS-AR+GL"],
    "AR": ["TDS-AR"],
    "GL": ["TDS-GL"],
}

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# How long an NDP may sit in one status before the Tree view raises it. Measured
# from the moment Jira's changelog says it entered that status.
NDP_AGE_WARN_DAYS = float(os.getenv("NDP_AGE_WARN_DAYS", "7"))  # over this: yellow
NDP_AGE_FLAG_DAYS = float(os.getenv("NDP_AGE_FLAG_DAYS", "14"))  # over this: red, flagged

# Finished plans: how long ago they finished is not a problem, so they are never aged.
NDP_DONE_STATUSES = {"Verified", "Deployed", "Closed", "Done", "Cancelled", "Rejected"}

# Not yet submitted for deployment. Their age is shown but never flagged, since an
# NDP normally waits in Open while its backlogs are still being built.
NDP_UNSUBMITTED_STATUSES = {"Open"}

# ---- SharePoint (GLreport site) ------------------------------------------------
# The library is reached through OneDrive sync rather than the Graph API: no app
# registration or tenant admin consent, and OneDrive carries every write back to
# SharePoint with version history. SHAREPOINT_DIR is the local folder standing for
# GL_BL; left empty, the usual sync locations are searched for it.
SHAREPOINT_DIR = os.getenv("SHAREPOINT_DIR", "").strip()
# Where a quarter's working files sit under that folder.
SHAREPOINT_SUBDIR = os.getenv("SHAREPOINT_SUBDIR", "{quarter}/Updated").strip()
# Shown in the UI so people can open the same folder in a browser.
SHAREPOINT_WEB_URL = os.getenv(
    "SHAREPOINT_WEB_URL",
    "https://tdworldwide.sharepoint.com/sites/GLreport/Shared%20Documents/Forms/AllItems.aspx"
    "?id=%2Fsites%2FGLreport%2FShared%20Documents%2FGL%5FBL%2F{quarter}%2FUpdated",
).strip()
# The original of every file the platform rewrites is kept here first. SharePoint
# version history is the real safety net; this is the one that needs no browser.
SHAREPOINT_BACKUP_DIR = Path(
    os.getenv("SHAREPOINT_BACKUP_DIR", BACKEND_DIR / "backups" / "sharepoint")
)
