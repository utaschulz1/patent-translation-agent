# ============================================================
# lara_glossary_download.py
# ============================================================
# Downloads all glossaries currently stored on Lara as CSV files.
# Output: lara_glossary_download/<glossary_name>.csv
#
# USAGE   python lara_glossary_download.py
#
# SETUP
#   LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be in .env
# ============================================================

import os
from pathlib import Path
from dotenv import load_dotenv
from lara_sdk import AccessKey, Translator

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

access_key_id     = os.environ.get("LARA_ACCESS_KEY_ID", "").strip()
access_key_secret = os.environ.get("LARA_ACCESS_KEY_SECRET", "").strip()

if not access_key_id or not access_key_secret:
    print("ERROR: LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be set in .env.")
    exit(1)

lara = Translator(AccessKey(id=access_key_id, secret=access_key_secret))

OUT_DIR = Path(__file__).parent / "lara_glossary_download"

glossaries = lara.glossaries.list()

if not glossaries:
    print("No glossaries found on Lara.")
    exit(0)

print(f"Found {len(glossaries)} glossar{'y' if len(glossaries) == 1 else 'ies'} on Lara.")

OUT_DIR.mkdir(exist_ok=True)

for g in glossaries:
    csv_bytes = lara.glossaries.export(g.id, "csv/table-uni", source="en")
    out_path = OUT_DIR / f"{g.name}.csv"
    out_path.write_bytes(csv_bytes)
    lines = csv_bytes.decode("utf-8").count("\n")
    print(f"  Saved: {out_path.name}  ({lines} lines, {g.id})")

print(f"\nDone. Files saved to: {OUT_DIR}")
