"""
xtrf_post_comment.py — Issue Resolution step: post the final-outcome comment to XTRF

Selects one of 3 fixed "telegram style" templates and posts it to the
matching XTRF Issue Resolution job. Reuses xtrf_upload.py's own
auth/session/job-lookup helpers (_load_creds, _make_session, _login,
_find_job_id) rather than duplicating them.

--outcome is normally OMITTED — it's auto-determined from
pre-processing/issue_resolution_status.json (written by
ISSUE_RESOLUTION_REVIEW_CHECK) plus whether an XTM corrections file was
produced (written by XTM_SEGMENT_MATCH), so this step needs no manual
input for the common case:

  status.any_needed_work == False                       -> no_action
  any_needed_work == True, no corrections xlsx produced  -> resolved_no_xtm
  any_needed_work == True, a corrections xlsx exists     -> resolved_with_xtm

Pass --outcome explicitly only to override this.

POST ENDPOINT (confirmed live via a captured browser request, 2026-08-20 —
see .claude/commands/xtrf.md):

    PUT {BASE_URL}/jobs/classic/{job_id}/comments
    Content-Type: text/plain; charset=utf-8
    body: the raw comment text itself — no JSON wrapping, no field name.
    (Confirmed by an exact Content-Length match: a real 17-character
    comment produced Content-Length: 17.)

--dry-run still defaults to True. Real posting (--live) is now implemented,
but every first live call in this codebase needs explicit user approval
before being run for real — this one is no exception just because the
endpoint is now known.

Usage:
    python xtrf_post_comment.py --pid <project_id>                        # auto-detect outcome
    python xtrf_post_comment.py --pid <project_id> --outcome resolved_no_xtm   # override
"""

import argparse
import json
import sys
from pathlib import Path

import project_log
from xtrf_upload import BASE_URL, _load_creds, _make_session, _login, _find_job_id

TEMPLATES = {
    "no_action": "No comments, no tracked changes, no action required.",
    "resolved_no_xtm": "Comments answered, tracked changes resolved, no action required.",
    "resolved_with_xtm": "Comments/tracked changes resolved, XTM corrected.",
}

CORRECTIONS_XLSX_GLOB = "*_revised_translation_checks_issue_resolution.xlsx"


def determine_outcome(project_id: str) -> str:
    """Auto-picks a TEMPLATES key from issue_resolution_status.json — see the
    module docstring for the exact decision table.

    Args:
        project_id: the project to determine the outcome for.

    Returns:
        One of "no_action", "resolved_no_xtm", "resolved_with_xtm".

    Raises:
        FileNotFoundError: ISSUE_RESOLUTION_REVIEW_CHECK hasn't been run yet.
        ValueError: not all parts are resolved yet.
    """
    pre_folder = project_log.find_project_dir(project_id)
    status_path = pre_folder / "issue_resolution_status.json"
    if not status_path.exists():
        raise FileNotFoundError(
            f"No issue_resolution_status.json in {pre_folder}. "
            "Run ISSUE_RESOLUTION_REVIEW_CHECK first, or pass --outcome explicitly."
        )
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if not status.get("all_clean", False):
        raise ValueError(
            "issue_resolution_status.json says not all parts are resolved yet — "
            "refusing to auto-pick an outcome for an unfinished job. "
            "Resolve remaining parts (or pass --outcome explicitly if you're sure)."
        )
    if not status.get("any_needed_work", True):
        return "no_action"
    has_corrections = bool(list(pre_folder.glob(CORRECTIONS_XLSX_GLOB)))
    return "resolved_with_xtm" if has_corrections else "resolved_no_xtm"


def run(project_id: str, outcome: str | None = None, dry_run: bool = True) -> None:
    """Posts (or dry-runs) the outcome comment to the matching XTRF job.

    Args:
        project_id: the project whose Issue Resolution job to comment on.
        outcome: one of TEMPLATES' keys, or None to auto-detect (see
            determine_outcome).
        dry_run: if True (the default), prints what would be posted and
            makes no network write. If False, actually PUTs the comment —
            see the module docstring for the confirmed endpoint/payload.
    """
    if outcome is None:
        outcome = determine_outcome(project_id)
        print(f"Auto-detected outcome: {outcome}")
    elif outcome not in TEMPLATES:
        raise ValueError(f"Unknown outcome {outcome!r}. Known: {list(TEMPLATES)}")
    comment = TEMPLATES[outcome]

    creds = _load_creds()
    session = _make_session()
    print("Logging in to XTRF...")
    _login(session, creds)

    print(f"Looking up job for '{project_id}'...")
    job_id = _find_job_id(session, project_id, prefer_type_keyword="issue")
    print(f"  Found job ID: {job_id}")
    print(f"  Comment: {comment!r}")

    url = f"{BASE_URL}/jobs/classic/{job_id}/comments"

    if dry_run:
        print(f"[DRY RUN] would PUT to {url}")
        print(f"  body (text/plain, {len(comment.encode('utf-8'))} bytes): {comment!r}")
        return

    # No JSON wrapping — confirmed via a captured browser request (2026-08-20):
    # the body is the raw comment text itself, sent as text/plain. Also mirrors
    # xtrf_job_setup.py's _get_job in sending time-zone-offset-in-minutes, since
    # that's present on the real browser request too and costs nothing to match.
    r = session.put(
        url,
        data=comment.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8", "time-zone-offset-in-minutes": "60"},
    )
    r.raise_for_status()
    print(f"Posted comment to job {job_id}.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True)
    parser.add_argument("--outcome", default=None, choices=list(TEMPLATES),
                         help="Override auto-detection (see module docstring for the default logic)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    parser.add_argument("--live", dest="dry_run", action="store_false",
                         help="Actually post the comment instead of dry-running it")
    args = parser.parse_args()
    try:
        run(args.pid, args.outcome, dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
