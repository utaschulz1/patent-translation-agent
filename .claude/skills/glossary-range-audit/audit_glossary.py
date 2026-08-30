#!/usr/bin/env python3
"""
Cross-check a clean_glossary_<PID>.csv against a specific segment-ID range of
the bilingual _translated.xlsx, plus whatever *_canonical_glossary.csv /
*_inconsistency_table.csv / *_flags.csv frequency tables sit next to it.

The evidence-gathering logic (segment loading, whole-word attestation,
frequency-table cross-referencing) lives in agent/glossary_lib/attestation.py
since PRD_glossary_agent.md Phase 0 — this script is the skill's CLI wrapper
around it.

Produces two files (never prints the full corpus/report to stdout — read
them with the Read tool, per this project's convention of not reasoning over
truncated chat output):

  <outdir>/<range_label>_dump.txt     EN/DE text of the segment range, one
                                       block per segment id, for manual reading.
  <outdir>/<range_label>_audit.json   Per-glossary-row attestation report.

Usage:
  python audit_glossary.py <bilingual_xlsx> <clean_glossary_csv> \
      --min-id 369 --max-id 430 [--outdir DIR]

Both paths accept a directory instead of a file — the script will glob for
the first *_translated.xlsx / clean_glossary_*.csv it finds there.
"""
import argparse
import csv
import glob
import json
import os
import sys
from pathlib import Path

# This script lives under agent/.claude/skills/glossary-range-audit/ — put
# agent/ itself on the path so glossary_lib imports resolve when the script
# is run directly from anywhere.
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from glossary_lib.attestation import (  # noqa: E402
    find_segs,
    load_frequency_tables,
    load_segments,
    lookup_in_tables,
)


def resolve_path(path, pattern):
    """Resolve a directory argument to the first file matching pattern in it."""
    if os.path.isdir(path):
        matches = sorted(glob.glob(os.path.join(path, pattern)))
        if not matches:
            sys.exit(f"No file matching {pattern!r} found in {path}")
        return matches[0]
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="bilingual *_translated.xlsx, or a directory containing one")
    ap.add_argument("glossary", help="clean_glossary_<PID>.csv, or a directory containing one")
    ap.add_argument("--min-id", type=int, default=None, help="first segment Id to include (inclusive)")
    ap.add_argument("--max-id", type=int, default=None, help="last segment Id to include (inclusive)")
    ap.add_argument("--outdir", default=None, help="defaults to the glossary file's directory")
    args = ap.parse_args()

    xlsx_path = resolve_path(args.xlsx, "*_translated.xlsx")
    glossary_path = resolve_path(args.glossary, "clean_glossary_*.csv")
    outdir = args.outdir or os.path.dirname(os.path.abspath(glossary_path))
    if args.min_id is None and args.max_id is None:
        label = "full_document"
    else:
        label = f"seg{args.min_id or 'start'}-{args.max_id or 'end'}"

    segs = load_segments(xlsx_path, args.min_id, args.max_id)
    if not segs:
        sys.exit("No segments found in that id range — check --min-id/--max-id against the sheet's Id column.")

    dump_path = os.path.join(outdir, f"{label}_dump.txt")
    with open(dump_path, "w", encoding="utf-8") as fh:
        for sid, en, de in segs:
            fh.write(f"[{sid}] EN: {en}\n[{sid}] DE: {de}\n\n")

    with open(glossary_path, encoding="utf-8-sig") as fh:
        glossary_rows = [row for row in csv.DictReader(fh) if row.get("EN")]

    tables = load_frequency_tables(os.path.dirname(os.path.abspath(glossary_path)))

    report = []
    for row in glossary_rows:
        en, de = row["EN"], row["DE"]
        en_segs = find_segs(en, segs, "en")
        de_segs = find_segs(de, segs, "de")
        entry = {
            "en": en,
            "de": de,
            "en_attested": bool(en_segs),
            "en_segments": en_segs,
            "de_attested": bool(de_segs),
            "de_segments": de_segs,
        }
        freq_hits = lookup_in_tables(en, tables)
        if freq_hits:
            entry["frequency_table_hits"] = freq_hits
        report.append(entry)

    report_path = os.path.join(outdir, f"{label}_audit.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    neither = sum(1 for e in report if not e["en_attested"] and not e["de_attested"])
    en_only = sum(1 for e in report if e["en_attested"] and not e["de_attested"])
    both = sum(1 for e in report if e["en_attested"] and e["de_attested"])
    print(f"{len(segs)} segments in range [{args.min_id}, {args.max_id}] from {os.path.basename(xlsx_path)}")
    print(f"{len(glossary_rows)} glossary rows checked")
    print(f"  both EN+DE attested : {both}")
    print(f"  EN attested, DE not : {en_only}  <- investigate; DE value may be wrong")
    print(f"  neither attested    : {neither}  <- likely unused/standard-glossary noise, verify before dropping")
    if tables:
        print(f"cross-referenced frequency tables: {', '.join(tables)}")
    else:
        print("no *_canonical_glossary.csv / *_inconsistency_table.csv / *_flags.csv found next to the glossary")
    print(f"\nwrote {dump_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
