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
TEST_SEGMENT_LIMIT: int | None = 80
START_FROM_SEGMENT_ID: int     = 221
UPLOAD_BATCH_SIZE       = 15    # re-open editor every N segments to get a fresh session token
BATCH_WAIT_SECONDS      = 120   # wait between batches for server to release doc lock
DEBUG_SOURCE_NODES_LIMIT       = 0
SEGMENT_ID_FILTER: set[int] | None = None  # set via --segments; overrides range/limit

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
    for _event, pair in ET.iterparse(str(path), events=["start-ns"]):
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

    if SEGMENT_ID_FILTER is not None:
        segments = [(uid, t) for uid, t in segments if uid in SEGMENT_ID_FILTER]
        print(f"  SEGMENT FILTER: {sorted(SEGMENT_ID_FILTER)} → {len(segments)} segment(s)")
    else:
        if START_FROM_SEGMENT_ID > 1:
            segments = [(uid, t) for uid, t in segments if uid >= START_FROM_SEGMENT_ID]
            print(f"  Starting from segment ID {START_FROM_SEGMENT_ID} ({len(segments)} segments remaining)")
        if TEST_SEGMENT_LIMIT is not None:
            segments = segments[:TEST_SEGMENT_LIMIT]
            print(f"  TEST MODE: capped at {TEST_SEGMENT_LIMIT} segments")

    non_empty = sum(1 for _, t in segments if t)
    print(f"  {len(segments)} segments ({non_empty} non-empty, {len(segments)-non_empty} empty/skipped)")

    username, password = _load_creds()
    _xtm_up.DEBUG_SOURCE_NODES_LIMIT = DEBUG_SOURCE_NODES_LIMIT

    def _hard_login():
        """New HTTP session + full login + claim + open editor."""
        s = requests.Session()
        s.headers.update({
            "Accept":     "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
                "Gecko/20100101 Firefox/149.0"
            ),
        })
        uu = _login(s, username, password)
        s.headers.update({"uust": uu, "X-Requested-With": "XMLHttpRequest"})
        tsk = _find_task(_get_tasks(s), project_id)
        tsk = _claim_group_task(s, tsk, uu, project_id)
        if tsk["additionalData"].get("actorType") != "INTERNALLINGUIST":
            raise RuntimeError(
                f"Task actor is still '{tsk['additionalData'].get('actorType')}' — "
                "automatic claim failed. Accept the task manually in XTM, then re-run."
            )
        wb_url, tok = _open_editor_write(s, tsk, uu)
        csrf = _init_workbench(s, wb_url, tok)
        time.sleep(3)
        _keepalive(s)
        return s, tsk, uu, tok, csrf

    def _reopen_editor(s, tsk, uu):
        """Reuse existing HTTP session — just re-open the editor for a fresh token."""
        wb_url, tok = _open_editor_write(s, tsk, uu)
        csrf = _init_workbench(s, wb_url, tok)
        time.sleep(3)
        _keepalive(s)
        return tok, csrf

    print("\nSteps 1–4 — Login, claim task, open editor...")
    session, task, uust, session_token, csrf_token = _hard_login()
    print(f"  Session token: {session_token[:12]}...")

    # Upload loop:
    #   - between batches: lightweight editor re-open (same HTTP session)
    #   - on server rejection or re-open failure: hard re-login after BATCH_WAIT_SECONDS,
    #     then resume from the failed segment
    todo         = list(segments)     # remaining segments, shrinks as batches succeed
    results:     dict[int, str] = {}
    retry_counts: dict[int, int] = {}  # how many times each segment has been retried
    batch_num    = 0

    while todo:
        batch     = todo[:UPLOAD_BATCH_SIZE]
        first_id  = batch[0][0]
        last_id   = batch[-1][0]
        batch_num += 1
        print(f"\nBatch {batch_num} — segments {first_id}–{last_id} ({len(batch)} segments)...")

        batch_results = _upload_via_stomp(session, session_token, csrf_token, batch)

        # Segments the server rejected or never attempted
        retry_ids = {uid for uid, st in batch_results.items()
                     if st == "not attempted" or st.startswith("failed")}

        # Record only the successful ones
        for uid, st in batch_results.items():
            if uid not in retry_ids:
                results[uid] = st

        if retry_ids:
            # Increment retry counters; give up on segments that have failed twice
            permanent: set[int] = set()
            for uid in retry_ids:
                retry_counts[uid] = retry_counts.get(uid, 0) + 1
                if retry_counts[uid] >= 2:
                    permanent.add(uid)
                    results[uid] = "skipped (permanent server rejection — check manually in XTM)"
                    print(f"  Segment {uid}: giving up after {retry_counts[uid]} attempts — mark for manual fix.")

            retry_ids -= permanent
            if not retry_ids:
                todo = todo[UPLOAD_BATCH_SIZE:]
                continue

            print(f"  {len(retry_ids)} segment(s) failed/not-attempted — "
                  f"hard re-login in {BATCH_WAIT_SECONDS}s, resuming from segment {min(retry_ids)}...")
            time.sleep(BATCH_WAIT_SECONDS)
            session, task, uust, session_token, csrf_token = _hard_login()
            print(f"  New session token: {session_token[:12]}...")
            # Put failed/not-attempted back at the front of todo
            retry_map = {uid: txt for uid, txt in segments if uid in retry_ids}
            todo = [(uid, retry_map[uid]) for uid in sorted(retry_ids)] + todo[UPLOAD_BATCH_SIZE:]
        else:
            todo = todo[UPLOAD_BATCH_SIZE:]
            if todo:
                print(f"  Batch done — re-opening editor...")
                try:
                    session_token, csrf_token = _reopen_editor(session, task, uust)
                    print(f"  Session token: {session_token[:12]}...")
                except Exception as exc:
                    print(f"  Editor re-open failed ({exc}) — hard re-login in {BATCH_WAIT_SECONDS}s...")
                    time.sleep(BATCH_WAIT_SECONDS)
                    session, task, uust, session_token, csrf_token = _hard_login()
                    print(f"  New session token: {session_token[:12]}...")

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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument(
        "--segments", "-s", default=None,
        help="Comma-separated segment IDs to (re-)upload, e.g. 18,22,23,28. "
             "Overrides START_FROM_SEGMENT_ID and TEST_SEGMENT_LIMIT.",
    )
    args = ap.parse_args()

    if args.segments:
        try:
            global SEGMENT_ID_FILTER
            SEGMENT_ID_FILTER = {int(x.strip()) for x in args.segments.split(",")}
        except ValueError:
            print("ERROR: --segments must be comma-separated integers, e.g. 18,22,23")
            raise SystemExit(1)

    try:
        run(args.project_id)
    except (RuntimeError, TimeoutError) as e:
        print(f"\nError: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
