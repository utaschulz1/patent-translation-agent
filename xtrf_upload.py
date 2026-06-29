"""
xtrf_upload.py  —  XTRF workflow final step

Uploads 4 deliverable files for a completed patent translation job:
  - *_German (Claims/Description/...).docx
  - *_German (Claims/Description/...).pdf
  - project_QA_Report_<project_id>.xlsx
  - Appendix A*<project_id>*.xlsx

Usage:
    python xtrf_upload.py <project_id>

    Example:
        python xtrf_upload.py PLPA_2605_P0021
"""

import argparse
import mimetypes
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import WORK_DIR

BASE_URL = "https://comunicadk.s.xtrf.eu/vendors"
_ENV = Path(__file__).parent / ".env"

_GERMAN_FILE_RE = re.compile(r"_German\b", re.IGNORECASE)


def _load_creds() -> dict:
    load_dotenv(_ENV)
    return {
        "email": os.environ["COMUNICA_JOBLIST_USERNAME"],
        "password": os.environ["COMUNICA_JOBLIST_PASSWORD"],
    }


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    })
    return s


def _login(session: requests.Session, creds: dict) -> None:
    r = session.post(f"{BASE_URL}/sign-in", json=creds)
    r.raise_for_status()


def _find_job_id(session: requests.Session, project_id: str) -> int:
    """Return the XTRF job id for the given project_id (searches IN_PROGRESS jobs).

    A project can have more than one matching job at once, e.g. the main
    translation job plus a separate, not-yet-accepted "Issues resolution"
    job scheduled for later. PENDING jobs are not ready to receive target
    files, so IN_PROGRESS jobs are preferred when both are present.
    """
    statuses = "IN_PROGRESS,IN_PROGRESS_AWAITING_CORRECTIONS,PENDING"
    r = session.get(f"{BASE_URL}/jobs", params={"statuses": statuses})
    r.raise_for_status()
    jobs = r.json()
    matches = [j for j in jobs if project_id in j.get("overview", {}).get("projectName", "")]
    if not matches:
        raise ValueError(
            f"No IN_PROGRESS job found for project '{project_id}'. "
            "Check XTRF or pass a different status."
        )
    in_progress = [j for j in matches if j.get("overview", {}).get("status") != "PENDING"]
    candidates = in_progress or matches
    if len(candidates) > 1:
        details = ", ".join(
            f"{j['id']} ({j.get('overview', {}).get('type')}, {j.get('overview', {}).get('status')})"
            for j in candidates
        )
        raise ValueError(f"Multiple matching jobs for '{project_id}': {details}. Pass a more specific id.")
    return candidates[0]["id"]


def _find_project_folder(project_id: str) -> Path:
    """Find the ComunicaDK folder whose name contains project_id."""
    matches = [p for p in WORK_DIR.iterdir() if p.is_dir() and project_id in p.name]
    if not matches:
        raise FileNotFoundError(
            f"No folder containing '{project_id}' found in {WORK_DIR}"
        )
    if len(matches) > 1:
        print(f"  Warning: multiple folders match '{project_id}', using {matches[0].name}")
    return matches[0]


def _find_files(folder: Path, project_id: str) -> tuple[Path, Path, Path, Path | None]:
    """
    Return (docx, pdf, qa_xlsx, appendix_xlsx) deliverable files from the project folder.
    Raises if any is missing or ambiguous.
    """
    docx_files     = [p for p in folder.glob("*.docx") if _GERMAN_FILE_RE.search(p.stem)]
    pdf_files      = [p for p in folder.glob("*.pdf")  if _GERMAN_FILE_RE.search(p.stem)]
    qa_xlsx_files  = [p for p in folder.glob("project_QA_Report_*.xlsx")]
    app_xlsx_files = [
        p for p in folder.glob("Appendix A*.xlsx")
        if project_id in p.name
    ]

    def _one(label: str, found: list[Path]) -> Path:
        if not found:
            raise FileNotFoundError(f"No {label} file found in {folder}")
        if len(found) > 1:
            names = ", ".join(p.name for p in found)
            raise ValueError(f"Multiple {label} files found: {names}")
        return found[0]

    appendix = app_xlsx_files[0] if len(app_xlsx_files) == 1 else None
    if len(app_xlsx_files) > 1:
        names = ", ".join(p.name for p in app_xlsx_files)
        raise ValueError(f"Multiple Appendix A xlsx files found: {names}")

    return (
        _one("German docx", docx_files),
        _one("German pdf", pdf_files),
        _one("QA xlsx", qa_xlsx_files),
        appendix,
    )


def _upload_file(session: requests.Session, job_id: int, path: Path) -> dict:
    """Upload a single file to the XTRF target-files endpoint."""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    url = f"{BASE_URL}/jobs/classic/{job_id}/target-files"
    with open(path, "rb") as fh:
        r = session.post(
            url,
            files={"file": (path.name, fh, mime)},
            headers={"Accept": "text/plain, */*; q=0.01"},
        )
    if not r.ok:
        print(f"\n  Response body: {r.text[:1000]}", file=sys.stderr)
    r.raise_for_status()
    return r.json() if r.content else {}


def run(project_id: str) -> None:
    creds = _load_creds()
    session = _make_session()

    print(f"Logging in to XTRF...")
    _login(session, creds)

    print(f"Looking up job for '{project_id}'...")
    job_id = _find_job_id(session, project_id)
    print(f"  Found job ID: {job_id}")

    folder = _find_project_folder(project_id)
    print(f"  Project folder: {folder.name}")

    docx, pdf, xlsx, appendix = _find_files(folder, project_id)
    print(f"  Files to upload:")
    print(f"    {docx.name}")
    print(f"    {pdf.name}")
    print(f"    {xlsx.name}")
    if appendix:
        print(f"    {appendix.name}")

    upload_files = [p for p in (docx, pdf, xlsx, appendix) if p is not None]
    for path in upload_files:
        print(f"Uploading {path.name} ...", end=" ", flush=True)
        _upload_file(session, job_id, path)
        print("ok")

    if appendix is None:
        print("No Appendix A uploaded")

    # Verify
    r = session.get(f"{BASE_URL}/jobs/classic/{job_id}/target-files")
    r.raise_for_status()
    uploaded = r.json()
    print(f"\nVerified — {len(uploaded)} file(s) now on XTRF:")
    for f in uploaded:
        print(f"  {f['name']}  ({f['size']})")


def main():
    parser = argparse.ArgumentParser(description="Upload deliverables to XTRF vendor portal")
    parser.add_argument("project_id", help="Project ID, e.g. PLPA_2605_P0021")
    args = parser.parse_args()
    try:
        run(args.project_id)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
