"""
xtm_verify_correction.py — Issue Resolution step: round-trip check after XTM_CORRECTION_UPLOAD

Refreshes Final_<stem>.xlsx (reusing xtm_final_download.run(..., only="xlsx")
— same preview-download mechanism, not a duplicate), then for every segment
id in the *_revised_translation_checks_issue_resolution.xlsx that
xtm_segment_match.py produced:

  (a) confirms the current Target text matches the expected corrected text
      exactly
  (b) confirms the segment immediately before and the segment immediately
      after it (by row position in the pre-upload snapshot
      xtm_segment_match.py froze) are byte-identical to that snapshot

A segment that failed to save during XTM_CORRECTION_UPLOAD (a tag/lag
issue) is expected to also fail here — this script only reports, it never
retries or auto-fixes.

Usage:
    python xtm_verify_correction.py --pid <project_id>

Exit code 0 only if every corrected segment and its neighbors pass.
"""

import argparse
import sys
from pathlib import Path

import openpyxl

import project_log
import xtm_final_download

CHECKS_GLOB = "*_revised_translation_checks_issue_resolution.xlsx"


def _load_id_target_rows(xlsx_path: Path) -> list[tuple[int, str]]:
    """(id, target) for every data row, in sheet order — row order matters here."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        seg_id = row[0]
        if seg_id is None:
            continue
        rows.append((int(seg_id), (row[2] if len(row) > 2 else None) or ""))
    return rows


def _find_one(folder: Path, pattern: str, label: str) -> Path:
    """Globs pattern in folder, requiring exactly one match.

    Raises:
        FileNotFoundError: no match.
        ValueError: more than one match.
    """
    matches = list(folder.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No {label} ({pattern}) in {folder}")
    if len(matches) > 1:
        raise ValueError(f"Multiple {label} found: {[p.name for p in matches]}")
    return matches[0]


def verify(checks_path: Path, snapshot_path: Path, current_path: Path) -> list[dict]:
    """Returns a list of {segment_id, checks: {...}} results, one per corrected segment."""
    expected = dict(_load_id_target_rows(checks_path))  # id -> expected corrected text
    snapshot_rows = _load_id_target_rows(snapshot_path)
    current_by_id = dict(_load_id_target_rows(current_path))

    results = []
    for idx, (seg_id, _snap_target) in enumerate(snapshot_rows):
        if seg_id not in expected:
            continue

        checks = {}

        current_target = current_by_id.get(seg_id)
        if current_target is None:
            checks["target_updated"] = (False, "segment not found in current download")
        else:
            checks["target_updated"] = (
                current_target == expected[seg_id],
                None if current_target == expected[seg_id]
                else f"expected {expected[seg_id]!r}, got {current_target!r}",
            )

        for label, neighbor_idx in (("before", idx - 1), ("after", idx + 1)):
            if neighbor_idx < 0 or neighbor_idx >= len(snapshot_rows):
                checks[f"neighbor_{label}"] = (True, "no neighbor at this edge of the sheet — skipped")
                continue
            neighbor_id, neighbor_snapshot_text = snapshot_rows[neighbor_idx]
            neighbor_current_text = current_by_id.get(neighbor_id)
            if neighbor_current_text is None:
                checks[f"neighbor_{label}"] = (False, f"segment {neighbor_id} not found in current download")
            else:
                ok = neighbor_current_text == neighbor_snapshot_text
                checks[f"neighbor_{label}"] = (
                    ok, None if ok else f"segment {neighbor_id} changed: "
                                         f"{neighbor_snapshot_text!r} -> {neighbor_current_text!r}"
                )

        results.append({"segment_id": seg_id, "checks": checks})

    return results


def run(project_id: str) -> bool:
    """Re-downloads current XTM segment state and verifies every corrected
    segment (plus its immediate neighbors) against the pre-upload snapshot.

    Short-circuits (trivially True, no XTM call) if no corrections checks
    xlsx exists — nothing was corrected, so there's nothing to verify.

    Args:
        project_id: the project to verify.

    Returns:
        True if every corrected segment and its neighbors passed all checks
        (or there was nothing to verify), False if anything failed.
    """
    pre_folder = project_log.find_project_dir(project_id)
    project_folder = pre_folder.parent

    if not list(pre_folder.glob(CHECKS_GLOB)):
        # Nothing was corrected (XTM_SEGMENT_MATCH found no fixes needed, or the
        # job needed no resolution at all) — trivially verified, nothing to check.
        print("No corrections checks xlsx found — nothing was corrected, nothing to verify.")
        return True

    checks_path = _find_one(pre_folder, CHECKS_GLOB, "corrections checks xlsx")
    snapshot_path = _find_one(project_folder, "Final_*_preupload_snapshot.xlsx", "pre-upload snapshot")

    print("Re-downloading current segment state from XTM...")
    xtm_final_download.run(project_id, only="xlsx")
    # Final_*.xlsx also matches the snapshot's own name — exclude it explicitly.
    candidates = [p for p in project_folder.glob("Final_*.xlsx") if "_preupload_snapshot" not in p.stem]
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly 1 non-snapshot Final_*.xlsx, found: {[p.name for p in candidates]}")
    current_path = candidates[0]

    results = verify(checks_path, snapshot_path, current_path)
    if not results:
        print("No corrected segments to verify (empty checks file).")
        return True

    all_pass = True
    for r in results:
        seg_id = r["segment_id"]
        seg_pass = all(ok for ok, _ in r["checks"].values())
        all_pass = all_pass and seg_pass
        status = "PASS" if seg_pass else "FAIL"
        print(f"segment {seg_id}: {status}")
        for check_name, (ok, detail) in r["checks"].items():
            if not ok:
                print(f"  - {check_name}: {detail}")

    return all_pass


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True)
    args = parser.parse_args()
    try:
        ok = run(args.pid)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if not ok:
        print("\nVerification FAILED for at least one segment — see above. No auto-retry.")
        sys.exit(1)
    print("\nAll corrected segments verified OK.")


if __name__ == "__main__":
    main()
