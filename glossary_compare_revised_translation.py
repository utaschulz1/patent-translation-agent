"""
glossary_compare_revised_translation.py — Verb and noun glossary compliance check.

Reads the *_translated_checks.xlsx for the active project, copies ID/EN/DE
into a new revised_translation_checks.xlsx, then annotates column D with
glossary mismatches found via lookup-based lemmatization (verbs) and
truncation matching (nouns).

Annotation format in column D:
  EN found, DE absent  → "EN: {term} ({n}), DE: missing, expected: {de_term}"
  EN and DE found,
  counts differ        → "EN: {term} ({en_n}), DE: {de_term} ({de_n})"
"""

import glob
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment
import pandas as pd

import project_log

HERE = Path(__file__).parent
HEADER_ROWS = 3  # rows 1–3 are filename / column-name / language lines in the xlsx


# ── Verb lookup tables ────────────────────────────────────────────────────────

with open(HERE / "EN_verb_lemma_lookup.json", encoding="utf-8") as fh:
    en_verb_lookup: dict[str, str] = json.load(fh)

with open(HERE / "DE_verb_lemma_lookup.json", encoding="utf-8") as fh:
    de_verb_lookup: dict[str, str] = json.load(fh)


def _count_lemmas(text: str, lookup: dict[str, str]) -> dict[str, int]:
    """Return a dict of {lemma: occurrence_count} for all lookup-matched words in text."""
    counts: dict[str, int] = defaultdict(int)
    for m in re.finditer(r"\b\w+\b", text.lower()):
        lemma = lookup.get(m.group())
        if lemma:
            counts[lemma] += 1
    return dict(counts)


def _count_en_phrase(en_term: str, en_text: str) -> int:
    """Count case-insensitive whole-phrase occurrences of en_term in en_text."""
    return len(re.findall(re.escape(en_term), en_text, re.IGNORECASE))


def _count_noun_in_de(de_term: str, de_text: str, other_de_terms: list[str] | None = None) -> int:
    """Count occurrences of de_term in de_text using truncation matching.

    Skips terms shorter than 5 characters.
    Single-word: stem-matches each text token (truncate both sides to min_len - 1).
    Multi-word: truncates the full phrase by 2 chars and counts substring occurrences.

    other_de_terms: other DE glossary terms (single-word, len >= 5). Tokens that
    stem-match a longer entry in this list are excluded — they belong to that
    glossary pair, not to de_term.
    """
    if len(de_term) < 5:
        return 0

    de_lower   = de_term.lower()
    text_lower = de_text.lower()

    if " " in de_term:
        search = de_lower[:-2]
        count, start = 0, 0
        while (pos := text_lower.find(search, start)) != -1:
            count += 1
            start = pos + 1
        return count

    # Words longer than de_term drawn from other glossary DE entries (both
    # single-word entries and individual words of multi-word entries).  A token
    # that stem-matches one of these belongs to that glossary pair, not to
    # de_term.  Example: "Vorrichtungsabdeckung" is a word inside the multi-word
    # entry "dielektrische Vorrichtungsabdeckung", so it must not be counted
    # toward "Vorrichtung".
    longer_de: list[str] = []
    if other_de_terms:
        for other in other_de_terms:
            ol = other.lower()
            words = ol.split() if " " in ol else [ol]
            for w in words:
                if len(w) > len(de_lower) and len(w) >= 5:
                    longer_de.append(w)

    # Split on whitespace and strip surrounding punctuation only — hyphens are
    # preserved so that "SL-Kanals" stays as one token and matches "SL-Kanal".
    tokens = [t.strip('.,;:()[]!?"\'') for t in text_lower.split()]
    tokens = [t for t in tokens if t]

    count = 0
    for token in tokens:
        if len(token) < len(de_lower):
            continue    # token shorter than glossary term → different word, not an inflected form
        min_len = min(len(de_lower), len(token))
        if min_len < 5:
            continue
        if de_lower[: min_len - 1] == token[: min_len - 1]:
            if longer_de and len(token) > len(de_lower):
                if any(
                    len(token) >= len(ol) and token[: len(ol) - 1] == ol[: len(ol) - 1]
                    for ol in longer_de
                ):
                    continue    # token matches a longer glossary entry — skip
            count += 1
    return count


# ── Project glossary ──────────────────────────────────────────────────────────

proj_dir = project_log.project_dir()

glossary_files = [
    f for f in glob.glob(str(proj_dir / "glossary_*.csv"))
    if not any(x in f for x in ("results", "flags"))
]
if not glossary_files:
    raise FileNotFoundError(f"No glossary_*.csv found in {proj_dir}")

gloss_df = pd.read_csv(
    glossary_files[0], encoding="utf-8-sig",
    comment="#", header=0, usecols=[0, 1],
)
gloss_df.columns = ["EN", "DE"]

# Build verb-only lookup: en_lemma → de_lemma.
# Filters to entries whose EN term is a known verb; lemmatizes both sides.
glossary_verb_lookup: dict[str, str] = {}
for _, row in gloss_df.iterrows():
    en_raw = str(row["EN"]).strip().lower()
    de_raw = str(row["DE"]).strip().lower()
    if " " in de_raw:           # skip multi-word DE phrases — not in DE verb lookup
        continue
    en_lemma = en_verb_lookup.get(en_raw)
    if en_lemma is None:        # not a known verb, skip
        continue
    de_lemma = de_verb_lookup.get(de_raw, de_raw)
    glossary_verb_lookup.setdefault(en_lemma, de_lemma)

print(f"Glossary: {glossary_files[0]}")
print(f"Verb entries loaded: {len(glossary_verb_lookup)}")
for en, de in glossary_verb_lookup.items():
    print(f"  {en} → {de}")

# Build noun lookup: all non-verb entries with DE term >= 5 chars.
glossary_noun_lookup: dict[str, str] = {}  # en_phrase (lower) → de_phrase (original)
for _, row in gloss_df.iterrows():
    en_raw = str(row["EN"]).strip()
    de_raw = str(row["DE"]).strip()
    if en_verb_lookup.get(en_raw.lower()) is not None:
        continue    # verb — handled separately
    if len(de_raw) < 5:
        continue    # too short for reliable truncation matching
    glossary_noun_lookup.setdefault(en_raw.lower(), de_raw)

print(f"Noun entries loaded: {len(glossary_noun_lookup)}")
for en, de in glossary_noun_lookup.items():
    print(f"  {en} → {de}")


# ── Source xlsx ───────────────────────────────────────────────────────────────

for pattern in [
    str(proj_dir / "*_translated_checks.xlsx"),
    str(proj_dir / "*_checks.xlsx"),
    str(proj_dir / "*_translated.xlsx"),
]:
    src_files = [f for f in glob.glob(pattern) if not Path(f).name.startswith("~$")]
    if src_files:
        break

if not src_files:
    raise FileNotFoundError(f"No translated_checks xlsx found in {proj_dir}")

src_path = Path(src_files[0])
print(f"\nSource: {src_path.name}")

src_wb = openpyxl.load_workbook(src_path)
src_ws = src_wb.active


# ── Build output workbook ─────────────────────────────────────────────────────

out_wb = openpyxl.Workbook()
out_ws = out_wb.active

# Copy 3-row header, columns A–C only
for row_num in range(1, HEADER_ROWS + 1):
    for col in range(1, 4):
        out_ws.cell(row=row_num, column=col).value = src_ws.cell(row=row_num, column=col).value

out_ws.cell(row=2, column=4).value = "Glossary Checks"

out_ws.column_dimensions["B"].width = 60
out_ws.column_dimensions["C"].width = 60
out_ws.column_dimensions["D"].width = 55


# ── Process data rows ─────────────────────────────────────────────────────────

annotated = 0

for row_num in range(HEADER_ROWS + 1, src_ws.max_row + 1):
    seg_id  = src_ws.cell(row=row_num, column=1).value
    en_text = src_ws.cell(row=row_num, column=2).value
    de_text = src_ws.cell(row=row_num, column=3).value

    out_ws.cell(row=row_num, column=1).value = seg_id
    out_ws.cell(row=row_num, column=2).value = en_text
    out_ws.cell(row=row_num, column=3).value = de_text

    if not en_text or not de_text:
        continue

    en_counts = _count_lemmas(str(en_text), en_verb_lookup)
    de_counts = _count_lemmas(str(de_text), de_verb_lookup)

    notes = []

    # Verb check
    for en_lemma, en_count in sorted(en_counts.items()):
        de_lemma = glossary_verb_lookup.get(en_lemma)
        if de_lemma is None:
            continue
        de_count = de_counts.get(de_lemma, 0)
        if de_count == 0:
            notes.append(
                f"EN: {en_lemma} ({en_count}), DE: missing, expected: {de_lemma}"
            )
        elif de_count != en_count:
            notes.append(
                f"EN: {en_lemma} ({en_count}), DE: {de_lemma} ({de_count})"
            )

    # Noun check — longest-match-wins: collect all glossary phrase matches with
    # their character positions, then discard any match fully contained within
    # a longer match. This prevents "sl traffic" firing inside "lte sl traffic".
    en_text_lower = str(en_text).lower()
    all_matches: list[tuple[int, int, str]] = []
    for en_term in glossary_noun_lookup:
        for m in re.finditer(re.escape(en_term), en_text_lower):
            all_matches.append((m.start(), m.end(), en_term))

    valid_matches = [
        (s, e, t) for s, e, t in all_matches
        if not any(
            s2 <= s and e2 >= e and (s2, e2) != (s, e)
            for s2, e2, _ in all_matches
        )
    ]

    noun_en_counts: dict[str, int] = defaultdict(int)
    for _, _, en_term in valid_matches:
        noun_en_counts[en_term] += 1

    for en_term, en_count in sorted(noun_en_counts.items()):
        de_term = glossary_noun_lookup[en_term]
        de_count = _count_noun_in_de(de_term, str(de_text), list(glossary_noun_lookup.values()))
        if de_count == 0:
            notes.append(
                f"EN: {en_term} ({en_count}), DE: missing, expected: {de_term}"
            )
        elif de_count != en_count:
            notes.append(
                f"EN: {en_term} ({en_count}), DE: {de_term} ({de_count})"
            )

    if notes:
        cell = out_ws.cell(row=row_num, column=4)
        cell.value = "\n".join(notes)
        cell.alignment = Alignment(wrap_text=True)
        annotated += 1


# ── Save ──────────────────────────────────────────────────────────────────────

out_name = src_path.name.replace("_translated_checks.xlsx", "_revised_translation_checks.xlsx")
if out_name == src_path.name:          # fallback if pattern didn't match
    out_name = src_path.stem + "_revised_translation_checks.xlsx"
out_path = proj_dir / out_name
try:
    out_wb.save(out_path)
except PermissionError:
    stamp = datetime.now().strftime("%H%M%S")
    out_path = proj_dir / out_name.replace(".xlsx", f"_{stamp}.xlsx")
    out_wb.save(out_path)

print(f"\nAnnotated {annotated} segment(s).")
print(f"Saved: {out_path}")
