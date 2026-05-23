"""
extract_align_bilingual_pdf.py
==============================
Extracts and aligns patent claims from a bilingual EPO B1 grant specification
PDF, producing a side-by-side EN / DE spreadsheet suitable for translation
review or CAT-tool pre-processing.

Background
----------
EPO B1 publication PDFs use a fixed two-column page layout.  pdfplumber's
default extract_text() reads characters in visual (top-to-bottom,
left-to-right) order and merges both columns row-by-row, producing a single
stream where every other word belongs to a different language.  This makes
regex-based claim boundary detection impossible.

The script works around this by cropping each page into two independent
bounding boxes (left column / right column) before calling extract_text(),
so the full text of the left column is read first and the full text of the
right column is appended after it.  Two additional exclusion zones are applied
per page:

  * Top margin  (y < 57 pt)  — removes the running EPO document header that
    appears on every page (e.g. "11 EP 4 413 931 B1 12").
  * Centre strip (x ≈ 300–319 pt) — removes the EPO line-reference numbers
    (5, 10, 15 … 55) printed between the two columns.  Without this exclusion
    those numbers appear at the start of right-column lines and prevent the
    claim-number regex from firing (e.g. "5 4. The stabilization system …"
    instead of "4. The stabilization system …").

After extraction the text is split into language sections using the standard
EPO section headings ("Claims" → "Patentansprüche" → "Revendications"), each
section is split on claim-number boundaries, and the EN / DE paragraph lists
are zipped into a flat DataFrame with an "ID" column ("Claim N.M") to preserve
sub-clause granularity.

Typical page-geometry values for A4 EPO B1 PDFs (verified against
EP 4 413 931 B1):
  Page width  : 595.28 pt
  Left column : x  71 – 284 pt
  Centre gap  : x 295 – 315 pt   (EPO line numbers reside here)
  Right column: x 319 – 540 pt
  Header row  : y  40 –  55 pt

Usage
-----
  python extract_align_bilingual_pdf.py -f path/to/patent.pdf
  python extract_align_bilingual_pdf.py -f patent.pdf -o results --format csv

Arguments
---------
  -f / --file     Path to the bilingual EPO B1 PDF.  Required.
  -o / --output   Output directory (created if absent).  Default: "output".
  --format        "xlsx" (default) or "csv".

Output
------
  <output_dir>/<pdf_stem>_aligned_claims.xlsx  (or .csv)

  Columns: ID | EN | DE
  Each row corresponds to one text line of a claim.  Multi-line claims
  receive consecutive IDs "Claim N.1", "Claim N.2", etc.  When EN and DE
  line counts differ (due to different hyphenation), the shorter side is
  padded with empty strings so neither column loses content.

Dependencies
------------
  pymupdf (fitz), pandas, openpyxl (for xlsx output)

  Note: pdfplumber was used in earlier versions but cannot recover inter-word
  spacing for EPO PDFs that store glyph sequences without explicit space
  characters.  PyMuPDF uses font-metric glyph widths to determine word
  boundaries, which correctly separates "A stabilization system" where
  pdfplumber produces "Astabilizationsystem".
"""

import os
import re
import argparse
import pandas as pd
import fitz  # PyMuPDF
from itertools import zip_longest


def _column_to_text(page, x_min, x_max, y_min):
    """Extract one column of text from a page using character bbox gap detection.

    EPO PDFs mix two font encoding strategies on the same page: some character
    runs include explicit Unicode space characters (gap = 0 between chars,
    explicit ' ' token present); others pack glyphs with no spaces at all
    (words like "Astabilizationsystem" stored as a single text run).

    Both strategies are handled by measuring the gap between each character's
    right bounding-box edge (bbox[2]) and the next character's left edge
    (bbox[0]):

      * gap ≤ 0.5 pt  →  characters belong to the same word (either touching,
        overlapping through kerning, or a narrow ligature gap)
      * gap >  0.5 pt  →  insert a word-space before the next character

    This correctly tokenises both cases: for runs with explicit spaces the
    gap fires on the space character itself; for tight runs like
    "Thestabilizationsystemofclaim5" the ~1.33 pt encoding gap between
    logical words triggers the split while the 0 pt intra-word gaps do not.

    Characters whose bbox[0] falls outside [x_min, x_max) or whose bbox[1]
    (top) is less than y_min are excluded (column banding + header removal).

    Parameters
    ----------
    page : fitz.Page
        PyMuPDF page object.
    x_min, x_max : float
        Horizontal band for this column.
    y_min : float
        Minimum y value; characters above this are header/footer noise.

    Returns
    -------
    str
        Newline-delimited text with one visual line per PDF text line.
    """
    # Collect characters that fall within this column band
    chars = []
    for block in page.get_text("rawdict", flags=0)["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span["chars"]:
                    x0, y0, x1, y1 = ch["bbox"]
                    if x_min <= x0 < x_max and y0 > y_min:
                        chars.append({"x0": x0, "y0": y0, "x1": x1, "c": ch["c"]})

    if not chars:
        return ""

    # Sort: primary key = rounded y (line), secondary = x (left-to-right)
    chars.sort(key=lambda c: (round(c["y0"]), c["x0"]))

    # Group into visual lines (y0 within 5 pt = same line)
    line_groups: list[list[dict]] = []
    current: list[dict] = [chars[0]]
    for ch in chars[1:]:
        if abs(ch["y0"] - current[0]["y0"]) <= 5:
            current.append(ch)
        else:
            line_groups.append(current)
            current = [ch]
    line_groups.append(current)

    # Build one text string per line, inserting spaces at word boundaries
    result_lines = []
    for line_chars in line_groups:
        line_chars.sort(key=lambda c: c["x0"])
        text = line_chars[0]["c"]
        for i in range(1, len(line_chars)):
            gap = line_chars[i]["x0"] - line_chars[i - 1]["x1"]
            if gap > 0.5:
                text += " " + line_chars[i]["c"]
            else:
                text += line_chars[i]["c"]
        stripped = text.strip()
        if stripped:
            result_lines.append(stripped)

    return "\n".join(result_lines)


def extract_text_two_column(pdf_path):
    """Extract the full document text while preserving column reading order.

    EPO B1 PDFs use a two-column layout.  A naïve full-page extraction
    interleaves both columns row-by-row, making claim segmentation
    impossible.  This function filters characters from each page into a left-
    column band and a right-column band and concatenates the left column
    first, so the text of the left column for all pages precedes the right.

    Word boundaries are detected from character bbox right-edges rather than
    relying on explicit space characters in the PDF stream (see
    _column_to_text for the full explanation).

    Two x-bands are excluded from every page:

      * Top margin  (y < 57 pt)  — the running EPO document header printed
        across the full page width ("11 EP 4 413 931 B1 12").

      * Centre strip  (x ≈ 300–319 pt)  — the EPO paragraph line-reference
        numbers (5, 10, 15 … 55) typeset between the two columns.  Without
        this exclusion they appear at the start of right-column lines and
        break the downstream claim-number split regex.

    Column boundaries (verified against EP 4 413 931 B1 on A4, 595.28 pt wide):
      left_end    ≈ 300 pt  (50.4 % of page width)
      right_start ≈ 319 pt  (53.5 % of page width)

    Parameters
    ----------
    pdf_path : str
        Absolute or relative path to the PDF file.

    Returns
    -------
    str
        Concatenated plain text of all pages, left column before right
        column, with newline padding between column blocks.
    """
    print(f"[*] Extracting raw text from: {pdf_path}")
    parts = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            pw = page.rect.width
            header_bottom = 57       # skip EPO page-header row
            left_end = pw * 0.504    # ~300 pt — stops before EPO line numbers
            right_start = pw * 0.535 # ~319 pt — starts after EPO line numbers

            for x_min, x_max in [(0, left_end), (right_start, pw)]:
                col_text = _column_to_text(page, x_min, x_max, header_bottom)
                if col_text.strip():
                    parts.append(col_text)

    return "\n".join(parts)


def _join_claim_lines(lines):
    """Join a list of PDF text lines into one continuous string.

    EPO PDFs hyphenate long words at line boundaries by inserting a "-" at
    the end of a line and continuing the word on the next line (e.g.
    "loca-\\ntion").  These soft wrap-hyphens are collapsed so the
    reconstructed word reads correctly.  All other line boundaries are
    replaced with a single space.

    Parameters
    ----------
    lines : list[str]
        Raw PDF text lines as produced by splitting the claim body on "\\n".

    Returns
    -------
    str
        A single string with wrap-hyphens removed and words correctly joined.
    """
    text = ''
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if text.endswith('-'):
            # Soft wrap-hyphen: drop the hyphen and join without a space.
            text = text[:-1] + line
        elif text:
            text += ' ' + line
        else:
            text = line
    return text


def _split_subclauses(text):
    """Split a claim body string into individual sub-clauses.

    EPO claims separate sub-clauses with semicolons, but the same character
    also appears inside parenthetical references such as "(202; 2302)".  A
    parenthesis-depth counter is used so that only *top-level* semicolons
    (depth == 0) trigger a split, leaving internal reference numbers intact.

    After splitting, a leading "and " or "or " connector is stripped from
    each part — EPO style writes the last element as "; and\\nan implant…",
    which would otherwise produce a spurious "and" at the start of a row.

    Parameters
    ----------
    text : str
        A single continuous claim-body string (output of _join_claim_lines).

    Returns
    -------
    list[str]
        One entry per sub-clause.  If no top-level semicolons are found
        (e.g. a simple single-sentence dependent claim), returns a
        single-element list containing the whole text.
    """
    parts = []
    depth = 0
    current = ''
    for ch in text:
        if ch == '(':
            depth += 1
            current += ch
        elif ch == ')':
            depth = max(0, depth - 1)   # guard against malformed parens
            current += ch
        elif ch == ';' and depth == 0:
            stripped = current.strip()
            if stripped:
                parts.append(stripped)
            current = ''
        else:
            current += ch
    # The final sub-clause ends with "." rather than ";"
    stripped = current.strip()
    if stripped:
        parts.append(stripped)

    # Strip leading connectors EPO places before the last element
    # Covers English (and/or), German (und), and French (et)
    clean = [re.sub(r'^(?:and|or|und|et)\s+', '', p, flags=re.IGNORECASE) for p in parts]
    clean = [p for p in clean if p]
    return clean if clean else [text]


def segment_by_claim(text, keyword, stop_keyword=None):
    """Parse a named claims section from the full document text.

    Locates the section that starts with *keyword* (e.g. "Claims") and
    optionally ends just before *stop_keyword* (e.g. "Patentansprüche"),
    then splits it into individual claims by detecting the pattern
    "\\n<digit(s)>. " at the start of a line.

    Each claim's body is first reassembled into a single continuous string
    (collapsing soft wrap-hyphens), then split into sub-clauses at top-level
    semicolons.  This produces one entry per logical sub-clause rather than
    one entry per raw PDF line, so rows in the final spreadsheet correspond
    to complete phrases rather than arbitrary line-wrap fragments.

    Parameters
    ----------
    text : str
        The full extracted document text (output of extract_text_two_column).
    keyword : str
        The section-heading string to search for, e.g. "Claims" or
        "Patentansprüche".  The search is case-sensitive and finds the first
        occurrence, which is always the section heading in EPO B1 PDFs
        (earlier occurrences of "claims" in the description use lower case).
    stop_keyword : str or None
        If given, the section ends just before this string.  Used to prevent
        German claim numbers from overwriting English ones (both run 1–N)
        and to prevent French content from polluting the German section.
        Pass None to read until the end of the document.

    Returns
    -------
    dict[int, list[str]]
        Mapping of claim number → list of sub-clause strings.
        Returns an empty dict and prints a warning if *keyword* is not found.

    Examples
    --------
    >>> en = segment_by_claim(text, "Claims", stop_keyword="Patentansprüche")
    >>> de = segment_by_claim(text, "Patentansprüche", stop_keyword="Revendications")
    >>> en[1]
    ['A stabilization system, comprising: a delivery device (202; 2302)…',
     'an annular anchor (204; 2304) implantable at a target site…',
     'an implant (106) deliverable through the inner sleeve…']
    """
    start = text.find(keyword)
    if start == -1:
        print(f"[!] Warning: '{keyword}' not found in extracted text.")
        return {}

    end = len(text)
    if stop_keyword:
        stop_pos = text.find(stop_keyword, start + len(keyword))
        if stop_pos != -1:
            end = stop_pos

    section_text = text[start:end]

    # Split at every newline that is immediately followed by "N. " where N is
    # one or more digits.  This matches EPO claim headings like "1. A method…"
    # while ignoring sub-clause references like "according to claim 1."
    # (because those have the digit at the end of a line, not the start).
    chunks = re.split(r'\n(?=\d+\.\s)', section_text)

    claims_dict = {}
    for chunk in chunks:
        m = re.match(r'^(\d+)\.\s(.*)', chunk.strip(), re.DOTALL)
        if m:
            claim_num = int(m.group(1))
            joined = _join_claim_lines(m.group(2).split('\n'))
            claims_dict[claim_num] = _split_subclauses(joined)
    return claims_dict


def main():
    """Entry point: parse arguments, extract claims, and write the output file.

    Pipeline
    --------
    1. Extract full document text with column-aware PDF reading.
    2. Locate the "Claims" section (EN) and "Patentansprüche" section (DE).
    3. Split each section into individual claims and their sub-clause lines.
    4. Zip EN and DE paragraph lists for each claim number, padding the
       shorter list with empty strings so no content is dropped.
    5. Write the resulting DataFrame to xlsx or UTF-8-BOM csv.

    The output file is named <pdf_stem>_aligned_claims.<ext> and placed in
    the directory specified by --output (default: "output/").

    Exit behaviour
    --------------
    Prints an error and returns early (without raising) if the input file
    does not exist or if neither language section yields any claims.  All
    other exceptions propagate normally.
    """
    parser = argparse.ArgumentParser(
        description="Extract and align EN/DE claims from an EPO B1 patent PDF."
    )
    parser.add_argument("-f", "--file", required=True,
                        help="Path to the input PDF file.")
    parser.add_argument("-o", "--output", default="output",
                        help="Output directory (created if absent). Default: 'output'.")
    parser.add_argument("--format", choices=["csv", "xlsx"], default="xlsx",
                        help="Output file format. Default: xlsx.")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[X] Error: Input file '{args.file}' does not exist.")
        return

    os.makedirs(args.output, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(args.file))[0]

    full_text = extract_text_two_column(args.file)

    # Bound each language section so that claim numbers (which restart at 1
    # in every language) do not collide across sections.
    en_claims = segment_by_claim(full_text, "Claims",
                                 stop_keyword="Patentansprüche")
    de_claims = segment_by_claim(full_text, "Patentansprüche",
                                 stop_keyword="Revendications")

    if not en_claims and not de_claims:
        print("[X] Error: No claims parsed. Check the PDF text layer.")
        return

    # Build rows: one row per sub-clause line, padded so both columns always
    # cover the same set of claim numbers even if one language is missing.
    rows = []
    row_num = 0
    for c_id in sorted(set(en_claims) | set(de_claims)):
        en_paras = en_claims.get(c_id, [""])
        de_paras = de_claims.get(c_id, [""])
        for en_p, de_p in zip_longest(en_paras, de_paras, fillvalue=""):
            row_num += 1
            rows.append({"ID": row_num, "EN": en_p, "DE": de_p})

    df = pd.DataFrame(rows)

    if args.format == "xlsx":
        out_path = os.path.join(args.output, f"{base_name}_aligned_claims.xlsx")
        df.to_excel(out_path, index=False, engine='openpyxl')
    else:
        out_path = os.path.join(args.output, f"{base_name}_aligned_claims.csv")
        # UTF-8 BOM ensures German umlauts render correctly when opened directly
        # in Microsoft Excel without an explicit import wizard step.
        df.to_csv(out_path, index=False, encoding='utf-8-sig')

    print(f"[+] Saved aligned claims to: {out_path}")


if __name__ == "__main__":
    main()
