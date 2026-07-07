"""
lara_segment.py — Single-segment Lara translation for the CAT UI.

Public API:
    translate(source_text, before_sources, after_sources) -> str
"""

import json
import os
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


def translate(
    source_text: str,
    before_sources: list[str],
    after_sources: list[str],
    project_id: str | None = None,
) -> str:
    """Translate a single source segment using surrounding confirmed segments as context."""
    lara = _get_lara()
    glossary_ids = _get_glossary_ids(project_id)

    print(f"[lara] project={project_id!r} glossaries={glossary_ids}", flush=True)
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

    result = lara.translate(window, **kwargs)
    translation = result.translation[target_idx].text.strip()
    print(f"[lara] result={translation!r}", flush=True)
    return translation
