# ============================================================
# verb_lemma_sync.py
# ============================================================
# Thin wrapper — the implementation moved to glossary_lib/lemma_sync.py
# (PRD_glossary_agent.md §4, Phase 0). Everything re-exported here so every
# existing importer and test keeps working unchanged.
#
# Original purpose (see glossary_lib/lemma_sync.py for the full history):
# grows the shared EN_verb_lemma_lookup.json / DE_verb_lemma_lookup.json
# tables with verbs a project's cleaned glossary introduces that neither
# table recognizes yet. A verb missing from EN_verb_lemma_lookup.json doesn't
# just fail silently: build_glossary_lookups() falls back to routing it
# through noun-phrase matching, whose length heuristic is backwards for verb
# conjugation (aufweisen -> aufweist is *shorter*) — the "having" false
# positive fixed on 2026-07-31.
# ============================================================

from glossary_lib.lemma_sync import (  # noqa: F401
    AGENT_DIR,
    DE_ADJ_SUFFIXES,
    DE_LEMMA_PATH,
    DERIVATION_PROMPT_TEMPLATE,
    EN_LEMMA_PATH,
    NON_VERB_DE_TERMS,
    SYSTEM_PROMPT,
    _clean_de_form,
    _resolve_de,
    find_unknown_verbs,
    merge_derivations,
    request_verb_derivations,
    sync_verb_lemma_tables,
    write_lemma_table,
)
from glossary_lib.validate import parse_json_object_lenient  # noqa: F401
