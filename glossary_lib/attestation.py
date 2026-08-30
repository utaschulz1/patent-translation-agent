"""glossary_lib.attestation — source/target attestation against real segment text.

Moved from llm_glossary_cleanup.py (_appears_in) and the glossary-range-audit
skill's audit_glossary.py (load_segments, find_segs, load_frequency_tables,
lookup_in_tables) — the skill script now imports from here, ending the
skill/production fork of the same logic.
"""

import csv
import glob
import os
import re
import sys

import openpyxl

WORD_CLASS = r"[A-Za-zÀ-ÿ]"

CANONICAL_GLOB_SUFFIXES = ("_canonical_glossary.csv", "_inconsistency_table.csv", "_flags.csv")


def _appears_in(en_term: str, text: str) -> bool:
    """Whether en_term is attested in text, tolerating common inflections.

    Catches inflected forms: "form" → "formed", "forming", "forms" — critical
    for standard_glossary terms that only appear inflected in patent source
    text (e.g. "form" never appears bare — only as "formed in the sled").
    Without this, _appears_in("form", text) returns False and the term is
    silently excluded from the clean glossary even though it is in the source.
    The explicit suffix list avoids false matches like "formal" or "former".
    """
    term_lower = en_term.lower()
    if re.search(r"\b" + re.escape(term_lower) + r"\b", text):
        return True
    if re.search(r"\b" + re.escape(term_lower) + r"(?:s|d|ed|ing|en|es)\b", text):
        return True
    if term_lower.startswith("to "):
        bare = term_lower[3:].strip()
        if bare and re.search(r"\b" + re.escape(bare) + r"\w*\b", text):
            return True
    return False


def _as_int(x):
    """int(x) or None — sheet Id cells can hold headers or blanks."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def load_segments(xlsx_path, min_id=None, max_id=None) -> list[tuple[int, str, str]]:
    """Load (id, en, de) triples from a bilingual xlsx, optionally id-filtered.

    Args:
        xlsx_path: path to a *_translated.xlsx (Id/Source/Target columns).
        min_id: first segment Id to include (inclusive), or None.
        max_id: last segment Id to include (inclusive), or None.

    Returns:
        Sorted list of (segment_id, en_text, de_text).
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    segs = []
    for r in rows:
        sid = _as_int(r[0])
        if sid is None:
            continue
        if min_id is not None and sid < min_id:
            continue
        if max_id is not None and sid > max_id:
            continue
        segs.append((sid, r[1] or "", r[2] or ""))
    segs.sort(key=lambda t: t[0])
    return segs


def find_segs(term: str, segs: list[tuple[int, str, str]], which: str) -> list[int]:
    """Segment ids whose EN (which='en') or DE (which='de') text contains
    term as a whole word.

    Checked per-segment rather than against one concatenated/bracket-tagged
    string — patent body text routinely contains literal "[0042]"-style
    paragraph numbers, which collided with an earlier bracket-tag-scanning
    approach as soon as this ran against more than the claims (paragraph
    numbers never appear in claims text, so the bug was invisible until
    whole-document mode).
    """
    if not term:
        return []
    pat = re.compile(r"(?<!" + WORD_CLASS + r")" + re.escape(term) + r"(?!" + WORD_CLASS + r")", re.IGNORECASE)
    return sorted(sid for sid, en, de in segs if pat.search(en if which == "en" else de))


def load_frequency_tables(glossary_dir: str) -> dict:
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


def lookup_in_tables(term: str, tables: dict) -> dict:
    """Rows across all frequency tables whose EN key equals term (case-insensitive)."""
    hits = {}
    for name, t in tables.items():
        if not t["en_col"]:
            continue
        matches = [r for r in t["rows"] if (r.get(t["en_col"]) or "").strip().lower() == term.strip().lower()]
        if matches:
            hits[name] = matches
    return hits
