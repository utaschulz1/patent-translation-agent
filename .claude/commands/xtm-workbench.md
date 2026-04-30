# XTM Workbench skill

You are helping with `xtm_upload_translations.py`, a script that pushes revised translations
from Excel into the XTM Workbench via its STOMP-over-SockJS WebSocket API.

## Step 1 — Load context

Before answering, read:
1. The script itself: `xtm_upload_translations.py`
2. The memory file at `C:\Users\utasc\.claude\projects\c--Users-utasc-OneDrive-Dokumente-Code-Python-patent-translation-agent\memory\xtm_websocket_protocol.md`

## Step 2 — Domain knowledge (authoritative, apply without re-deriving)

### Transport
STOMP over SockJS WebSocket at:
`wss://word.welocalize.com/workbench/ws/{server_id}/{session_id}/websocket?_s={session_token}`
Messages are JSON arrays wrapping STOMP frames.

---

### TRANS_UNIT_UPDATED — two payload shapes

XTM sends this message in two structurally different forms depending on how the segment
arrived in the cache:

**Direct activation** (segment you just sent `/workbench/trans-unit/activate` for):
```json
{ "id": 354, "source": {"nodes": [...]}, "matchesInfo": {...} }
```
Source nodes are at `payload["source"]["nodes"]`.

**Prefetch** (server proactively sends N+1 while you activate N):
```json
{ "id": 355, "matchesInfo": {"matches": [{"source": {"nodes": [...]}, ...}]} }
```
No top-level `"source"` key. Source nodes are under `payload["matchesInfo"]["matches"][0]["source"]["nodes"]`.

When N+1 is later activated the server does NOT resend a TU_UPDATED for it; it prefetches N+2.

**Extraction order in code:**
```python
source_nodes = tu_payload.get("source", {}).get("nodes", [])
if not source_nodes:
    _matches = tu_payload.get("matchesInfo", {}).get("matches", [])
    if _matches:
        source_nodes = _clean_source_nodes(_matches[0].get("source", {}).get("nodes", []))
```
`_clean_source_nodes` strips DELETION-decorated nodes (fuzzy diff artefacts).

---

### Match classification and what happens per type

`_best_match = (tu_payload.get("matchesInfo", {}).get("matches") or [{}])[0]`

| Match type | Detection | `auto_confirm_label` | Target used |
|---|---|---|---|
| No match / not in cache | `_best_match == {}` | `None` | `_build_target_nodes([], excel_text)` — plain TEXT, **no tags** |
| Fuzzy < 100% | `_match_quality` is non-empty and ≠ `"100%"` | `None` | `_build_target_nodes(source_nodes, excel_text)` |
| 100% (non-MT) | `matchQuality == "100%"` and `matchType != "MACHINE_TRANSLATION"` | `"100%"` | `matches[0]["target"]["nodes"]` (XTM pre-fill) |
| Internal repetition | `repetitionType == "INTERNAL"` and not fuzzy | `"repetition"` | `matches[0]["target"]["nodes"]` (XTM pre-fill) |
| ICE | `iceMatch == True` and not fuzzy | `"ICE"` | `matches[0]["target"]["nodes"]` (XTM pre-fill) |

**Label precedence:** ICE > repetition > 100%

**Critical gotcha — untranslated internal repetitions:**
XTM marks a segment as `repetitionType = "INTERNAL"` even when the first occurrence of that
segment has NOT been translated yet. In that case `matches[0]["target"]["nodes"]` may be `[]`
(empty) or contain whatever fuzzy TM hit was pre-filled for the first occurrence — not a
confirmed translation. The `_is_fuzzy` guard in the code catches this when `matchQuality`
is a fuzzy percentage, but if the repetition has no `matchQuality` at all and empty target
nodes, the code will send `{"nodes": []}` to XTM and XTM's behaviour is unspecified.

**How to identify an untranslated repetition:**
- `repetitionType == "INTERNAL"` is set, AND
- `matchQuality` is a fuzzy percentage (e.g. `"75%"`), OR
- `matches[0]["target"]["nodes"]` is `[]` or absent

---

### Upload flow (critical ordering)

```
[init]  activate(seg[0], forceTransUnitsUpdate=true) → wait_for TU_UPDATED (unit_id=seg[0])

[loop]  for each segment i:
          classify match type from tu_updates[unit_id]
          build target_nodes (TM pre-fill OR _build_target_nodes(source_nodes, excel_text))
          send /workbench/save-unit
          send /workbench/trans-unit/activate(seg[i+1], forceTransUnitsUpdate=true)  ← MUST come before waiting
          drain 9 s:
            collect SAVE_RESPONSE        → check result.type == "SUCCESS"
            collect TU_UPDATED(seg[i+1]) → cache tu_updates[seg[i+1]]
```

XTM does not process the save until it receives the activate for the next segment.
Waiting for SAVE_RESPONSE BEFORE sending activate causes an infinite deadlock.

---

### Tag placement in `_build_target_nodes`

- No INLINE in source → `[TEXT(excel_text)]`
- INLINEs present — split by position of last TEXT node in source:
  - opening INLINEs (index < last TEXT): `[TEXT(prefix), INLINE, TEXT(" " + translation)]`
  - closing INLINEs (index > last TEXT): `[TEXT(translation), INLINE]`
  - space goes AFTER the tag, not before it

---

### Known operational limits

| Issue | Detail |
|---|---|
| SESSION_EXPIRED | Server terminates STOMP session after ~15 segment operations. `RECONNECT_EVERY` reconnects before the limit, reusing the same `_s` token. Saves beyond ~13 segments per connection may time out. |
| Document lock | `openEditor.serv readOnly=false` takes an exclusive write lock. Lock persists if process crashes before the `finally` block sends `DISCONNECT\n\n\x00`. Recovery: wait ~15–30 min or ask PM to force-release. |
| Empty target nodes on auto-confirm | If `matches[0]["target"]["nodes"] == []` for an ICE/100%/rep segment, the save sends empty nodes and XTM behaviour is unknown. |

---

## Step 3 — Typical tasks this skill is invoked for

- **Debugging save failures**: check SAVE_RESPONSE `result.type` and `result.message`; check whether `tu_updates` has the segment's payload; check source node shape.
- **Diagnosing wrong translations saved**: determine which match type fired for the segment by checking `_match_quality`, `iceMatch`, `repetitionType` in the cached payload. Enable `DEBUG_SOURCE_NODES_LIMIT` to print raw payloads.
- **Extending the script**: respect the activate-before-SAVE_RESPONSE ordering; always pass `forceTransUnitsUpdate: true`; always send DISCONNECT in the finally block.
- **Investigating a specific segment**: set `START_FROM_SEGMENT_ID` to the segment ID and `TEST_SEGMENT_LIMIT = 1`; set `DEBUG_SOURCE_NODES_LIMIT = 1` to dump the raw TU_UPDATED payload.
