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

THE POST ENDPOINT AND PAYLOAD ARE GENUINELY UNKNOWN AND NOT GUESSED HERE.
--dry-run defaults to True and is the only implemented path: it prints the
template, the job id, and what *would* be posted, then exits 0 without
making a network write. Real posting requires the endpoint to be found
first (capture a real note submission's network request through the XTRF
web UI, or find it in API docs if any exist) and recorded in
.claude/commands/xtrf.md — and even once known, the first live call needs
explicit user approval, same as any other first-time live write in this
codebase.

Usage:
    python xtrf_post_comment.py --pid <project_id>                        # auto-detect outcome
    python xtrf_post_comment.py --pid <project_id> --outcome resolved_no_xtm   # override
"""

import argparse
import json
import sys
from pathlib import Path

import project_log
from xtrf_upload import _load_creds, _make_session, _login, _find_job_id

TEMPLATES = {
    "no_action": "No comments, no tracked changes, no action required.",
    "resolved_no_xtm": "Comments answered, tracked changes resolved, no action required.",
    "resolved_with_xtm": "Comments/tracked changes resolved, XTM corrected.",
}

CORRECTIONS_XLSX_GLOB = "*_revised_translation_checks_issue_resolution.xlsx"


def determine_outcome(project_id: str) -> str:
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

    if dry_run:
        print(f"[DRY RUN] would POST to <unknown endpoint> — comment-post endpoint not yet researched. "
              f"See xtrf_post_comment.py's module docstring.")
        return

    raise NotImplementedError(
        "Live comment posting is not implemented — the XTRF endpoint/payload for this "
        "is unresearched. Run with --dry-run (the default) until that's found and "
        "recorded in .claude/commands/xtrf.md, and get explicit approval before the "
        "first live call."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True)
    parser.add_argument("--outcome", default=None, choices=list(TEMPLATES),
                         help="Override auto-detection (see module docstring for the default logic)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    parser.add_argument("--live", dest="dry_run", action="store_false",
                         help="Attempt a real post instead of dry-run (not implemented — see docstring)")
    args = parser.parse_args()
    try:
        run(args.pid, args.outcome, dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
