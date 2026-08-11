"""
issue_resolution_locate.py — Issue Resolution step 1: locate + rename files

Given the unzipped Issue Resolution deliverable in a project's
pre-processing/ folder (written by xtrf_job_setup.py's Issue Resolution
branch), finds every DTP-produced docx that needs review, makes an
"(Issue Resolution)"-renamed copy of each, and locates the job's Xbench
report. Writes pre-processing/issue_resolution_manifest.json, which every
downstream Issue Resolution step reads instead of re-deriving these paths.

A DTP worker's filename is manual human input, not a generated string, so
matching tolerates common formatting drift (double spaces, underscores,
casing) rather than failing the whole workflow over a typo.

Usage:
    python issue_resolution_locate.py --pid <project_id>
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

import project_log

UTILITIES_DIR = Path(__file__).parent / "utilities"
sys.path.insert(0, str(UTILITIES_DIR))

from resolve_tracked_changes import build_list_report  # noqa: E402
from extract_docx_comments import get_comment_reply_status  # noqa: E402

# Tolerant match for "(<initials> Issues)" / "(<initials> No Changes)":
# [\s_]+ between initials and keyword handles a double space, an underscore,
# or any other separator instead of assuming exactly one plain space; \s*
# soaks up stray whitespace just inside the parens; IGNORECASE catches
# "issues"/"NO CHANGES" typos.
ISSUES_RE = re.compile(r"\(\s*([\w-]+)[\s_]+(Issues|No[\s_]+Changes)\s*\)", re.IGNORECASE)

# Excludes names already containing "_checked" so re-running this script
# (e.g. after a partial failure) doesn't pick up its own prior output.
XBENCH_XLSX_RE = re.compile(r"^Xbench_QA_Report(?!.*_checked).*\.xlsx$", re.IGNORECASE)
XBENCH_TXT_RE = re.compile(r"^No error found in Xbench report.*\.txt$", re.IGNORECASE)


def _task_work_dirs(pre_folder: Path) -> list[Path]:
    """Every 'Work Files' directory whose parent is 'Task Files', anywhere in the tree."""
    return [d for d in pre_folder.rglob("Work Files") if d.is_dir() and d.parent.name == "Task Files"]


def _original_source_dirs(pre_folder: Path) -> list[Path]:
    """Every 'Work Files' directory whose parent is 'Original Source Files', anywhere in the tree."""
    return [d for d in pre_folder.rglob("Work Files") if d.is_dir() and d.parent.name == "Original Source Files"]


def _extract_part(stem: str, match: re.Match) -> str:
    """The '(<Part>)' segment immediately before the Issues/No Changes match, if any.

    Multi-part jobs have it (e.g. "... (Specification) (B2R Issues) ..."
    -> "Specification"); single-part jobs often don't (e.g.
    "..._German (HLL Issues) ..." with nothing between "_German" and the
    match) -> falls back to "Document".
    """
    prefix = stem[: match.start()].rstrip()
    m = re.search(r"\(([^()]+)\)\s*$", prefix)
    return m.group(1).strip() if m else "Document"


def _renamed_name(stem: str, match: re.Match, suffix: str) -> str:
    """Replace the matched '(<initials> Issues/No Changes)' span with '(Issue Resolution)'."""
    return f"{stem[:match.start()]}(Issue Resolution){stem[match.end():]}{suffix}"


def _original_state(docx_path: Path) -> tuple[bool, bool]:
    """(had_comments, had_tracked_changes) — ground truth, captured once here before any
    interactive editing happens. Tracked changes disappear from the docx once
    accepted/rejected, so this is the only point this can ever be determined;
    comments persist (a reply doesn't remove the comment) so it would still be
    derivable later, but recording both here keeps the signal in one place."""
    with zipfile.ZipFile(docx_path) as z:
        had_comments = "word/comments.xml" in z.namelist() and bool(get_comment_reply_status(docx_path))
        had_tracked_changes = bool(build_list_report(z.read("word/document.xml")))
    return had_comments, had_tracked_changes


def locate(pre_folder: Path) -> dict:
    task_work_dirs = _task_work_dirs(pre_folder)
    if not task_work_dirs:
        raise FileNotFoundError(
            f"No 'Task Files/Work Files' directory found anywhere under {pre_folder}. "
            "Was the Issue Resolution zip unpacked here?"
        )

    # ---- docx parts ----
    candidates: dict[str, list[Path]] = {}  # part -> matching docx paths
    match_by_path: dict[Path, tuple[str, re.Match]] = {}
    for work_dir in task_work_dirs:
        for docx_path in work_dir.glob("*.docx"):
            m = ISSUES_RE.search(docx_path.stem)
            if not m:
                continue
            part = _extract_part(docx_path.stem, m)
            candidates.setdefault(part, []).append(docx_path)
            match_by_path[docx_path] = (part, m)

    if not candidates:
        searched = ", ".join(str(d) for d in task_work_dirs)
        raise FileNotFoundError(
            f"No docx matching '(<initials> Issues)' or '(<initials> No Changes)' found in: {searched}"
        )

    ambiguous = {part: paths for part, paths in candidates.items() if len(paths) > 1}
    if ambiguous:
        details = "; ".join(
            f"{part}: {', '.join(p.name for p in paths)}" for part, paths in ambiguous.items()
        )
        raise ValueError(f"Multiple candidate docx files for the same part — {details}")

    # ---- original source file(s), shared across parts (best-effort, non-fatal) ----
    source_files: list[Path] = []
    for d in _original_source_dirs(pre_folder):
        source_files.extend(p for p in d.iterdir() if p.is_file())
    source_file = None
    if not source_files:
        print("  WARNING: no file found under 'Original Source Files/Work Files' — cross-reference source unknown.")
    else:
        source_file = sorted(source_files)[0]
        if len(source_files) > 1:
            print(f"  WARNING: multiple original source files found, using {source_file.name}: "
                  f"{[p.name for p in source_files]}")

    # ---- rename each part's docx ----
    parts_out = []
    for part in sorted(candidates):
        docx_path = candidates[part][0]
        _, m = match_by_path[docx_path]
        renamed_name = _renamed_name(docx_path.stem, m, docx_path.suffix)
        renamed_path = docx_path.with_name(renamed_name)
        renamed_path.write_bytes(docx_path.read_bytes())
        had_comments, had_tracked_changes = _original_state(renamed_path)
        print(f"  {part}: {docx_path.name}")
        print(f"    -> {renamed_path.name}"
              f"  (had_comments={had_comments}, had_tracked_changes={had_tracked_changes})")
        parts_out.append({
            "part": part,
            "original_docx": str(docx_path),
            "renamed_docx": str(renamed_path),
            "source_file": str(source_file) if source_file else None,
            "had_comments": had_comments,
            "had_tracked_changes": had_tracked_changes,
        })

    # ---- Xbench report ----
    xbench_file = None
    xbench_kind = None
    xbench_upload_name = None
    xlsx_matches, txt_matches = [], []
    for work_dir in task_work_dirs:
        xlsx_matches.extend(p for p in work_dir.iterdir() if p.is_file() and XBENCH_XLSX_RE.match(p.name))
        txt_matches.extend(p for p in work_dir.iterdir() if p.is_file() and XBENCH_TXT_RE.match(p.name))

    if xlsx_matches and txt_matches:
        raise ValueError(
            f"Found both an Xbench xlsx and a 'no error' txt — ambiguous: "
            f"{[p.name for p in xlsx_matches]} vs {[p.name for p in txt_matches]}"
        )
    if len(xlsx_matches) > 1:
        raise ValueError(f"Multiple Xbench xlsx files found: {[p.name for p in xlsx_matches]}")
    if len(txt_matches) > 1:
        raise ValueError(f"Multiple 'no error' Xbench txt files found: {[p.name for p in txt_matches]}")

    if xlsx_matches:
        xbench_file = xlsx_matches[0]
        checked_path = xbench_file.with_name(f"{xbench_file.stem}_checked{xbench_file.suffix}")
        checked_path.write_bytes(xbench_file.read_bytes())
        xbench_kind = "xlsx"
        xbench_upload_name = str(checked_path)
        print(f"  Xbench: {xbench_file.name} -> {checked_path.name}")
    elif txt_matches:
        xbench_file = txt_matches[0]
        xbench_kind = "txt_no_error"
        xbench_upload_name = str(xbench_file)
        print(f"  Xbench: {xbench_file.name} (no error report — uploaded as-is, not renamed)")
    else:
        raise FileNotFoundError(
            f"No Xbench_QA_Report*.xlsx or 'No error found in Xbench report*.txt' found in: "
            f"{', '.join(str(d) for d in task_work_dirs)}"
        )

    return {
        "parts": parts_out,
        "xbench_file": str(xbench_file),
        "xbench_kind": xbench_kind,
        "xbench_upload_name": xbench_upload_name,
    }


def run(project_id: str) -> dict:
    pre_folder = project_log.find_project_dir(project_id)
    print(f"Pre-processing folder: {pre_folder}")

    result = locate(pre_folder)
    result = {"project_id": project_id, **result}

    manifest_path = pre_folder / "issue_resolution_manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nManifest written: {manifest_path}")
    print(f"  {len(result['parts'])} part(s), xbench_kind={result['xbench_kind']}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, help="Project ID, e.g. HALA_2607_P0624")
    args = parser.parse_args()
    try:
        run(args.pid)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
