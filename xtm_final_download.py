"""
xtm_final_download.py — Download the 3 end-of-workflow files from XTM Workbench.

Saves to the matching ComunicaDK project folder (WORK_DIR/<folder containing project_id>):
  1. Target docx   → <stem>_German (Claims).docx
  2. Bilingual PDF → <stem>_German (Claims).docx.pdf
  3. Final Excel   → Final_<stem>.xlsx

where <stem> is the source document name as returned by XTM (e.g. EP3928538_clean_XTM).

Usage:
    python xtm_final_download.py <project_id>
    python xtm_final_download.py HALA_2605_P0439
"""

import re
import sys
from pathlib import Path

import xtm_initial_download as _xtm
from config import WORK_DIR

# ── Preview type constants ────────────────────────────────────────────────────
PREVIEW_TYPE_XLSX = "EXCEL_EXTENDED_TABLE"   # confirmed
PREVIEW_TYPE_DOCX = "TARGET"                 # confirmed from WebSocket capture
PREVIEW_TYPE_PDF  = "PDF_SIDE_BY_SIDE"       # confirmed from WebSocket capture
# ─────────────────────────────────────────────────────────────────────────────


def _find_comunica_folder(project_id: str) -> Path:
    """Return the ComunicaDK delivery folder whose name contains project_id."""
    for d in sorted(WORK_DIR.iterdir()):
        if d.is_dir() and project_id in d.name:
            return d
    raise RuntimeError(
        f"No ComunicaDK folder containing '{project_id}' found in {WORK_DIR}\n"
        f"  Create the delivery folder first."
    )


def _download_file(
    session,
    session_token: str,
    csrf_token: str,
    preview_type: str,
) -> tuple[bytes, str]:
    """Generate a preview and download it. Returns (content_bytes, original_filename)."""
    print(f"  Generating {preview_type}...")
    ticket = _xtm._generate_preview(session, session_token, csrf_token, preview_type)
    print(f"  Ticket: {ticket}")

    r = session.get(
        "https://word.welocalize.com/workbench/web/preview/document",
        params={"_s": session_token, "downloadTicket": ticket},
        stream=True,
    )
    r.raise_for_status()

    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename[^;=\n]*=\s*["\']?([^"\';\n]+)', cd)
    orig_name = m.group(1).strip() if m else f"download_{preview_type}"

    content = b"".join(r.iter_content(8192))
    return content, orig_name


def _stem_from_docx_name(orig_name: str) -> str:
    """Strip the .docx extension to get the naming stem (e.g. 'EP3928538_clean_XTM')."""
    if orig_name.lower().endswith(".docx"):
        return orig_name[:-5]
    return orig_name


def run(project_id: str) -> None:
    comunica_dir = _find_comunica_folder(project_id)
    print(f"Destination: {comunica_dir}")

    print("\nStep 1 — Login and open XTM workbench...")
    session, session_token, csrf_token = _xtm._setup_session(project_id)

    # ── Target docx ──────────────────────────────────────────────────────────
    print("\nStep 2 — Downloading target docx...")
    docx_bytes, docx_orig = _download_file(session, session_token, csrf_token, PREVIEW_TYPE_DOCX)
    stem = _stem_from_docx_name(docx_orig)
    docx_path = comunica_dir / f"{stem}_German (Claims).docx"
    docx_path.write_bytes(docx_bytes)
    print(f"  Saved: {docx_path.name}  ({len(docx_bytes):,} bytes)")

    # ── Bilingual PDF ─────────────────────────────────────────────────────────
    print("\nStep 3 — Downloading bilingual PDF...")
    pdf_bytes, _pdf_orig = _download_file(session, session_token, csrf_token, PREVIEW_TYPE_PDF)
    pdf_path = comunica_dir / f"{stem}_German (Claims).docx.pdf"
    pdf_path.write_bytes(pdf_bytes)
    print(f"  Saved: {pdf_path.name}  ({len(pdf_bytes):,} bytes)")

    # ── Final Excel ───────────────────────────────────────────────────────────
    print("\nStep 4 — Downloading final Excel...")
    xlsx_bytes, _xlsx_orig = _download_file(session, session_token, csrf_token, PREVIEW_TYPE_XLSX)
    xlsx_path = comunica_dir / f"Final_{stem}.xlsx"
    xlsx_path.write_bytes(xlsx_bytes)
    print(f"  Saved: {xlsx_path.name}  ({len(xlsx_bytes):,} bytes)")

    print(f"\nDone. 3 files saved to: {comunica_dir}")
    print(f"  {docx_path.name}")
    print(f"  {pdf_path.name}")
    print(f"  {xlsx_path.name}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python xtm_final_download.py <project_id>")
        raise SystemExit(1)
    run(sys.argv[1])


if __name__ == "__main__":
    main()
