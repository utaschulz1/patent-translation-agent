#!/usr/bin/env python3
"""
Cross-check a clean_glossary_<PID>.csv against a specific segment-ID range of
the bilingual _translated.xlsx, plus whatever *_canonical_glossary.csv /
*_inconsistency_table.csv / *_flags.csv frequency tables sit next to it.

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
import re
import sys

import openpyxl

WORD_CLASS = r"[A-Za-zÀ-ÿ]"


def resolve_path(path, pattern):
    if os.path.isdir(path):
        matches = sorted(glob.glob(os.path.join(path, pattern)))
        if not matches:
            sys.exit(f"No file matching {pattern!r} found in {path}")
        return matches[0]
    return path


def as_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def load_segments(xlsx_path, min_id, max_id):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    segs = []
    for r in rows:
        sid = as_int(r[0])
        if sid is None:
            continue
        if min_id is not None and sid < min_id:
            continue
        if max_id is not None and sid > max_id:
            continue
        segs.append((sid, r[1] or "", r[2] or ""))
    segs.sort(key=lambda t: t[0])
    return segs


def find_segs(term, segs, which):
    """Segment ids whose EN (which='en') or DE (which='de') text contains
    term as a whole word. Checked per-segment rather than against one
    concatenated/bracket-tagged string — patent body text routinely contains
    literal "[0042]"-style paragraph numbers, which collided with an earlier
    bracket-tag-scanning approach as soon as this ran against more than the
    claims (paragraph numbers never appear in claims text, so the bug was
    invisible until whole-document mode)."""
    if not term:
        return []
    pat = re.compile(r"(?<!" + WORD_CLASS + r")" + re.escape(term) + r"(?!" + WORD_CLASS + r")", re.IGNORECASE)
    return sorted(sid for sid, en, de in segs if pat.search(en if which == "en" else de))


CANONICAL_GLOB_SUFFIXES = ("_canonical_glossary.csv", "_inconsistency_table.csv", "_flags.csv")


def load_frequency_tables(glossary_dir):
    """Auto-discover the pipeline's raw frequency/canonical-vote CSVs
    (noun_canonical_glossary.csv, verb_canonical_glossary.csv,
    capability_canonical_glossary.csv, noun_inconsistency_table.csv,
    verb_flags.csv, capability_flags.csv, ...). Column names vary by table
    type, so this is deliberately loose: any column that looks like an EN
    key (starts with 'EN' or is literally 'Segment ID'/'EN Phrase') is
    treated as the lookup key.
    """
    tables = {}
    for path in glob.glob(os.path.join(glossary_dir, "*.csv")):
        base = os.path.basename(path)
        if not any(base.endswith(suf) for suf in CANONICAL_GLOB_SUFFIXES):
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
        except Exception as e:
            print(f"warning: failed to read {base}: {e}", file=sys.stderr)
            continue
        if not rows:
            continue
        en_col = next((c for c in reader.fieldnames if c and c.strip().lower() in
                       ("en", "en verb", "en phrase")), None)
        tables[base] = {"fieldnames": reader.fieldnames, "en_col": en_col, "rows": rows}
    return tables


def lookup_in_tables(term, tables):
    hits = {}
    for name, t in tables.items():
        if not t["en_col"]:
            continue
        matches = [r for r in t["rows"] if (r.get(t["en_col"]) or "").strip().lower() == term.strip().lower()]
        if matches:
            hits[name] = matches
    return hits


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
