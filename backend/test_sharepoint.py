"""Checks for SharePoint file access, against a stand-in for the synced folder.

No server and no real SharePoint: a temp folder plays the part of the OneDrive-
synced GL_BL folder. What matters here is the write path, because it replaces a
file the whole team shares — it must refuse a stale preview, refuse a file open in
Excel, keep the original, and never leave half a workbook for OneDrive to upload.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="gl_bl_"))
# Point the module at the stand-in folder before it reads its configuration.
os.environ["SHAREPOINT_DIR"] = str(ROOT)
os.environ["SHAREPOINT_BACKUP_DIR"] = str(ROOT / "_backups")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services import sharepoint  # noqa: E402
from app.services.sharepoint import SharePointError  # noqa: E402

failures: list[str] = []
QUARTER = "2026Q4"
FOLDER = ROOT / QUARTER / "Updated"


def check(condition, message):
    if not condition:
        failures.append(message)


def refused(call, status, contains):
    try:
        call()
    except SharePointError as exc:
        check(exc.status == status, f"expected {status}, got {exc.status}: {exc}")
        check(contains in str(exc), f"message should mention {contains!r}: {exc}")
        return
    failures.append(f"expected a refusal mentioning {contains!r}, but it went through")


def setup():
    FOLDER.mkdir(parents=True)
    (FOLDER / "GL_Summary_2026Q4.xlsx").write_bytes(b"gl-original")
    time.sleep(0.02)
    (FOLDER / "AR_GL_Summary_2026Q4.xlsx").write_bytes(b"argl")
    (FOLDER / "AR_Summary_2026Q4.xlsm").write_bytes(b"ar")
    (FOLDER / "~$AR_Summary_2026Q4.xlsm").write_bytes(b"owner")  # Excel's lock file
    (FOLDER / ".~bm-leftover.tmp").write_bytes(b"x")
    (FOLDER / "notes.docx").write_bytes(b"not a workbook")


def test_finding_and_listing():
    check(sharepoint.folder(QUARTER) == FOLDER, f"wrong folder: {sharepoint.folder(QUARTER)}")
    files = {f.name: f for f in sharepoint.list_workbooks(QUARTER)}
    check(set(files) == {"GL_Summary_2026Q4.xlsx", "AR_GL_Summary_2026Q4.xlsx",
                         "AR_Summary_2026Q4.xlsm"},
          f"listing should hold only the three workbooks: {sorted(files)}")
    check(files["AR_GL_Summary_2026Q4.xlsx"].kind == "AR_GL",
          "an AR_GL file must not be read as AR just because it starts with AR_")
    check(files["AR_Summary_2026Q4.xlsm"].kind == "AR", "AR file kind wrong")
    check(files["GL_Summary_2026Q4.xlsx"].kind == "GL", "GL file kind wrong")
    check(files["AR_Summary_2026Q4.xlsm"].open_here, "Excel's ~$ owner file not noticed")
    check(not files["GL_Summary_2026Q4.xlsx"].open_here, "a closed file reported open")
    check(sharepoint.list_workbooks("2099Q1") == [], "a missing quarter should list nothing")
    print(f"listing: {sorted(files)}; lock and temp files skipped, kinds right")


def test_names_cannot_leave_the_folder():
    (ROOT / "secret.xlsx").write_bytes(b"outside")
    refused(lambda: sharepoint.locate(QUARTER, "../../secret.xlsx"), 400, "is not a workbook")
    refused(lambda: sharepoint.locate(QUARTER, "notes.docx"), 400, "is not a workbook")
    refused(lambda: sharepoint.locate(QUARTER, "gone.xlsx"), 404, "no longer in")
    print("names: ../ traversal, non-workbooks and missing files refused")


def test_write_guards():
    path = sharepoint.locate(QUARTER, "GL_Summary_2026Q4.xlsx")
    token = sharepoint.info(path).token

    # Someone saves the file between the preview and the update.
    time.sleep(0.02)
    path.write_bytes(b"gl-edited-by-a-colleague")
    refused(lambda: sharepoint.replace(path, b"ours", token), 409, "changed after you previewed")
    check(path.read_bytes() == b"gl-edited-by-a-colleague", "a stale write overwrote the file")

    # The file is open in Excel on this PC.
    token = sharepoint.info(path).token
    owner = FOLDER / "~$GL_Summary_2026Q4.xlsx"
    owner.write_bytes(b"owner")
    refused(lambda: sharepoint.replace(path, b"ours", token), 409, "open in Excel")
    owner.unlink()

    backup = sharepoint.replace(path, b"refreshed", token)
    check(path.read_bytes() == b"refreshed", "the new bytes did not land")
    check(backup.read_bytes() == b"gl-edited-by-a-colleague",
          "the backup must hold the file as it was just before the update")
    leftovers = [p.name for p in FOLDER.iterdir() if p.name.startswith(".~bm-") and p.name != ".~bm-leftover.tmp"]
    check(not leftovers, f"staging files left in the shared folder: {leftovers}")
    print(f"writes: stale preview refused, open file refused, backup kept at {backup.name}")


def test_open_in_excel_without_an_owner_file():
    """Opened from OneDrive, Excel leaves no ~$ file; this is what undid real updates."""
    path = sharepoint.locate(QUARTER, "GL_Summary_2026Q4.xlsx")
    check(sharepoint.in_use(path, titles=["GL_Summary_2026Q4.xlsx - Excel"]) is not None,
          "a desktop Excel window on the workbook was not noticed")
    check(sharepoint.in_use(path, titles=["GL_Summary_2026Q4 - Excel"]) is not None,
          "an Excel window without the extension shown was not noticed")
    check(sharepoint.in_use(path, titles=["GL_Summary_2026Q4.xlsx - Excel Online - Edge"]) is not None,
          "Excel for the web in a browser tab was not noticed")
    check(sharepoint.in_use(path, titles=["GL_Summary_2026Q3.xlsx - Excel", "Inbox - Outlook"]) is None,
          "another workbook's window was mistaken for this one")

    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        # Hold the file the way Excel does: no sharing at all.
        handle = k32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
        try:
            token = sharepoint.info(path).token
            refused(lambda: sharepoint.replace(path, b"ours", token), 409, "locked by another")
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
        check(sharepoint.in_use(path, titles=[]) is None, "a released file still reads as locked")
    print("open in Excel: window titles and exclusive locks both refuse the update")


def main():
    setup()
    for test in (test_finding_and_listing, test_names_cannot_leave_the_folder, test_write_guards,
                 test_open_in_excel_without_an_owner_file):
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__} raised {type(exc).__name__}: {exc}")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: the shared folder is listed safely and only written when it is safe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
