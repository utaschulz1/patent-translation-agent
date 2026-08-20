"""
xtm_final_download.py — Download the end-of-workflow files from XTM Workbench.

Saves to the matching ComunicaDK project folder (WORK_DIR/<folder containing project_id>):
  1. Target docx   → <stem>_German (Claims).docx
  2. Bilingual PDF → <stem>_German (Claims).docx.pdf
  3. Final Excel   → Final_<stem>.xlsx

where <stem> is the source document name as returned by XTM (e.g. EP3928538_clean_XTM).

Use --only to skip files you don't need — e.g. the Issue Resolution
XTM_SEGMENTS_DOWNLOAD step only needs the Excel for segment matching, so it
runs with --only xlsx to skip two preview-generation round-trips against a
server known to be laggy under load.

Usage:
    python xtm_final_download.py <project_id> [--only all|docx|pdf|xlsx]
    python xtm_final_download.py HALA_2605_P0439
    python xtm_final_download.py HALA_2607_P0624 --only xlsx
"""

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

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
    orig_name = unquote(m.group(1).strip()) if m else f"download_{preview_type}"

    content = b"".join(r.iter_content(8192))
    return content, orig_name


def _strip_ext(name: str, ext: str) -> str:
    """Strip ext (e.g. '.docx') from name if present, else return name unchanged."""
    return name[: -len(ext)] if name.lower().endswith(ext.lower()) else name


def _stem_from_docx_name(orig_name: str) -> str:
    """Strip the .docx extension to get the naming stem (e.g. 'EP3928538_clean_XTM')."""
    return _strip_ext(orig_name, ".docx")


ONLY_CHOICES = ("all", "docx", "pdf", "xlsx")


def run(project_id: str, only: str = "all") -> None:
    """Downloads the requested end-of-workflow file(s) from XTM Workbench.

    Args:
        project_id: the project to download for — its ComunicaDK delivery
            folder must already exist.
        only: "all" (default) or one of "docx"/"pdf"/"xlsx" to skip the
            others' preview-generation round-trips.

    Raises:
        ValueError: unknown `only` value.
        RuntimeError: no ComunicaDK folder found for project_id.
    """
    if only not in ONLY_CHOICES:
        raise ValueError(f"Unknown --only value {only!r}. Known: {ONLY_CHOICES}")

    comunica_dir = _find_comunica_folder(project_id)
    print(f"Destination: {comunica_dir}")

    print("\nStep 1 — Login and open XTM workbench...")
    session, session_token, csrf_token = _xtm._setup_session(project_id)

    stem: str | None = None
    saved_names: list[str] = []

    # ── Target docx ──────────────────────────────────────────────────────────
    if only in ("all", "docx"):
        print("\nStep 2 — Downloading target docx...")
        docx_bytes, docx_orig = _download_file(session, session_token, csrf_token, PREVIEW_TYPE_DOCX)
        stem = _stem_from_docx_name(docx_orig)
        docx_path = comunica_dir / f"{stem}_German (Claims).docx"
        docx_path.write_bytes(docx_bytes)
        print(f"  Saved: {docx_path.name}  ({len(docx_bytes):,} bytes)")
        saved_names.append(docx_path.name)

    # ── Bilingual PDF ─────────────────────────────────────────────────────────
    if only in ("all", "pdf"):
        print("\nStep 3 — Downloading bilingual PDF...")
        pdf_bytes, pdf_orig = _download_file(session, session_token, csrf_token, PREVIEW_TYPE_PDF)
        if stem is None:  # pdf-only run — derive stem from the pdf's own name
            stem = _strip_ext(_strip_ext(pdf_orig, ".pdf"), ".docx")
        pdf_path = comunica_dir / f"{stem}_German (Claims).docx.pdf"
        pdf_path.write_bytes(pdf_bytes)
        print(f"  Saved: {pdf_path.name}  ({len(pdf_bytes):,} bytes)")
        saved_names.append(pdf_path.name)

    # ── Final Excel ───────────────────────────────────────────────────────────
    if only in ("all", "xlsx"):
        print("\nStep 4 — Downloading final Excel...")
        xlsx_bytes, xlsx_orig = _download_file(session, session_token, csrf_token, PREVIEW_TYPE_XLSX)
        if stem is None:  # xlsx-only run (e.g. Issue Resolution segment matching)
            stem = _strip_ext(xlsx_orig, ".xlsx")
        xlsx_path = comunica_dir / f"Final_{stem}.xlsx"
        xlsx_path.write_bytes(xlsx_bytes)
        print(f"  Saved: {xlsx_path.name}  ({len(xlsx_bytes):,} bytes)")
        saved_names.append(xlsx_path.name)

    print(f"\nDone. {len(saved_names)} file(s) saved to: {comunica_dir}")
    for name in saved_names:
        print(f"  {name}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Download end-of-workflow files from XTM Workbench")
    parser.add_argument("project_id")
    parser.add_argument("--only", choices=ONLY_CHOICES, default="all",
                         help="Which file(s) to download (default: all)")
    args = parser.parse_args()
    run(args.project_id, only=args.only)


if __name__ == "__main__":
    main()
