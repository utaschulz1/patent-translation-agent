"""
lara_segment.py — Single-segment Lara translation for the CAT UI.

Public API:
    translate(source_text, before_sources, after_sources) -> str
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from lara_sdk import AccessKey, TextBlock, Translator

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

SRC_LANG = "en"
TGT_LANG = "de"
INSTRUCTIONS = ["Use precise, formal language suitable for patent claims and descriptions."]

_access_key_id = os.environ.get("LARA_ACCESS_KEY_ID", "").strip()
_access_key_secret = os.environ.get("LARA_ACCESS_KEY_SECRET", "").strip()

_lara: Translator | None = None


def _get_lara() -> Translator:
    global _lara
    if _lara is None:
        if not _access_key_id or not _access_key_secret:
            raise RuntimeError("LARA_ACCESS_KEY_ID and LARA_ACCESS_KEY_SECRET must be set in agent/.env")
        _lara = Translator(AccessKey(id=_access_key_id, secret=_access_key_secret))
    return _lara


def _get_glossary_ids(project_id: str | None = None) -> list[str]:
    """Load project-specific or any available glossary from lara_glossaries.json."""
    registry_path = Path(__file__).parent / "lara_glossaries.json"
    if not registry_path.exists():
        return []
    registry: dict = json.loads(registry_path.read_text(encoding="utf-8"))
    if project_id:
        key = f"glossary_{project_id}"
        if key in registry:
            return [registry[key]]
    # Fallback: first available glossary
    for val in registry.values():
        if isinstance(val, str):
            return [val]
    return []


def _get_memory_ids(project_id: str | None = None) -> list[str]:
    """Load ICE TM and client TM memory IDs from lara_memories.json."""
    registry_path = Path(__file__).parent / "lara_memories.json"
    if not registry_path.exists() or not project_id:
        return []
    registry: dict = json.loads(registry_path.read_text(encoding="utf-8"))
    ids = []
    ice_key = f"memory_{project_id}"
    if ice_key in registry:
        ids.append(registry[ice_key])
    client_key = f"client_memory_{project_id}"
    if client_key in registry:
        ids.append(registry[client_key])
    return ids


def translate(
    source_text: str,
    before_sources: list[str],
    after_sources: list[str],
    project_id: str | None = None,
) -> str:
    """Translate a single source segment using surrounding confirmed segments as context."""
    lara = _get_lara()
    glossary_ids = _get_glossary_ids(project_id)
    memory_ids = _get_memory_ids(project_id)

    print(f"[lara] project={project_id!r} glossaries={glossary_ids} memories={memory_ids}", flush=True)
    print(f"[lara] context_before={before_sources}", flush=True)
    print(f"[lara] source={source_text!r}", flush=True)
    print(f"[lara] context_after={after_sources}", flush=True)

    window = (
        [TextBlock(text=s, translatable=False) for s in before_sources]
        + [TextBlock(text=source_text, translatable=True)]
        + [TextBlock(text=s, translatable=False) for s in after_sources]
    )
    target_idx = len(before_sources)

    kwargs: dict = {
        "source": SRC_LANG,
        "target": TGT_LANG,
        "instructions": INSTRUCTIONS,
        "no_trace": True,
    }
    if glossary_ids:
        kwargs["glossaries"] = glossary_ids
    if memory_ids:
        kwargs["adapt_to"] = memory_ids

    result = lara.translate(window, **kwargs)
    translation = result.translation[target_idx].text.strip()
    print(f"[lara] result={translation!r}", flush=True)
    return translation


def update_project_tm(project_id: str, segments: list[tuple[str, str]]) -> dict:
    """Upload confirmed segments to the project's Lara TM, creating it if needed.

    segments: list of (source_text, target_text) pairs
    Returns {"memory_id": str, "count": int, "created": bool}
    """
    if not segments:
        raise ValueError("No segments to upload")

    lara = _get_lara()
    memories_path = Path(__file__).parent / "lara_memories.json"
    registry: dict = json.loads(memories_path.read_text(encoding="utf-8")) if memories_path.exists() else {}

    memory_key = f"client_memory_{project_id}"
    memory_id = registry.get(memory_key)
    if not memory_id:
        raise ValueError(f"No client TM found for {project_id!r} — run ADD_CLIENT_TM first")
    client = project_id.split("_")[0]
    print(f"[update_tm] Using Lara memory: {memory_id}  ({client})", flush=True)

    # Build TMX
    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parts = [
        '<?xml version="1.0" ?>\n'
        '<!DOCTYPE tmx SYSTEM "https://uri.etsi.org/lis/002/v1.4.2/tmx14.dtd">\n'
        '<tmx version="1.4">\n'
        '  <header creationtool="patent-translation-app" creationtoolversion="1.0"\n'
        '          datatype="PlainText" segtype="sentence"\n'
        f'          adminlang="en-US" srclang="en-US" creationdate="{ts}"/>\n'
        '  <body>\n'
    ]
    for i, (src, tgt) in enumerate(segments):
        parts.append(
            f'    <tu tuid="upd_{i}">\n'
            f'      <tuv xml:lang="en-US"><seg>{_esc(src)}</seg></tuv>\n'
            f'      <tuv xml:lang="de-DE"><seg>{_esc(tgt)}</seg></tuv>\n'
            f'    </tu>\n'
        )
    parts.append("  </body>\n</tmx>\n")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".tmx", delete=False, encoding="utf-8")
    tmp.write("".join(parts))
    tmp.close()

    try:
        import_job = lara.memories.import_tmx(memory_id, tmp.name)
        print(f"[update_tm] Upload started (job: {import_job.id}) — waiting...", flush=True)
        lara.memories.wait_for_import(import_job)
        print(f"[update_tm] Done. {len(segments)} segment(s) added to {memory_id}  ({client})", flush=True)
    finally:
        os.unlink(tmp.name)

    return {"memory_id": memory_id, "count": len(segments)}
