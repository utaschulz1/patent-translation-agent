# ============================================================
# llm_glossary_revise.py
# ============================================================
# Optional second-pass LLM review of an already-cleaned project glossary
# (clean_glossary_<id>.csv), triggered on demand from the "Use LLM" button
# in the GLOSSARY_REVIEWED step of the frontend — never run automatically.
#
# Reviews three quality patterns a human catches by eye but the first
# consolidation pass (llm_glossary_cleanup.py) doesn't specifically look
# for: ordinal-duplicate entries ("first X"/"second X") that break the
# glossary checker's contiguous-phrase matching, generic modifiers fused
# into a noun-phrase entry that lose consistency coverage for the bare
# noun elsewhere, and impractical verb-form assignments where a low-
# frequency verb got the clean German form and a high-frequency verb got
# the awkward one. See glossary_revise_prompt.md for the exact rules.
#
# The EPO title row (if present) is cleaned deterministically in Python —
# stripping the "EPO EN:"/"EPO DE:" label and any inner commas is a plain
# mechanical transform, not a judgement call, so it never goes through the
# LLM at all. The standard-glossary section (locked anchors appended at
# the end of the file) is left untouched and reattached unchanged.
#
# Public API:
#   load_prompt(proj_dir) -> (text, is_override)
#   save_prompt_override(proj_dir, text)
#   reset_prompt_override(proj_dir)
#   revise_glossary(glossary_text, prompt_text, proj_dir, client, model) -> str
# ============================================================

import csv
import io
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DEFAULT_PROMPT_PATH = HERE / "glossary_revise_prompt.md"
OVERRIDE_PROMPT_FILENAME = "glossary_revise_prompt_override.md"

SYSTEM_PROMPT = """\
You are a German patent translator specialising in EP patent claims and \
descriptions. You follow EPO translation conventions and German patent language \
standards. You produce formal, precise German suitable for legal patent documents.\
"""


# ── Prompt storage ──────────────────────────────────────────────────────────

def _override_prompt_path(proj_dir: Path) -> Path:
    return proj_dir / OVERRIDE_PROMPT_FILENAME


def load_prompt(proj_dir: Path) -> tuple[str, bool]:
    """Returns (prompt_text, is_override). Project override wins if present."""
    override_path = _override_prompt_path(proj_dir)
    if override_path.exists():
        return override_path.read_text(encoding="utf-8"), True
    return DEFAULT_PROMPT_PATH.read_text(encoding="utf-8"), False


def save_prompt_override(proj_dir: Path, text: str) -> None:
    _override_prompt_path(proj_dir).write_text(text, encoding="utf-8")


def reset_prompt_override(proj_dir: Path) -> None:
    path = _override_prompt_path(proj_dir)
    if path.exists():
        path.unlink()


# ── clean_glossary_<id>.csv parsing / reassembly ────────────────────────────
# Format written by llm_glossary_cleanup.py: header row, optional EPO title
# row, blank line, main resolved terms, blank line, appended standard terms.

def parse_clean_glossary(
    text: str,
) -> tuple[tuple[str, str] | None, list[tuple[str, str]], list[tuple[str, str]]]:
    """Split glossary CSV text into (epo_row, main_rows, standard_rows).

    epo_row is only extracted when a cell literally starts with "EPO EN:" or
    "EPO DE:" — the current on-disk format. Once cleaned (see
    clean_epo_title_row), a re-run of this parser no longer finds it, and it
    correctly becomes a normal member of main_rows from then on.
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return None, [], []
    rows = rows[1:]  # drop "EN,DE" header

    sections: list[list[list[str]]] = [[]]
    for row in rows:
        is_blank = not row or all(not c.strip() for c in row)
        if is_blank:
            if sections[-1]:
                sections.append([])
            continue
        sections[-1].append(row)
    sections = [s for s in sections if s]

    if not sections:
        return None, [], []

    epo_row: tuple[str, str] | None = None
    first = sections[0]
    if first and len(first[0]) >= 2 and (
        first[0][0].strip().upper().startswith("EPO EN:")
        or first[0][1].strip().upper().startswith("EPO DE:")
    ):
        epo_row = (first[0][0].strip(), first[0][1].strip())
        sections[0] = first[1:]
    sections = [s for s in sections if s]

    def _pairs(section: list[list[str]]) -> list[tuple[str, str]]:
        return [(r[0].strip(), r[1].strip()) for r in section if len(r) >= 2]

    main_rows = _pairs(sections[0]) if sections else []
    standard_rows = _pairs(sections[1]) if len(sections) > 1 else []
    return epo_row, main_rows, standard_rows


def clean_epo_title_row(en: str, de: str) -> tuple[str, str]:
    """Deterministic (non-LLM) cleanup: strip 'EPO EN:'/'EPO DE:' labels and
    inner commas — a plain mechanical transform, not a judgement call."""
    en = re.sub(r"^EPO\s+EN:\s*", "", en, flags=re.IGNORECASE).strip()
    de = re.sub(r"^EPO\s+DE:\s*", "", de, flags=re.IGNORECASE).strip()
    en = re.sub(r",\s*", " ", en).strip()
    de = re.sub(r",\s*", " ", de).strip()
    return en, de


def reassemble_glossary(
    epo_row: tuple[str, str] | None,
    main_rows: list[tuple[str, str]],
    standard_rows: list[tuple[str, str]],
) -> str:
    # No blank line after epo_row: once cleaned it's just a normal row (see
    # clean_epo_title_row), and a blank line here would create a false extra
    # section boundary on the *next* parse — a second "Use LLM" click would
    # then misread the rest of the glossary as the standard-vocab tail and
    # silently exclude it from review.
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["EN", "DE"])
    if epo_row:
        writer.writerow(list(epo_row))
    for en, de in main_rows:
        writer.writerow([en, de])
    if standard_rows:
        writer.writerow([])
        for en, de in standard_rows:
            writer.writerow([en, de])
    return buf.getvalue()


# ── Frequency reference data (structured counts only — no raw sentences) ────

def _load_frequency_csv(path: Path, en_col: str, de_col: str) -> list[dict]:
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return []
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "en": str(row.get(en_col, "")).strip(),
            "de": str(row.get(de_col, "")).strip(),
            "count": int(row.get("Count", 0) or 0),
            "total": int(row.get("Total EN Occurrences", 0) or 0),
        })
    return rows


def load_frequency_data(proj_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (verb_frequency_data, noun_frequency_data) from the canonical
    glossary CSVs already produced by the extraction pipeline. Structured
    counts only, by design — no source/target sentences (see conversation
    2026-08-02: raw context risked diluting focus and adding echo-risk for
    a benefit the manual-review track record didn't support)."""
    verb_data = _load_frequency_csv(proj_dir / "verb_canonical_glossary.csv", "EN Verb", "DE Verb")
    noun_data = _load_frequency_csv(proj_dir / "noun_canonical_glossary.csv", "EN Phrase", "DE Phrase")
    return verb_data, noun_data


# ── LLM call ─────────────────────────────────────────────────────────────────

def _parse_json_array_lenient(raw: str) -> list[dict]:
    fence = raw.find("```")
    if fence != -1:
        raw = raw[fence:]
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    bracket = raw.find("[")
    if bracket > 0:
        raw = raw[bracket:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _validate_rows(items: list[dict]) -> tuple[list[tuple[str, str]], list[str]]:
    """Same duplicate-detection contract as llm_glossary_cleanup.py's
    validate_result, minus the standard_glossary conflict check (not
    relevant here — this pass never touches the standard section)."""
    en_seen: dict[str, str] = {}
    de_seen: dict[str, str] = {}
    errors: list[str] = []
    clean_rows: list[tuple[str, str]] = []

    for item in items:
        en = str(item.get("en", "")).strip()
        de = str(item.get("de", "")).strip()
        if not en or not de:
            errors.append(f"Skipped empty entry: {item!r}")
            continue
        en_l, de_l = en.lower(), de.lower()

        if en_l in en_seen and en_seen[en_l].lower() == de_l:
            continue  # exact duplicate, silently dropped

        if de_l in de_seen and de_seen[de_l].lower() != en_l:
            errors.append(f'DE duplicate: "{de}" assigned to both "{de_seen[de_l]}" and "{en}"')
        else:
            de_seen[de_l] = en

        if en_l in en_seen and en_seen[en_l].lower() != de_l:
            errors.append(f'EN duplicate: "{en}" appears with both "{en_seen[en_l]}" and "{de}"')
        else:
            en_seen[en_l] = de

        clean_rows.append((en, de))

    return clean_rows, errors


def revise_glossary(
    glossary_text: str,
    prompt_text: str,
    proj_dir: Path,
    client,
    model: str,
) -> str:
    """Runs the second-pass review and returns the revised glossary CSV text.
    Never writes to disk — the caller (the /glossary/llm-revise endpoint)
    hands the result back to the frontend for the user to review/edit/save,
    same as any other manual edit in this step.
    """
    epo_row, main_rows, standard_rows = parse_clean_glossary(glossary_text)
    if epo_row:
        epo_row = clean_epo_title_row(*epo_row)

    verb_freq, noun_freq = load_frequency_data(proj_dir)

    input_data = {
        "current_glossary": [{"en": en, "de": de} for en, de in main_rows],
        "verb_frequency_data": verb_freq,
        "noun_frequency_data": noun_freq,
    }
    prompt = prompt_text.replace(
        "{INPUT_JSON}", json.dumps(input_data, ensure_ascii=False, indent=2)
    )

    def _call(messages: list[dict]) -> str:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            timeout=300,
            messages=messages,
        )
        return resp.choices[0].message.content.strip()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    raw = _call(messages)
    items = _parse_json_array_lenient(raw)
    revised_rows, errors = _validate_rows(items)

    if errors:
        error_lines = "\n".join(f"- {e}" for e in errors)
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                f"Your response contains {len(errors)} error(s):\n{error_lines}\n\n"
                "Return the complete corrected JSON array — all rows, not just the "
                "changed ones. No explanation, no prose, no markdown fences."
            )},
        ]
        raw_retry = _call(retry_messages)
        retry_items = _parse_json_array_lenient(raw_retry)
        if retry_items:
            revised_rows, errors = _validate_rows(retry_items)

    if not revised_rows:
        raise ValueError(
            "LLM response could not be parsed into any valid glossary rows "
            "— the glossary was left unchanged."
        )

    if len(revised_rows) < len(main_rows) * 0.7:
        print(
            f"[glossary-revise] WARNING: revised list has {len(revised_rows)} rows, "
            f"down from {len(main_rows)} — review carefully before saving.",
            flush=True,
        )

    return reassemble_glossary(epo_row, revised_rows, standard_rows)
