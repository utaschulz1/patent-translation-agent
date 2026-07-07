"""
import_segments.py — Parse the XTM XLF file and populate the segments DB table.

Usage: python import_segments.py <project_id>

Reads the original XTM XLF (not *_GERMAN.xlf, not *_CAT_revised.xlf) from the
project's pre-processing folder and writes one row per trans-unit to the
segments table. Safe to re-run: INSERT OR IGNORE skips existing rows.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lxml import etree

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import workflow_db as db
from project_log import find_project_dir


def _extract_seg_id(xtm_url: str) -> int | None:
    try:
        qs = parse_qs(urlparse(xtm_url).query)
        return int(qs["segmentId"][0])
    except (KeyError, ValueError, TypeError):
        return None


def _plain_text(element) -> str:
    """Join all text nodes under element, ignoring tag names."""
    parts = []
    if element.text:
        parts.append(element.text)
    for child in element:
        parts.append(_plain_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def _serialize(element) -> str:
    return etree.tostring(element, encoding="unicode")


def _find_xtm_url(tu, xtm_ns: str) -> str | None:
    """Return the xtm:url attribute value, trying both namespaced and fallback forms."""
    if xtm_ns:
        v = tu.get(f"{{{xtm_ns}}}url")
        if v:
            return v
    # Fallback: scan all attributes for one containing segmentId
    for val in tu.attrib.values():
        if "segmentId" in val:
            return val
    return None


def run(project_id: str) -> None:
    db.init_db()  # ensure segments table exists (safe to call repeatedly)
    pre_dir = find_project_dir(project_id)
    xlf_files = [
        f for f in pre_dir.glob("*.xlf")
        if not f.name.endswith("_GERMAN.xlf") and not f.name.endswith("_CAT_revised.xlf")
    ]
    if not xlf_files:
        raise FileNotFoundError(f"No source XLF found in {pre_dir}")
    xlf_path = sorted(xlf_files)[0]
    print(f"[import_segments] Parsing {xlf_path.name}", flush=True)

    tree = etree.parse(str(xlf_path))
    root = tree.getroot()

    # Detect namespaces
    xliff_ns = root.nsmap.get(None, "urn:oasis:names:tc:xliff:document:1.2")
    xtm_ns = root.nsmap.get("xtm", "")

    def _find(el, tag):
        node = el.find(f"{{{xliff_ns}}}{tag}")
        if node is None:
            node = el.find(tag)
        return node

    def _findall(el, tag):
        nodes = el.findall(f".//{{{xliff_ns}}}{tag}")
        if not nodes:
            nodes = el.findall(f".//{tag}")
        return nodes

    trans_units = _findall(root, "trans-unit")
    print(f"[import_segments] Found {len(trans_units)} trans-units", flush=True)

    imported = skipped = 0
    for tu in trans_units:
        xtm_url = _find_xtm_url(tu, xtm_ns)
        if not xtm_url:
            continue

        seg_id = _extract_seg_id(xtm_url)
        if seg_id is None:
            continue

        source_el = _find(tu, "source")
        if source_el is None:
            continue

        source_text = _plain_text(source_el)
        source_xml = _serialize(source_el)

        target_el = _find(tu, "target")
        state_qualifier = target_el.get("state-qualifier", "") if target_el is not None else ""

        if state_qualifier == "exact-match":
            match_quality = "exact-match"
            pretranslation = _plain_text(target_el) if target_el is not None else None
            status = "ICE"
        elif state_qualifier == "leveraged-tm":
            match_quality = "leveraged-tm"
            pretranslation = _plain_text(target_el) if target_el is not None else None
            status = "100%"
        elif state_qualifier == "fuzzy-match":
            match_quality = "fuzzy-match"
            pretranslation = None
            status = "PENDING"
        else:
            match_quality = state_qualifier or "mt-suggestion"
            pretranslation = None
            status = "PENDING"

        db.upsert_segment(
            project_id=project_id,
            seg_id=seg_id,
            source_text=source_text,
            source_xml=source_xml,
            match_quality=match_quality,
            pretranslation=pretranslation,
            status=status,
        )
        imported += 1

    print(
        f"[import_segments] Done: {imported} segments written "
        f"(existing rows silently skipped by INSERT OR IGNORE)",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: import_segments.py <project_id>")
        sys.exit(1)
    run(sys.argv[1])
