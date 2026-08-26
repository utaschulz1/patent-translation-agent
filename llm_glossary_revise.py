# ============================================================
# llm_glossary_revise.py
# ============================================================
# Optional second-pass LLM review of an already-cleaned project glossary
# (clean_glossary_<id>.csv), triggered on demand from the "Use LLM" button
# in the GLOSSARY_REVIEWED step of the frontend — never run automatically.
# Deliberately a plain function call, not a graph: this step has no
# multi-turn state to track, so a LangGraph agent (see glossary_agent/)
# would only add ceremony here.
#
# Grounded, single-pass consolidation+audit review (rewritten 2026-08-26
# after a real one-shot-vs-multi-node-agent comparison — see
# corrected_PRD_GLOSSARY_AGENT.md and the memory entry it links — showed a
# single well-grounded call is competitive with a 7-9-call agent pipeline
# on quality and ~3.5x cheaper). Originally this pass reviewed only three
# narrow structural patterns (ordinal duplicates, fused generic modifiers,
# verb-form rebalancing) against the already-consolidated glossary plus
# bare frequency counts, deliberately WITHOUT raw source/target sentences
# (2026-08-02 decision: "raw context risked diluting focus and adding
# echo-risk for a benefit the manual-review track record didn't support").
# That decision is superseded here: real testing showed the raw segment
# corpus, EPO title, styleguide, standard glossary, and the agent's
# learnings doc are exactly what's needed to catch fabricated entries and
# dropped-but-attested terms — the two real failure modes that testing
# found. See glossary_revise_prompt.md for the full rule set.
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

from glossary_lib.attestation import _appears_in, load_segments
from glossary_lib.csv_io import load_standard_glossary, read_epo_title

HERE = Path(__file__).parent
DEFAULT_PROMPT_PATH = HERE / "glossary_revise_prompt.md"
OVERRIDE_PROMPT_FILENAME = "glossary_revise_prompt_override.md"
STYLEGUIDE_PATH = HERE / "_styleguide.md"
LEARNINGS_PATH = HERE / "_glossary_agent_learnings.md"

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
# The implementations moved to glossary_lib/csv_io.py (PRD_glossary_agent.md
# §4, Phase 0) and are re-exported here unchanged.

from glossary_lib.csv_io import (  # noqa: E402, F401
    clean_epo_title_row,
    parse_clean_glossary,
    reassemble_glossary,
)


# ── Frequency reference data (majority-vote counts, not verdicts) ──────────

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


def load_frequency_data(proj_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (verb_frequency_data, noun_frequency_data, capability_frequency_data)
    from the canonical glossary CSVs already produced by the extraction
    pipeline — raw majority-vote observations, not verdicts (a majority can
    be systematically wrong, e.g. a repeated mistranslation)."""
    verb_data = _load_frequency_csv(proj_dir / "verb_canonical_glossary.csv", "EN Verb", "DE Verb")
    noun_data = _load_frequency_csv(proj_dir / "noun_canonical_glossary.csv", "EN Phrase", "DE Phrase")
    cap_data = _load_frequency_csv(proj_dir / "capability_canonical_glossary.csv", "EN Verb", "DE Verb")
    return verb_data, noun_data, cap_data


def _find_translated_xlsx(proj_dir: Path) -> Path | None:
    candidates = sorted(
        f for f in proj_dir.glob("*_translated.xlsx")
        if not f.name.startswith("~$") and not f.name.endswith("_checks.xlsx")
    )
    return candidates[0] if candidates else None


def load_raw_context(proj_dir: Path, project_id: str) -> dict:
    """Everything a grounded, single-pass review needs beyond the
    already-consolidated glossary: the real bilingual segment corpus (for
    attestation — the only real defense against a fabricated DE value or a
    dropped-but-attested verb), the EPO title, the styleguide, the
    project-relevant slice of the standard glossary, and this project's own
    learned rules. All read directly off disk, no LLM calls, safe to call
    unconditionally — missing files degrade to empty/blank, never an error,
    since this review pass is optional by design and must still run on a
    minimal project.
    """
    xlsx_path = _find_translated_xlsx(proj_dir)
    segments = load_segments(xlsx_path) if xlsx_path else []

    epo_en, epo_de = read_epo_title(proj_dir / f"glossary_{project_id}.csv")
    if epo_en and epo_de:
        epo_en, epo_de = clean_epo_title_row(epo_en, epo_de)

    standard = load_standard_glossary(HERE)
    source_text = " ".join(en for _, en, _ in segments).lower()
    relevant_standard = {en: de for en, de in standard.items() if _appears_in(en, source_text)}

    styleguide_text = STYLEGUIDE_PATH.read_text(encoding="utf-8") if STYLEGUIDE_PATH.exists() else ""
    learnings_text = LEARNINGS_PATH.read_text(encoding="utf-8") if LEARNINGS_PATH.exists() else ""

    return {
        "segments": [{"id": sid, "en": en, "de": de} for sid, en, de in segments],
        "epo_title": {"en": epo_en, "de": epo_de},
        "standard_glossary": [{"en": en, "de": de} for en, de in relevant_standard.items()],
        "styleguide_text": styleguide_text,
        "learnings_text": learnings_text,
    }


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
    project_id: str,
    session_id: str | None = None,
) -> str:
    """Runs the grounded consolidation+audit review and returns the revised
    glossary CSV text. Never writes to disk — the caller (the
    /glossary/llm-revise endpoint) hands the result back to the frontend for
    the user to review/edit/save, same as any other manual edit in this
    step.
    """
    epo_row, main_rows, standard_rows = parse_clean_glossary(glossary_text)
    if epo_row:
        epo_row = clean_epo_title_row(*epo_row)

    verb_freq, noun_freq, cap_freq = load_frequency_data(proj_dir)
    raw_context = load_raw_context(proj_dir, project_id)

    input_data = {
        "current_glossary": [{"en": en, "de": de} for en, de in main_rows],
        "verb_frequency_data": verb_freq,
        "noun_frequency_data": noun_freq,
        "capability_frequency_data": cap_freq,
        **raw_context,
    }
    prompt = prompt_text.replace(
        "{INPUT_JSON}", json.dumps(input_data, ensure_ascii=False, indent=2)
    )

    session_key = session_id or f"{project_id}_GlossaryLLM"

    def _call(messages: list[dict]) -> str:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=8192,
            temperature=0,
            timeout=300,
            messages=messages,
            extra_body={"session_id": session_key},
        )
        finish_reason = resp.choices[0].finish_reason
        content = (resp.choices[0].message.content or "").strip()
        if finish_reason != "stop" and not content:
            raise ValueError(
                f"LLM response was truncated (finish_reason={finish_reason!r}) before any "
                "content was produced — the glossary was left unchanged. Try again or reduce "
                "the amount of context (a smaller benchmark range/segment corpus)."
            )
        return content

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
