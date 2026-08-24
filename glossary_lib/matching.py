"""glossary_lib.matching — the production checker's matching logic.

Moved from glossary_compare_revised_translation.py: _count_lemmas,
_count_en_phrase, _count_noun_in_de, _mask_de_noun_phrases,
build_glossary_lookups, check_segment_glossary. This logic defines what a
well-formed glossary entry is in production — the glossary agent treats it as
ground truth (PRD §1).

Lemma tables are loaded through load_lemma_tables() instead of bare
module-level open() calls; the module still keeps baseline table globals so
the legacy module's import-time behavior (and every existing caller) is
unchanged.
"""

import glob
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

# agent/ — glossary_lib sits one level below the shared tables.
AGENT_DIR = Path(__file__).parent.parent

EN_BASELINE_PATH = AGENT_DIR / "EN_verb_lemma_lookup.json"
DE_BASELINE_PATH = AGENT_DIR / "DE_verb_lemma_lookup.json"

# Project-scoped overlay files (PRD §6b): live in the project's own
# pre-processing folder on the persistent volume, so lemma growth survives
# Railway deploys (which re-download agent/ fresh, wiping runtime writes to
# the baseline files) and stays scoped to the domain that produced it.
EN_OVERLAY_NAME = "EN_verb_lemma_overlay.json"
DE_OVERLAY_NAME = "DE_verb_lemma_overlay.json"

_DE_ADJ_SUFFIXES = ("em", "er", "es", "en", "e", "s")


def load_lemma_tables(proj_dir: Path | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Load the EN/DE verb lemma lookup tables: shared baseline + project overlay.

    The repo-shipped baseline tables are read-only at runtime; per-project
    additions live in overlay JSONs inside proj_dir and are merged on top
    (overlay wins on a key conflict — rare, since both sides are
    additive-only). Missing overlay files are simply skipped.

    Args:
        proj_dir: the project's pre-processing folder, or None for the
            baseline tables alone.

    Returns:
        (en_table, de_table) — surface form → infinitive lemma.
    """
    with open(EN_BASELINE_PATH, encoding="utf-8") as fh:
        en_table: dict[str, str] = json.load(fh)
    with open(DE_BASELINE_PATH, encoding="utf-8") as fh:
        de_table: dict[str, str] = json.load(fh)
    if proj_dir is not None:
        for name, table in ((EN_OVERLAY_NAME, en_table), (DE_OVERLAY_NAME, de_table)):
            overlay_path = Path(proj_dir) / name
            if overlay_path.exists():
                with open(overlay_path, encoding="utf-8") as fh:
                    table.update(json.load(fh))
    return en_table, de_table


# Baseline tables loaded once at import — same objects the legacy module
# re-exports as its own en_verb_lookup/de_verb_lookup globals.
en_verb_lookup, de_verb_lookup = load_lemma_tables()


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
                other_words = other.lower().split()
                # Compare word count, not string length: a plural/case-inflected
                # sibling entry (e.g. "diskrete Ausgangsleiter" for singular
                # "diskret Ausgangsleiter") is a few characters longer but has the
                # *same* number of stems — it is the same phrase, not a longer
                # phrase this one is embedded in. Only a genuine extra component
                # word (one more stem than de_term) qualifies for masking here.
                if len(other_words) <= len(de_stems):
                    continue
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
    # that matches one of these belongs to that glossary pair, not to
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

    def _term_matches_token(term: str, token: str) -> bool:
        """True if token is term with a short inflectional suffix, or a German
        compound with term as its final component (the semantic head — German
        compounds are head-final, so a term appearing as a compound's tail is
        "the same concept, compounded": System -> Subsystem/Speichersubsystem.
        A term appearing only as a *leading* modifier before a different head
        noun is a different, more specific concept and must not match:
        Beleuchtung ("illumination") must not match inside Beleuchtungsquelle
        ("illumination source") — Quelle, not Beleuchtung, is the head there.
        """
        idx = token.find(term)
        if idx == -1:
            return False
        # term starts the token, only a short suffix follows → plain inflection
        # (System -> Systems/Systeme; NOT Systemsteuerung, tail is too long).
        if idx == 0 and len(token) <= len(term) + 3:
            return True
        # term ends the token (allowing a short trailing inflection of the
        # compound itself, e.g. plural "-e" on "Speichersubsysteme") → term is
        # the compound's head noun.
        if idx + len(term) >= len(token) - 3:
            return True
        return False

    count = 0
    for token in tokens:
        if len(token) < len(de_lower):
            continue    # token shorter than glossary term → different word, not an inflected form
        if not _term_matches_token(de_lower, token):
            continue
        if longer_de and any(_term_matches_token(ol, token) for ol in longer_de):
            continue    # token also matches a longer, more specific glossary entry — skip
        count += 1
    return count


def _mask_de_noun_phrases(de_text: str, de_noun_terms: list[str]) -> str:
    """Blank out every occurrence of each multi-word noun-phrase glossary DE
    value in de_text, so a subsequent DE verb-lemma count doesn't also count
    it.

    Mirrors the EN-side noun-phrase masking already done in
    check_segment_glossary before EN verb counting — but that masking only
    ever touched en_text; the DE verb-lemma counter had no equivalent, so a
    Partizip-II adjective inside an already-tracked noun-phrase compound
    (e.g. "erweiterten" inside "erweiterten effektiven Anzeigebereichs")
    silently inflated the bare verb's count too ("expand" reported as
    seen 4 times in a segment where the actual verb "erweitern" occurs
    once, HALA_2608_P0655 2026-08-22). Single-word noun terms are not
    masked here — the collision this guards against is specifically a
    verb's participle surviving as the trailing adjective/head-noun word of
    a multi-word phrase; a bare single-word noun colliding with a verb
    lemma is a different, unconfirmed risk not worth the extra masking.
    """
    text_lower = de_text.lower()
    multiword_terms = [t for t in de_noun_terms if " " in t]
    # Longest (most words) first: a shorter phrase's pattern can otherwise
    # partially match the tail of a longer phrase that contains it (e.g.
    # "effektiven Anzeigebereichs" inside "erweiterten effektiven
    # Anzeigebereichs"), blanking out just that tail and leaving the longer
    # phrase's own leading word ("erweiterten") behind, unmasked, once its
    # turn comes — masking longest-first avoids that self-collision.
    multiword_terms.sort(key=lambda t: len(t.split()), reverse=True)
    for term in multiword_terms:
        parts = []
        for word in term.lower().split():
            stem = word
            for suffix in _DE_ADJ_SUFFIXES:
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    stem = word[: -len(suffix)]
                    break
            parts.append(re.escape(stem) + r"\w*")
        pat = re.compile(r"\s+".join(parts), re.IGNORECASE)
        text_lower = pat.sub(lambda m: " " * len(m.group()), text_lower)
    return text_lower


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

    en_table, de_table = load_lemma_tables(proj_dir)

    verb_lookup: dict[str, str] = {}
    verb_fallback: dict[str, str] = {}
    for _, row in gloss_df.iterrows():
        en_raw = str(row["EN"]).strip().lower()
        de_raw = str(row["DE"]).strip().lower()
        if " " in de_raw:
            continue
        en_lemma = en_table.get(en_raw)
        if en_lemma is None:
            continue
        de_lemma = de_table.get(de_raw)
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
        if en_table.get(en_raw.lower()) is not None:
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
    lemma_tables: tuple[dict, dict] | None = None,
) -> list[str]:
    """Run verb + noun glossary checks on a single segment. Returns list of issue strings.

    lemma_tables: optional (en_table, de_table) pair from load_lemma_tables —
    defaults to the shared baseline tables, preserving the historical
    behavior for callers that don't pass project-scoped tables.
    """
    en_table, de_table = lemma_tables if lemma_tables is not None else (en_verb_lookup, de_verb_lookup)
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

    en_counts = _count_lemmas(masked_en, en_table)
    masked_de_for_verbs = _mask_de_noun_phrases(de_text, all_de_noun_terms)
    de_counts = _count_lemmas(masked_de_for_verbs, de_table, strip_de_adj=True)

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
