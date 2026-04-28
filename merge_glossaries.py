"""
merge_glossaries.py  —  Append verb, noun and standard glossaries into the project glossary.

Appends all rows as-is (including frequencies and alternatives) so the result
can be reviewed and cleaned manually before use.

Columns in output:
    EN, DE, Canonical, Count, Total

Usage:
    python merge_glossaries.py <project_id>
    e.g.  python merge_glossaries.py SYITCL_2604_P0068
"""

import csv
import sys
from pathlib import Path

from project_log import project_dir

HERE = Path(__file__).parent


def _sources(proj_dir: Path) -> list[dict]:
    return [
        {
            "path": proj_dir / "verb_canonical_glossary.csv",
            "en_col": "EN Verb",
            "de_col": "DE Verb",
        },
        {
            "path": proj_dir / "noun_canonical_glossary.csv",
            "en_col": "EN Phrase",
            "de_col": "DE Phrase",
        },
        {
            "path": HERE / "standard_glossary.csv",
            "en_col": "EN",
            "de_col": "DE",
        },
    ]


OUT_HEADER = ["EN", "DE", "Canonical", "Count", "Total"]


def load_rows(source: dict) -> list[dict]:
    path = source["path"]
    if not path.exists():
        print(f"  Skipping {path.name} (not found)")
        return []
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append({
                "EN":        row.get(source["en_col"], "").strip(),
                "DE":        row.get(source["de_col"], "").strip(),
                "Canonical": row.get("Canonical", "").strip(),
                "Count":     row.get("Count", "").strip(),
                "Total":     row.get("Total EN Occurrences", "").strip(),
            })
    return rows


def main():
    if len(sys.argv) < 2:
        print("Usage: python merge_glossaries.py <project_id>")
        raise SystemExit(1)
    project_id = sys.argv[1]

    proj_dir = project_dir()
    glossary_path = proj_dir / f"glossary_{project_id}.csv"
    if not glossary_path.exists():
        print(f"Project glossary not found: {glossary_path}")
        raise SystemExit(1)

    all_rows: list[dict] = []
    for source in _sources(proj_dir):
        rows = load_rows(source)
        print(f"  {source['path'].name}: {len(rows)} row(s)")
        all_rows.extend(rows)

    with open(glossary_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_HEADER)
        writer.writerows(all_rows)

    print(f"Appended {len(all_rows)} row(s) to {glossary_path.name}")

    reminder = (
        "# CLEAN-UP: For EN multi-word terms where DE is adj.+noun "
        "(e.g. 'selective co-product' -> 'selektives Co-Produkt'), "
        "strip the EN adjective or add a bare-noun entry — "
        "glossary_compare.py only matches exact EN keys.\n"
    )
    content = glossary_path.read_text(encoding="utf-8-sig")
    glossary_path.write_text(reminder + content, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
