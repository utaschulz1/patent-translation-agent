"""
get_XTRF_job.py — Step 3a (XTRF-native): select next job directly from XTRF vendor portal

Replaces the Gmail-based get_XTRF_link.py. Queries GET /vendors/jobs, filters out
already-processed jobs, sorts by deadline, and returns the earliest one.

State logged to project_log.json per XTRF job ID (string):
  LINK_EXTRACTED   job selected and returned

Return value matches get_XTRF_link.run(): (xtrf_url, project_id, job_id_str)
The job_id_str replaces the Gmail message ID as the project_log key.
"""

import os
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import project_log

_ENV = Path(__file__).parent / ".env"
BASE_URL = "https://comunicadk.s.xtrf.eu/vendors"
_DONE_STATES = {"LINK_EXTRACTED", "JOB_FINISHED_SUCCESSFULLY"}

_DEADLINE_FIELDS = ("deadline", "deadlineDate", "dueDate", "finishDate")


def _load_creds() -> dict:
    load_dotenv(_ENV)
    return {
        "email": os.environ["COMUNICA_JOBLIST_USERNAME"],
        "password": os.environ["COMUNICA_JOBLIST_PASSWORD"],
    }


def _login(session: requests.Session, creds: dict) -> None:
    r = session.post(f"{BASE_URL}/login", json=creds)
    r.raise_for_status()


def _parse_deadline(overview: dict) -> datetime | None:
    for field in _DEADLINE_FIELDS:
        val = overview.get(field)
        if val is None:
            continue
        if isinstance(val, (int, float)):  # Unix ms timestamp
            try:
                return datetime.fromtimestamp(val / 1000)
            except Exception:
                pass
        if isinstance(val, str):
            # XTRF format: "02-06-2026 11:00 WEST" — strip timezone suffix, use first 16 chars
            clean = val[:16]
            for fmt in ("%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.strptime(clean, fmt)
                except ValueError:
                    pass
    return None


def run(target_project_id: str | None = None) -> tuple[str, str, str] | None:
    """
    Query XTRF for IN_PROGRESS jobs, skip already-processed ones, return the one
    with the earliest deadline.

    If target_project_id is given, only that project is considered.
    Returns (xtrf_url, project_id, job_id_str) or None if nothing to do.
    """
    creds = _load_creds()
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    })
    _login(session, creds)

    statuses = "IN_PROGRESS,IN_PROGRESS_AWAITING_CORRECTIONS,PENDING"
    r = session.get(f"{BASE_URL}/jobs", params={"statuses": statuses})
    r.raise_for_status()
    jobs = r.json()

    if not jobs:
        print("No IN_PROGRESS jobs found on XTRF.")
        return None

    full_log = project_log.get_all_logs()

    def _is_processed(job_id: str) -> bool:
        return any(
            e.get("state") in _DONE_STATES
            for e in full_log.get(job_id, {}).get("events", [])
        )

    candidates = [j for j in jobs if not _is_processed(str(j["id"]))]

    if not candidates:
        print(f"All {len(jobs)} XTRF job(s) already processed.")
        return None

    if target_project_id:
        candidates = [
            j for j in candidates
            if target_project_id in j.get("overview", {}).get("projectName", "")
        ]
        if not candidates:
            print(f"ERROR: No unprocessed XTRF job found for project {target_project_id}.")
            return None

    candidates.sort(key=lambda j: (
        1 if _parse_deadline(j.get("overview", {})) is None else 0,
        _parse_deadline(j.get("overview", {})) or datetime.max,
    ))

    for job in candidates:
        job_id = str(job["id"])
        overview = job.get("overview", {})
        project_name = overview.get("projectName", "")
        project_id = project_name.split("|")[-1].strip()
        dl = _parse_deadline(overview)

        if dl is None:
            print(f"WARNING: deadline not found. Overview keys: {list(overview.keys())}")

        stype = overview.get("jobType")  # e.g. "Post-editing"
        dl_str = dl.strftime('%d-%m-%Y %H:%M') if dl else 'unknown'
        print(f"XTRF job {job_id} ({project_id}) — deadline: {dl_str}" +
              (f" — job type: {stype}" if stype else ""))

        # Proceed silently if jobType is absent or is post-editing.
        # Prompt for anything else (translation, review, proofreading, etc.).
        is_post_edit = stype is None or "post" in stype.lower()

        if not is_post_edit:
            answer = input(
                f"  '{stype}' is not post-editing. Proceed with standard translation workflow? [Y/N]: "
            ).strip().upper()
            if answer != "Y":
                print(f"  Skipping {project_id}.")
                continue

        xtrf_url = f"{BASE_URL}/#/jobs/classic/{job_id}"
        project_log.log_event(job_id, "LINK_EXTRACTED", detail=f"project={project_id}")
        return xtrf_url, project_id, job_id

    print("No suitable unprocessed XTRF jobs found.")
    return None


if __name__ == "__main__":
    result = run()
    if result:
        xtrf_url, project_id, job_id = result
        print(f"URL:     {xtrf_url}")
        print(f"Project: {project_id}")
        print(f"Job ID:  {job_id}")
