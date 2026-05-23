"""
workflow_review.py — Terminology analysis on any bilingual Excel file.

Runs the three LLM consistency checks (verb, noun, capability-predicate) and
merges the resulting glossaries. Safe to run alongside an active workflow
project — does not touch project_log.

Input Excel must have the standard 3-column layout:
  Row 1–3: header rows (skipped)
  Row 4+:  col A = segment ID, col B = EN source, col C = DE target

Steps:
  1  LLM verb consistency check
  2  LLM noun consistency check
  3  LLM capability-predicate check
  4  Merge glossaries

Usage:
    python workflow_review.py --file <excel>
    python workflow_review.py --file <excel> --output-folder <folder>
    python workflow_review.py --file <excel> --seg-range 1-50
"""

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent


def _run(script: Path, *args) -> None:
    import subprocess
    result = subprocess.run([sys.executable, str(script), *args])
    if result.returncode != 0:
        raise RuntimeError(f"{script.name} exited with code {result.returncode}")


def _crash(step: str, err: RuntimeError) -> None:
    print(f"\n{'─' * 60}")
    print(f"CRASH at step {step}: {err}")
    print(f"{'─' * 60}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Terminology analysis on a bilingual Excel file.")
    parser.add_argument("--file",          required=True, help="Bilingual Excel file to analyse")
    parser.add_argument("--output-folder", help="Folder for all output files (default: same folder as input file)")
    parser.add_argument("--seg-range",     help="Segment range e.g. 1-50 (passed to LLM scripts)")
    args = parser.parse_args()

    excel_path = Path(args.file).resolve()
    if not excel_path.exists():
        print(f"ERROR: file not found: {excel_path}")
        sys.exit(1)

    file_args   = ["--file", str(excel_path)]
    folder_args = ["--output-folder", args.output_folder] if args.output_folder else []

    seg_args = []
    if args.seg_range:
        m = re.match(r"(\d+)-(\d+)", args.seg_range)
        if m:
            seg_args = [m.group(1), m.group(2)]
        else:
            print(f"WARNING: invalid --seg-range {args.seg_range!r}, ignoring.")

    output_folder = Path(args.output_folder) if args.output_folder else excel_path.parent
    print(f"Input:  {excel_path.name}")
    print(f"Output: {output_folder}")

    for label, script in [
        ("verb check",       HERE / "LLM_verb_comparison_xlsx.py"),
        ("noun check",       HERE / "LLM_noun_comparison_xlsx.py"),
        ("capability check", HERE / "LLM_capability_comparison_xlsx.py"),
    ]:
        print(f"\nStep — {label}")
        try:
            _run(script, *file_args, *folder_args, *seg_args)
        except RuntimeError as e:
            _crash(label, e)

    # Derive project_id for the glossary filename from the excel stem
    stem = excel_path.stem
    for suffix in ("_aligned", "_iptranslated", "_translated", "_checks"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    project_id = stem

    # merge_glossaries uses project_log — set context just for this one call,
    # then immediately restore it so the active project is unaffected.
    import project_log, json
    _ctx_file = Path(project_log._CTX_FILE)
    _saved = _ctx_file.read_text(encoding="utf-8") if _ctx_file.exists() else None
    try:
        print("\nStep — merge glossaries")
        project_log.set_context(project_id, output_folder)
        _run(HERE / "merge_glossaries.py", project_id)
    except RuntimeError as e:
        _crash("merge glossaries", e)
    finally:
        if _saved is not None:
            _ctx_file.write_text(_saved, encoding="utf-8")
        elif _ctx_file.exists():
            _ctx_file.unlink()

    print(f"\nDone. Results in: {output_folder}")


if __name__ == "__main__":
    main()
