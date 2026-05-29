"""
consolidate_scorecards.py — Extract QA comments from all scorecard xlsx files,
consolidate into one CSV, and analyse each correction two ways:

  linter_fires  — which linter checks actually fire on the (en_source, de_translation)
                  pair (i.e. would the linter have caught this before review?)
  comment_classification — keyword scan of the reviewer's feedback comment,
                  indicating what kind of fix was needed (glossary term, linter
                  pattern, manual judgment)

Outputs (in the patent-translation-agent folder):
  scorecard_consolidated.csv   — all corrections with both analysis columns
  scorecard_log.json           — tracks which files have been processed

Re-run any time new scorecards are added; already-processed files are skipped
unless --reprocess is passed.

Usage:
  python consolidate_scorecards.py              # incremental (skip already logged)
  python consolidate_scorecards.py --reprocess  # reprocess everything
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

import openpyxl

# ── Paths ─────────────────────────────────────────────────────────────────────

from config import SCORECARD_DIR
HERE = Path(__file__).parent
CSV_OUT       = HERE / "scorecard_consolidated.csv"
LOG_FILE      = HERE / "scorecard_log.json"

CSV_COLUMNS = [
    "source_file",
    "en_source",
    "de_translation",
    "de_correction",
    "error_category",
    "severity",
    "feedback_reviewer",
    "feedback_translator",
    "linter_fires",           # actual linter output on (en_source, de_translation)
    "comment_classification", # keyword scan of reviewer comment
]


# ── Linter integration ────────────────────────────────────────────────────────

from linter import (
    GermanClaimNoArticle,
    missing_leading_number,
    different_end_punctuation,
    source_punctuation_where_none_in_target,
    target_punctuation_where_none_in_source,
    leading_trailing_spaces,
    negation_not_transferred,
    regular_space_before_unit,
    hyphen_in_number_range,
    in_response_to_mistranslated,
    plurality_not_transferred,
    beide_ambiguous,
    welche_relativpronomen,
    werden_dynamic,
    preposition_contraction,
    betraegt_stative,
    same_selbe,
    same_gleich_missing,
    comprise_umfassen,
    vielzahl_plurality,
)

# Stateless checks — called directly
_STATELESS_CHECKS = [
    missing_leading_number,
    different_end_punctuation,
    source_punctuation_where_none_in_target,
    target_punctuation_where_none_in_source,
    leading_trailing_spaces,
    negation_not_transferred,
    regular_space_before_unit,
    hyphen_in_number_range,
    in_response_to_mistranslated,
    plurality_not_transferred,
    beide_ambiguous,
    welche_relativpronomen,
    werden_dynamic,
    preposition_contraction,
    betraegt_stative,
    same_selbe,
    same_gleich_missing,
    comprise_umfassen,
    vielzahl_plurality,
]


def run_linter(en_src: str, de_trans: str) -> str:
    """Run all linter checks on one (en_source, de_translation) pair.
    Returns a semicolon-separated list of check names that fired, or '' if none.
    """
    fired: list[str] = []

    # Stateful check — fresh instance per row
    check = GermanClaimNoArticle()
    result = check(en_src, de_trans)
    if result:
        fired.append("german_claim_no_article")

    # Stateless checks
    for fn in _STATELESS_CHECKS:
        if fn(en_src, de_trans):
            fired.append(fn.__name__)

    return "; ".join(fired)


# ── Comment-based classification (keyword scan of reviewer feedback) ──────────

def _text(*parts: str | None) -> str:
    return " ".join(p.lower() for p in parts if p)


_COMMENT_RULES: list[tuple[str, list[str]]] = [
    ("linter:preposition_contraction",
     ["beim ", "im ", " vom ", " zum ", " zur ", "zusammengezogen", "kontraktionen"]),
    ("linter:betraegt_stative",
     ["beträgt", "betragen"]),
    ("linter:werden_dynamic",
     ["stative", "eventive", "passive state", "zustand", "befindet sich",
      "wird verwendet", "bestimmt wird"]),
    ("linter:welche_relativpronomen",
     ["welche", "welcher", "welches"]),
    ("linter:in_response_to_mistranslated",
     ["in reaktion", "als reaktion"]),
    ("linter:same_selbe",
     ["dieselbe", "derselbe", "dasselbe", "gleiche"]),
    ("linter:comprise_umfassen",
     ["umfassend", "umfasst", "comprising"]),
    ("linter:vielzahl_plurality",
     ["vielzahl", "plurality"]),
    ("linter:german_claim_no_article",
     ["kein artikel", "ohne artikel", "präambel", "preamble"]),
    ("linter:negation_not_transferred",
     ["negation", "nicht übertragen", "nicht fehlt", "kein fehlt"]),
    ("linter:hyphen_in_number_range",
     ["gedankenstrich", "en dash", "bindestrich", "–", "alt+0150"]),
    ("linter:regular_space_before_unit",
     ["non-breaking", "geschütztes leerzeichen", "nbsp", "alt+0160"]),
    ("glossary:apparatus/device→Einrichtung/Vorrichtung",
     ["apparatus", "einrichtung", "vorrichtung", "gerät →", "→ gerät"]),
    ("glossary:configured_to→konfiguriert_um",
     ["konfiguriert", "configured to"]),
    ("glossary:include→aufweisen/beinhalten",
     ["include", "aufweisen", "beinhalten"]),
    ("glossary:consist_of→bestehen_aus",
     ["consist of", "bestehen aus"]),
    ("glossary:said→definite_article",
     ["said", "besagte", "genannte"]),
    ("glossary:form→ausbilden/bilden",
     ["form =", "ausbilden", "bilden", "formen"]),
    ("glossary:using→mithilfe",
     ["using", "unter verwendung", "mithilfe"]),
    ("glossary:such_that→derart_dass",
     ["such that", "derart, dass"]),
    ("glossary:at_least→mindestens",
     ["at least", "mindestens", "zumindest"]),
    ("glossary:respectively→beziehungsweise",
     ["respectively", "beziehungsweise", "bzw."]),
    ("glossary:provide→bereitstellen",
     ["provide", "bereitstellen"]),
    ("glossary:method→Verfahren",
     ["method →", "verfahren →", "→ verfahren"]),
    ("glossary:acronym_in_compound",
     ["akronym", "acronym", "kompositum", "compound", "klammern"]),
    ("manual:genitive_separation",
     ["genitiv nicht trennen", "genitive nicht trennen", "genitive trennen"]),
    ("manual:word_order",
     ["wortstellung", "word order", "satzstellung", "stellung des verbs",
      "verb ans ende", "verb position"]),
    ("manual:syntax",
     ["syntax", "satzstruktur", "subordinate", "nebensatz"]),
    ("manual:terminology_research",
     ["recherche", "fachterm", "termino", "fachbegriff", "kontext"]),
]


def classify_comment(en_src: str | None, de_trans: str | None, de_corr: str | None,
                     category: str | None, feedback: str | None) -> str:
    combined = _text(en_src, de_trans, de_corr, category, feedback)
    hits = []
    for label, keywords in _COMMENT_RULES:
        if any(kw in combined for kw in keywords):
            hits.append(label)
    return "; ".join(dict.fromkeys(hits)) if hits else "manual:unclassified"


# ── File processing ───────────────────────────────────────────────────────────

def extract_rows(xlsx_path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.worksheets[1]
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # skip header
        en_src   = str(row[1]).strip() if row[1] else None
        de_trans = str(row[2]).strip() if row[2] else None
        de_corr  = str(row[3]).strip() if row[3] else None
        category = str(row[4]).strip() if row[4] else None
        severity = str(row[5]).strip() if row[5] else None
        fb_rev   = str(row[6]).strip() if row[6] else None
        fb_trans = str(row[7]).strip() if row[7] else None

        if not any([en_src, de_trans, de_corr, category, fb_rev]):
            continue
        if de_trans and de_corr and de_trans == de_corr:
            continue

        linter_result = run_linter(en_src or "", de_trans or "")
        comment_class = classify_comment(en_src, de_trans, de_corr, category, fb_rev)

        rows.append({
            "source_file":           xlsx_path.name,
            "en_source":             en_src or "",
            "de_translation":        de_trans or "",
            "de_correction":         de_corr or "",
            "error_category":        category or "",
            "severity":              severity or "",
            "feedback_reviewer":     fb_rev or "",
            "feedback_translator":   fb_trans or "",
            "linter_fires":          linter_result,
            "comment_classification": comment_class,
        })
    wb.close()
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main(reprocess: bool = False) -> None:
    log: dict[str, dict] = {}
    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text(encoding="utf-8"))

    xlsx_files = sorted(SCORECARD_DIR.glob("*.xlsx"))
    to_process = [f for f in xlsx_files if reprocess or f.name not in log]

    if not to_process:
        print("No new scorecards to process.")
        return

    existing_rows: list[dict] = []
    if CSV_OUT.exists() and not reprocess:
        with CSV_OUT.open(encoding="utf-8-sig", newline="") as fh:
            existing_rows = list(csv.DictReader(fh))

    new_rows: list[dict] = []
    for xlsx in to_process:
        print(f"Processing: {xlsx.name} … ", end="", flush=True)
        try:
            rows = extract_rows(xlsx)
            new_rows.extend(rows)
            log[xlsx.name] = {
                "analyzed": str(date.today()),
                "rows_extracted": len(rows),
            }
            print(f"{len(rows)} rows")
        except Exception as exc:
            print(f"ERROR: {exc}")
            log[xlsx.name] = {"analyzed": str(date.today()), "error": str(exc)}

    all_rows = ([] if reprocess else existing_rows) + new_rows

    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    LOG_FILE.write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nDone. {len(new_rows)} rows processed ({len(all_rows)} total).")
    print(f"CSV:  {CSV_OUT}")
    print(f"Log:  {LOG_FILE}")


if __name__ == "__main__":
    main(reprocess="--reprocess" in sys.argv)
