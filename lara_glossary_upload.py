# ============================================================
# lara_glossary_upload.py
# ============================================================
# Converts the current project glossary CSV to Lara format and uploads it.
# Run this before lara_translate.py whenever the glossary changes.
#
# What it does:
#   1. Reads projects/<id>/glossary_<id>.csv  (EN + DE columns)
#   2. Deletes any existing Lara glossary     (Pro plan: max 1)
#   3. Creates a new glossary named after the project
#   4. Uploads a clean en/de CSV
#   5. Writes LARA_GLOSSARY_IDS=<id> to lara_glossaries.json for lara_translate.py to use
#
# USAGE   python lara_glossary_upload.py [--pid <project_id>]
#           --pid   project folder name under projects/; defaults to current project context
#
# SETUP
#   LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be in .env
# ============================================================

import argparse
import csv
import os
import sys
import tempfile
import time
from pathlib import Path
from dotenv import load_dotenv

from lara_sdk import AccessKey, Translator

from project_log import project_dir as _pdir, load_context as _load_ctx

_args = argparse.ArgumentParser()
_args.add_argument("--pid", default=None, help="Project ID (folder name under projects/). Defaults to current project context.")
_args = _args.parse_args()

ENV_PATH = Path(__file__).parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)

# ============================================================
# Auth
# ============================================================

access_key_id     = os.environ.get("LARA_ACCESS_KEY_ID", "").strip()
access_key_secret = os.environ.get("LARA_ACCESS_KEY_SECRET", "").strip()

if not access_key_id or not access_key_secret:
    print("ERROR: LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be set in .env.")
    exit()

lara = Translator(AccessKey(id=access_key_id, secret=access_key_secret))

# ============================================================
# Find project glossary
# ============================================================

if _args.pid:
    project_id = _args.pid
    proj_dir = Path(__file__).parent / "projects" / project_id
    if not proj_dir.exists():
        print(f"ERROR: Project folder not found: {proj_dir}")
        sys.exit(1)
else:
    project_id = _load_ctx()["project_id"]
    proj_dir = _pdir()

# Prefer the LLM-cleaned glossary; fall back to the raw project glossary.
clean_path = proj_dir / f"clean_glossary_{project_id}.csv"
raw_path   = proj_dir / f"glossary_{project_id}.csv"

if clean_path.exists():
    glossary_path = clean_path
elif raw_path.exists():
    glossary_path = raw_path
else:
    print(f"ERROR: No glossary CSV found in '{proj_dir}'.")
    sys.exit(1)

print(f"Project:  {project_id}")
print(f"Glossary: {glossary_path.name}")

# ============================================================
# Parse glossary — EN + DE columns, skip comments and blanks
# ============================================================

terms: dict[str, str] = {}  # EN → DE (last occurrence wins for duplicates)

with open(glossary_path, newline="", encoding="utf-8-sig") as f:
    for line in f:
        if line.startswith("#"):
            continue
        break  # first non-comment line is the header
    f.seek(0)
    raw = [l for l in f if not l.startswith("#")]

reader = csv.DictReader(raw)
if "EN" not in (reader.fieldnames or []) or "DE" not in (reader.fieldnames or []):
    print(f"ERROR: glossary must have EN and DE columns. Found: {reader.fieldnames}")
    exit()

skipped = 0
for row in reader:
    en = row.get("EN", "").strip()
    de = row.get("DE", "").strip()
    if not en or not de:
        skipped += 1
        continue
    if en.upper().startswith("EPO EN:") or de.upper().startswith("EPO DE:"):
        skipped += 1
        continue
    terms[en] = de

print(f"Parsed {len(terms)} terms ({skipped} skipped — empty EN or DE).")

# ============================================================
# Delete existing glossaries (Pro plan allows only one)
# ============================================================

existing = lara.glossaries.list()
if existing:
    print(f"\nFound {len(existing)} existing glossar{'y' if len(existing) == 1 else 'ies'} on Lara:")
    for g in existing:
        print(f"  {g.id}  {g.name}")
    print("Deleting...")
    for g in existing:
        lara.glossaries.delete(g.id)
        print(f"  Deleted: {g.name}")
else:
    print("\nNo existing glossaries on Lara.")

# ============================================================
# Create new glossary
# ============================================================

glossary_name = f"glossary_{project_id}"
glossary = lara.glossaries.create(glossary_name)
print(f"\nCreated glossary: {glossary.id}  ({glossary_name})")

# ============================================================
# Build Lara-format CSV in memory and upload
# ============================================================

tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
writer = csv.writer(tmp)
writer.writerow(["en", "de"])
for en, de in terms.items():
    writer.writerow([en, de])
tmp.close()

import_job = lara.glossaries.import_csv(glossary.id, tmp.name)
os.unlink(tmp.name)
print(f"Upload started (job: {import_job.id}) — waiting for completion...")

while True:
    status = lara.glossaries.get_import_status(import_job.id)
    progress = status.progress
    print(f"  Progress: {progress:.0%}")
    if progress >= 1.0:
        break
    time.sleep(1)

print(f"Upload complete. {len(terms)} terms in glossary '{glossary_name}'.")

# ============================================================
# Save glossary ID to lara_glossaries.json
# ============================================================

import json

GLOSSARIES_FILE = Path(__file__).parent / "lara_glossaries.json"

registry: dict = {}
if GLOSSARIES_FILE.exists():
    registry = json.loads(GLOSSARIES_FILE.read_text(encoding="utf-8"))

registry[glossary_name] = glossary.id
GLOSSARIES_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\nSaved to lara_glossaries.json: {glossary_name} → {glossary.id}")
print("Run lara_translate.py — the glossary will be applied automatically.")
