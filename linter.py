"""
linter.py — Segment-level lint checks on *_revised_translation_checks.xlsx.

Reads the active project's *_revised_translation_checks.xlsx, inserts a
"Linter" column as column D (shifting Glossary Checks to column E), and
for each segment whose source starts with a leading number/marker that is
absent from the translation:
  - prepends the marker + one space to the target cell, and
  - annotates column D with what was added.

Patterns detected:
  [NNNN]     patent paragraph numbers, e.g. [0003]
  N.N        sub-numbered items, e.g. 1.2
  N.         numbered list items, e.g. 2.

Input / output: same *_revised_translation_checks.xlsx file (in-place,
collision-safe on PermissionError).
"""

import glob
import re
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, PatternFill

import project_log

HEADER_ROWS = 3

# Order matters: more specific patterns first.
_LEADING_PATTERNS = [
    re.compile(r"^\[\d+\]"),       # [0003]
    re.compile(r"^\d+\.\d+"),      # 1.2
    re.compile(r"^\d+\.(?!\d)"),   # 2.  (not followed by another digit)
]

_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")


def _leading_marker(text: str) -> str | None:
    s = text.strip()
    for pat in _LEADING_PATTERNS:
        m = pat.match(s)
        if m:
            return m.group()
    return None


# ── Locate input file ─────────────────────────────────────────────────────────

proj_dir = project_log.project_dir()

src_files = [
    f for f in glob.glob(str(proj_dir / "*_revised_translation_checks.xlsx"))
    if not Path(f).name.startswith("~$")
]
if not src_files:
    raise FileNotFoundError(f"No *_revised_translation_checks.xlsx found in {proj_dir}")

src_path = Path(src_files[0])
print(f"Input: {src_path.name}")

wb = openpyxl.load_workbook(src_path)
ws = wb.active

# ── Insert column D (idempotent: only skip if linter column already confirmed) ─

already_linted = (
    ws.cell(row=2, column=4).value == "Linter"
    and ws.cell(row=2, column=5).value == "Glossary Checks"
)

if already_linted:
    print("Linter column already present — overwriting annotations.")
    for row_num in range(HEADER_ROWS + 1, ws.max_row + 1):
        cell = ws.cell(row=row_num, column=4)
        cell.value = None
        cell.fill = PatternFill()
else:
    ws.insert_cols(4)

ws.cell(row=2, column=4).value = "Linter"
ws.column_dimensions["D"].width = 45

# ── Process data rows ─────────────────────────────────────────────────────────

annotated = 0

for row_num in range(HEADER_ROWS + 1, ws.max_row + 1):
    en_text = ws.cell(row=row_num, column=2).value
    de_cell = ws.cell(row=row_num, column=3)
    de_text = de_cell.value

    if not en_text:
        continue

    marker = _leading_marker(str(en_text))
    if marker is None:
        continue

    de_str = str(de_text).strip() if de_text else ""
    if not de_str.startswith(marker):
        # Fix: prepend marker + space to the translation
        de_cell.value = f"{marker} {de_str}"

        # Annotate column D
        lint_cell = ws.cell(row=row_num, column=4)
        lint_cell.value = f'Leading marker added: "{marker}"'
        lint_cell.alignment = Alignment(wrap_text=True)
        lint_cell.fill = _FILL
        annotated += 1

# ── Save ──────────────────────────────────────────────────────────────────────

out_path = src_path
try:
    wb.save(out_path)
except PermissionError:
    stamp = datetime.now().strftime("%H%M%S")
    out_path = src_path.parent / src_path.name.replace(".xlsx", f"_{stamp}.xlsx")
    wb.save(out_path)

print(f"Fixed and annotated {annotated} segment(s).")
print(f"Saved: {out_path}")
