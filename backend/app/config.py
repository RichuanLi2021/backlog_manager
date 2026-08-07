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
