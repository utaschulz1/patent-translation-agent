"""glossary_lib.csv_io — clean_glossary_<PID>.csv reading, writing, and the
EPO-title row conventions.

Moved from llm_glossary_revise.py (parse_clean_glossary, clean_epo_title_row,
reassemble_glossary) plus write_clean_glossary extracted from
llm_glossary_cleanup.clean_glossary()'s write block and read_epo_title from
its title scan.

File convention (fixed contract, PRD §6): utf-8-sig BOM, literal EN,DE header,
plain comma-separated; sections separated by blank lines: optional EPO-title
row, project terms, appended standard terms.
"""

import csv
import io
import re
from pathlib import Path


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
    """Render (epo_row, main_rows, standard_rows) back into glossary CSV text.

    No blank line after epo_row: once cleaned it's just a normal row (see
    clean_epo_title_row), and a blank line here would create a false extra
    section boundary on the *next* parse — a second parse would then misread
    the rest of the glossary as the standard-vocab tail.
    """
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


def load_standard_glossary(agent_dir: Path) -> dict[str, str]:
    """Read the FULL standard_glossary.csv, unfiltered by source relevance.

    Distinct from llm_glossary_cleanup.load_cleanup_inputs's relevant_standard
    (which is already filtered to terms attested somewhere in the project's
    source text) — callers that need to classify a term as "is this a
    standard-glossary term at all" (e.g. the C15 unattested-row classifier)
    need the unfiltered file, not the per-project subset.

    Returns:
        {en_lower: de} — empty dict if the file is missing.
    """
    path = agent_dir / "standard_glossary.csv"
    standard: dict[str, str] = {}
    if not path.exists():
        return standard
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                en, de = row[0].strip(), row[1].strip()
                if en and de:
                    standard[en.lower()] = de
    return standard


def filter_relevant_standard(standard: dict[str, str], source_text: str) -> dict[str, str]:
    """Filter a full standard-glossary dict (as returned by load_standard_glossary)
    down to only the terms attested in source_text (already lowercased).

    Shared by llm_glossary_cleanup.py and llm_glossary_revise.py so the
    attestation-filter semantics — including inflection tolerance — live in
    exactly one place instead of being forked per call site.
    """
    from glossary_lib.attestation import _appears_in

    return {en: de for en, de in standard.items() if _appears_in(en, source_text)}


def read_epo_title(glossary_path: Path) -> tuple[str, str]:
    """Read the EPO title from a glossary_<PID>.csv's labeled row.

    The title lives as an "EPO EN:"/"EPO DE:" prefixed row (merge_glossaries
    convention). Returns ("", "") when the file or row is absent — a missing
    title is a reportable condition, never an error, and must never be
    invented (glossary-range-audit SKILL.md Step 1b).
    """
    epo_en, epo_de = "", ""
    if glossary_path.exists():
        with open(glossary_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                cells = [c.strip() for c in row]
                if any(c.upper().startswith("EPO EN:") or c.upper().startswith("EPO DE:") for c in cells):
                    for c in cells:
                        if c.upper().startswith("EPO EN:"):
                            epo_en = c[7:].strip()
                        elif c.upper().startswith("EPO DE:"):
                            epo_de = c[7:].strip()
                    break
    return epo_en, epo_de


def write_clean_glossary(
    path: Path,
    epo_row: tuple[str, str] | None,
    rows: list[tuple[str, str]],
    standard_rows: list[tuple[str, str]],
    labeled_title: bool = True,
) -> None:
    """Write a clean_glossary_<PID>.csv in the exact downstream contract.

    Args:
        path: output CSV path.
        epo_row: (en, de) title pair, or None to omit the title row.
        rows: the resolved project term pairs.
        standard_rows: relevant standard-glossary pairs to append as the
            final section.
        labeled_title: True writes the legacy "EPO EN: ..."/"EPO DE: ..."
            labeled row followed by a blank line (llm_glossary_cleanup.py's
            historical format); False writes the already-cleaned title as a
            normal first data row with no trailing blank line (the agent's
            output contract, PRD §6 — pass the pair through
            clean_epo_title_row first).
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["EN", "DE"])
        if epo_row and epo_row[0] and epo_row[1]:
            if labeled_title:
                writer.writerow([f"EPO EN: {epo_row[0]}", f"EPO DE: {epo_row[1]}"])
                writer.writerow([])
            else:
                writer.writerow([epo_row[0], epo_row[1]])
        elif labeled_title:
            writer.writerow([])
        for en, de in rows:
            writer.writerow([en, de])
        if standard_rows:
            writer.writerow([])
            for en, de in standard_rows:
                writer.writerow([en, de])
