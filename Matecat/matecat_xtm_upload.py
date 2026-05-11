"""
matecat_xtm_upload.py  —  XTM Workbench: upload MateCat translations from XLF

Reads segment IDs and translation text from a *_GERMAN.xlf file
(downloaded via matecat_download.py) and pushes each translation into the
matching XTM segment via the STOMP WebSocket protocol.

Segment IDs are mapped from the XLF trans-unit id attribute (e.g. "t4" → 4).
Translation text is extracted from <target> elements, including text inside
inline tags (<g>, <x/>, etc.).

Usage:
    - Accept the task in XTM (claim from USERGROUP if needed).
    - Set START_FROM_SEGMENT_ID and TEST_SEGMENT_LIMIT as needed.
    - Run:  python matecat_xtm_upload.py <project_id>
    e.g.    python matecat_xtm_upload.py LABI_2605_P0009
"""

import json
import os
import random
import re
import string
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import websocket as _websocket
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from xtm_initial_download import (
    BASE_URL,
    WB_BASE,
    _find_pre_folder,
    _get_tasks,
    _init_workbench,
    _keepalive,
    _load_creds,
    _login,
    _find_task,
)
import xtm_upload_translations as _xtm_up
from xtm_upload_translations import (
    _claim_group_task,
    _open_editor_write,
    _upload_via_stomp,
)

AUTO_CONFIRM_MATCHES    = True   # ICE / 100% / repetition segments via XTM pre-fill
KEEPALIVE_INTERVAL      = 25
RECONNECT_EVERY         = 9999
TEST_SEGMENT_LIMIT: int | None = 15
START_FROM_SEGMENT_ID: int     = 122
DEBUG_SOURCE_NODES_LIMIT       = 0

_XLF_NS = "urn:oasis:names:tc:xliff:document:1.2"

def _ns(tag: str) -> str:
    return f"{{{_XLF_NS}}}{tag}"


def _target_text(target: ET.Element) -> str:
    """Extract plain text from <target>, including text inside inline tags."""
    return "".join(target.itertext()).strip()


def _segment_id_from_unit_id(unit_id: str) -> int | None:
    """Convert XLF trans-unit id (e.g. 't4') to XTM integer segment ID (4)."""
    if unit_id.startswith("t") and unit_id[1:].isdigit():
        return int(unit_id[1:])
    # Fallback: try parsing segmentId from xtm:url if available
    return None


def _read_xlf(path: Path) -> list[tuple[int, str]]:
    """Return (unit_id, translation_text) pairs from a *_GERMAN.xlf file.

    Skips segments with no translation (empty <target>).
    """
    for event, pair in ET.iterparse(str(path), events=["start-ns"]):
        ET.register_namespace(*pair)

    tree = ET.parse(path)
    segments: list[tuple[int, str]] = []

    for tu in tree.getroot().iter(_ns("trans-unit")):
        raw_id   = tu.get("id", "")
        seg_id   = _segment_id_from_unit_id(raw_id)

        # Fallback: extract segmentId from xtm:url attribute
        if seg_id is None:
            xtm_url = tu.get("{urn:xliff-xtm-extensions}url", "")
            m = re.search(r"segmentId=(\d+)", xtm_url)
            if m:
                seg_id = int(m.group(1))

        if seg_id is None:
            print(f"  Warning: cannot determine segment ID for trans-unit id={raw_id!r}, skipping")
            continue

        target = tu.find(_ns("target"))
        if target is None:
            continue

        text = _target_text(target)
        segments.append((seg_id, text))

    return segments


def run(project_id: str) -> None:
    proj_dir = ROOT / "projects" / project_id

    # Find *_GERMAN.xlf
    xlf_files = list(proj_dir.glob("*_GERMAN.xlf"))
    if not xlf_files:
        raise RuntimeError(f"No *_GERMAN.xlf found in {proj_dir}\nRun matecat_download.py first.")
    if len(xlf_files) > 1:
        print(f"  Multiple _GERMAN.xlf files, using: {xlf_files[0].name}")
    xlf_path = xlf_files[0]

    # Fail fast before XTM login
    print(f"Reading translations from {xlf_path.name}...")
    segments = _read_xlf(xlf_path)

    if START_FROM_SEGMENT_ID > 1:
        segments = [(uid, t) for uid, t in segments if uid >= START_FROM_SEGMENT_ID]
        print(f"  Starting from segment ID {START_FROM_SEGMENT_ID} ({len(segments)} segments remaining)")
    if TEST_SEGMENT_LIMIT is not None:
        segments = segments[:TEST_SEGMENT_LIMIT]
        print(f"  TEST MODE: capped at {TEST_SEGMENT_LIMIT} segments")

    non_empty = sum(1 for _, t in segments if t)
    print(f"  {len(segments)} segments ({non_empty} non-empty, {len(segments)-non_empty} empty/skipped)")

    username, password = _load_creds()
    session = requests.Session()
    session.headers.update({
        "Accept":     "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
            "Gecko/20100101 Firefox/149.0"
        ),
    })

    print("\nStep 1 — Login to XTM Workbench...")
    uust = _login(session, username, password)
    session.headers.update({"uust": uust, "X-Requested-With": "XMLHttpRequest"})

    print("Step 2 — Fetching task list...")
    tasks = _get_tasks(session)
    print(f"  {len(tasks)} task(s) in progress")
    task = _find_task(tasks, project_id)
    ad   = task["additionalData"]
    print(f"  Found: {ad.get('projectName', '?')}  (file {ad.get('fileId', '?')})")
    print(f"  actorType: {ad.get('actorType', '?')}")

    print("Step 3 — Claiming task for INTERNALLINGUIST (if needed)...")
    task = _claim_group_task(session, task, uust, project_id)
    actor_after = task["additionalData"].get("actorType", "?")
    if actor_after != "INTERNALLINGUIST":
        raise RuntimeError(
            f"Task actor is still '{actor_after}' — automatic claim failed.\n"
            "  Please accept the task manually in XTM, then re-run."
        )

    print("Step 4 — Opening workbench editor (write mode)...")
    wb_url, session_token = _open_editor_write(session, task, uust)
    print(f"  Session token: {session_token[:12]}...")

    csrf_token = _init_workbench(session, wb_url, session_token)
    time.sleep(3)
    _keepalive(session)

    _xtm_up.DEBUG_SOURCE_NODES_LIMIT = DEBUG_SOURCE_NODES_LIMIT

    print("Step 5 — Uploading translations via WebSocket...")
    results = _upload_via_stomp(session, session_token, csrf_token, segments)

    saved         = sum(1 for s in results.values() if s == "saved")
    confirmed     = sum(1 for s in results.values() if s.startswith("confirmed"))
    skipped       = sum(1 for s in results.values() if s == "skipped")
    not_attempted = sum(1 for s in results.values() if s == "not attempted")
    failed        = {uid: s for uid, s in results.items() if s.startswith("failed")}

    print()
    print("=== Upload summary ===")
    print(f"  Saved:         {saved}")
    print(f"  Confirmed:     {confirmed}  (ICE / 100% / repetition)")
    print(f"  Skipped:       {skipped}  (empty translation)")
    if not_attempted:
        print(f"  Not attempted: {not_attempted}")
    print(f"  Failed:        {len(failed)}")
    if failed:
        for uid, reason in sorted(failed.items()):
            print(f"    segment {uid}: {reason}")
    print(f"  Total:         {len(results)}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python matecat_xtm_upload.py <project_id>")
        raise SystemExit(1)
    try:
        run(sys.argv[1])
    except (RuntimeError, TimeoutError) as e:
        print(f"\nError: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
