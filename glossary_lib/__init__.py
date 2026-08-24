"""glossary_lib — shared internal subpackage for glossary logic.

Single home for the functions currently forked between the production pipeline
and the audit-skill scripts: statistical classification (ordinal merge,
consistent/inconsistent), source attestation, checker matching
(_count_lemmas/_count_noun_in_de/check_segment_glossary), verb lemma sync, and
clean_glossary CSV I/O. Both the legacy path (llm_glossary_cleanup.py,
glossary_compare_revised_translation.py, ...) and the glossary_agent/ graph
nodes import from here; legacy modules become thin re-exporting wrappers.

Internal subpackage only — deliberately NOT a distributable package until a
second real consuming project exists.

Design and migration table: agent/PRD_glossary_agent.md §4. Planned modules:
csv_io.py, classify.py, attestation.py, matching.py, lemma_sync.py, validate.py
(PRD Phase 0/0b — not implemented yet).
"""
