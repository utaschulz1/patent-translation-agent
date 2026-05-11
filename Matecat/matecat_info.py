# ============================================================
# matecat_info.py
# ============================================================
# Discovery script: prints available MT engines and TM keys
# for your MateCat account. Run once to find:
#   - Lara engine ID  → fill MATECAT_ENGINE_ID in matecat_upload.py
#   - TM key(s)       → assign one per client in matecat_projects.json
#
# USAGE   python matecat_info.py
#
# SETUP
#   Add to .env:
#     MATECAT_API_KEY=yourkey-yoursecret
# ============================================================

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

API_KEY = os.environ.get("MATECAT_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: MATECAT_API_KEY not set in .env")
    print("  Format: MATECAT_API_KEY=yourkey-yoursecret")
    sys.exit(1)

BASE = "https://www.matecat.com"

# Show what we're sending so auth issues are easy to diagnose
_parts = API_KEY.split("-", 1)
print(f"API key loaded: {API_KEY[:4]}...{API_KEY[-4:]}  ({len(API_KEY)} chars, {len(_parts)} part(s) separated by '-')")
if any(c in API_KEY for c in (' ', '\t', '\r', '\n')):
    print(f"  WARNING: key contains whitespace — repr: {repr(API_KEY)}")
print()

# MateCat auth: x-matecat-key header with the combined key-secret string.
# If you see 401 below, check your MateCat profile (Profile → API key) and make
# sure MATECAT_API_KEY in .env contains the full key as shown there.
session = requests.Session()
session.headers.update({"x-matecat-key": API_KEY})


def _get(path: str) -> dict | list:
    r = session.get(f"{BASE}{path}")
    if not r.ok:
        print(f"  HTTP {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    return r.json()


# ── MT engines ───────────────────────────────────────────────────────────────

print("=" * 60)
print("MT ENGINES  (GET /api/v3/engines/list)")
print("=" * 60)
try:
    engines = _get("/api/v3/engines/list")
    if not engines:
        print("  (no engines found — is the API key correct?)")
    for eng in engines if isinstance(engines, list) else engines.get("engines", []):
        eid   = eng.get("id", "?")
        name  = eng.get("name", "?")
        etype = eng.get("type", "?")
        extra = eng.get("description", "") or eng.get("provider", "")
        print(f"  id={eid:<8}  type={etype:<20}  name={name}  {extra}")
except Exception as e:
    print(f"  Error fetching engines: {e}")

# ── TM keys ──────────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("TM KEYS  (GET /api/v3/keys/list)")
print("=" * 60)
try:
    keys_resp = _get("/api/v3/keys/list")
    keys = keys_resp if isinstance(keys_resp, list) else keys_resp.get("tm_keys", [])
    if not keys:
        print("  (no TM keys found)")
    for k in keys:
        key    = k.get("key", "?")
        name   = k.get("name", "?")
        r_flag = "r" if k.get("r") else "-"
        w_flag = "w" if k.get("w") else "-"
        print(f"  key={key:<20}  name={name:<30}  permissions={r_flag}{w_flag}")
except Exception as e:
    print(f"  Error fetching TM keys: {e}")

print()
print("Next steps:")
print("  1. Find Lara in the engines list above → set MATECAT_ENGINE_ID in matecat_upload.py")
print("  2. Choose or note a TM key per client (LABI, RTC, …) → will be stored in matecat_projects.json")
print("  3. If no TM keys exist, create one in the MateCat UI:")
print("     Project Settings → Translation Memory and Termbase → + New resource")
