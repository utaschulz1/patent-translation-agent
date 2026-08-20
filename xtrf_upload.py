"""
xtrf_upload.py  —  XTRF workflow final step

Uploads deliverable files to XTRF. Two profiles, selected with --profile:

  post-editing (default, unchanged behaviour) — 4 files found by globbing
  the project folder:
    - *_German (Claims/Description/...).docx
    - *_German (Claims/Description/...).pdf
    - project_QA_Report_<project_id>.xlsx
    - Appendix A*<project_id>*.xlsx

  issue-resolution — 2 files per part, resolved from
  pre-processing/issue_resolution_manifest.json (written by
  issue_resolution_locate.py) rather than globbed: the part's renamed
  "(Issue Resolution)" docx, and the job's Xbench file. Use --part to
  upload a single part; omit it to upload every part in the manifest.

Usage:
    python xtrf_upload.py <project_id> [--profile post-editing|issue-resolution] [--part NAME]

    Examples:
        python xtrf_upload.py PLPA_2605_P0021
        python xtrf_upload.py HALA_2607_P0624 --profile issue-resolution
        python xtrf_upload.py HALA_2607_P0624 --profile issue-resolution --part Specification
"""

import argparse
import json
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

FILE_PROFILES = ("post-editing", "issue-resolution")


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


def _find_job_id(
    session: requests.Session, project_id: str, prefer_type_keyword: str | None = None
) -> int:
    """Return the XTRF job id for the given project_id (searches IN_PROGRESS jobs).

    A project can have more than one matching job at once, e.g. the main
    translation job plus a separate, not-yet-accepted "Issues resolution"
    job scheduled for later. When prefer_type_keyword is given (e.g. "issue"),
    candidates whose overview.type contains it are preferred over the rest —
    used by the issue-resolution profile to target the Issue Resolution job
    rather than the original translation job when both are present. PENDING
    jobs are not ready to receive target files, so IN_PROGRESS jobs are
    preferred when both are present.
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
    if prefer_type_keyword:
        keyword_matches = [
            j for j in matches
            if prefer_type_keyword.lower() in (j.get("overview", {}).get("type") or "").lower()
        ]
        if keyword_matches:
            matches = keyword_matches
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


def _find_files_post_editing(folder: Path, project_id: str) -> tuple[Path, Path, Path, Path | None]:
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


def _find_files_issue_resolution(folder: Path, part: str | None) -> list[Path]:
    """
    Return deliverable files for the issue-resolution profile: the renamed
    "(Issue Resolution)" docx for each part named in
    pre-processing/issue_resolution_manifest.json (written by
    issue_resolution_locate.py) — or just the one matching `part` if given —
    plus the job's Xbench file (shared across parts, included once).
    """
    pre_folder = folder / "pre-processing"
    manifest_path = pre_folder / "issue_resolution_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No issue_resolution_manifest.json in {pre_folder}. "
            "Run ISSUE_RESOLUTION_LOCATE first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Gate: never upload work that ISSUE_RESOLUTION_REVIEW_CHECK hasn't confirmed
    # clean. Status is per-part, so a targeted --part upload only needs that
    # part clean; an upload-everything run needs all_clean.
    status_path = pre_folder / "issue_resolution_status.json"
    if not status_path.exists():
        raise FileNotFoundError(
            f"No issue_resolution_status.json in {pre_folder}. "
            "Run ISSUE_RESOLUTION_REVIEW_CHECK first — uploading unreviewed work is not allowed."
        )
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status_by_part = {p["part"]: p for p in status["parts"]}

    if part:
        part_status = status_by_part.get(part)
        if part_status is None:
            raise ValueError(f"No status for part '{part}' — run ISSUE_RESOLUTION_REVIEW_CHECK first.")
        if not part_status["clean"]:
            raise ValueError(
                f"Part '{part}' is not resolved ({len(part_status['problems'])} unresolved item(s)) — "
                "resolve it and re-run ISSUE_RESOLUTION_REVIEW_CHECK before uploading."
            )
    elif not status["all_clean"]:
        unresolved = [p["part"] for p in status["parts"] if not p["clean"]]
        raise ValueError(
            f"Not all parts are resolved yet: {unresolved}. "
            "Resolve them and re-run ISSUE_RESOLUTION_REVIEW_CHECK before uploading, "
            "or upload just the clean part(s) individually with --part."
        )

    parts = manifest["parts"]
    if part:
        parts = [p for p in parts if p["part"] == part]
        if not parts:
            available = ", ".join(p["part"] for p in manifest["parts"])
            raise ValueError(f"No part named '{part}' in manifest. Available: {available}")

    files = [Path(p["renamed_docx"]) for p in parts]
    if manifest.get("xbench_upload_name"):
        files.append(Path(manifest["xbench_upload_name"]))
    return files


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


def run(project_id: str, profile: str = "post-editing", part: str | None = None) -> None:
    if profile not in FILE_PROFILES:
        raise ValueError(f"Unknown profile {profile!r}. Known: {FILE_PROFILES}")

    creds = _load_creds()
    session = _make_session()

    print(f"Logging in to XTRF...")
    _login(session, creds)

    print(f"Looking up job for '{project_id}'...")
    prefer_type_keyword = "issue" if profile == "issue-resolution" else None
    job_id = _find_job_id(session, project_id, prefer_type_keyword=prefer_type_keyword)
    print(f"  Found job ID: {job_id}")

    folder = _find_project_folder(project_id)
    print(f"  Project folder: {folder.name}")

    if profile == "post-editing":
        docx, pdf, xlsx, appendix = _find_files_post_editing(folder, project_id)
        upload_files = [p for p in (docx, pdf, xlsx, appendix) if p is not None]
        appendix_uploaded = appendix is not None
    else:
        upload_files = _find_files_issue_resolution(folder, part)
        appendix_uploaded = None  # not applicable to this profile

    print(f"  Files to upload:")
    for p in upload_files:
        print(f"    {p.name}")

    for path in upload_files:
        print(f"Uploading {path.name} ...", end=" ", flush=True)
        _upload_file(session, job_id, path)
        print("ok")

    if appendix_uploaded is False:
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
    parser.add_argument("--profile", choices=FILE_PROFILES, default="post-editing",
                         help="Which file set to upload (default: post-editing)")
    parser.add_argument("--part", default=None,
                         help="issue-resolution profile only: upload just this part (e.g. Specification). "
                              "Omit to upload every part in the manifest.")
    args = parser.parse_args()
    try:
        run(args.project_id, profile=args.profile, part=args.part)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
