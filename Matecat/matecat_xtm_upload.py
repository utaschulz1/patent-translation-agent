"""
matecat_xtm_upload.py  —  XTM Workbench: upload MateCat translations from XLF

Reads segment IDs and translation text from a *_GERMAN.xlf file
(downloaded via matecat_download.py) and pushes each translation into the
matching XTM segment via the STOMP WebSocket protocol.

Segment IDs are mapped from the XLF trans-unit id attribute (e.g. "t4" → 4).
Translation text is extracted from <target> elements, including text inside
inline tags (<g>, <x/>, etc.).

Usage:
    python matecat_xtm_upload.py <project_id> [options]

    # Upload all segments
    python matecat_xtm_upload.py LABI_2605_P0009

    # Select a specific file when the project has multiple tasks (e.g. drawings + claims)
    python matecat_xtm_upload.py CATG_2605_P0229 --file "Anmeldefassung"

    # Upload a segment range only (replaces setting START_FROM_SEGMENT_ID/TEST_SEGMENT_LIMIT)
    python matecat_xtm_upload.py CATG_2605_P0229 --seg-range 421-483

    # Re-upload specific segments after matecat_xtm_verify.py found mismatches
    python matecat_xtm_upload.py CATG_2605_P0229 --segments 421,435,449

    # Combine file selection with a range
    python matecat_xtm_upload.py CATG_2605_P0229 --file "Anmeldefassung" --seg-range 421-483

Options:
    --file SUBSTR       Filename substring to select the right XTM task when a project
                        has multiple files. If omitted and multiple tasks exist, all are
                        listed so you can identify the right substring.
    --seg-range S-E     Upload segments S through E inclusive (e.g. 421-483).
    --segments A,B,C    Upload a specific comma-separated list of segment IDs.

Prerequisites:
    - Accept the task in XTM (or let the script claim it automatically).
    - Run matecat_download.py first to get the *_GERMAN.xlf file.
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
TEST_SEGMENT_LIMIT: int | None = None
START_FROM_SEGMENT_ID: int     = 1
UPLOAD_BATCH_SIZE       = 15    # re-open editor every N segments to get a fresh session token
BATCH_WAIT_SECONDS      = 120   # wait between batches for server to release doc lock
DEBUG_SOURCE_NODES_LIMIT       = 14
SEGMENT_ID_FILTER: set[int] | None = None  # set via --segments; overrides range/limit
FILE_FILTER: str | None = None             # set via --file; selects task by filename substring

_XLF_NS = "urn:oasis:names:tc:xliff:document:1.2"

def _ns(tag: str) -> str:
    return f"{{{_XLF_NS}}}{tag}"


def _target_text(target: ET.Element) -> str:
    """Extract plain text from <target>, including text inside inline tags."""
    return "".join(target.itertext()).strip()


def _xlf_inline_seq(elem: ET.Element) -> list[tuple[str, str]]:
    """Return ordered (kind, xlf_id) for every inline tag in an XLF element.

    kind: 'x' for <x/>, 'g_open' / 'g_close' for <g> open/close.
    Recurses into nested elements so <x> inside <g> is captured in document order.
    """
    result: list[tuple[str, str]] = []

    def walk(e: ET.Element) -> None:
        for child in e:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "x":
                result.append(("x", child.get("id", "")))
            elif local == "g":
                result.append(("g_open", child.get("id", "")))
                walk(child)
                result.append(("g_close", child.get("id", "")))

    walk(elem)
    return result


def _xlf_target_to_nodes(
    xlf_src: ET.Element,
    xlf_tgt: ET.Element,
    source_nodes: list[dict],
) -> tuple[list[dict] | None, str | None]:
    """Build XTM target nodes directly from XLF target tag positions.

    Maps XLF inline tags to XTM INLINE nodes by greedy type-based matching:
    walks src_seq and xtm_inlines in parallel, skipping XLF entries whose type
    doesn't match the next available XTM node (those became SP nodes in XTM).
    Then walks the XLF target element to place the matched nodes at the
    positions the translator established.

    Returns:
      (nodes, 'xlf_driven')  — success; use these nodes
      (None,  'piled')       — XLF src/tgt tag sequences differ; caller falls back
      (None,  'no_xtm_nodes')— XTM sent no INLINE nodes for this segment
      (None,  None)          — segment has no inline tags at all; nothing to record
    """
    src_seq = _xlf_inline_seq(xlf_src)
    tgt_seq = _xlf_inline_seq(xlf_tgt)

    if not src_seq and not tgt_seq:
        return None, None

    xtm_inlines = [n for n in source_nodes if n.get("type") == "INLINE" and "inlineId" in n]

    if not xtm_inlines:
        return None, "no_xtm_nodes"

    # Build pos_map greedily: walk src_seq in order, matching each entry to the
    # next compatible XTM INLINE node. XLF tags that became SP nodes in XTM
    # (no inlineId) are silently skipped because their type won't match.
    # This handles both leading SP-mapped x-tags AND SP-mapped reference-group
    # G containers (e.g. <g><x/><x/><x/></g>) anywhere in the sequence.
    # G open/close pairings are tracked by xlf_id → xtm inlineId.
    pos_map: dict[tuple[str, str], dict] = {}
    _xtm_iter = iter(xtm_inlines)
    _cur = next(_xtm_iter, None)
    _open_g_ids: dict[str, int] = {}  # xlf g id → xtm inlineId of matched open

    for _kind, _xlf_id in src_seq:
        if _cur is None:
            break
        _xtm_type = _cur.get("inlineType")
        if _kind == "x" and _xtm_type == "X":
            pos_map[("x", _xlf_id)] = _cur
            _cur = next(_xtm_iter, None)
        elif _kind == "g_open" and _xtm_type == "G":
            pos_map[("g_open", _xlf_id)] = _cur
            _open_g_ids[_xlf_id] = _cur["inlineId"]
            _cur = next(_xtm_iter, None)
        elif _kind == "g_close" and _xlf_id in _open_g_ids:
            if _xtm_type == "G" and _cur.get("inlineId") == _open_g_ids[_xlf_id]:
                pos_map[("g_close", _xlf_id)] = _cur
                del _open_g_ids[_xlf_id]
                _cur = next(_xtm_iter, None)
        # else: XLF tag is SP-mapped in XTM — skip it

    if not pos_map:
        return None, "piled"

    # Verify the real (non-SP-mapped) tags appear in the same relative order in
    # both source and target.  SP-mapped tags may legitimately be absent from
    # tgt_seq (dropped by MT); genuine reorderings in the remaining tags still
    # return "piled".  This replaces the old strict src_seq == tgt_seq check.
    real_src = [(k, i) for (k, i) in src_seq if (k, i) in pos_map]
    real_tgt = [(k, i) for (k, i) in tgt_seq if (k, i) in pos_map]
    if real_src != real_tgt:
        return None, "piled"

    nodes: list[dict] = []

    def walk(e: ET.Element) -> None:
        if e.text and e.text.strip():
            nodes.append({"type": "TEXT", "decorations": [], "content": e.text})
        for child in e:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            xlf_id = child.get("id", "")
            if local == "x":
                xtm_node = pos_map.get(("x", xlf_id))
                if xtm_node:
                    nodes.append(dict(xtm_node))
            elif local == "g":
                open_node  = pos_map.get(("g_open",  xlf_id))
                close_node = pos_map.get(("g_close", xlf_id))
                if open_node:
                    nodes.append(dict(open_node))
                walk(child)
                if close_node:
                    nodes.append(dict(close_node))
            if child.tail and child.tail.strip():
                nodes.append({"type": "TEXT", "decorations": [], "content": child.tail})

    walk(xlf_tgt)

    if not nodes:
        return None, "piled"

    return nodes, "xlf_driven"


def _segment_id_from_unit_id(unit_id: str) -> int | None:
    """Convert XLF trans-unit id (e.g. 't4') to XTM integer segment ID (4)."""
    if unit_id.startswith("t") and unit_id[1:].isdigit():
        return int(unit_id[1:])
    # Fallback: try parsing segmentId from xtm:url if available
    return None


def _read_xlf(
    path: Path,
) -> tuple[list[tuple[int, str]], dict[int, tuple[ET.Element, ET.Element]]]:
    """Return (segments, xlf_data) from a *_GERMAN.xlf file.

    segments:  (unit_id, translation_text) pairs; skips units with no <target>.
    xlf_data:  unit_id → (source_elem, target_elem) for XLF-driven tag placement.
    """
    for _event, pair in ET.iterparse(str(path), events=["start-ns"]):
        ET.register_namespace(*pair)

    tree = ET.parse(path)
    segments: list[tuple[int, str]] = []
    xlf_data: dict[int, tuple[ET.Element, ET.Element]] = {}

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

        source = tu.find(_ns("source"))
        text = _target_text(target)
        segments.append((seg_id, text))
        if source is not None:
            xlf_data[seg_id] = (source, target)

    return segments, xlf_data


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
    segments, xlf_data = _read_xlf(xlf_path)

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

    tag_stats: dict[str, list[int]] = {}

    # KNOWN ISSUE: paragraph-number-only segments of the form X [NNNN] X SP
    # (no body text after SP) are uploaded with both X tags before [NNNN] instead
    # of one before and one after.  Root cause not yet identified; needs further
    # investigation.  Segments WITH body text after SP place tags correctly.
    def _xlf_node_builder(unit_id: int, source_nodes: list[dict]):
        if unit_id not in xlf_data:
            return None, None
        xlf_src, xlf_tgt = xlf_data[unit_id]
        nodes, outcome = _xlf_target_to_nodes(xlf_src, xlf_tgt, source_nodes)
        if outcome == "xlf_driven" and nodes:
            # Reclassify as 'piled' when INLINEs are piled before the first TEXT node.
            # Trailing INLINEs (after last TEXT) are legitimate end-of-segment markers
            # and must NOT be flagged. Only flag when at least one INLINE precedes the
            # first TEXT and no INLINE sits between two TEXT nodes (mid-text).
            text_idx    = [i for i, n in enumerate(nodes) if n.get("type") == "TEXT"]
            inline_idx  = [i for i, n in enumerate(nodes) if n.get("type") == "INLINE"]
            if text_idx and inline_idx:
                first_text, last_text = text_idx[0], text_idx[-1]
                has_pre  = any(i < first_text for i in inline_idx)
                has_mid  = any(first_text < i < last_text for i in inline_idx)
                if has_pre and not has_mid:
                    # Fall through to _build_target_nodes: it extracts the leading
                    # text prefix correctly (e.g. "[0013]") and places INLINEs after
                    # it, whereas the XLF-driven nodes have them before.
                    return None, "piled"
        return nodes, outcome

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
        tsk = _find_task(_get_tasks(s), project_id, file_filter=FILE_FILTER)
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

        batch_results = _upload_via_stomp(
            session, session_token, csrf_token, batch,
            target_node_builder=_xlf_node_builder,
            tag_stats=tag_stats,
        )

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

    xlf_driven = tag_stats.get("xlf_driven", [])
    piled      = tag_stats.get("piled", [])
    no_nodes   = tag_stats.get("no_xtm_nodes", [])
    if xlf_driven or piled or no_nodes:
        print()
        print("=== Tag placement summary ===")
        print(f"  XLF-driven (sequences matched): {len(xlf_driven)}")
        if xlf_driven:
            print(f"    Segments: {xlf_driven}")
        print(f"  Piled at boundary (mismatch):   {len(piled)}")
        if piled:
            print(f"    Segments: {piled}")
        print(f"  Plain text (no XTM INLINE nodes): {len(no_nodes)}")
        if no_nodes:
            print(f"    Segments: {no_nodes}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument(
        "--segments", "-s", default=None,
        help="Comma-separated segment IDs to (re-)upload, e.g. 18,22,23,28. "
             "Overrides START_FROM_SEGMENT_ID and TEST_SEGMENT_LIMIT.",
    )
    ap.add_argument(
        "--seg-range", default=None, metavar="START-END",
        help="Inclusive segment ID range to upload, e.g. 421-483.",
    )
    ap.add_argument(
        "--file", default=None,
        help="Filename substring to select the right task when a project has multiple files, e.g. 'Claims'.",
    )
    args = ap.parse_args()

    if args.segments:
        try:
            global SEGMENT_ID_FILTER
            SEGMENT_ID_FILTER = {int(x.strip()) for x in args.segments.split(",")}
        except ValueError:
            print("ERROR: --segments must be comma-separated integers, e.g. 18,22,23")
            raise SystemExit(1)

    if args.file:
        global FILE_FILTER
        FILE_FILTER = args.file

    if args.seg_range:
        try:
            parts = args.seg_range.split("-")
            start, end = int(parts[0].strip()), int(parts[1].strip())
            global START_FROM_SEGMENT_ID, TEST_SEGMENT_LIMIT
            START_FROM_SEGMENT_ID = start
            TEST_SEGMENT_LIMIT    = end - start + 1
        except (ValueError, IndexError):
            print("ERROR: --seg-range must be START-END, e.g. 421-483")
            raise SystemExit(1)

    try:
        run(args.project_id)
    except (RuntimeError, TimeoutError) as e:
        print(f"\nError: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
