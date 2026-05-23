"""
xtm_probe_preview_types.py — Find valid previewType values for XTM Workbench.

Logs in, opens the workbench, then tries each candidate previewType over WebSocket
with a short timeout. Reports which ones get any server response.

Usage:
    python xtm_probe_preview_types.py <project_id>
"""

import json
import random
import string
import sys
import time

import xtm_initial_download as _xtm

CANDIDATES = [
    # target docx candidates
    "TARGET_FILE",
    "GENERATE_TARGET_FILES",
    "TRANSLATED_DOCUMENT",
    "TARGET",
    "DOWNLOAD_TARGET",
    "TRANSLATED_TARGET_FILE",
    "TARGET_ONLY",
    "DOCX",
    # pdf candidates
    "PDF_BILINGUAL",
    "PDF",
    "BILINGUAL_PDF",
    "PDF_SOURCE_TARGET_TABLE",
    "PDF_SRC_TGT",
    "PDF_PREVIEW",
    "SOURCE_TARGET_PDF",
]

PROBE_TIMEOUT = 8   # seconds to wait per candidate before giving up


def _probe(session, session_token, csrf_token, preview_type: str) -> bool:
    """Return True if the server responds to this previewType within PROBE_TIMEOUT seconds."""
    import websocket as _websocket

    server_id = str(random.randint(0, 999)).zfill(3)
    session_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    ws_url = (
        f"wss://word.welocalize.com/workbench/ws/{server_id}/{session_id}"
        f"/websocket?_s={session_token}"
    )
    cookie_str = "; ".join(f"{c.name}={c.value}" for c in session.cookies)

    ws = _websocket.WebSocket()
    ws.settimeout(5)
    try:
        ws.connect(ws_url, cookie=cookie_str)
        ws.recv()  # SockJS open frame

        connect_frame = (
            f"CONNECT\nX-CSRF-TOKEN:{csrf_token}\n"
            f"accept-version:1.0,1.1,1.2\nheart-beat:10000,10000\n\n\x00"
        )
        ws.send(json.dumps([connect_frame]))
        ws.recv()  # CONNECTED

        ws.send(json.dumps(["SUBSCRIBE\nid:sub-0\ndestination:/user/queue/main\n\n\x00"]))

        request_id = str(int(time.time() * 1000))
        body = json.dumps({"requestId": request_id, "previewType": preview_type})
        send_frame = (
            f"SEND\ndestination:/workbench/document/preview/generate\n"
            f"_s:{session_token}\ncontent-length:{len(body)}\n\n{body}\x00"
        )
        ws.send(json.dumps([send_frame]))

        ws.settimeout(2)
        deadline = time.time() + PROBE_TIMEOUT
        messages = []
        while time.time() < deadline:
            try:
                raw = ws.recv()
                if raw and raw not in ("h", "o"):
                    messages.append(raw[:200])
                    if "PREVIEW_GENERATION" in raw or "ERROR" in raw.upper():
                        break
            except _websocket.WebSocketTimeoutException:
                continue
        return bool(messages), messages
    except Exception as e:
        return False, [f"exception: {e}"]
    finally:
        try:
            ws.close()
        except Exception:
            pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python xtm_probe_preview_types.py <project_id>")
        raise SystemExit(1)

    project_id = sys.argv[1]
    print("Logging in and opening workbench...")
    session, session_token, csrf_token = _xtm._setup_session(project_id)
    print(f"Ready. Probing {len(CANDIDATES)} previewType candidates ({PROBE_TIMEOUT}s each)...\n")

    results = {}
    for pt in CANDIDATES:
        print(f"  {pt:<35}", end="", flush=True)
        got_response, messages = _probe(session, session_token, csrf_token, pt)
        status = "RESPONSE" if got_response else "silent"
        print(status)
        if got_response:
            for m in messages:
                print(f"    {m[:120]}")
        results[pt] = got_response
        time.sleep(1)

    print("\n=== Summary ===")
    for pt, ok in results.items():
        if ok:
            print(f"  GOT RESPONSE: {pt}")
    no_response = [pt for pt, ok in results.items() if not ok]
    if no_response:
        print(f"  Silent ({len(no_response)}): {', '.join(no_response)}")


if __name__ == "__main__":
    main()
