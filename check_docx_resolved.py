"""
check_docx_resolved.py — Issue Resolution step: is there anything left to resolve?

Deterministic gate, no LLM call. Reads pre-processing/issue_resolution_manifest.json
(written by issue_resolution_locate.py) and, for every part's renamed docx, checks:

  - tracked changes: none may remain
  - comments: every ROOT comment (one that isn't itself a reply) must have at
    least one reply authored by --reply-author specifically

"Has >=1 reply" alone is NOT treated as resolved — a comment can arrive with
a reply already in it that isn't ours (a DTP-side or other party's note), so
counting any reply as "done" would silently skip comments that still need
our attention. Only a reply from the given author counts.

A part with zero comments AND zero tracked changes needs no interactive
review at all — this is what lets the common "nothing to do" Issue
Resolution job (the large majority, per real-world volume) skip the
docx-comment-reply / resolve-tracked-changes skills entirely.

Writes pre-processing/issue_resolution_status.json — the single
machine-readable signal every downstream step (XTRF upload, XTM matching,
the final XTRF comment) reads instead of re-deriving or guessing:

  {
    "all_clean": true,
    "any_needed_work": false,
    "parts": [{"part": "Claims", "clean": true, "had_comments": false,
                "had_tracked_changes": false, "problems": []}]
  }

"any_needed_work" comes from issue_resolution_locate.py's manifest (the
had_comments/had_tracked_changes ground truth captured once, before any
editing) — NOT from this run's own findings, because accepted tracked
changes disappear from the docx, so a clean re-run after real work looks
identical to a docx that never had anything wrong with it unless that
original fact is preserved separately. This is what lets ISSUE_RESOLUTION_XTRF_UPLOAD
and XTRF_COMMENT_POST tell "genuinely nothing to do" apart from "resolved by hand" —
both are "clean" here, but they need different downstream behaviour (the second one
needs its comment/tracked-change fixes considered for XTM propagation, the first
one never does).

Usage:
    python check_docx_resolved.py --pid <project_id> [--reply-author "<translator name>"]

Exit code 0 only if every part is fully clean. REPEATABLE — re-run after
doing interactive skill work on whichever parts were reported unresolved.
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

import project_log
from config import TRANSLATOR_NAME

UTILITIES_DIR = Path(__file__).parent / "utilities"
sys.path.insert(0, str(UTILITIES_DIR))

from resolve_tracked_changes import build_list_report  # noqa: E402
from extract_docx_comments import get_comment_reply_status  # noqa: E402


def check_part(docx_path: Path, reply_author: str) -> list[str]:
    """Checks one part's docx for unresolved tracked changes and unreplied comments.

    Args:
        docx_path: the renamed "(Issue Resolution)" docx for this part.
        reply_author: only a reply from this author counts as resolving a comment.

    Returns:
        Human-readable problem descriptions, one per unresolved item — empty
        list means the part is clean.
    """
    problems = []

    with zipfile.ZipFile(docx_path) as z:
        document_xml = z.read("word/document.xml")
    tracked_changes = build_list_report(document_xml)
    for change in tracked_changes:
        problems.append(
            f"unresolved tracked change ({change['type']}) at {change['location']}: "
            f"{change.get('old_text') or ''!r} -> {change.get('new_text') or ''!r}"
        )

    threads = get_comment_reply_status(docx_path)
    for cid, thread in threads.items():
        matching = [r for r in thread["replies"] if r.get("author") == reply_author]
        if not matching:
            reply_authors = [r.get("author") for r in thread["replies"]]
            if reply_authors:
                problems.append(
                    f"comment {cid} (by {thread['author']}) has replies from "
                    f"{reply_authors} but none from '{reply_author}'"
                )
            else:
                problems.append(f"comment {cid} (by {thread['author']}) has no reply yet")

    return problems


def run(project_id: str, reply_author: str) -> dict:
    """Checks every part in the manifest and writes issue_resolution_status.json.

    Args:
        project_id: the project to check.
        reply_author: only replies from this author count as "resolved" —
            see the module docstring for why.

    Returns:
        The status dict written to issue_resolution_status.json.

    Raises:
        FileNotFoundError: if ISSUE_RESOLUTION_LOCATE hasn't been run yet.
    """
    pre_folder = project_log.find_project_dir(project_id)
    manifest_path = pre_folder / "issue_resolution_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest at {manifest_path}. Run ISSUE_RESOLUTION_LOCATE first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    parts_status = []
    for part in manifest["parts"]:
        docx_path = Path(part["renamed_docx"])
        problems = check_part(docx_path, reply_author)
        clean = not problems
        needed_work = part.get("had_comments", False) or part.get("had_tracked_changes", False)
        if clean:
            note = "nothing to resolve" if not needed_work else "resolved"
            print(f"{part['part']} ({docx_path.name}): clean — {note}.")
        else:
            print(f"{part['part']} ({docx_path.name}): {len(problems)} unresolved item(s):")
            for p in problems:
                print(f"  - {p}")
        parts_status.append({
            "part": part["part"],
            "clean": clean,
            "had_comments": part.get("had_comments", False),
            "had_tracked_changes": part.get("had_tracked_changes", False),
            "problems": problems,
        })

    status = {
        "all_clean": all(p["clean"] for p in parts_status),
        "any_needed_work": any(p["had_comments"] or p["had_tracked_changes"] for p in parts_status),
        "parts": parts_status,
    }
    status_path = pre_folder / "issue_resolution_status.json"
    status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nStatus written: {status_path}")
    if not status["all_clean"]:
        print(f"\nIn a Claude Code session (Remote Control works fine): "
              f"cd \"{pre_folder}\" and invoke the issue-resolution-review skill for {project_id}.")
    return status


def main():
    """CLI entry point — see the module docstring for exit-code semantics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True)
    parser.add_argument("--reply-author", default=TRANSLATOR_NAME,
                         help=f'Author name the docx-comment-reply skill was told to use (default: "{TRANSLATOR_NAME}")')
    args = parser.parse_args()
    try:
        status = run(args.pid, args.reply_author)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if not status["all_clean"]:
        print("\nNot resolved — see the command above. Re-run this check once done.")
        sys.exit(1)
    print("\nAll parts resolved." if status["any_needed_work"] else "\nNothing needed resolving.")


if __name__ == "__main__":
    main()
