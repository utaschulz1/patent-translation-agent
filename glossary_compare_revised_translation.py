"""
glossary_compare_revised_translation.py — Verb and noun glossary compliance check.
No LLM used — only lookup-based lemmatization and truncation matching.

Usage: python glossary_compare_revised_translation.py [--pid <project_id>]
  --pid   project folder name under projects/; defaults to current project context

Reads the *_translated.xlsx for the active project, copies ID/EN/DE
into a new revised_translation_checks.xlsx, then annotates column D with
glossary mismatches found via lookup-based lemmatization (verbs) and
truncation matching (nouns).

Annotation format in column D:
  EN found, DE absent  → "EN: {term} ({n}), DE: missing, expected: {de_term}"
  EN and DE found,
  counts differ        → "EN: {term} ({en_n}), DE: {de_term} ({de_n})"

Constraint — source-triggered only: checks are initiated by finding a glossary
term in the EN source. A DE glossary term that appears in the target without a
corresponding EN term in the source is not detected here. Target-triggered
checks (e.g. "umfass*" without "compris*", "Vielzahl" without "plurality") are
handled by the linter instead.

Public API (importable):
  build_glossary_lookups(proj_dir) → (verb_lookup, verb_fallback, noun_lookup, all_de_noun_terms)
  check_segment_glossary(en_text, de_text, verb_lookup, noun_lookup, all_de_noun_terms, verb_fallback) → list[str]
"""

import argparse
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


_DE_ADJ_SUFFIXES = ("em", "er", "es", "en", "e")


def _count_lemmas(text: str, lookup: dict[str, str], strip_de_adj: bool = False) -> dict[str, int]:
    """Return a dict of {lemma: occurrence_count} for all lookup-matched words in text.

    strip_de_adj: when True, words not found directly are retried after stripping
    German adjective inflection endings (-e/-en/-er/-em/-es).  Enables Partizip-II
    adjective forms like "angeordnete" to match the base entry "angeordnet".
    """
    counts: dict[str, int] = defaultdict(int)
    for m in re.finditer(r"\b\w+\b", text.lower()):
        word = m.group()
        lemma = lookup.get(word)
        if lemma is None and strip_de_adj:
            for suffix in _DE_ADJ_SUFFIXES:
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    lemma = lookup.get(word[: -len(suffix)])
                    if lemma:
                        break
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
        # Stem each word by stripping known adj suffixes, then build a regex so
        # that inflected forms (e.g. "optischen" matching "optische") are found.
        de_stems: list[str] = []
        parts: list[str] = []
        for word in de_lower.split():
            stem = word
            for suffix in _DE_ADJ_SUFFIXES:
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    stem = word[: -len(suffix)]
                    break
            de_stems.append(stem)
            parts.append(re.escape(stem) + r"\w*")

        # Mask longer multi-word DE phrases that contain this phrase as a
        # component (same problem as single-word masking, but for phrases).
        # Example: "organisierte Punktwolke" inside "geglättete organisierte
        # Punktwolke" — mask the longer phrase first so findall below only
        # counts standalone occurrences.
        if other_de_terms:
            for other in other_de_terms:
                if " " not in other or len(other) <= len(de_term):
                    continue
                other_words = other.lower().split()
                other_stems = []
                for w in other_words:
                    stem = w
                    for suffix in _DE_ADJ_SUFFIXES:
                        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                            stem = w[: -len(suffix)]
                            break
                    other_stems.append(stem)
                if not all(ds in other_stems for ds in de_stems):
                    continue
                other_parts = [re.escape(s) + r"\w*" for s in other_stems]
                mask_pat = re.compile(r"\s+".join(other_parts), re.IGNORECASE)
                text_lower = mask_pat.sub(lambda m: " " * len(m.group()), text_lower)

        return len(re.findall(r"\s+".join(parts), text_lower))

    # Mask multi-word DE phrases that contain de_term as a component word.
    # Their tokens must not be counted toward the single-word entry — they
    # belong to the longer phrase pair (e.g. "visuelle Anzeige" → "visual display"
    # should not also contribute to the count for standalone "Anzeige" → "display").
    if other_de_terms:
        for other in other_de_terms:
            if " " not in other:
                continue
            other_words = other.lower().split()
            if de_lower not in other_words:
                continue
            parts = []
            for word in other_words:
                stem = word
                for suffix in _DE_ADJ_SUFFIXES:
                    if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                        stem = word[: -len(suffix)]
                        break
                parts.append(re.escape(stem) + r"\w*")
            phrase_pat = re.compile(r"\s+".join(parts), re.IGNORECASE)
            text_lower = phrase_pat.sub(lambda m: " " * len(m.group()), text_lower)

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
                # Require > 2 chars longer so German inflections (+e/+s/+en/+er/+em/+es)
                # don't suppress tokens of the same root. Only genuine compounds are
                # typically 3+ chars longer than the base term.
                if len(w) > len(de_lower) + 2 and len(w) >= 5:
                    longer_de.append(w)

    # Split on whitespace and strip surrounding punctuation only — hyphens are
    # preserved so that "SL-Kanals" stays as one token and matches "SL-Kanal".
    tokens = [t.strip('.,;:()[]!?"\'') for t in text_lower.split()]
    tokens = [t for t in tokens if t]

    count = 0
    for token in tokens:
        if len(token) < len(de_lower):
            continue    # token shorter than glossary term → different word, not an inflected form
        if len(token) > len(de_lower) + 3:
            continue    # token much longer than glossary term → German compound word, not an inflection
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


# ── Public API ────────────────────────────────────────────────────────────────

def build_glossary_lookups(proj_dir: Path) -> tuple[dict, dict, dict, list]:
    """Load the project glossary and return (verb_lookup, verb_fallback, noun_lookup, all_de_noun_terms).

    verb_lookup:      {en_lemma: de_lemma}   — full lemma-based matching
    verb_fallback:    {en_lemma: de_raw}     — word/truncation matching for verbs whose
                                               DE form is not in de_verb_lookup
    noun_lookup:      {en_phrase_lower: de_phrase_original}
    all_de_noun_terms: list of all DE values in noun_lookup (for compound masking)
    """
    glossary_files = [
        f for f in glob.glob(str(proj_dir / "clean_glossary_*.csv"))
        if not any(x in f for x in ("results", "flags"))
    ]
    if not glossary_files:
        raise FileNotFoundError(f"No clean_glossary_*.csv found in {proj_dir}")

    gloss_df = pd.read_csv(
        glossary_files[0], encoding="utf-8-sig",
        comment="#", header=0, usecols=[0, 1],
        keep_default_na=False,
    )
    gloss_df.columns = ["EN", "DE"]

    verb_lookup: dict[str, str] = {}
    verb_fallback: dict[str, str] = {}
    for _, row in gloss_df.iterrows():
        en_raw = str(row["EN"]).strip().lower()
        de_raw = str(row["DE"]).strip().lower()
        if " " in de_raw:
            continue
        en_lemma = en_verb_lookup.get(en_raw)
        if en_lemma is None:
            continue
        de_lemma = de_verb_lookup.get(de_raw)
        if de_lemma is not None:
            verb_lookup.setdefault(en_lemma, de_lemma)
        else:
            # DE form not in lemma table — fall back to truncation word matching
            # (same approach as noun checker). _count_noun_in_de's own guards
            # (token length ±3, prefix-match) keep false positives low.
            verb_fallback.setdefault(en_lemma, de_raw)

    noun_lookup: dict[str, str] = {}
    for _, row in gloss_df.iterrows():
        en_raw = str(row["EN"]).strip()
        de_raw = str(row["DE"]).strip()
        if en_verb_lookup.get(en_raw.lower()) is not None:
            continue
        if len(de_raw) < 5:
            continue
        noun_lookup.setdefault(en_raw.lower(), de_raw)

    all_de_noun_terms = list(noun_lookup.values())
    return verb_lookup, verb_fallback, noun_lookup, all_de_noun_terms


def check_segment_glossary(
    en_text: str,
    de_text: str,
    verb_lookup: dict,
    noun_lookup: dict,
    all_de_noun_terms: list[str],
    verb_fallback: dict | None = None,
) -> list[str]:
    """Run verb + noun glossary checks on a single segment. Returns list of issue strings."""
    notes: list[str] = []

    # ── Noun phrase matches (computed first so their spans can be masked from
    # verb counting — a verb used attributively inside a glossary noun phrase,
    # e.g. "selecting" in "radius selecting means", must not be counted as a
    # standalone verb action when the phrase itself is translated as a compound).
    en_text_lower = en_text.lower()
    all_matches: list[tuple[int, int, str]] = []
    for en_term in noun_lookup:
        pat = r"\b" + re.escape(en_term) + r"s?\b"
        for m in re.finditer(pat, en_text_lower):
            all_matches.append((m.start(), m.end(), en_term))

    # When two terms match the same span (e.g. "segment" and "segments" both
    # matching the token "segments" via the s? suffix), keep only the longest
    # (most specific) term so the singular doesn't produce a phantom count.
    span_best: dict[tuple[int, int], str] = {}
    for s, e, t in all_matches:
        if (s, e) not in span_best or len(t) > len(span_best[(s, e)]):
            span_best[(s, e)] = t
    all_matches = [(s, e, t) for (s, e), t in span_best.items()]

    valid_matches = [
        (s, e, t) for s, e, t in all_matches
        if not any(
            s2 <= s and e2 >= e and (s2, e2) != (s, e)
            for s2, e2, _ in all_matches
        )
    ]

    # ── Verb check — mask noun-phrase spans before counting EN verb lemmas
    masked_chars = list(en_text_lower)
    for s, e, _ in valid_matches:
        for i in range(s, e):
            masked_chars[i] = " "
    masked_en = "".join(masked_chars)

    en_counts = _count_lemmas(masked_en, en_verb_lookup)
    de_counts = _count_lemmas(de_text, de_verb_lookup, strip_de_adj=True)

    _fallback = verb_fallback or {}
    for en_lemma, en_count in sorted(en_counts.items()):
        de_lemma = verb_lookup.get(en_lemma)
        if de_lemma is not None:
            de_count = de_counts.get(de_lemma, 0)
            de_label = de_lemma
        elif en_lemma in _fallback:
            de_label = _fallback[en_lemma]
            de_count = _count_noun_in_de(de_label, de_text, all_de_noun_terms)
        else:
            continue
        print(f"[gloss-verb] '{en_lemma}'×{en_count} → '{de_label}'×{de_count}", flush=True)
        if de_count == 0:
            notes.append(f"EN: {en_lemma} ({en_count}), DE: missing, expected: {de_label}")
        elif de_count != en_count:
            notes.append(f"EN: {en_lemma} ({en_count}), DE: {de_label} ({de_count})")

    # ── Noun check
    noun_en_counts: dict[str, int] = defaultdict(int)
    for _, _, en_term in valid_matches:
        noun_en_counts[en_term] += 1

    for en_term, en_count in sorted(noun_en_counts.items()):
        de_term = noun_lookup[en_term]
        de_count = _count_noun_in_de(de_term, de_text, all_de_noun_terms)
        print(f"[gloss-noun] '{en_term}'×{en_count} → '{de_term}'×{de_count}", flush=True)
        if de_count == 0:
            notes.append(f"EN: {en_term} ({en_count}), DE: missing, expected: {de_term}")
        elif de_count != en_count:
            notes.append(f"EN: {en_term} ({en_count}), DE: {de_term} ({de_count})")

    return notes


# ── Script entry point ────────────────────────────────────────────────────────

def main() -> None:
    _parser = argparse.ArgumentParser()
    _parser.add_argument("--pid", default=None)
    args = _parser.parse_args()

    if args.pid:
        proj_dir = project_log.find_project_dir(args.pid)
    else:
        proj_dir = project_log.project_dir()

    verb_lookup, verb_fallback, noun_lookup, all_de_noun_terms = build_glossary_lookups(proj_dir)

    print(f"Glossary: {proj_dir}")
    print(f"Verb entries loaded: {len(verb_lookup)}")
    for en, de in verb_lookup.items():
        print(f"  {en} → {de}")
    print(f"Verb fallback entries: {len(verb_fallback)}")
    for en, de in verb_fallback.items():
        print(f"  {en} → {de} (word match)")
    print(f"Noun entries loaded: {len(noun_lookup)}")
    for en, de in noun_lookup.items():
        print(f"  {en} → {de}")

    for pattern in [
        str(proj_dir / "*_revised_translation_checks.xlsx"),
        str(proj_dir / "*_GERMAN_translated.xlsx"),
        str(proj_dir / "*_translated.xlsx"),
    ]:
        src_files = [f for f in glob.glob(pattern) if not Path(f).name.startswith("~$")]
        if src_files:
            break

    if not src_files:
        raise FileNotFoundError(f"No _translated.xlsx found in {proj_dir}")

    src_path = Path(src_files[0])
    print(f"\nSource: {src_path.name}")

    src_wb = openpyxl.load_workbook(src_path)
    src_ws = src_wb.active

    out_wb = openpyxl.Workbook()
    out_ws = out_wb.active

    for row_num in range(1, HEADER_ROWS + 1):
        for col in range(1, 4):
            out_ws.cell(row=row_num, column=col).value = src_ws.cell(row=row_num, column=col).value

    out_ws.cell(row=2, column=4).value = "Glossary Checks"
    out_ws.column_dimensions["B"].width = 60
    out_ws.column_dimensions["C"].width = 60
    out_ws.column_dimensions["D"].width = 55

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

        notes = check_segment_glossary(
            str(en_text), str(de_text), verb_lookup, noun_lookup, all_de_noun_terms,
            verb_fallback=verb_fallback,
        )

        if notes:
            cell = out_ws.cell(row=row_num, column=4)
            cell.value = "\n".join(notes)
            cell.alignment = Alignment(wrap_text=True)
            annotated += 1

    out_name = src_path.name.replace("_translated.xlsx", "_revised_translation_checks.xlsx")
    if out_name == src_path.name:
        out_name = src_path.stem + "_re-checked.xlsx"
    out_path = proj_dir / out_name
    try:
        out_wb.save(out_path)
    except PermissionError:
        stamp = datetime.now().strftime("%H%M%S")
        out_path = proj_dir / out_name.replace(".xlsx", f"_{stamp}.xlsx")
        out_wb.save(out_path)

    print(f"\nAnnotated {annotated} segment(s).")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
