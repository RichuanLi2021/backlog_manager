"""The GLreport SharePoint library, reached through its OneDrive-synced folder.

Reading and writing happen on local files; OneDrive carries every write back to
SharePoint, where version history keeps the previous copy. Nothing here talks to
SharePoint directly, so a Graph API backend could replace this module without the
callers noticing.

A write replaces a shared team file, so it is guarded three ways: the file must
be unchanged since the preview the person approved, the original is backed up
first, and the new bytes land with an atomic rename so OneDrive never picks up a
half-written workbook.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import SHAREPOINT_BACKUP_DIR, SHAREPOINT_DIR, SHAREPOINT_SUBDIR

# Windows attribute OneDrive sets on a cloud-only placeholder (Files On-Demand).
RECALL_ON_DATA_ACCESS = 0x400000
WORKBOOK_SUFFIXES = {".xlsx", ".xlsm"}


class SharePointError(RuntimeError):
    """Something the person can act on, with the HTTP status that fits it."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class FileInfo:
    name: str
    path: Path
    size: int
    modified: datetime
    token: str  # changes whenever the file does; used to refuse stale writes
    kind: str | None  # report the name suggests: AR_GL, AR or GL
    open_here: bool  # Excel on this PC holds it open
    cloud_only: bool  # a placeholder OneDrive downloads on first read


def candidates() -> list[Path]:
    """Where the GL_BL folder can appear once synced, most likely first."""
    if SHAREPOINT_DIR:
        return [Path(SHAREPOINT_DIR)]
    home = Path.home()
    found: list[Path] = []
    for od in sorted(home.glob("OneDrive*")):
        # "Add shortcut to My files": newer OneDrive files it under Shortcuts as
        # "<site> - <folder>", e.g. "GL report - GL_BL"; older builds at the root.
        found += sorted(p for p in (od / "Shortcuts").glob("*GL_BL") if p.is_dir())
        found.append(od / "GL_BL")
    # "Sync" on the library puts it under a folder named after the organisation.
    found += [lib / "GL_BL" for lib in sorted(home.glob("*/GLreport*"))]
    return found


def root() -> Path | None:
    return next((p for p in candidates() if p.is_dir()), None)


def folder(quarter: str) -> Path | None:
    base = root()
    return base / SHAREPOINT_SUBDIR.format(quarter=quarter) if base else None


def guess_kind(name: str) -> str | None:
    upper = name.upper()
    # AR_GL first: an AR_GL workbook name also starts with "AR_".
    for kind in ("AR_GL", "AR", "GL"):
        if upper.startswith(f"{kind}_"):
            return kind
    return None


def _token(stat: os.stat_result) -> str:
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def _open_here(path: Path) -> bool:
    """Excel's owner file sits beside a workbook it has open on this machine.

    Excel prefixes the whole name with ~$; Word-style truncation replaces the first
    two characters instead. Both are checked. Someone editing in a browser leaves
    no trace here, which is what the token check is for.
    """
    return any(
        (path.parent / owner).exists() for owner in (f"~${path.name}", f"~${path.name[2:]}")
    )


def info(path: Path) -> FileInfo:
    stat = path.stat()
    attrs = getattr(stat, "st_file_attributes", 0)
    return FileInfo(
        name=path.name,
        path=path,
        size=stat.st_size,
        modified=datetime.fromtimestamp(stat.st_mtime),
        token=_token(stat),
        kind=guess_kind(path.name),
        open_here=_open_here(path),
        cloud_only=bool(attrs & RECALL_ON_DATA_ACCESS),
    )


def list_workbooks(quarter: str) -> list[FileInfo]:
    """Workbooks in the quarter's folder, newest first. Lock and temp files skipped."""
    where = folder(quarter)
    if where is None or not where.is_dir():
        return []
    files = [
        info(p)
        for p in where.iterdir()
        if p.is_file()
        and p.suffix.lower() in WORKBOOK_SUFFIXES
        and not p.name.startswith(("~$", ".~"))
    ]
    return sorted(files, key=lambda f: f.modified, reverse=True)


def locate(quarter: str, name: str) -> Path:
    """Resolve a file name inside the quarter's folder, and only inside it."""
    where = folder(quarter)
    if where is None or not where.is_dir():
        raise SharePointError(f"The {quarter} folder is not available on this PC.", 404)
    path = (where / name).resolve()
    # A name like "..\..\x.xlsx" must not reach outside the shared folder.
    if path.parent != where.resolve() or path.suffix.lower() not in WORKBOOK_SUFFIXES:
        raise SharePointError(f"'{name}' is not a workbook in the {quarter} folder.", 400)
    if not path.is_file():
        raise SharePointError(f"'{name}' is no longer in the {quarter} folder.", 404)
    return path


def read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except PermissionError as exc:
        raise SharePointError(
            f"{path.name} could not be read. If OneDrive is still downloading it, "
            "wait a moment and try again.",
            409,
        ) from exc


def replace(path: Path, data: bytes, expected_token: str) -> Path:
    """Put new bytes in place of a shared file, returning where the original went."""
    current = info(path)
    if current.token != expected_token:
        raise SharePointError(
            f"{path.name} changed after you previewed it (saved "
            f"{current.modified:%Y-%m-%d %H:%M}). Scan it again so you approve what is "
            "really there now.",
            409,
        )
    if current.open_here:
        raise SharePointError(
            f"{path.name} is open in Excel on this PC. Close it there first, so your "
            "unsaved changes and this update cannot overwrite each other.",
            409,
        )

    SHAREPOINT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = SHAREPOINT_BACKUP_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
    backup.write_bytes(read(path))

    # Written beside the target and renamed over it: OneDrive only ever sees the old
    # file or the complete new one. The ".~" prefix keeps it out of listings.
    staging = path.parent / f".~bm-{uuid.uuid4().hex}.tmp"
    try:
        staging.write_bytes(data)
        os.replace(staging, path)
    except PermissionError as exc:
        raise SharePointError(
            f"{path.name} is locked, probably open in Excel or mid-sync in OneDrive. "
            "Close it, wait for OneDrive to settle, and try again. Nothing was changed.",
            409,
        ) from exc
    finally:
        staging.unlink(missing_ok=True)
    return backup
