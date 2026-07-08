"""
add_client_tm.py — Resolve the client TM for a project and register it.

Extracts the client acronym from the project ID (first segment before '_'),
looks it up in the client_tms registry in lara_memories.json.
If not found, creates a new Lara memory named after the acronym and adds it.
Saves client_memory_{project_id} to lara_memories.json so that
lara_translate.py and lara_segment.py can use it for adapt_to.

USAGE   python add_client_tm.py --pid <project_id>
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from lara_sdk import AccessKey, Translator

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

project_id = _args.pid
client = project_id.split("_")[0]
print(f"[client_tm] Project: {project_id}  |  Client acronym: {client}", flush=True)

MEMORIES_FILE = Path(os.environ.get("LARA_MEMORIES_PATH", str(Path(__file__).parent / "lara_memories.json")))
registry: dict = json.loads(MEMORIES_FILE.read_text(encoding="utf-8")) if MEMORIES_FILE.exists() else {}

client_tms: dict = registry.setdefault("client_tms", {})
client_registry_key = f"client_memory_{project_id}"

if client in client_tms:
    memory_id = client_tms[client]
    print(f"[client_tm] Found existing TM for '{client}': {memory_id}", flush=True)
else:
    lara = Translator(AccessKey(id=access_key_id, secret=access_key_secret))
    memory = lara.memories.create(client)
    memory_id = memory.id
    client_tms[client] = memory_id
    print(f"[client_tm] Created new Lara memory for '{client}': {memory_id}", flush=True)

registry[client_registry_key] = memory_id
MEMORIES_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[client_tm] Saved: {client_registry_key} → {memory_id}", flush=True)
