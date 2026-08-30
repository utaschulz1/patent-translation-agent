"""glossary_lib.validate — LLM-response parsing and glossary-row validation.

Moved from llm_glossary_cleanup.py (parse_response, validate_result, _norm_en)
and verb_lemma_sync.py (parse_json_object_lenient), plus the shared
parse_json_lenient used by the glossary agent's LLM nodes (PRD §8: bounded
trailing-comma repair before giving up).
"""

import json
import re

# EN pairs that legitimately share the same DE in German patent language.
# "have" and "having" both → "aufweisen" is standard EPO practice.
# Lives here (not classify.py) because validate_result consumes it; classify.py
# re-exports it for prompt-building via _shared_de_note.
SHARED_DE_ALLOWED: set[frozenset] = {
    frozenset({"have",    "having"}),
    frozenset({"comprise", "comprising"}),
}


def parse_response(raw: str) -> list[dict]:
    """Parse an LLM's JSON-array response, tolerant of markdown fences and
    leading prose. Raises ValueError when no JSON array can be recovered."""
    # Strip markdown fence wherever it appears (LLM sometimes adds prose before it)
    fence = raw.find("```")
    if fence != -1:
        raw = raw[fence:]
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # Fallback: find the JSON array start in case there is still leading prose
    bracket = raw.find("[")
    if bracket > 0:
        raw = raw[bracket:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse LLM response as JSON: {e}\n"
            f"Raw response (first 600 chars):\n{raw[:600]}"
        ) from e
    if not isinstance(parsed, list):
        raise ValueError("LLM response is not a JSON array.")
    return parsed


def parse_json_object_lenient(raw: str) -> dict:
    """Parse an LLM's JSON-object response, tolerant of markdown fences.

    Returns {} on any failure instead of raising — callers treat this as a
    non-fatal "nothing to add", never as a reason to abort a larger pipeline.
    """
    fence = raw.find("```")
    if fence != -1:
        raw = raw[fence:]
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    brace = raw.find("{")
    if brace > 0:
        raw = raw[brace:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def parse_json_lenient(raw: str, expect: type = list):
    """Parse an LLM response as JSON with fence stripping, leading-prose
    skipping, and a trailing-comma repair pass.

    The trailing-comma glitch (",}" / ",]") is a real, twice-observed LLM
    formatting failure from the review agent's production use — repairing it
    here is cheaper and more reliable than re-prompting for it.

    Args:
        raw: the model's response content.
        expect: `list` or `dict` — the JSON container type required.

    Returns:
        The parsed value.

    Raises:
        ValueError: if no JSON of the expected type can be recovered even
            after repair. The message carries a 600-char excerpt for the
            error report.
    """
    text = raw.strip()
    fence = text.find("```")
    if fence != -1:
        text = text[fence:]
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    opener = "[" if expect is list else "{"
    start = text.find(opener)
    if start > 0:
        text = text[start:]
    for candidate in (text, _TRAILING_COMMA_RE.sub(r"\1", text)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, expect):
            return parsed
    raise ValueError(
        f"Could not parse LLM response as JSON {expect.__name__}.\n"
        f"Raw response (first 600 chars):\n{raw[:600]}"
    )


def validate_result(
    items: list[dict], relevant_standard: dict[str, str]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Validate consolidated glossary rows for EN/DE uniqueness and
    standard-glossary conformance.

    Returns (clean_rows, errors). errors is empty iff the result is valid.
    """
    de_seen:    dict[str, str]        = {}
    en_seen:    dict[str, str]        = {}
    errors:     list[str]             = []
    clean_rows: list[tuple[str, str]] = []

    for item in items:
        en = str(item.get("en", "")).strip()
        de = str(item.get("de", "")).strip()
        if not en or not de:
            errors.append(f"Skipped empty entry: {item!r}")
            continue
        de_lower = de.lower()
        en_lower = en.lower()

        # Skip exact duplicates (same EN and same DE already seen) silently.
        if en_lower in en_seen and en_seen[en_lower].lower() == de_lower:
            continue

        if de_lower in de_seen:
            pair = frozenset({de_seen[de_lower].lower(), en_lower})
            if pair not in SHARED_DE_ALLOWED:
                errors.append(
                    f'DE duplicate: "{de}" assigned to both "{de_seen[de_lower]}" and "{en}"'
                )
        else:
            de_seen[de_lower] = en

        if en_lower in en_seen:
            if en_seen[en_lower].lower() != de_lower:
                errors.append(
                    f'EN duplicate: "{en}" appears with both "{en_seen[en_lower]}" and "{de}"'
                )
        else:
            en_seen[en_lower] = de

        if en_lower in relevant_standard:
            expected = relevant_standard[en_lower]
            if expected.lower() != de_lower:
                errors.append(
                    f'Standard glossary conflict: "{en}" → "{de}" '
                    f'(standard requires "{expected}")'
                )

        clean_rows.append((en, de))

    return clean_rows, errors


def _norm_en(en: str) -> str:
    """Normalize an EN key for duplicate detection across spaCy hyphen
    artefacts ("computer - implement" vs "computer-implement")."""
    return re.sub(r"\s*-\s*", "-", en.lower())
