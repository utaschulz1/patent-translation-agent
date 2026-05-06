"""
linter.py — Segment-level lint checks on *_revised_translation_checks.xlsx.

Reads the active project's *_revised_translation_checks.xlsx, inserts a
"Linter" column as column D (shifting Glossary Checks to column E), and
annotates each segment with any issues found.

Checks:
  german_claim_no_article             — German article (Der/Die/Das/Ein/Eine) at start of claim text
  missing_leading_number              — leading [NNNN] / N.N / N. present in source but absent in target
  different_end_punctuation           — source and target end with different punctuation characters
  source_punctuation_where_none_in_target — source ends with punctuation but target ends with letter/digit
  target_punctuation_where_none_in_source — target ends with punctuation but source ends with letter/digit
  leading_trailing_spaces             — leading or trailing whitespace in the target cell value
  negation_not_transferred            — "not"/"no"/"none" in source but "nicht"/"kein" absent from target
  regular_space_before_unit           — regular space between number and unit should be non-breaking space (Alt+0160)
  hyphen_in_number_range              — hyphen between digits in target should be en dash (Alt+0150)
  in_response_to_mistranslated        — "in Reaktion" in target when source has "in response to" (→ "als Reaktion auf")
  plurality_not_transferred           — "plurality" count in source must match "Vielzahl" count in target
  beide_ambiguous                     — "beide*" in target flagged as ambiguous (zwei / either / both)
  preposition_contraction             — German im/vom/am/beim/zum/zur contractions in target

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
_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")


# ── Checks ────────────────────────────────────────────────────────────────────
# Each check is a function (source: str, target: str) -> str | None.
# Return an annotation string when an issue is found, None otherwise.

_LEADING_PATTERNS = [          # order matters: more specific first
    re.compile(r"^\[\d+\]"),   # [0003]
    re.compile(r"^\d+\.\d+"),  # 1.2
    re.compile(r"^\d+\.(?!\d)"),  # 2.  (not followed by another digit)
]

_TRAILING_PUNCT_RE        = re.compile(r"[^\w\s]$")  # last non-word, non-space char
_TRAILING_LETTERDIGIT_RE  = re.compile(r"\w$")        # last letter or digit (no trailing punct)

_PRP_CONTRACTIONS = ["im", "vom", "am", "beim", "zum", "zur"]
_PRP_EXCEPTIONS   = ["im Wesentlichen", "zur Verwendung", "zum Beispiel"]

_NEG_SOURCE_RE  = re.compile(r"\b(not|no|none)\b", re.IGNORECASE)
_BEIDE_RE           = re.compile(r"\bbeid[e]\w*\b", re.IGNORECASE)  # beide/beiden/beides/beider/beidem
_PLURALITY_SRC_RE   = re.compile(r"\bpluralit\w*\b", re.IGNORECASE)
_PLURALITY_TGT_RE   = re.compile(r"\bVielzahl\b", re.IGNORECASE)
_IN_RESPONSE_TO_RE  = re.compile(r"\bin response to\b", re.IGNORECASE)
_IN_REAKTION_RE     = re.compile(r"\bin Reaktion\b", re.IGNORECASE)
_RANGE_HYPHEN_RE    = re.compile(r"\d\s*-\s*\d")  # digit-hyphen-digit, with optional spaces

_UNIT_LIST = sorted([
    # Temperature
    "°C", "°F",
    # Frequency
    "THz", "GHz", "MHz", "kHz", "Hz",
    # Pressure
    "GPa", "MPa", "kPa", "mbar", "bar", "Pa",
    # Resistance
    "MΩ", "kΩ", "Ω",
    # Power
    "GW", "MW", "kW", "mW", "W",
    # Voltage
    "MV", "kV", "mV", "V",
    # Current
    "kA", "mA", "μA", "nA", "A",
    # Capacitance
    "mF", "μF", "nF", "pF", "F",
    # Inductance
    "mH", "μH", "nH", "H",
    # Energy
    "GJ", "MJ", "kJ", "mJ", "J", "MeV", "keV", "eV",
    # Time
    "min", "ms", "μs", "ns", "ps", "s", "h",
    # Length
    "km", "cm", "mm", "μm", "nm", "pm", "m",
    # Mass
    "kg", "mg", "μg", "ng", "g", "t",
    # Volume
    "mL", "μL", "ml", "μl", "L", "l",
    # Sound level
    "dBm", "dB",
    # Amount of substance
    "mmol", "μmol", "nmol", "mol",
    # Concentration
    "ppm", "ppb", "wt%", "vol%",
    # Rotation / data
    "rpm", "Gbit/s", "Mbit/s", "kbit/s",
    # Force
    "kN", "mN", "N",
    # Temperature / angle / percent
    "K", "%", "°",
], key=len, reverse=True)  # longest first so alternation matches greedily

_REGULAR_SPACE_UNIT_RE = re.compile(
    r"\d (?:" + "|".join(re.escape(u) for u in _UNIT_LIST) + r")(?!\w)"
)
_NEG_TARGET_RE  = re.compile(r"\b(nicht|kein)", re.IGNORECASE)  # catches kein/keine/keinen/…

_CLAIM_MARKER_RE    = re.compile(r"^\d+\.(?!\d)\s*$")   # standalone "1."  (no following text)
_CLAIM_WITH_TEXT_RE = re.compile(r"^\d+\.(?!\d)\s+\S")  # "1. The device…"
_CLAIM_STRIP_RE     = re.compile(r"^\d+\.(?!\d)\s*")    # strip leading "1. " from target
_GERMAN_ARTICLE_RE  = re.compile(r"^(Der|Die|Das|Ein|Eine)\b", re.IGNORECASE)

_PRP_EXCEPTION_RES    = [re.compile(re.escape(e), re.IGNORECASE) for e in _PRP_EXCEPTIONS]
_PRP_CONTRACTION_RES  = {
    w: re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
    for w in _PRP_CONTRACTIONS
}


class GermanClaimNoArticle:
    """Flag a German article at the start of claim text.

    Fires for two segment types:
      • source starts with "N. some text"  (self-contained claim line)
      • source is preceded by a standalone claim marker "N." in the previous row

    State is carried across calls, so the singleton in CHECKS sees rows in order.
    Tests should create a fresh instance (GermanClaimNoArticle()) per test case.
    """

    def __init__(self) -> None:
        self._prev_was_marker = False

    def __call__(self, source: str, target: str) -> str | None:
        is_marker        = bool(_CLAIM_MARKER_RE.match(source))
        is_claim_segment = bool(_CLAIM_WITH_TEXT_RE.match(source)) or self._prev_was_marker
        self._prev_was_marker = is_marker

        if not is_claim_segment:
            return None

        tgt = target.strip()
        tgt_text = _CLAIM_STRIP_RE.sub("", tgt)  # remove leading "1. " if present
        m = _GERMAN_ARTICLE_RE.match(tgt_text)
        if m:
            return f'error: German claims must not start with article ("{m.group(1)}" found)'
        return None


german_claim_no_article = GermanClaimNoArticle()


def missing_leading_number(source: str, target: str) -> str | None:
    """Flag when a leading number or marker present in source is absent from target."""
    for pat in _LEADING_PATTERNS:
        m = pat.match(source.strip())
        if m:
            marker = m.group()
            if not target.strip().startswith(marker):
                return f"missing leading number: {marker} found in source but not in target"
    return None


def different_end_punctuation(source: str, target: str) -> str | None:
    """Flag when source and target end with different punctuation characters."""
    src_match = _TRAILING_PUNCT_RE.search(source.strip())
    if src_match is None:
        return None
    src_punct = src_match.group()
    tgt_match = _TRAILING_PUNCT_RE.search(target.strip())
    tgt_punct = tgt_match.group() if tgt_match else "(none)"
    if src_punct != tgt_punct:
        return f'error: different end punctuation: "{src_punct}" found in source but "{tgt_punct}" found in target'
    return None


def source_punctuation_where_none_in_target(source: str, target: str) -> str | None:
    """Flag when source ends with punctuation but target ends with a letter or digit."""
    src_match = _TRAILING_PUNCT_RE.search(source)
    if src_match is None:
        return None
    if _TRAILING_LETTERDIGIT_RE.search(target.strip()):
        return f'error: source end punctuation where none in target: "{src_match.group()}" missing in target'
    return None


def target_punctuation_where_none_in_source(source: str, target: str) -> str | None:
    """Flag when target ends with punctuation but source ends with a letter or digit."""
    if not _TRAILING_LETTERDIGIT_RE.search(source):
        return None
    tgt_match = _TRAILING_PUNCT_RE.search(target.strip())
    if tgt_match:
        return f'error: target punctuation where none in source: "{tgt_match.group()}" added in target'
    return None


def negation_not_transferred(source: str, target: str) -> str | None:
    """Flag when 'not'/'no'/'none' count in source exceeds 'nicht'/'kein' count in target."""
    src_count = len(_NEG_SOURCE_RE.findall(source))
    if src_count == 0:
        return None
    tgt_count = len(_NEG_TARGET_RE.findall(target))
    if tgt_count < src_count:
        tgt_info = f'only {tgt_count}x "nicht"/"kein"' if tgt_count > 0 else '"nicht"/"kein" not found'
        return f'error: {src_count}x "not"/"no" in source but {tgt_info} in target'
    return None


def leading_trailing_spaces(_: str, target: str) -> str | None:
    """Flag leading or trailing whitespace in the target cell value."""
    stripped = target.strip()
    if target == stripped:
        return None
    parts = []
    if target != target.lstrip():
        parts.append("leading")
    if target != target.rstrip():
        parts.append("trailing")
    return f"error: {' and '.join(parts)} spaces in target"


def regular_space_before_unit(_: str, target: str) -> str | None:
    """Flag a regular space between a number and a unit; should be non-breaking space (U+00A0)."""
    if _REGULAR_SPACE_UNIT_RE.search(target):
        return "error: use non-breaking space (Alt+0160) between number and unit, not regular space"
    return None


def hyphen_in_number_range(_: str, target: str) -> str | None:
    """Flag a hyphen used between digits in target; number ranges require an en dash (–)."""
    if _RANGE_HYPHEN_RE.search(target):
        return 'error: use em dash (Alt+0150) for ranges, not hyphen'
    return None


def in_response_to_mistranslated(source: str, target: str) -> str | None:
    """Flag 'in Reaktion' in target when source contains 'in response to'."""
    if not _IN_RESPONSE_TO_RE.search(source):
        return None
    if _IN_REAKTION_RE.search(target):
        return 'error: "in response to" > "als Reaktion auf" (not "in Reaktion")'
    return None


def plurality_not_transferred(source: str, target: str) -> str | None:
    """Flag when 'plurality' count in source exceeds 'Vielzahl' count in target."""
    src_count = len(_PLURALITY_SRC_RE.findall(source))
    if src_count == 0:
        return None
    tgt_count = len(_PLURALITY_TGT_RE.findall(target))
    if tgt_count < src_count:
        tgt_info = f'only {tgt_count}x "Vielzahl"' if tgt_count > 0 else '"Vielzahl" not found'
        return f'error: {src_count}x "plurality" in source but {tgt_info} in target'
    return None


def beide_ambiguous(_: str, target: str) -> str | None:
    """Flag 'beide*' in target as potentially ambiguous."""
    m = _BEIDE_RE.search(target)
    if m:
        return f'error: "{m.group()}" in target — beide = zwei | einer von (either) | sowohl als auch (both the X and Y)'
    return None


def preposition_contraction(_: str, target: str) -> str | None:
    """Flag German preposition+article contractions (im/vom/am/beim/zum/zur) in target."""
    text = target.strip()
    for exc_re in _PRP_EXCEPTION_RES:
        text = exc_re.sub("", text)
    found = [w for w, pat in _PRP_CONTRACTION_RES.items() if pat.search(text)]
    if found:
        joined = ", ".join(f'"{w}"' for w in found)
        return f"error: Prp + article contraction {joined} used in target"
    return None


CHECKS = [
    german_claim_no_article,
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
    preposition_contraction,
]


if __name__ == "__main__":
    # ── Locate input file ─────────────────────────────────────────────────────

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

    # ── Insert column D (idempotent: only skip if linter column already present)

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
    ws.column_dimensions["D"].width = 55

    # ── Run checks over every data row ───────────────────────────────────────

    annotated = 0

    for row_num in range(HEADER_ROWS + 1, ws.max_row + 1):
        src_text = ws.cell(row=row_num, column=2).value
        tgt_text = ws.cell(row=row_num, column=3).value

        if not src_text:
            continue

        src_str = str(src_text).strip()
        tgt_str = str(tgt_text) if tgt_text else ""  # raw — checks do their own stripping

        issues = [
            result
            for check in CHECKS
            for result in (check(src_str, tgt_str),)
            if result is not None
        ]

        if issues:
            lint_cell = ws.cell(row=row_num, column=4)
            lint_cell.value = "\n".join(issues)
            lint_cell.alignment = Alignment(wrap_text=True)
            lint_cell.fill = _FILL
            annotated += 1

    # ── Save ─────────────────────────────────────────────────────────────────

    out_path = src_path
    try:
        wb.save(out_path)
    except PermissionError:
        stamp = datetime.now().strftime("%H%M%S")
        out_path = src_path.parent / src_path.name.replace(".xlsx", f"_{stamp}.xlsx")
        wb.save(out_path)

    print(f"Annotated {annotated} segment(s).")
    print(f"Saved: {out_path}")
