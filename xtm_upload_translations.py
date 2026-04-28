"""
xtm_upload_translations.py  —  XTM Workbench: upload revised translations from Excel

Reads segment IDs (Column A) and translation text (Column C) from a
*_revised_translation_checks*.xlsx file and pushes each translation into the
matching XTM segment via the STOMP WebSocket protocol.

Rows 1–3 of the Excel are header rows and are skipped automatically.
Column A must contain the integer segment ID that matches the XTM unitId.

Usage:
    python xtm_upload_translations.py <project_id>
    e.g.  python xtm_upload_translations.py AIPX_2604_P0012
"""

import json
import os
import random
import re
import string
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import openpyxl
import requests
import websocket as _websocket
from dotenv import load_dotenv

from xtm_xlsx_download_w_API import (
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

KEEPALIVE_INTERVAL = 25  # seconds between /sayHelloToServer.serv calls
RECONNECT_EVERY    = 15  # reopen WebSocket every N segments to prevent server state buildup
TEST_SEGMENT_LIMIT: int | None = 10   # set to None to process all segments
START_FROM_SEGMENT_ID: int = 358     # skip segments with ID below this value
DEBUG_SOURCE_NODES_LIMIT = 10       # print source nodes for first N segments; set to 0 to disable


# ---------------------------------------------------------------------------
# Claim group task (USERGROUP → INTERNALLINGUIST)
# ---------------------------------------------------------------------------

def _claim_group_task(
    session: requests.Session, task: dict, uust: str, project_id: str
) -> dict:
    """If the task actor is USERGROUP, claim it so the actor becomes INTERNALLINGUIST.

    XTM's openEditor.serv will return 'There is no requested document' when called
    with actorType=INTERNALLINGUIST on an unclaimed USERGROUP task.  This step must
    run before _open_editor_write.  Returns the (possibly updated) task dict.
    """
    ad = task["additionalData"]
    actor_type = ad.get("actorType", "USERGROUP")

    if actor_type == "INTERNALLINGUIST":
        print("  Task already assigned to INTERNALLINGUIST, skipping claim step.")
        return task

    print(f"  Task actor is '{actor_type}', claiming as INTERNALLINGUIST...")

    # Log CONTEXT_MENU so the correct endpoint can be identified if this fails
    context_menu = task.get("CONTEXT_MENU", "")
    if context_menu:
        print(f"  CONTEXT_MENU: {str(context_menu)[:600]}")

    r = session.post(
        f"{BASE_URL}/myinbox/takeGroupTask.serv",
        data={
            "stepReferenceId": ad["stepReferenceId"],
            "fileId":          ad["fileId"],
            "uust":            uust,
        },
    )
    print(f"  Claim response: {r.status_code} — {r.text[:300]}")

    if not r.ok:
        print(
            "  Warning: claim request failed.  Will attempt to open editor anyway.\n"
            "  If the next step fails, please claim the task manually in XTM and re-run."
        )
        return task

    # Re-fetch the task list so the updated actorType is visible
    time.sleep(2)
    updated_tasks = _get_tasks(session)
    updated_task = _find_task(updated_tasks, project_id)
    new_actor = updated_task["additionalData"].get("actorType", "?")
    print(f"  Updated actor type: {new_actor}")
    return updated_task


# ---------------------------------------------------------------------------
# Open editor for writing (readOnly=false)
# ---------------------------------------------------------------------------

def _open_editor_write(
    session: requests.Session, task: dict, uust: str
) -> tuple[str, str]:
    """POST to openEditor.serv with readOnly=false, return (wb_url, session_token)."""
    ad = task["additionalData"]
    payload = {
        "actorType":                  "INTERNALLINGUIST",
        "fileId":                     ad["fileId"],
        "groupTaskAction":            "undefined",
        "isGroupTaskWithPriorities":  "false",
        "readOnly":                   "false",
        "workflowStepName":           ad.get("stepName", ""),
        "stepReferenceId":            ad["stepReferenceId"],
        "taskType":                   "ACTIVE",
        "workflowReferenceStepName":  ad.get("stepReferenceName", ""),
        "uust":                       uust,
    }
    _MAX_ATTEMPTS = 3
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        r = session.post(
            f"{BASE_URL}/openEditor.serv",
            data=payload,
            allow_redirects=False,
        )
        r.raise_for_status()
        xml = r.text
        if "<result>error</result>" not in xml:
            break
        msg_m = re.search(r"<msg>(.*?)</msg>", xml)
        msg = msg_m.group(1) if msg_m else xml[:200]
        if attempt == _MAX_ATTEMPTS:
            raise RuntimeError(f"openEditor error after {_MAX_ATTEMPTS} attempts: {msg}")
        print(f"  openEditor attempt {attempt} failed ({msg}), retrying in 5s...")
        time.sleep(5)

    url_m = (
        re.search(r"<url>(.*?)</url>", xml, re.DOTALL)
        or re.search(r"<msg>(https?://.*?)</msg>", xml, re.DOTALL)
    )
    if url_m:
        wb_url = url_m.group(1).strip().replace("&amp;", "&")
    elif r.headers.get("Location"):
        wb_url = r.headers["Location"]
    else:
        raise RuntimeError(f"Cannot parse openEditor response:\n{xml[:500]}")

    session_token = parse_qs(urlparse(wb_url).query).get("_s", [None])[0]
    if not session_token:
        raise RuntimeError(f"No _s token in workbench URL: {wb_url}")
    return wb_url, session_token


# ---------------------------------------------------------------------------
# Excel helpers
# ---------------------------------------------------------------------------

def _find_excel(project_id: str) -> Path:
    """Find *_revised_translation_checks*.xlsx in the project pre-processing folder."""
    pre = _find_pre_folder(project_id)
    matches = list(pre.glob("*_revised_translation_checks*.xlsx"))
    if not matches:
        raise RuntimeError(
            f"No *_revised_translation_checks*.xlsx found in {pre}\n"
            f"Run the glossary check step first."
        )
    if len(matches) > 1:
        print(f"  Warning: multiple Excel files found, using {matches[0].name}")
    return matches[0]


def _read_translations(path: Path) -> list[tuple[int, str]]:
    """Return list of (unitId, translation_text) from Column A and C.

    Rows 1–3 are headers and are skipped. Empty Column C cells are kept as
    empty strings so the position mapping stays intact.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    # Validate that Column C is the translation column by checking the header rows
    header_values = [
        str(ws.cell(row=r, column=3).value or "").strip()
        for r in range(1, 4)
    ]
    MARKERS = ("target", "german", "de")
    if not any(
        marker in cell.lower()
        for cell in header_values
        for marker in MARKERS
    ):
        raise ValueError(
            f"Column C in {path.name} does not look like a translation column.\n"
            f"  Header rows (C1–C3): {header_values}\n"
            f"  Expected one of {MARKERS} (case-insensitive) in the first 3 rows."
        )

    segments: list[tuple[int, str]] = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        unit_id = row[0]
        text = row[2]  # Column C
        if unit_id is None:
            continue
        segments.append((int(unit_id), str(text).strip() if text is not None else ""))
    return segments


def _write_results_to_excel(path: Path, results: dict[int, str]) -> None:
    """Append an 'Upload Status' column to the Excel file with per-segment outcomes."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active

    # Reuse existing Upload Status column if present, otherwise append one
    status_col = ws.max_column + 1
    for col in range(1, ws.max_column + 1):
        if str(ws.cell(row=2, column=col).value or "").strip().lower() == "upload status":
            status_col = col
            break

    ws.cell(row=2, column=status_col).value = "Upload Status"

    for row in range(4, ws.max_row + 1):
        unit_id = ws.cell(row=row, column=1).value
        if unit_id is None:
            continue
        ws.cell(row=row, column=status_col).value = results.get(int(unit_id), "not attempted")

    wb.save(path)
    print(f"  Results written to column {status_col} of {path.name}")


# ---------------------------------------------------------------------------
# STOMP helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    """Current epoch milliseconds as a string, used as requestId."""
    return str(int(time.time() * 1000))


def _make_send_frame(destination: str, session_token: str, body: dict) -> str:
    """Wrap a STOMP SEND frame in the SockJS array envelope."""
    body_str = json.dumps(body, ensure_ascii=False)
    body_bytes = body_str.encode("utf-8")
    frame = (
        f"SEND\ndestination:{destination}\n"
        f"_s:{session_token}\ncontent-length:{len(body_bytes)}\n\n"
        f"{body_str}\x00"
    )
    return json.dumps([frame])


def _parse_stomp_messages(raw: str) -> list[dict]:
    """Extract parsed JSON payloads from a SockJS 'a[...]' frame."""
    if not raw.startswith("a"):
        return []
    results = []
    for frame in json.loads(raw[1:]):
        sep = frame.rfind("\n\n")
        if sep == -1:
            continue
        body_str = frame[sep + 2:].rstrip("\x00")
        if not body_str:
            continue
        try:
            msg = json.loads(body_str)
        except json.JSONDecodeError:
            continue
        results.append(msg)
    return results


# ---------------------------------------------------------------------------
# Tag-aware target node builder
# ---------------------------------------------------------------------------

def _build_target_nodes(source_nodes: list[dict], excel_text: str) -> list[dict]:
    """Build target nodes preserving INLINE tags from the source in correct positions.

    Handles two patterns seen in patent documents:
      X-type (standalone):  [0033]<INLINE/> text
      G-type (paired):      [0033]<INLINE> text <INLINE>

    Strategy: split INLINEs by their position relative to the last TEXT node in source.
    INLINEs that appear before the last TEXT = opening tags (go before translation).
    INLINEs that appear after the last TEXT  = closing tags (go after translation).
    This correctly places the closing G tag at the end instead of bunching all tags at the start.
    """
    if not any(n.get("type") == "INLINE" for n in source_nodes):
        return [{"type": "TEXT", "decorations": [], "content": excel_text}]

    # Source prefix: TEXT content before the first INLINE
    prefix = ""
    for node in source_nodes:
        if node.get("type") != "TEXT":
            break
        prefix += node.get("content", "")

    # Split INLINEs into opening (before last TEXT) and closing (after last TEXT)
    last_text_idx = max(
        (j for j, n in enumerate(source_nodes) if n.get("type") == "TEXT"),
        default=-1,
    )
    opening = [{**n} for j, n in enumerate(source_nodes) if n.get("type") == "INLINE" and j < last_text_idx]
    closing = [{**n} for j, n in enumerate(source_nodes) if n.get("type") == "INLINE" and j > last_text_idx]

    if not opening:
        # Trailing-only INLINE (e.g. "text <X/>") — no prefix, tag goes after translation
        return [{"type": "TEXT", "decorations": [], "content": excel_text}, *closing]

    # Strip the paragraph-number prefix from the Excel text (e.g. "[0033]")
    text = excel_text
    prefix_stripped = prefix.strip()
    if prefix_stripped and text.startswith(prefix_stripped):
        text = text[len(prefix_stripped):].lstrip()

    nodes: list[dict] = []
    if prefix_stripped:
        nodes.append({"type": "TEXT", "decorations": [], "content": prefix_stripped + " "})
    nodes.extend(opening)
    nodes.append({"type": "TEXT", "decorations": [], "content": text})
    nodes.extend(closing)
    return nodes


# ---------------------------------------------------------------------------
# Upload loop
# ---------------------------------------------------------------------------

def _upload_via_stomp(
    session: requests.Session,
    session_token: str,
    csrf_token: str,
    segments: list[tuple[int, str]],
) -> dict[int, str]:
    """Connect to the workbench WebSocket and upload all translations."""
    server_id = str(random.randint(0, 999)).zfill(3)
    session_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    ws_url = (
        f"wss://word.welocalize.com/workbench/ws/{server_id}/{session_id}"
        f"/websocket?_s={session_token}"
    )
    cookie_str = "; ".join(f"{c.name}={c.value}" for c in session.cookies)

    ws = _websocket.WebSocket()
    ws.connect(ws_url, cookie=cookie_str)
    ws.settimeout(5)  # short per-recv timeout so wait_for checks deadline frequently

    last_keepalive = time.time()
    tu_updates: dict[int, dict] = {}  # unit_id → TRANS_UNIT_UPDATED payload cache

    def send(destination: str, body: dict) -> None:
        ws.send(_make_send_frame(destination, session_token, body))

    def maybe_keepalive() -> None:
        nonlocal last_keepalive
        if time.time() - last_keepalive >= KEEPALIVE_INTERVAL:
            _keepalive(session)
            last_keepalive = time.time()

    def wait_for(msg_type: str, timeout: float = 30.0, unit_id: int | None = None) -> dict:
        """Recv WebSocket frames until a matching message arrives; return its payload.

        All TRANS_UNIT_UPDATED messages seen along the way are cached in tu_updates.
        If unit_id is given, only a message whose payload.unitId matches will satisfy
        the wait (useful for TRANS_UNIT_UPDATED to avoid stopping on a stale broadcast
        for the segment we just saved rather than the one we just activated).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = ws.recv()
            except _websocket.WebSocketTimeoutException:
                continue  # normal: no data in this 5 s window, check deadline and retry
            except (
                _websocket.WebSocketConnectionClosedException,
                _websocket.WebSocketProtocolException,
                OSError,
            ) as exc:
                raise RuntimeError(f"WebSocket connection lost while waiting for {msg_type}: {exc}") from exc
            if not raw or raw == "h":
                continue
            for msg in _parse_stomp_messages(raw):
                if msg.get("type") == "TRANS_UNIT_UPDATED":
                    p = msg.get("payload", {})
                    uid = p.get("unitId", p.get("id"))
                    if uid is not None:
                        tu_updates[uid] = p
                if msg.get("type") == msg_type:
                    p = msg.get("payload", {})
                    if unit_id is None or p.get("unitId", p.get("id")) == unit_id:
                        return p
        raise TimeoutError(f"Timed out after {timeout}s waiting for {msg_type} (unit_id={unit_id})")

    def _stomp_handshake() -> None:
        """Perform SockJS open + STOMP CONNECT + SUBSCRIBE on the current ws."""
        ws.recv()  # SockJS open frame 'o'
        connect_frame = (
            f"CONNECT\nX-CSRF-TOKEN:{csrf_token}\n"
            f"accept-version:1.0,1.1,1.2\nheart-beat:10000,10000\n\n\x00"
        )
        ws.send(json.dumps([connect_frame]))
        ws.recv()  # CONNECTED
        ws.send(json.dumps(["SUBSCRIBE\nid:sub-0\ndestination:/user/queue/main\n\n\x00"]))

    def _reconnect(current_unit_id: int) -> None:
        """Close the current WebSocket and open a fresh one, restoring STOMP state.

        Reassigning `ws` here (via nonlocal) is seen by all other inner functions
        because they read `ws` from the enclosing scope at call time.
        """
        nonlocal ws, last_keepalive
        print(f"  [{current_unit_id}/{segments[-1][0]}] Reconnecting WebSocket...")
        try:
            ws.close()
        except Exception:
            pass
        new_server_id  = str(random.randint(0, 999)).zfill(3)
        new_session_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        new_ws_url = (
            f"wss://word.welocalize.com/workbench/ws/{new_server_id}/{new_session_id}"
            f"/websocket?_s={session_token}"
        )
        ws = _websocket.WebSocket()
        ws.connect(new_ws_url, cookie=cookie_str)
        ws.settimeout(5)
        _stomp_handshake()
        send("/workbench/readChatInfo", {"requestId": _ts()})
        send("/workbench/document/init/rendered", {"requestId": _ts()})
        send("/workbench/trans-unit/activate", {
            "requestId": _ts(),
            "activatedTransUnitId": current_unit_id,
            "forceTransUnitsUpdate": True,
        })
        wait_for("TRANS_UNIT_UPDATED", timeout=15, unit_id=current_unit_id)
        last_keepalive = time.time()
        print("  Reconnected.")

    try:
        _stomp_handshake()

        # --- Init sequence ---
        send("/workbench/readChatInfo", {"requestId": _ts()})
        send("/workbench/document/init/rendered", {"requestId": _ts()})

        # --- Wait for first TRANS_UNIT_UPDATED; retry up to 3 times if server is slow ---
        _MAX_INIT_ATTEMPTS = 3
        _INIT_TIMEOUT = 15  # seconds per attempt
        for attempt in range(1, _MAX_INIT_ATTEMPTS + 1):
            send("/workbench/trans-unit/activate", {
                "requestId": _ts(),
                "activatedTransUnitId": segments[0][0],
                "forceTransUnitsUpdate": attempt > 1,  # force resend on retry
            })
            try:
                payload = wait_for("TRANS_UNIT_UPDATED", timeout=_INIT_TIMEOUT)
                tu_updates[segments[0][0]] = payload  # cache init segment
                break
            except TimeoutError:
                if attempt == _MAX_INIT_ATTEMPTS:
                    raise TimeoutError(
                        f"Server did not send TRANS_UNIT_UPDATED after "
                        f"{_MAX_INIT_ATTEMPTS} attempts ({_INIT_TIMEOUT}s each)"
                    )
                print(f"  No response from server (attempt {attempt}/{_MAX_INIT_ATTEMPTS}), retrying...")
        print(f"  Document: {payload.get('workbenchDocumentId', '?')}")
        # Print first segment state to help diagnose save errors
        debug_keys = ["status", "locked", "segmentType", "actorType", "workflowStepType",
                      "canEdit", "editable", "isLocked"]
        debug_info = {k: payload[k] for k in debug_keys if k in payload}
        if not debug_info:
            # Fall back to the full payload (truncated) so nothing is hidden
            debug_info = str(payload)[:600]
        print(f"  First segment state: {json.dumps(debug_info) if isinstance(debug_info, dict) else debug_info}")

        # --- Per-segment upload ---
        results: dict[int, str] = {}
        last_id = segments[-1][0]
        total = len(segments)
        consecutive_errors = 0
        _MAX_CONSECUTIVE_ERRORS = 10  # abort early if server keeps rejecting every save
        _debug_printed = 0

        for i, (unit_id, text) in enumerate(segments):
            if i > 0 and i % RECONNECT_EVERY == 0:
                _reconnect(unit_id)

            is_last = (i == total - 1)
            next_uid = segments[i + 1][0] if not is_last else None

            if not text:
                results[unit_id] = "skipped"
                print(f"  [{unit_id}/{last_id}] skipped (empty)")
                if next_uid is not None:
                    send("/workbench/trans-unit/activate", {
                        "requestId": _ts(),
                        "activatedTransUnitId": next_uid,
                        "forceTransUnitsUpdate": True,
                        "deactivatedTransUnitId": unit_id,
                    })
                    try:
                        wait_for("TRANS_UNIT_UPDATED", timeout=15, unit_id=next_uid)
                    except TimeoutError:
                        print(f"  [{unit_id}/{last_id}] Warning: no TRANS_UNIT_UPDATED for segment {next_uid} after skip")
                maybe_keepalive()
                continue

            word_count = len(text.split())
            preview = text[:70] + ("…" if len(text) > 70 else "")

            try:
                tu_payload = tu_updates.get(unit_id, {})
                source_nodes = tu_payload.get("source", {}).get("nodes", [])
                if not source_nodes:
                    _matches = tu_payload.get("matchesInfo", {}).get("matches", [])
                    if _matches:
                        source_nodes = _matches[0].get("source", {}).get("nodes", [])
                have_source = bool(source_nodes)
                target_nodes = _build_target_nodes(source_nodes, text)

                if DEBUG_SOURCE_NODES_LIMIT and _debug_printed < DEBUG_SOURCE_NODES_LIMIT:
                    raw_tu = tu_updates.get(unit_id)
                    print(f"\n  [DEBUG unit {unit_id}] tu_updates entry: {json.dumps(raw_tu, ensure_ascii=False) if raw_tu is not None else 'NOT IN CACHE'}")
                    print(f"  [DEBUG unit {unit_id}] target nodes (sending): {json.dumps(target_nodes, ensure_ascii=False)}\n")
                    _debug_printed += 1
                elif not have_source:
                    print(f"  [{unit_id}/{last_id}] WARNING: source nodes not received — saving as plain text (tags may be lost)")

                ts_ms = int(time.time() * 1000)
                send("/workbench/save-unit", {
                    "requestId": str(ts_ms),
                    "units": [{
                        "target": {"nodes": target_nodes},
                        "status": "DONE",
                        "statusOrigin": "M",
                        "timeTracking": {"timeSpent": min(20_000, max(2_000, word_count * 500))},
                        "unitId": unit_id,
                    }],
                })

                # Immediately activate next segment — XTM processes the save only after
                # seeing activate (mirrors browser: confirm button + click next = hourglass).
                if next_uid is not None:
                    send("/workbench/trans-unit/activate", {
                        "requestId": _ts(),
                        "activatedTransUnitId": next_uid,
                        "forceTransUnitsUpdate": True,
                        "deactivatedTransUnitId": unit_id,
                    })

                # Drain until both SAVE_RESPONSE for this segment and TRANS_UNIT_UPDATED
                # for the next are in hand — both arrive shortly after the activate above.
                save_resp = None
                next_tu_ready = (next_uid is None)
                deadline = time.time() + 30.0
                while time.time() < deadline and not (save_resp is not None and next_tu_ready):
                    try:
                        raw = ws.recv()
                    except _websocket.WebSocketTimeoutException:
                        continue
                    except (
                        _websocket.WebSocketConnectionClosedException,
                        _websocket.WebSocketProtocolException,
                        OSError,
                    ) as exc:
                        raise RuntimeError(f"WebSocket connection lost: {exc}") from exc
                    if not raw or raw == "h":
                        continue
                    for msg in _parse_stomp_messages(raw):
                        mtype = msg.get("type")
                        p = msg.get("payload", {})
                        if mtype == "TRANS_UNIT_UPDATED":
                            uid = p.get("unitId", p.get("id"))
                            print(f"    [DRAIN] TU_UPDATED uid={uid} (want {next_uid}){' ←' if uid == next_uid else ''}")
                            if uid is not None:
                                tu_updates[uid] = p
                            if uid == next_uid:
                                next_tu_ready = True
                        elif mtype == "SAVE_RESPONSE":
                            res_type = p.get("result", {}).get("type", "?")
                            print(f"    [DRAIN] SAVE_RESPONSE result={res_type}")
                            save_resp = p
                        elif mtype and mtype != "PROGRESS_UPDATE":
                            print(f"    [DRAIN] other: {mtype}")

                if not next_tu_ready:
                    print(f"  [{unit_id}/{last_id}] Warning: no TRANS_UNIT_UPDATED for segment {next_uid}, tags may be missing")

                result_type = save_resp.get("result", {}).get("type", "UNKNOWN") if save_resp else "TIMEOUT"
                if result_type != "SUCCESS":
                    reason = save_resp.get("result", {}).get("message", result_type) if save_resp else "timeout after 30s"
                    results[unit_id] = f"failed: {reason}"
                    consecutive_errors += 1
                    print(f"  [{unit_id}/{last_id}] FAILED: {reason}  ({word_count}w)")
                    print(f"    DEBUG full SAVE_RESPONSE: {json.dumps(save_resp, ensure_ascii=False)}")
                    if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                        print(
                            f"\n  Aborting: {consecutive_errors} consecutive save errors — "
                            "server is rejecting all writes.  Check step type and permissions.\n"
                            "  Mark remaining segments as 'not attempted'."
                        )
                        for uid, _ in segments[i + 1:]:
                            results[uid] = "not attempted"
                        break
                else:
                    consecutive_errors = 0
                    if have_source:
                        results[unit_id] = "saved"
                        print(f"  [{unit_id}/{last_id}] {preview}  ({word_count}w)")
                    else:
                        results[unit_id] = "saved (no source nodes — verify manually)"
                        print(f"  [{unit_id}/{last_id}] UNCERTAIN: {preview}  ({word_count}w) — saved without source nodes")

            except RuntimeError as exc:
                results[unit_id] = f"failed: {exc}"
                print(f"  [{unit_id}/{last_id}] FAILED: {exc}")
                for uid, _ in segments[i + 1:]:
                    results[uid] = "not attempted"
                break

            maybe_keepalive()

        return results

    finally:
        try:
            ws.send(json.dumps(["DISCONNECT\n\n\x00"]))
        except Exception:
            pass
        ws.close()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(project_id: str) -> None:
    """Open XTM Workbench in write mode and upload revised translations."""
    username, password = _load_creds()

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
            "Gecko/20100101 Firefox/149.0"
        ),
    })

    print("Step 1 — Login to XTM Workbench...")
    uust = _login(session, username, password)
    session.headers.update({"uust": uust, "X-Requested-With": "XMLHttpRequest"})

    print("Step 2 — Fetching task list...")
    tasks = _get_tasks(session)
    print(f"  {len(tasks)} task(s) in progress")

    task = _find_task(tasks, project_id)
    ad = task["additionalData"]
    print(f"  Found: {ad.get('projectName', '?')}  (file {ad.get('fileId', '?')})")
    print(f"  Step: {task.get('STEP', '?')}  type: {task.get('STEP_TYPE', '?')}  role: {task.get('ROLE', '?')}  actorType: {ad.get('actorType', '?')}")

    print("Step 3 — Claiming task for INTERNALLINGUIST (if needed)...")
    task = _claim_group_task(session, task, uust, project_id)

    print("Step 4 — Opening workbench editor (write mode)...")
    wb_url, session_token = _open_editor_write(session, task, uust)
    print(f"  Session token: {session_token[:12]}...")

    csrf_token = _init_workbench(session, wb_url, session_token)

    time.sleep(3)
    _keepalive(session)

    print("Step 5 — Reading translations from Excel...")
    excel_path = _find_excel(project_id)
    segments = _read_translations(excel_path)
    if START_FROM_SEGMENT_ID > 1:
        segments = [(uid, t) for uid, t in segments if uid >= START_FROM_SEGMENT_ID]
        print(f"  Starting from segment ID {START_FROM_SEGMENT_ID} ({len(segments)} segments remaining)")
    if TEST_SEGMENT_LIMIT is not None:
        segments = segments[:TEST_SEGMENT_LIMIT]
        print(f"  TEST MODE: capped at {TEST_SEGMENT_LIMIT} segments")
    non_empty = sum(1 for _, t in segments if t)
    print(f"  {len(segments)} segments read ({non_empty} non-empty) from {excel_path.name}")

    print("Step 6 — Uploading translations via WebSocket...")
    results = _upload_via_stomp(session, session_token, csrf_token, segments)

    print("\nStep 7 — Writing results to Excel...")
    _write_results_to_excel(excel_path, results)

    saved         = sum(1 for s in results.values() if s == "saved")
    skipped       = sum(1 for s in results.values() if s == "skipped")
    not_attempted = sum(1 for s in results.values() if s == "not attempted")
    failed        = {uid: s for uid, s in results.items() if s.startswith("failed")}

    print()
    print("=== Upload summary ===")
    print(f"  Saved:         {saved}")
    print(f"  Skipped:       {skipped}  (empty translation)")
    if not_attempted:
        print(f"  Not attempted: {not_attempted}  (connection lost before attempt)")
    print(f"  Failed:        {len(failed)}")
    if failed:
        for uid, reason in sorted(failed.items()):
            print(f"    segment {uid}: {reason}")
    print(f"  Total:         {len(results)}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python xtm_upload_translations.py <project_id>")
        raise SystemExit(1)
    run(sys.argv[1])


if __name__ == "__main__":
    main()
