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


def _window_titles() -> list[str]:
    """Titles of every top-level window on this desktop (Windows only)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            titles.append(buffer.value)
        return True

    user32.EnumWindows(collect, 0)
    return titles


def _locked(path: Path) -> bool:
    """Whether another program holds the file so it cannot be opened exclusively."""
    if os.name != "nt":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = ctypes.c_void_p
    generic_read, open_existing, sharing_violation, lock_violation = 0x80000000, 3, 32, 33
    handle = kernel32.CreateFileW(str(path), generic_read, 0, None, open_existing, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return kernel32.GetLastError() in (sharing_violation, lock_violation)
    kernel32.CloseHandle(ctypes.c_void_p(handle))
    return False


def in_use(path: Path, titles: list[str] | None = None) -> str | None:
    """Why the workbook is open somewhere on this PC, or None if it is free.

    Three signals, because each misses a case the others catch:
    - Excel's ~$ owner file, left beside a workbook opened from a plain folder.
      Opened from OneDrive or SharePoint, Excel leaves none.
    - A window titled with the workbook: desktop Excel, or Excel for the web in a
      browser tab. This is the case that silently undid updates — AutoSave writes
      the open copy back over anything saved underneath it.
    - The file refusing an exclusive open: Excel, or OneDrive mid-sync.
    """
    if any((path.parent / o).exists() for o in (f"~${path.name}", f"~${path.name[2:]}")):
        return "it is open in Excel on this PC"
    stem = path.stem.lower()
    for title in _window_titles() if titles is None else titles:
        lowered = title.lower()
        if lowered.startswith(stem) and "excel" in lowered:
            return f'it is open in Excel on this PC ("{title}")'
    if _locked(path):
        return "it is locked by another program, Excel or OneDrive mid-sync"
    return None


def _open_here(path: Path, titles: list[str] | None = None) -> bool:
    return in_use(path, titles) is not None


def info(path: Path, titles: list[str] | None = None) -> FileInfo:
    stat = path.stat()
    attrs = getattr(stat, "st_file_attributes", 0)
    return FileInfo(
        name=path.name,
        path=path,
        size=stat.st_size,
        modified=datetime.fromtimestamp(stat.st_mtime),
        token=_token(stat),
        kind=guess_kind(path.name),
        open_here=_open_here(path, titles),
        cloud_only=bool(attrs & RECALL_ON_DATA_ACCESS),
    )


def list_workbooks(quarter: str) -> list[FileInfo]:
    """Workbooks in the quarter's folder, newest first. Lock and temp files skipped."""
    where = folder(quarter)
    if where is None or not where.is_dir():
        return []
    titles = _window_titles()
    files = [
        info(p, titles)
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
    busy = in_use(path)
    if busy:
        raise SharePointError(
            f"{path.name} cannot be updated because {busy}. Close it everywhere first: "
            "while Excel has it open, AutoSave writes its copy back over this update a "
            "few minutes later and the changes disappear. Nothing was changed.",
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
