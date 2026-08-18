"""Dump a *_revised_translation_checks.xlsx to a JSON file for review.

Usage: python dump_checks.py <checks.xlsx> [output.json]

Writes a list of rows: {id, source, target, linter, glossary}.
Skips the title row and the ID/Source/Target/Linter/Glossary header rows.
Output defaults to <checks.xlsx>.dump.json next to the input file.
"""
import json
import sys
from pathlib import Path

import openpyxl


def dump(xlsx_path: str, out_path: str | None = None) -> str:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        id_, source, target, linter, glossary = (list(row) + [None] * 5)[:5]
        if id_ is None or not isinstance(id_, (int, float)):
            continue  # title row, header row, "EN"/"DE" subheader row
        rows.append(
            {
                "id": int(id_),
                "source": source,
                "target": target,
                "linter": linter,
                "glossary": glossary,
            }
        )

    if out_path is None:
        out_path = str(Path(xlsx_path).with_suffix("")) + ".dump.json"
    Path(out_path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    xlsx_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    written = dump(xlsx_path, out_path)
    print(f"wrote {written}")
