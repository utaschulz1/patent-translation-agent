# ============================================================
# ice_tm_creation.py
# ============================================================
# Extracts ICE (exact-match) and 100% (leveraged-tm) segments from the
# source XLF downloaded by XTM_FILES_DOWNLOADED, builds a TMX, and uploads
# it to Lara as a project-specific translation memory with adapt_to.
#
# If matches are found:
#   - Writes  ICE_{PID}.tmx to the project folder
#   - Creates a Lara memory named ICE_{PID}
#   - Uploads the TMX and waits for completion
#   - Saves the memory ID to lara_memories.json
#
# If no matches are found:
#   - Writes a conformant empty  {PID}.tmx  (no Lara upload)
#
# USAGE   python ice_tm_creation.py --pid <project_id>
# ============================================================

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from lara_sdk import AccessKey, Translator
from lxml import etree

from project_log import find_project_dir

_args = argparse.ArgumentParser()
_args.add_argument("--pid", required=True, help="Project ID (folder name under projects/)")
_args = _args.parse_args()

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

access_key_id     = os.environ.get("LARA_ACCESS_KEY_ID", "").strip()
access_key_secret = os.environ.get("LARA_ACCESS_KEY_SECRET", "").strip()

if not access_key_id or not access_key_secret:
    print("ERROR: LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be set in .env.")
    sys.exit(1)

lara = Translator(AccessKey(id=access_key_id, secret=access_key_secret))

# ============================================================
# Find source XLF
# ============================================================

project_id = _args.pid
proj_dir = find_project_dir(project_id)

xlf_files = [
    f for f in proj_dir.glob("*.xlf")
    if not f.name.endswith("_GERMAN.xlf") and not f.name.endswith("_CAT_revised.xlf")
]
if not xlf_files:
    print(f"ERROR: No source XLF found in {proj_dir}")
    sys.exit(1)

xlf_path = sorted(xlf_files)[0]
print(f"[ice_tm] Source XLF: {xlf_path.name}", flush=True)

# ============================================================
# Extract ICE and 100% matches
# ============================================================

def _plain_text(element) -> str:
    parts = []
    if element.text:
        parts.append(element.text)
    for child in element:
        parts.append(_plain_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


tree = etree.parse(str(xlf_path))
root = tree.getroot()
xliff_ns = root.nsmap.get(None, "urn:oasis:names:tc:xliff:document:1.2")


def _find(el, tag):
    node = el.find(f"{{{xliff_ns}}}{tag}")
    if node is None:
        node = el.find(tag)
    return node


def _findall(el, tag):
    nodes = el.findall(f".//{{{xliff_ns}}}{tag}")
    if not nodes:
        nodes = el.findall(f".//{tag}")
    return nodes


matches: list[tuple[str, str, str]] = []  # (tuid, source_text, target_text)

for tu in _findall(root, "trans-unit"):
    tuid = tu.get("id", "")
    source_el = _find(tu, "source")
    target_el = _find(tu, "target")
    if source_el is None or target_el is None:
        continue

    sq = target_el.get("state-qualifier", "")
    if sq not in ("exact-match", "leveraged-tm"):
        continue

    source = _plain_text(source_el)
    target = _plain_text(target_el)
    if not source or not target:
        continue

    matches.append((tuid, source, target))

ice_count  = sum(1 for tu in _findall(root, "trans-unit")
                 if (_find(tu, "target") is not None and
                     _find(tu, "target").get("state-qualifier") == "exact-match"))
tm100_count = len(matches) - ice_count

print(f"[ice_tm] ICE matches: {ice_count}  |  100% matches: {tm100_count}  |  total: {len(matches)}", flush=True)

# ============================================================
# Build TMX
# ============================================================

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

tmx_parts = [
    '<?xml version="1.0" ?>\n'
    '<!DOCTYPE tmx SYSTEM "https://uri.etsi.org/lis/002/v1.4.2/tmx14.dtd">\n'
    '<tmx version="1.4">\n'
    '  <header creationtool="patent-translation-app"\n'
    '          creationtoolversion="1.0"\n'
    '          datatype="PlainText"\n'
    '          segtype="sentence"\n'
    '          adminlang="en-US"\n'
    f'          srclang="en-US"\n'
    f'          creationdate="{timestamp}"/>\n'
    '  <body>\n'
]

for tuid, source, target in matches:
    tmx_parts.append(
        f'    <tu tuid="{_xml_escape(tuid)}">\n'
        f'      <tuv xml:lang="en-US"><seg>{_xml_escape(source)}</seg></tuv>\n'
        f'      <tuv xml:lang="de-DE"><seg>{_xml_escape(target)}</seg></tuv>\n'
        f'    </tu>\n'
    )

tmx_parts.append("  </body>\n</tmx>\n")
tmx_content = "".join(tmx_parts)

memory_name = f"ICE_{project_id}"
memory = lara.memories.create(memory_name)
print(f"[ice_tm] Created Lara memory: {memory.id}  ({memory_name})", flush=True)

if matches:
    tmx_path = proj_dir / f"ICE_{project_id}.tmx"
    tmx_path.write_text(tmx_content, encoding="utf-8")
    print(f"[ice_tm] Written: {tmx_path.name}", flush=True)

    import_job = lara.memories.import_tmx(memory.id, str(tmx_path))
    print(f"[ice_tm] Upload started (job: {import_job.id}) — waiting...", flush=True)
    lara.memories.wait_for_import(import_job)
    print(f"[ice_tm] Upload complete.", flush=True)
else:
    print(f"[ice_tm] No matches — empty memory created, ready for Update TM.", flush=True)

# ============================================================
# Save to lara_memories.json
# ============================================================

MEMORIES_FILE = Path(__file__).parent / "lara_memories.json"
registry: dict = {}
if MEMORIES_FILE.exists():
    registry = json.loads(MEMORIES_FILE.read_text(encoding="utf-8"))

registry[f"memory_{project_id}"] = memory.id
MEMORIES_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[ice_tm] Saved: memory_{project_id} → {memory.id}", flush=True)
