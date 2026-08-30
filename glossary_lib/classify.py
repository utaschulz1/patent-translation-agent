"""glossary_lib.classify — deterministic term classification.

Moved from llm_glossary_cleanup.py: the ordinal-modifier machinery
(ORDINAL_MODIFIERS, _strip_de_ordinal_word, _merge_ordinal_siblings,
_is_ordinal_variant — including the 2026-08-23 ordinal-sibling merge, which
must never be reimplemented or regressed), the SHARED_DE_ALLOWED prompt note,
and the consistent/inconsistent classification loops factored into callable
functions.

This is the "cheap statistical/data layer" the PRD keeps as-is: it measures
whether the MT used a term the same way every time — it makes no correctness
judgment (that is the agent's audit stage's job).
"""

from collections import defaultdict

from glossary_lib.validate import SHARED_DE_ALLOWED  # noqa: F401 — re-exported

# Noun phrase leading words that indicate a sequential/relative variant rather
# than a distinct concept.  A phrase is only filtered when its base (remaining
# words) exists as a standalone entry, ensuring glossary coverage is never lost.
ORDINAL_MODIFIERS: frozenset[str] = frozenset({
    "first", "second", "third", "fourth", "fifth",
    "other", "additional",
})

# Expected DE stem(s) for each ORDINAL_MODIFIERS word, used only to verify a
# sibling's canonical DE actually leads with the translation we'd expect
# before stripping it — never to guess. Some EN modifiers have more than one
# acceptable DE rendering.
_EN_TO_DE_ORDINAL_STEMS: dict[str, tuple[str, ...]] = {
    "first":      ("erst",),
    "second":     ("zweit",),
    "third":      ("dritt",),
    "fourth":     ("viert",),
    "fifth":      ("fünft",),
    "other":      ("ander",),
    "additional": ("zusätzlich", "weiter"),
}

# Same adjective-declension endings glossary_lib.matching's _DE_ADJ_SUFFIXES
# strips at check time — kept as a separate local constant rather than
# imported, since this is a small, self-contained concern.
_DE_ADJ_ENDINGS: tuple[str, ...] = ("em", "er", "es", "en", "e")


def _shared_de_note() -> str:
    """Render SHARED_DE_ALLOWED into prompt text so the LLM is actually told
    about these sanctioned overlaps, instead of only validate_result()
    tolerating them after the fact. Without this, the LLM — repeatedly
    instructed elsewhere in the prompt never to let two EN terms share a DE
    value — has no way to know these specific pairs are fine, and "resolves"
    the apparent conflict itself by inventing a wrong alternative DE for one
    of the two (e.g. "have" → "besitzen" instead of "aufweisen", found live
    on FRKE_2608_P0736, 2026-08-22)."""
    if not SHARED_DE_ALLOWED:
        return ""
    lines = "\n".join(
        f"  - {' / '.join(sorted(pair))}"
        for pair in sorted(SHARED_DE_ALLOWED, key=lambda p: sorted(p))
    )
    return (
        "The following EN term groups are expected to legitimately share one "
        "DE term — this is standard EPO practice, not a conflict. Do NOT "
        "invent a different DE value for one of them to avoid the overlap:\n"
        f"{lines}"
    )


def _strip_de_ordinal_word(de_value: str, en_modifier: str) -> str | None:
    """If de_value's leading word is a (possibly declined) form of the DE
    word expected for en_modifier, return the remainder of de_value.
    Otherwise None — a modifier that isn't actually translated as expected
    means we don't know enough to strip it safely, so this never guesses."""
    stems = _EN_TO_DE_ORDINAL_STEMS.get(en_modifier)
    if not stems:
        return None
    parts = de_value.split(None, 1)
    if len(parts) != 2:
        return None
    first_word, remainder = parts[0].lower(), parts[1]
    for stem in stems:
        if first_word == stem or any(first_word == stem + suf for suf in _DE_ADJ_ENDINGS):
            return remainder
    return None


def _merge_ordinal_siblings(
    noun_can: dict[str, dict[str, dict]],
) -> tuple[dict[str, str], set[str]]:
    """Collapse ordinal-modifier siblings of the same base noun phrase (e.g.
    "first image data" / "second image data") into one bare-base entry when
    they agree on the underlying DE term once each one's own ordinal word is
    stripped — a purely mechanical merge, no LLM judgment needed (matches
    the glossary-range-audit skill's Step 4 ordinal-collapse rule).

    Complements, rather than replaces, _is_ordinal_variant(): that function
    only fires when the bare base is *also* independently attested somewhere
    in the raw extraction, which never happens for a concept that only ever
    occurs modified (HALA_2608_P0655, 2026-08-23: "image data" never occurs
    unmodified — only as first/second/input/output/intermediate image data —
    so first/second image data survived as fully separate entries). This
    compares ordinal siblings to *each other* instead, so no third,
    independently-attested occurrence is required.

    Any mismatch — an unexpected leading DE word, or siblings that strip to
    different remainders — bails out for that whole group rather than
    guessing, leaving the phrases to go through normal classification
    unchanged.
    """
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)  # base -> [(modifier, en_phrase)]
    for en_phrase in noun_can:
        words = en_phrase.split()
        if len(words) < 2 or words[0] not in ORDINAL_MODIFIERS:
            continue
        base = " ".join(words[1:])
        groups[base].append((words[0], en_phrase))

    merged_bases: dict[str, str] = {}
    consumed: set[str] = set()

    for base, members in groups.items():
        if len(members) < 2:
            continue
        stripped: dict[str, str] = {}
        ok = True
        for modifier, en_phrase in members:
            de_map = noun_can[en_phrase]
            canonical_de = max(de_map.items(), key=lambda kv: kv[1]["count"])[0]
            remainder = _strip_de_ordinal_word(canonical_de, modifier)
            if remainder is None:
                ok = False
                break
            stripped[en_phrase] = remainder
        if not ok:
            continue
        remainders = set(stripped.values())
        if len(remainders) != 1:
            continue
        merged_bases[base] = next(iter(remainders))
        consumed.update(en_phrase for _, en_phrase in members)

    return merged_bases, consumed


def _is_ordinal_variant(en_phrase: str, known_phrases: set[str]) -> bool:
    """Return True if en_phrase starts with an ordinal/relative modifier AND
    its base phrase (modifier removed) exists as a standalone entry.
    Only filter when the base is present so glossary coverage is never lost."""
    words = en_phrase.split()
    if len(words) < 2 or words[0] not in ORDINAL_MODIFIERS:
        return False
    base = " ".join(words[1:])
    return base in known_phrases


def classify_pairs(
    groups: dict[str, dict[str, list[dict]]],
    max_instances: int = 1,
) -> tuple[dict[str, str], list[dict]]:
    """Classify verb/capability pair groups as consistent vs inconsistent.

    A group with exactly one observed DE form is consistent; anything else
    becomes an inconsistent entry carrying up to max_instances example
    source/target sentences per DE form (the shape llm_glossary_cleanup.py's
    prompt consumes).

    Args:
        groups: {en_lower: {de: [{"source": ..., "target": ...}, ...]}}.
        max_instances: examples per (en, de) pair to carry into the entry.

    Returns:
        (consistent {en: de}, inconsistent [{"en": ..., "instances": [...]}]).
    """
    consistent: dict[str, str] = {}
    inconsistent: list[dict] = []
    for en, de_dict in sorted(groups.items()):
        if len(de_dict) == 1:
            consistent[en] = next(iter(de_dict))
        else:
            instances = []
            for de, examples in de_dict.items():
                for ex in examples[:max_instances]:
                    instances.append({"de": de, "source": ex["source"], "target": ex["target"]})
            inconsistent.append({"en": en, "instances": instances})
    return consistent, inconsistent


def classify_nouns(
    noun_can: dict[str, dict[str, dict]],
    noun_deviations: dict[str, list[dict]],
) -> tuple[dict[str, str], list[dict], dict[str, str]]:
    """Classify noun phrases as consistent vs inconsistent, with ordinal
    handling applied first (merge siblings, filter redundant variants).

    Shortest phrase first so base terms are resolved before the compounds
    that contain them — the LLM prompt relies on that ordering.

    Args:
        noun_can: {en_lower: {de: {"count": N, "total": N, "canonical": bool}}}.
        noun_deviations: {en_lower: [{"de": ..., "source": ..., "target": ...}]}.

    Returns:
        (consistent_nouns {en: de},
         inconsistent_nouns [{"en", "canonical_de", "canonical_count",
                              "total", "deviations"}],
         merged_bases {base_en: de} — ordinal-sibling merges applied, already
         folded into consistent_nouns for bases not independently present).
    """
    consistent_nouns: dict[str, str] = {}
    inconsistent_nouns: list[dict] = []

    _noun_phrases = set(noun_can.keys())

    merged_bases, consumed_by_merge = _merge_ordinal_siblings(noun_can)
    for base, de in merged_bases.items():
        if base not in noun_can:
            consistent_nouns.setdefault(base, de)

    for en_phrase in sorted(noun_can.keys(), key=len):
        if en_phrase in consumed_by_merge:
            continue
        if _is_ordinal_variant(en_phrase, _noun_phrases):
            continue
        de_map         = noun_can[en_phrase]
        has_deviations = en_phrase in noun_deviations

        # Consistent: single DE form, count == total, no deviations recorded
        if not has_deviations and len(de_map) == 1:
            de_info = next(iter(de_map.values()))
            if de_info["count"] == de_info["total"]:
                consistent_nouns[en_phrase] = next(iter(de_map))
                continue

        # Inconsistent — find canonical (majority) entry
        canonical_de, canonical_info = max(
            de_map.items(), key=lambda kv: kv[1]["count"]
        )

        deviations = [
            d for d in noun_deviations.get(en_phrase, [])
            if d["de"] != canonical_de
        ]

        inconsistent_nouns.append({
            "en":              en_phrase,
            "canonical_de":    canonical_de,
            "canonical_count": canonical_info["count"],
            "total":           canonical_info["total"],
            "deviations":      deviations,
        })

    return consistent_nouns, inconsistent_nouns, merged_bases
