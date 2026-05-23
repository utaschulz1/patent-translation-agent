"""
archive_preprocessing.py — Move project working files to the XTRF pre-processing folder.

Usage:
    python archive_preprocessing.py                  # uses active project from current_project.json
    python archive_preprocessing.py HUAW_2604_P0819  # uses the given project ID
"""

import shutil
import sys
from pathlib import Path

import project_log
from config import PROJECTS_DIR, WORK_DIR


def _find_xtrf_folder(project_id: str) -> Path:
    """Return the XTRF job folder for a project by scanning WORK_DIR for a subfolder ending in _{project_id}."""
    matches = [p for p in WORK_DIR.iterdir() if p.is_dir() and p.name.endswith(f"_{project_id}")]
    if not matches:
        raise RuntimeError(f"No XTRF folder found for {project_id!r} in {WORK_DIR}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple XTRF folders for {project_id!r}: {[p.name for p in matches]}")
    return matches[0]


def main() -> None:
    """Move all files from the project working folder to the XTRF pre-processing subfolder.

    Resolves paths either from a project ID passed as a CLI argument or from the
    active project recorded in current_project.json.
    """
    if len(sys.argv) > 1:
        project_id = sys.argv[1]
        project_folder = PROJECTS_DIR / project_id
        if not project_folder.exists():
            raise RuntimeError(f"Project folder not found: {project_folder}")
        xtrf_folder = _find_xtrf_folder(project_id)
    else:
        ctx = project_log.load_context()
        project_id = ctx["project_id"]
        project_folder = Path(ctx["project_folder"])
        xtrf_folder = Path(ctx["xtrf_job_folder"])

    pre_folder = xtrf_folder / "pre-processing"
    pre_folder.mkdir(exist_ok=True)

    files = [
        f for f in project_folder.iterdir()
        if f.is_file() and not f.name.startswith("~$")
    ]

    if not files:
        print(f"No files to move in {project_folder}")
        return

    print(f"Project:  {project_id}")
    print(f"From:     {project_folder}")
    print(f"To:       {pre_folder}")
    print()

    locked: list[str] = []
    for f in sorted(files):
        dest = pre_folder / f.name
        try:
            shutil.move(str(f), str(dest))
            print(f"  {f.name}")
        except PermissionError:
            print(f"  {f.name}  <-- SKIPPED: close this file first, then re-run")
            locked.append(f.name)

    if locked:
        print(f"\nSkipped {len(locked)} locked file(s) — close them in Excel and re-run.")
        moved = len(files) - len(locked)
        if moved:
            print(f"Moved {moved} file(s).")
        return

    print(f"\nMoved {len(files)} file(s).")

    try:
        project_folder.rmdir()
        print(f"Deleted:  {project_folder}")
    except PermissionError:
        print(f"Warning:  Could not delete {project_folder} (OneDrive sync lock — delete manually)")


if __name__ == "__main__":
    main()
