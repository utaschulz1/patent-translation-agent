# ============================================================
# matecat_glossary_upload.py
# ============================================================
# Uploads clean_glossary_<id>.csv (or glossary_<id>.csv) as
# glossary TERMS to a MateCat TM memory (underline/highlight
# in editor) — separate from the main translation TM.
#
# Discovers the target TM key by querying /api/v3/keys/list
# and matching a name containing "glossary" + project/client.
# Saves the discovered key to matecat_projects.json so future
# uploads skip the discovery step.
#
# USAGE
#   python matecat_glossary_upload.py [--pid <project_id>]
# ============================================================

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

import openpyxl
import requests
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from project_log import project_dir as _pdir

BASE          = "https://www.matecat.com"
PROJECTS_FILE = HERE / "matecat_projects.json"

# ── Auth ──────────────────────────────────────────────────────────────────────

load_dotenv(dotenv_path=ROOT / ".env")
_cookie  = os.environ.get("MATECAT_COOKIE", "").strip()
_api_key = os.environ.get("MATECAT_API_KEY", "").strip()

if _cookie:
    HEADERS = {"Cookie": _cookie}
    print(f"Auth: session cookie ({_cookie[:20]}...)")
elif _api_key:
    HEADERS = {"x-matecat-key": _api_key}
    print(f"Auth: x-matecat-key")
else:
    print("ERROR: set MATECAT_COOKIE or MATECAT_API_KEY in .env")
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────

_ap = argparse.ArgumentParser()
_ap.add_argument("--pid", default=None,
                 help="Project ID (folder under projects/). Defaults to current context.")
_args = _ap.parse_args()

# ── Resolve project ───────────────────────────────────────────────────────────

if _args.pid:
    proj_dir = ROOT / "projects" / _args.pid
    if not proj_dir.exists():
        print(f"ERROR: Project folder not found: {proj_dir}")
        sys.exit(1)
else:
    proj_dir = _pdir()

project_id = proj_dir.name
client     = project_id.split("_")[0]
print(f"Project: {project_id}  (client: {client})")

# ── Find glossary CSV ────────────────────────────────────────────────────────

_clean = proj_dir / f"clean_glossary_{project_id}.csv"
_raw   = proj_dir / f"glossary_{project_id}.csv"
glos_csv = _clean if _clean.exists() else (_raw if _raw.exists() else None)

if not glos_csv:
    print(f"ERROR: No glossary CSV found in {proj_dir}")
    sys.exit(1)
print(f"Glossary CSV: {glos_csv.name}")

# ── Discover glossary TM key ──────────────────────────────────────────────────

registry    = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
client_data = registry.get("clients", {}).get(client, {})
glos_tm_key = client_data.get("glossary_tm_key", "")

if not glos_tm_key:
    print("No glossary_tm_key in matecat_projects.json — querying TM keys...")
    r = requests.get(f"{BASE}/api/v3/keys/list", headers=HEADERS)
    if not r.ok:
        print(f"ERROR: could not fetch TM keys ({r.status_code}) — {r.text[:200]}")
        sys.exit(1)
    resp  = r.json()
    keys  = resp if isinstance(resp, list) else resp.get("tm_keys", [])

    # Filter: name must contain "glossary" (case-insensitive)
    glos_keys = [k for k in keys if "glossary" in k.get("name", "").lower()]

    if not glos_keys:
        print("No TM key with 'glossary' in name found. All available keys:")
        for k in keys:
            print(f"  key={k.get('key','?')[:10]}...  name={k.get('name','?')}")
        glos_tm_key = input("Paste the TM key to use as glossary target: ").strip()
        if not glos_tm_key:
            print("Aborted.")
            sys.exit(0)
    elif len(glos_keys) == 1:
        glos_tm_key = glos_keys[0]["key"]
        print(f"Found glossary TM: '{glos_keys[0].get('name')}' → key {glos_tm_key[:6]}...")
    else:
        # Prefer a match that also contains the project_id or client name
        preferred = [k for k in glos_keys
                     if project_id.lower() in k.get("name", "").lower()
                     or client.lower() in k.get("name", "").lower()]
        if len(preferred) == 1:
            glos_tm_key = preferred[0]["key"]
            print(f"Found glossary TM: '{preferred[0].get('name')}' → key {glos_tm_key[:6]}...")
        else:
            print("Multiple glossary TM keys found:")
            for i, k in enumerate(glos_keys):
                print(f"  [{i}] key={k.get('key','?')[:10]}...  name={k.get('name','?')}")
            choice = input("Enter number to use: ").strip()
            try:
                glos_tm_key = glos_keys[int(choice)]["key"]
            except (ValueError, IndexError):
                print("Invalid choice. Aborted.")
                sys.exit(1)

    # Save back to matecat_projects.json
    registry.setdefault("clients", {}).setdefault(client, {})["glossary_tm_key"] = glos_tm_key
    PROJECTS_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved glossary_tm_key to {PROJECTS_FILE.name}")

else:
    print(f"Using glossary_tm_key from {PROJECTS_FILE.name}: {glos_tm_key[:6]}...")

# ── Convert CSV → XLSX ────────────────────────────────────────────────────────

print(f"\nConverting {glos_csv.name} to XLSX...")
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["en-US", "de-DE", ""])

terms_added = skipped = 0
with open(glos_csv, newline="", encoding="utf-8-sig") as f:
    lines = [l for l in f if not l.startswith("#")]
for row in csv.DictReader(lines):
    en = row.get("EN", "").strip()
    de = row.get("DE", "").strip()
    if not en or not de or en.startswith("EPO EN:"):
        skipped += 1
        continue
    ws.append([en, de, ""])
    terms_added += 1

print(f"  {terms_added} terms  ({skipped} skipped)")

tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
tmp.close()
wb.save(tmp.name)

# ── Upload to MateCat glossary TM ─────────────────────────────────────────────

print(f"\nUploading to MateCat glossary TM ({glos_tm_key[:6]}...)...")
with open(tmp.name, "rb") as f:
    r = requests.post(
        f"{BASE}/api/v3/glossaries/import/",
        headers=HEADERS,
        data={"tm_key": glos_tm_key},
        files={"file": (f"glossary_{project_id}.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
os.unlink(tmp.name)

if r.ok:
    print(f"  {r.status_code} — glossary upload accepted.")
    print(f"  {terms_added} terms will appear as underlines/highlights in the MateCat editor.")
elif r.status_code == 401:
    print(f"  ERROR: 401 Unauthorized — session cookie has expired.")
    print("  Refresh MATECAT_COOKIE in .env:")
    print("  Browser → DevTools → Application → Cookies → matecat.com → copy all cookie values.")
    sys.exit(1)
else:
    print(f"  ERROR: {r.status_code} — {r.text[:300]}")
    sys.exit(1)
