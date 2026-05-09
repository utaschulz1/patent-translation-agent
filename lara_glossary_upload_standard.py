# ============================================================
# lara_glossary_upload_standard.py
# ============================================================
# Filters standard_glossary.csv to the terms that actually appear in the
# current project's source text, then uploads the result to Lara as the
# initial project glossary.
#
# Run this BEFORE lara_translate.py at the start of a new project so that
# core patent-language terms (comprising → umfassend, include → beinhalten,
# at least → mindestens, …) are applied from the very first translation pass.
#
# standard_glossary.csv format:  EN, DE  (columns 3+ are notes, ignored here)
#
# Steps:
#   1. Read standard_glossary.csv from the project root
#   2. Read source segments from the project's XTM Excel
#   3. Keep only rows whose EN term appears in the source text
#   4. Delete any existing Lara glossary, upload the filtered set, save ID
#
# SETUP
#   LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be in .env
# ============================================================

import csv
import json
import os
import re
import tempfile
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from lara_sdk import AccessKey, Translator

import project_log

HERE              = Path(__file__).parent
STANDARD_GLOSSARY = HERE / "standard_glossary.csv"
GLOSSARIES_FILE   = HERE / "lara_glossaries.json"

load_dotenv(dotenv_path=HERE / ".env")

# ── Auth ──────────────────────────────────────────────────────────────────────

access_key_id     = os.environ.get("LARA_ACCESS_KEY_ID", "").strip()
access_key_secret = os.environ.get("LARA_ACCESS_KEY_SECRET", "").strip()

if not access_key_id or not access_key_secret:
    print("ERROR: LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be set in .env.")
    exit()

lara = Translator(AccessKey(id=access_key_id, secret=access_key_secret))

# ── Read standard glossary (EN, DE; columns 3+ ignored) ──────────────────────

standard_terms: list[tuple[str, str]] = []

with open(STANDARD_GLOSSARY, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    next(reader, None)  # skip header row
    for row in reader:
        if len(row) < 2:
            continue
        en = row[0].strip()
        de = row[1].strip()
        if en and de:
            standard_terms.append((en, de))

print(f"Standard glossary: {len(standard_terms)} terms.")

# ── Read source text from project XTM Excel ───────────────────────────────────

proj_dir   = project_log.project_dir()
project_id = proj_dir.name

xlsx_files = sorted(
    f for f in proj_dir.glob("*.xlsx")
    if not f.name.startswith("~$")
    and not f.name.endswith("_translated.xlsx")
    and not f.name.endswith("_checks.xlsx")
)
if not xlsx_files:
    print(f"ERROR: No XTM Excel found in {proj_dir}")
    exit()

input_path = xlsx_files[0]
print(f"Source file: {input_path.name}")

raw_df  = pd.read_excel(input_path, header=None, engine="openpyxl")
data_df = raw_df.iloc[3:].reset_index(drop=True)
data_df.columns = ["ID", "Source", "Target"] + list(data_df.columns[3:])
source_text = " ".join(
    data_df["Source"].dropna().astype(str).tolist()
).lower()

print(f"Source text: {len(source_text):,} chars, {len(data_df.dropna(subset=['Source']))} segments.")

# ── Filter: keep terms present in source text ─────────────────────────────────

def _appears_in(en_term: str, text: str) -> bool:
    """Return True if en_term (case-insensitive, whole-word) occurs in text.

    For 'to X' entries (infinitive prefix), also tries the bare verb so that
    'to map' matches text containing 'map', 'maps', 'mapped', 'mapping'.
    """
    term_lower = en_term.lower()
    if re.search(r"\b" + re.escape(term_lower) + r"\b", text):
        return True
    if term_lower.startswith("to "):
        bare = term_lower[3:].strip()
        if bare and re.search(r"\b" + re.escape(bare) + r"\w*\b", text):
            return True
    return False


kept:    list[tuple[str, str]] = []
skipped: list[str]             = []

for en, de in standard_terms:
    if _appears_in(en, source_text):
        kept.append((en, de))
    else:
        skipped.append(en)

print(f"\nKept    ({len(kept)}): {', '.join(e for e, _ in kept)}")
print(f"Skipped ({len(skipped)}): {', '.join(skipped)}")

if not kept:
    print("\nNo standard glossary terms found in source text — nothing to upload.")
    exit()

# ── Delete existing Lara glossary (Pro plan: max 1) ───────────────────────────

existing = lara.glossaries.list()
if existing:
    print(f"\n{len(existing)} existing glossar{'y' if len(existing) == 1 else 'ies'} — deleting...")
    for g in existing:
        lara.glossaries.delete(g.id)
        print(f"  Deleted: {g.name}")
else:
    print("\nNo existing glossaries on Lara.")

# ── Create glossary and upload filtered terms ─────────────────────────────────

glossary_name = f"glossary_{project_id}"
glossary      = lara.glossaries.create(glossary_name)
print(f"\nCreated: {glossary.id}  ({glossary_name})")

tmp = tempfile.NamedTemporaryFile(
    mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
)
writer = csv.writer(tmp)
writer.writerow(["en", "de"])
for en, de in kept:
    writer.writerow([en, de])
tmp.close()

job = lara.glossaries.import_csv(glossary.id, tmp.name)
os.unlink(tmp.name)
print(f"Uploading {len(kept)} terms (job: {job.id})...")

while True:
    status = lara.glossaries.get_import_status(job.id)
    print(f"  {status.progress:.0%}")
    if status.progress >= 1.0:
        break
    time.sleep(1)

print("Upload complete.")

# ── Save glossary ID to lara_glossaries.json ─────────────────────────────────

registry: dict = {}
if GLOSSARIES_FILE.exists():
    registry = json.loads(GLOSSARIES_FILE.read_text(encoding="utf-8"))

registry[glossary_name] = glossary.id
GLOSSARIES_FILE.write_text(
    json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
)

print(f"\nSaved: {glossary_name} → {glossary.id}")
print(f"Run lara_translate.py — {len(kept)} standard terms will be applied.")
