# PRD: Glossary Agent — evidence-grounded glossary consolidation as a LangGraph/FastAPI agent

**Status:** Draft v2 — 2026-08-24, open questions resolved with the user (see §11/§12)
**Replaces (behind a feature flag):** `agent/llm_glossary_cleanup.py`'s LLM consolidation call + the manually-invoked `glossary-range-audit` Claude Code skill
**Does NOT replace:** the statistical extraction/classification layer, the output CSV contract, or anything downstream of `clean_glossary_<PID>.csv`

---

## 1. Problem statement

Today, glossary quality is produced in two disconnected passes:

1. **`llm_glossary_cleanup.py`** (the `GLOSSARY_ANALYZED` step's final command) makes one batch
   DeepSeek call that consolidates majority-vote canonical/frequency tables into a first-draft
   glossary. It resolves *inconsistent* terms (where the MT disagreed with itself), but a term the
   MT rendered the **same wrong way every time** sails through as "consistent" with zero scrutiny —
   consistency classification measures agreement, not correctness, and nothing in the pipeline
   judges correctness at all.
2. **The `glossary-range-audit` skill** — a manual, session-by-session Claude Code invocation that
   applies exactly that missing judgment: attestation checks against real segment text, EPO-title
   grounding, bidirectional uniqueness, domain fit. It works, but only when a human remembers to
   run it, and it re-derives context the first pass already had in hand.

Every class of error the audit skill has caught in live use survived the first pass precisely
because of this split. Concrete, documented cases:

- **Fabricated entries.** `using,mithilfe` — "mithilfe" never occurs anywhere in the target text
  (the real translations were "verwendet"/"Verwendung", already covered by `use,verwenden`).
  `enable,in die Lage versetzen` — that DE phrase never appears; "enable" only ever occurs inside
  `chip enable pin` → `Chipaktivierungspin`, which had **no** entry at all. A fabricated bare-word
  row shipped while the real compound was missing (MICTCH_2608_P0124).
- **EPO-title verification claimed but never enforced.** `llm_glossary_cleanup.py`'s own prompt
  says "key terms in the title set the translation family for the whole patent," but nothing
  verifies this happened. RTC_2608_P1331: the raw MT majority-voted `Prüfvorrichtung`/`prüfen`
  (7/8) for "testing device"/"test" while the EPO title itself reads "...BUILT-IN-**TEST**..." —
  the final professional translation used `Testvorrichtung`/`testen` throughout. The title was
  right there; nothing checked against it.
- **Systematic MT register confusion.** HALA_2608_P0655: "input image data" rendered three
  different ways (`Eingangsbilddaten` / `Eingabebilddaten` / `eingegebene Bilddaten`) across the
  invention's two most central data objects — the Eingang/Eingabe ↔ Ausgang/Ausgabe port-vs-manual
  sense confusion, a recurring electronics-patent failure mode the first pass has no rule for.
- **Ordinal duplicates** (`first image data`/`second image data` as separate rows that break the
  checker's shared-noun-phrase matching) shipped in every glossary until the mechanical merge was
  added to `llm_glossary_cleanup.py` on 2026-08-23 (`_merge_ordinal_siblings`) — and that fix only
  exists because the audit skill kept catching them by hand.
- **Bidirectional-consistency collapses.** FRKE_2608_P0736: the raw MT rendered both `exhibit` and
  `provide` as `führt (zu)` — 100% internally consistent, therefore invisible to the first pass,
  but wrong: two distinct claim concepts collapsed into one indistinguishable German verb, while
  `provide→bereitstellen` was a hard `standard_glossary.csv` requirement and `exhibit` needed a
  third distinct word (`zeigen`).

The split also costs real money and time in the wrong place: the cheap pass runs unsupervised, and
the expensive judgment happens later, manually, per-session, re-reading everything from scratch —
if it happens at all.

**The agent's job:** one continuous, evidence-grounded reasoning pass at first-draft time, doing
once and automatically what the audit skill currently encodes as manual procedure — while keeping
the cheap statistical layer, the output contract, and everything downstream unchanged.

---

## 2. Current-state architecture

### The `GLOSSARY_ANALYZED` step (app.py `STEP_SCRIPTS`)

```
LLM_verb_comparison_xlsx.py {seg_start} {seg_end}      ─┐  spaCy/LLM extraction from the
LLM_noun_comparison_xlsx.py {seg_start} {seg_end}       ├─ pretranslated xlsx → segment-pair
LLM_capability_comparison_xlsx.py {seg_start} {seg_end}─┘  CSVs + canonical/frequency tables
merge_glossaries.py {project_id}
llm_glossary_cleanup.py                                 ←  the part this PRD replaces
```

`llm_glossary_cleanup.py` (`clean_glossary(proj_dir, project_id)`):

1. Reads `verb_segment_pairs.csv`, `capability_segment_pairs.csv`,
   `noun_canonical_glossary.csv`, `verb_canonical_glossary.csv`, `noun_inconsistency_table.csv`,
   `glossary_<PID>.csv` (EPO title source), `standard_glossary.csv`.
2. Filters the standard glossary to source-attested terms via `_appears_in()` against the first
   project `*.xlsx`'s Source column (falls back to *the whole standard glossary* if no xlsx is
   found — the documented contamination failure mode).
3. Classifies each term **consistent** (single DE form observed) vs **inconsistent** (multiple),
   after `_merge_ordinal_siblings`/`_is_ordinal_variant` collapse ordinal-modifier siblings.
4. One DeepSeek-V3 batch call (temperature 0) resolves the inconsistent sets; `validate_result()`
   checks EN/DE uniqueness (minus `SHARED_DE_ALLOWED`) and standard-glossary conflicts; one retry
   on validation errors; LLM-echoed title rows dropped; LLM-omitted consistent terms restored.
5. Writes `clean_glossary_<PID>.csv`: `EN,DE` header, labeled EPO-title row, blank line, project
   terms, blank line, appended relevant-standard terms (utf-8-sig).
6. Calls `verb_lemma_sync.sync_verb_lemma_tables()` to grow the shared lemma lookup tables.

### After it, today

- **`GLOSSARY_REVIEWED`** (MUTABLE step): manual CSV editing in the frontend, plus an optional
  "Use LLM" second pass (`llm_glossary_revise.py`) that fixes ordinal duplicates / fused generic
  modifiers and deterministically cleans the EPO-title row (`clean_epo_title_row`).
- **`glossary-range-audit` skill** (manual, Claude Code): the real judgment pass — Steps 1–6
  content curation against a claims benchmark range, Step 7 whole-document artifact/gap triage
  (4-bucket), Step 8 synthesis back into the CSV.
- **Downstream consumers (all unchanged by this PRD):** `lara_glossary_upload.py`,
  `CSV2TMX-XLSX.py`, the CAT UI glossary check, and
  `glossary_compare_revised_translation.py` — whose `_count_lemmas` / `_count_noun_in_de` /
  `check_segment_glossary` matching logic **defines what a well-formed entry is** in production.

### Data contracts at each boundary (unchanged)

| Boundary | File(s) | Producer → Consumer |
|---|---|---|
| Extraction → consolidation | `*_segment_pairs.csv`, `*_canonical_glossary.csv`, `noun_inconsistency_table.csv` | comparison scripts → cleanup/agent |
| Title source | `glossary_<PID>.csv` ("EPO EN:"/"EPO DE:" prefixed row) | merge_glossaries → cleanup/agent |
| Shared anchors | `standard_glossary.csv`, `_styleguide.md` | repo → cleanup/agent |
| Lemma tables | `EN_verb_lemma_lookup.json`, `DE_verb_lemma_lookup.json` | verb_lemma_sync ↔ checker (project-scoped overlay added by this PRD — §6b) |
| **Output** | `clean_glossary_<PID>.csv` | cleanup/agent → everything downstream |

---

## 3. Proposed LangGraph architecture

Package layout mirrors the review agent exactly: `glossary_agent/` in the **outer repo**
(`graph.py`, `api.py`, `__init__.py`), own `SqliteSaver` checkpoint DB
(`glossary_agent_checkpoints.db`, `GLOSSARY_CHECKPOINT_DB_PATH` env override, absolute-path rule
per the DB_PATH lesson), `thread_id = project_id`, status derived entirely from
`graph.get_state()` (interrupts checked before `state.next`, same as `review_agent.get_status`).
Shared logic lives in `agent/glossary_lib/` (§4) so both the old path and the graph nodes import
identical code.

### State schema (TypedDict, checkpoint-serializable)

```python
class TermVerdict(TypedDict):
    en: str
    de: str                      # the currently-chosen DE value
    origin: str                  # "consistent" | "resolved" | "standard" | "added" | "merged_ordinal"
    action: str                  # "keep" | "amend" | "delete" | "add"
    evidence: dict               # attestation segs, freq-table hits, checker notes, lemma status
    reasoning: str               # one-sentence justification (audit log, Step 8 synthesis-log analog)

class GlossaryState(TypedDict):
    project_id: str
    project_folder: str          # explicit, caller-supplied (review-agent convention)
    workflow_kind: str           # "post-editing" | "proofreading" — from workflow_db job_type
    benchmark_range: tuple[int, int] | None   # Lara column → run seg_range → whole doc (§3.3 chain)
    run_seg_range: tuple[int, int] | None     # the seg_range /start was triggered with, if any
    epo_title: dict              # {"en", "de", "usable": bool, "verdict": str}
    standard_relevant: list[dict]
    consistent_terms: list[dict]
    inconsistent_sets: dict      # verbs / nouns / capabilities, same shapes as today
    draft_rows: list[dict]       # post-resolution draft glossary
    evidence: dict               # per-row attestation + lemma-sweep + live-checker results
    flagged: list[dict]          # rows triaged as needing LLM judgment
    verdicts: list[TermVerdict]
    scope_question: dict | None  # payload for the confirm_scope interrupt, when triggered
    final_rows: list[tuple[str, str]]
    output_path: str | None
    report: str
    stop_reason: str | None      # None while running; terminal vocabulary mirrors review agent
    pending_decision: dict | None
```

### Node breakdown

**Deterministic (no LLM), all imported from `glossary_lib`:**

1. **`load_inputs`** — one node reads every input file, resolves the EPO title row, loads
   `standard_glossary.csv` + `_styleguide.md` + lemma tables (shared + project overlay, §6b),
   and reads the bilingual xlsx corpus once into state. **Hard-fails** (routes to error END) if
   the xlsx is missing — today that silently appends the entire unfiltered standard glossary
   ("no XTM Excel found" warning), the documented root cause of the 96/141-unattested
   contamination incident. A missing corpus makes evidence-grounded reasoning impossible; it is
   an error, not a degraded mode.
2. **`classify_terms`** — `_appears_in()` standard-glossary filtering, consistent/inconsistent
   classification, `_merge_ordinal_siblings`/`_is_ordinal_variant` — byte-for-byte the same logic
   as today, imported not reimplemented. **The 2026-08-23 ordinal-merge code moves to
   `glossary_lib` and is called from both paths; the agent must not regress or fork it.**
3. **`resolve_range`** — determines `workflow_kind` and `benchmark_range` via a three-level
   fallback chain, never by re-asking the user (decision, 2026-08-24, amended same day):
   1. **The `Lara` marker column in `*_translated.xlsx`** (column 4, written per segment by
      `lara_translate.py` on successful translation): the set of Lara-marked segment ids *is*
      the pretranslation range — by construction the same scope the extraction scripts
      analyzed, so the right reasoning benchmark.
   2. **If no `Lara` column exists** (e.g. proofreading-shape corpus with no pretranslation):
      the `seg_range` this `GLOSSARY_ANALYZED` run was triggered with. The step is manually
      triggered and already requires a `seg_range` whenever the document exceeds 50 segments
      (the `_get_segment_info` gate in `app.py`'s `run_step`); the agent's `/start` runs the
      extraction subprocesses itself, so it holds that same range and carries it into graph
      state — no separate persistence needed.
   3. **If the run's `seg_range` is also empty:** the whole document — safe by the same logic
      as the extraction scripts' own fallback (`seg_start, seg_end = 1, len(segments)`), since
      an empty range only passes the gate for documents of ≤50 segments anyway.

   This chain covers **description-only jobs with no special handling** (decision, 2026-08-24):
   pretranslation starts at the beginning of the document, the already-translated claims having
   been TMX'd into the Lara engine upstream — so the Lara column/run range is the benchmark as
   normal, and description-only jobs essentially never reach the proofreading workflow
   (external-reference support dropped).

   Other behavior: section-boundary rows inside the benchmark (e.g. an `ABSTRACT` header) are
   noted in the report and excluded from claims-specific rule triggers (the
   `including`-in-the-abstract lesson), but not silently dropped. **Proofreading workflow**
   additionally sets the whole-document mode flag (node 7b runs). `confirm_scope` remains only
   as a last resort for the degenerate case the chain can't reach — no Lara column, no run
   `seg_range`, and a >50-segment document (only possible when the app's gate was bypassed,
   e.g. a direct Swagger `/start` with an explicit `project_folder`).

   A smarter upstream claims-identification step (find the claims in the source, drop
   repetitive parallel claim sets, never pretranslate the detailed description) is **future
   work**, out of this PRD's scope — see §12.
4. **`gather_evidence`** — the mechanized Step 2 of the audit skill, per draft row:
   - EN/DE attestation against the benchmark range **and** whole corpus
     (`audit_glossary.py`'s `find_segs` logic, moved into `glossary_lib`).
   - Frequency-table cross-reference hits.
   - **Verb lemma sweep:** `_count_lemmas(claims_text, EN_lookup)` diffed against glossary EN
     keys — the check that caught `perform` and `write` being dropped without a decision. Lemmas
     only ever embedded in tracked compounds are auto-filtered by checking their segment hits.
   - **Live-checker completeness run:** `build_glossary_lookups` + `check_segment_glossary` over
     every benchmark segment. This is the *only* check that catches the `anzuzeigen` class of gap
     (a document's actual separable zu-infinitive surface form missing from the DE lemma table
     while the bare infinitive passes a key lookup) — a static dictionary check is explicitly
     insufficient, per the HALA live miss. Checker notes on verb rows feed lemma additions (§6b).
   - **Bidirectional index:** DE value/lemma → owning EN entries, across the draft AND
     `standard_glossary.csv`, to detect two-EN-one-DE collapses mechanically before any LLM call.

**LLM nodes (each with bounded tool loop, config-driven limits, conditional failure routing):**

5. **`check_epo_title`** — small call implementing SKILL.md Step 1b: is the DE title usable as a
   domain anchor (watch for the "Anhang"-for-limb / "Airbag"-for-cuff dictionary-plausible-but-
   domain-wrong patterns)? Output: usable/unusable verdict + the anchor term pairs it establishes
   (only for terms actually attested in the corpus — verified deterministically afterward, not
   trusted from the LLM). Extraction problems are fixed deterministically upstream in
   `load_inputs` (reconstruct from `glossary_<PID>.csv` or skip) — **never invented**; an
   unusable title is reported as errata and the run proceeds without an anchor.
6. **`resolve_inconsistent`** — the successor of today's batch call, same input shapes, same
   prompt lineage (including `_shared_de_note()` — the `have→besitzen` lesson: constraints the
   validator tolerates must be *told* to the model), plus two new inputs: the title anchors from
   node 5 (a sound attested title term **outranks the raw-MT majority** — the
   Prüfvorrichtung/Testvorrichtung rule) and the bidirectional index (so exhibit/provide-style
   collapses are presented as conflicts to resolve, not left implicit). Output validated by
   `validate_result()`; one bounded re-prompt on validation errors, as today.
7. **`audit_flagged`** — **the genuinely new stage.** Input: only the triaged `flagged` subset
   (§7), each row bundled with its gathered evidence and the 2–4 real segment contexts involved.
   The prompt encodes the audit skill's Step 3/4 judgment rules directly:
   - reason domain-fit first; canonical tables are attestation evidence, never a verdict;
   - `standard_glossary.csv`/`_styleguide.md` checked before frequency tables; a single
     uncommented standard row is a hard requirement signal;
   - consistency across all contexts outranks standard-ness when the standard term doesn't fit
     every context;
   - DE-attested-nowhere ⇒ fabrication candidate → delete, after tracing whether a real compound
     entry is missing instead (the `chip enable pin` pattern);
   - masking-compound technique for context-dependent bare terms (`any one of the preceding
     claims`, `for use`) instead of overwriting the general default;
   - category rules: claims-attested verbs always kept; `at least` and `by` always kept; `use`
     gets the narrow finite-verb-only check;
   - structural rules (generic-modifier splitting with the bare-noun row preserved, prefer intact
     compounds, duplicate/stem-inconsistency collapse).
   Tools (review-agent `classify` pattern): `get_segments(ids)` (full EN/DE text),
   `count_pattern(regex)` over the corpus, `check_entry(en, de)` (runs the real checker for one
   candidate row). Output: `TermVerdict` list with per-row reasoning strings.
7b. **`whole_doc_pass`** — **proofreading workflow only** (decision, 2026-08-24; skipped
   entirely for post-editing, where the corpus is raw MT and Step-7 findings are only meaningful
   post-correction). Runs the audit skill's Step 7 against the complete existing translation:
   whole-document attestation + live-checker run, 4-bucket triage of flagged keys. Bucket 2
   (brittle stored form) and bucket 3 (missing entry, claims-priority sourcing) produce
   `TermVerdict`s that flow into `apply_verdicts`; bucket 1 (checker code bug suspicion) and
   bucket 4 (genuine cross-document inconsistency) are **report-only** — the agent never edits
   checker code or launders a translation error into the CSV. Claims priority is enforced
   deterministically: a bucket-3 DE value is sourced from the claims rendering whenever the
   concept appears there, regardless of whole-document majority.
8. **`report_node`** — human-readable summary grouped by kind of fix (the audit skill's Step 9
   shape), including report-only findings that never touch the CSV: raw-MT inconsistencies worth
   knowing at proofreading time, title errata, bucket-1/4 findings, `standard_glossary.csv`
   tension notes.

**Deterministic tail:**

9. **`apply_verdicts`** — merges verdicts into `final_rows`; re-runs `validate_result()` and the
   bidirectional index as a hard gate (an LLM verdict that reintroduces a DE duplicate is a
   validation failure, not a shipped row); appends still-relevant standard terms not already
   present (today's `extra_standard` logic).
10. **`write_glossary`** — writes `clean_glossary_<PID>.csv` in the exact existing convention
    (§6), with the EPO title row passed through `clean_epo_title_row()` — label prefix stripped,
    inner commas replaced — so the shipped file no longer carries the "EPO EN:" provenance labels
    the audit skill currently has to strip by hand. Backs up an existing file first
    (`.bak_agent_<timestamp>` — REPEATABLE step, so re-runs are normal; every write pass keeps
    its own backup, the skill's Step 0/8 discipline).
11. **`sync_lemmas`** — `verb_lemma_sync.sync_verb_lemma_tables()` retargeted at the
    **project-scoped lemma overlay** (§6b), **plus** additions derived from node 4's live-checker
    notes: a verb row whose document surface form the checker couldn't resolve gets that form
    (and its LLM-derived paradigm) added — closing `verb_lemma_sync`'s known blind spot, where a
    base form already known from an earlier project never gets missing paradigm members
    (separable zu-infinitives) backfilled because its trigger only fires on an *unrecognized base
    form*. Additive-only, never overwrites, same as today.
12. **`finalize`** — sets `stop_reason: "completed"`.

### Edges

```
START → load_inputs → classify_terms → resolve_range
resolve_range --(degenerate: no Lara column, no run seg_range, >50 segments)--> confirm_scope [interrupt]
resolve_range --(normal)--> gather_evidence
confirm_scope → gather_evidence            # resume is forward-only, see below
gather_evidence → check_epo_title → resolve_inconsistent
resolve_inconsistent --(_route_after_llm: failure)--> END
resolve_inconsistent --(ok)--> triage → audit_flagged
audit_flagged --(_route_after_llm: failure)--> END
audit_flagged --(post-editing)--> apply_verdicts
audit_flagged --(proofreading)--> whole_doc_pass → apply_verdicts
apply_verdicts → report → write_glossary → sync_lemmas → finalize → END
```

Every LLM node writes its own `stop_reason` on failure and is followed by a conditional edge
(`add_conditional_edges`) that routes straight to END — the review agent's `_route_after_classify`
pattern, applied from day one so a parse failure can never fall through into `apply_verdicts`/
`report` and be summarized as a clean success (§8).

### Human-in-the-loop: one interrupt, edges traced before design

Per the terminal-resume warning: the review agent's original CAT UI design assumed a
resume-one-segment-at-a-time loop that the actual graph edges made structurally impossible
(`await_feedback`'s resume is consumed once; there is no path back to the same interrupt). This
graph therefore gets exactly **one** interrupt node, `confirm_scope`, with forward-only semantics
mapped now:

- **Trigger conditions (only these):** (a) the degenerate range case — no `Lara` column, no run
  `seg_range`, and a >50-segment document, i.e. the §3.3 fallback chain is exhausted (only
  reachable when the app's own seg_range gate was bypassed, e.g. a direct Swagger `/start`);
  (b) `classify_terms`/`gather_evidence` detect a contamination-scale situation that survived
  `load_inputs`' hard-fail (a large fraction of draft rows unattested for a reason other than a
  missing xlsx) — SKILL.md Step 5's "put large scope decisions to the user."
- **Resume payload:** `{"range": [min,max]} | {"drop_unattested": bool}` (one decision object).
- **On resume:** `Command(goto="gather_evidence", update={"pending_decision": ...})` — strictly
  forward. Resuming twice is impossible by construction (the graph never re-enters
  `confirm_scope`); a wrong answer is corrected by `/cancel` + fresh `/start` — cheap and
  natural now that the step is REPEATABLE (§5).
- **Everything else is *not* an interrupt.** The human review point for glossary *content*
  already exists downstream: `GLOSSARY_REVIEWED` is a MUTABLE step with a working editor and an
  existing "one live editable field" UI. The agent's proposals land in the CSV and the report;
  the human edits the CSV itself there — no parallel "proposed vs. editable copy" is built,
  honoring the approve-clobbers-edit lesson from the review agent's CAT UI by not creating a
  second editable surface at all.

---

## 4. `agent/glossary_lib/` subpackage

**Building `agent/glossary_lib/` as an internal subpackage is an explicit goal of this PRD,
not a compromise:** defining the clean internal boundary now — while this code is being touched
anyway — is cheap and pays off immediately, since both the legacy path and the graph nodes
import the same functions instead of forking them (today the audit skill's scripts and the
production checker already duplicate logic). What is out of scope is only **distribution**: a
public, installable package would mean locking in an API boundary against vague requirements
with zero external consumers to validate it — revisit that once a second real consuming project
exists, at which point the subpackage's already-clean internal API is the natural starting
point. Legacy modules become thin re-exporting wrappers so every existing importer keeps
working unchanged.

### Module layout and what migrates where

| New module | Migrated functions (source file) |
|---|---|
| `glossary_lib/csv_io.py` | `parse_clean_glossary`, `clean_epo_title_row`, reassembly/writer logic (`llm_glossary_revise.py`); a new `write_clean_glossary(path, epo, rows, standard_rows)` extracted from `llm_glossary_cleanup.clean_glossary`'s write block; EPO-title read from `glossary_<PID>.csv` (`llm_glossary_cleanup.py`) |
| `glossary_lib/classify.py` | `ORDINAL_MODIFIERS`, `_EN_TO_DE_ORDINAL_STEMS`, `_strip_de_ordinal_word`, `_merge_ordinal_siblings`, `_is_ordinal_variant`, `SHARED_DE_ALLOWED`, `_shared_de_note`, consistent/inconsistent classification loops (`llm_glossary_cleanup.py`) |
| `glossary_lib/attestation.py` | `_appears_in` (`llm_glossary_cleanup.py`); `load_segments`, `find_segs`, `load_frequency_tables`, `lookup_in_tables` (`audit_glossary.py` — the skill script then imports from here too, ending the skill/production code fork) |
| `glossary_lib/matching.py` | `_count_lemmas`, `_count_en_phrase`, `_count_noun_in_de`, `_mask_de_noun_phrases`, `_DE_ADJ_SUFFIXES`, `build_glossary_lookups`, `check_segment_glossary` (`glossary_compare_revised_translation.py`); **lemma-table loading becomes an explicit `load_lemma_tables(proj_dir)` (shared baseline + project overlay merge, §6b) instead of module-level globals** — explicit parameter passing over ambient state, per house convention |
| `glossary_lib/lemma_sync.py` | Whole public surface of `verb_lemma_sync.py`, retargeted at the project overlay (§6b) |
| `glossary_lib/validate.py` | `parse_response`, `validate_result`, `_norm_en` (`llm_glossary_cleanup.py`); `parse_json_object_lenient` (`verb_lemma_sync.py`) + a new shared `parse_json_lenient` with bounded trailing-comma repair (§8) |

### Migration plan for existing callers — no breakage

1. Move function bodies; each legacy module re-exports (`from glossary_lib.matching import
   _count_lemmas, ...`) and keeps its `main()`/`__main__` entry point. `STEP_SCRIPTS` command
   lines, `app.py` imports, `review_agent/graph.py`'s `_build_lint_checks` import of
   `build_glossary_lookups`, and the CAT UI check endpoint all keep working with zero edits.
2. Test suites (`test_llm_glossary_cleanup.py`, `test_glossary_compare_revised_translation.py`,
   `test_verb_lemma_sync.py`, `test_linter.py` — 309 tests) run unmodified against the re-exports
   first (proving the move is behavior-neutral), then get their imports pointed at `glossary_lib`
   in a separate mechanical commit.
3. `glossary_lib` functions take explicit paths/arguments (no `project_log` context reads inside
   the library); context resolution stays in the thin script wrappers.
4. Convention throughout (existing and new code alike): Google-style docstrings on every function;
   comments only for genuinely non-obvious constraints, no line-by-line narration.

---

## 5. FastAPI / workflow-manager integration

### Insertion point: behind `GLOSSARY_ANALYZED`, not a new step

- **Step type changes `ONCE` → `REPEATABLE`** (decision, 2026-08-24) — consistent with the
  graph's cancel/re-run recovery model and with `TRANSLATION_REVIEW`'s precedent. Re-runs
  overwrite the single step row with `run_count` incremented; `write_glossary`'s per-run backups
  keep prior outputs recoverable.
- **Flag off (default at rollout):** `GLOSSARY_ANALYZED` runs exactly today's five subprocess
  commands, `llm_glossary_cleanup.py` included. Nothing changes.
- **Flag on (`GLOSSARY_AGENT_ENABLED=1`, env-level; overridable per-run via an optional
  `use_agent` field on the run body for A/B testing):** the step's command list drops
  `llm_glossary_cleanup.py`; when the four extraction subprocesses finish successfully,
  the run task schedules the graph via the generalized `_schedule_review_task` machinery
  (renamed `_schedule_agent_task`, keyed `(project_id, step_name)`), and the step **stays
  `IN_PROGRESS`** until the graph reaches a terminal state. The old path remains one env var away
  for the whole rollout — no rip-out.

### Routes (mirroring `TRANSLATION_REVIEW`'s precedent of bypassing `run_script_async` for graphs)

```
POST /api/projects/{pid}/glossary-agent/start     # extraction subprocesses + graph, 409 if running
GET  /api/projects/{pid}/glossary-agent/status    # get_status() from the checkpointer
POST /api/projects/{pid}/glossary-agent/resume    # confirm_scope answer only
POST /api/projects/{pid}/glossary-agent/finish    # completes the workflow step — WITH bounded retry
POST /api/projects/{pid}/glossary-agent/cancel    # wipes checkpoint thread; 409 while in_progress
```

Plus a mounted sub-app (`app.mount("/glossary-agent", glossary_app)`) exposing the same operations
with explicit `project_folder` for Swagger-driven testing without DB/project registration — the
review agent's proven "testable interface before any frontend exists" split.

- **`/finish` retry-on-conflict from day one:** the frontend's `finalizeReviewStep()` pattern —
  up to 5 retries at 1.5s on 409 — is reused verbatim, because the same TOCTOU gap (a client
  observes "completed" milliseconds before the final checkpoint commit lands) is structural, not
  review-agent-specific. Failure after retries is reported honestly, never swallowed.
- **`project_log.json` / `workflow_db` step-state:** `db.start_step` on `/start`,
  `db.complete_step(pid, "GLOSSARY_ANALYZED", metadata={...})` from `/finish` with the run's
  summary (counts per verdict action, report path). Failure/cancel → `FAILED`, same as review.
- **Frontend:** the `GLOSSARY_ANALYZED` step panel polls status **indefinitely** (no attempt cap
  — the 40s-cap incident is a named anti-pattern), re-fetches live status on page load regardless
  of any cached running flag, surfaces the `confirm_scope` question inline when
  `stop_reason == "awaiting_input"`, and streams the graph's logs through the existing
  `_ReviewLogBufferHandler` demux pattern (a second handler keyed on the new step name).
- **"Step awaiting input" badge (decision, 2026-08-24):** a generic badge on the project list
  whenever any agent step (`TRANSLATION_REVIEW` or `GLOSSARY_ANALYZED`) is paused at an
  interrupt — one shared mechanism (project-list endpoint aggregates each agent's
  `get_status()`; badge on `awaiting_input`), fixing the "run paused while the user was away and
  nothing said so" gap for both agents at once. Built in Phase 3.

### Swagger documentation standard (budgeted work, not an afterthought)

Every model field documented in plain language for a reader with no code knowledge and no memory
between calls: the sub-app carries a top-level walkthrough of the actual call sequence; every
`stop_reason` value states what it means *and what to do next*; id formats, file paths, and
payload shapes are restated inline wherever referenced, never "see above." The review agent's
`api.py` (`SegmentDecision`/`ReviewResumeBody`/`StatusResponse` docs) is the concrete bar to meet.

---

## 6. Data contracts

### 6a. Glossary I/O — unchanged

**Inputs consumed** (all pre-existing, produced by the untouched extraction commands):
`verb_segment_pairs.csv`, `capability_segment_pairs.csv` (optional), `noun_canonical_glossary.csv`,
`verb_canonical_glossary.csv`, `capability_canonical_glossary.csv` (optional),
`noun_inconsistency_table.csv`, `glossary_<PID>.csv`, the project's bilingual `*.xlsx` (including
its `Lara` column for the pretranslation range), `standard_glossary.csv`, `_styleguide.md`,
lemma tables (§6b).

**Output produced:** `clean_glossary_<PID>.csv`, byte-compatible with every downstream consumer:

- `utf-8-sig` (BOM), literal `EN,DE` header, plain comma-separated, no unnecessary quoting.
- EPO title as a normal first data row, **already passed through `clean_epo_title_row()`** — no
  `"EPO EN:"`/`"EPO DE:"` label prefixes, inner commas replaced by spaces. (The one deliberate
  delta vs. `llm_glossary_cleanup.py`'s labeled row: this is the contract the decisions section
  fixes, and what `llm_glossary_revise.py` already produces; downstream readers take column 0/1
  positionally and are unaffected.)
- Section structure preserved: title row, blank line, project terms, blank line, appended
  relevant-standard terms — `parse_clean_glossary` must keep round-tripping it.

**Side-effect files:** lemma overlay growth (§6b), the report (markdown string in state + saved as
`glossary_agent_report_<PID>.md` next to the CSV), and a pre-write backup of any existing CSV.

Nothing downstream — checker, Lara/XTM upload, CAT UI, `GLOSSARY_REVIEWED` editor — changes.

### 6b. Project-scoped lemma overlay — fixed in one go (decision, 2026-08-24)

The Railway durability problem (`/app/agent/` re-downloaded fresh from GitHub every deploy, so
`verb_lemma_sync`'s writes to the shared lookup tables evaporate at the next deploy — the
standing `ISSUES.md` entry, auto-push rejected) is solved **inside this PRD**, not deferred:

- The repo-shipped `EN_verb_lemma_lookup.json` / `DE_verb_lemma_lookup.json` become a
  **read-only shared baseline** (versioned in git, edited only deliberately by hand/commit).
- Each project gets an **overlay pair** in its own pre-processing folder
  (`projects/<...>/pre-processing/EN_verb_lemma_overlay.json` / `DE_verb_lemma_overlay.json`),
  living with the rest of the project data on the persistent `/data` volume — so it survives
  deploys for exactly as long as the project itself does.
- `glossary_lib.matching.load_lemma_tables(proj_dir)` merges baseline + overlay at load time
  (additive merge; overlay wins on the — rare, since both sides are additive-only — key
  conflicts). Every checker path (`glossary_compare_revised_translation.py` script, CAT UI
  endpoint, review agent's `_build_lint_checks`, this agent's `gather_evidence`) loads through
  it, so project-specific verb paradigms are visible wherever the project is checked.
- `sync_lemmas` (and the new checker-note backfill) writes **only the overlay** — the shared
  baseline is never written at runtime anymore.
- Side benefit, explicitly wanted: new-domain verbs stop accumulating in one ever-growing shared
  table that the user suspects already clutters checks across unrelated domains — a pharma
  project's paradigms stay in the pharma project's folder.
- Migration: nothing to migrate — existing shared-table content stays as the baseline; overlays
  start empty per project. `verb_lemma_sync.py`'s wrapper keeps its signature with the overlay
  paths as the new defaults.

### 6c. Companion linter check (independent deliverable, decision, 2026-08-24)

The client-dictated `standard_glossary.csv` can be unreasonable (contradictory terms); the agent's
ceiling for shared-file defects stays **report-only** — it proposes, never edits. The former
`multiple,multiple` row is already deleted by the user and is replaced by a **linter check**, not
a glossary entry:

> If `mehr*` occurs *x* times in a target segment: when "more" appears anywhere in the source
> claims text but not *x* times in the currently-checked segment's own source, flag
> `"x times 'mehr*' in target but y times in source"`.

This is target-triggered (linter territory, per the checker's source-triggered-only design) and
needs document-level context ("anywhere in the source claims text"), i.e. the same
document-order-stateful pattern as `german_claim_no_article`. It ships as a `linter.py` check +
tests, independent of the agent's phases.

---

## 7. Cost / latency and triage strategy

**The cheap layer always runs first.** LLM reasoning never sees: the unfiltered standard glossary
(`_appears_in` filtering is deterministic and stays), ordinal siblings (merged mechanically),
or rows the evidence layer can positively clear. Triage after `gather_evidence`:

| Bucket | Criteria (all deterministic) | LLM cost |
|---|---|---|
| **Clean** | EN+DE attested in benchmark range; DE value/lemma unique bidirectionally; checker run produces no note; not title-anchored; no styleguide/standard tension | none — passes through to `apply_verdicts` as `keep` |
| **Flagged** | any of: DE unattested anywhere; EN attested only inside compounds; bidirectional collision; title-anchor mismatch; standard-glossary tension; checker note; lemma-sweep gap (candidate `add`); duplicate/stem-inconsistency pair | batched into `audit_flagged` |
| **Inconsistent sets** | today's classification | `resolve_inconsistent` batch call (as today) |

On observed projects the flagged bucket is a minority of rows (the HALA live run: ~10 findings
out of ~50 entries), so `audit_flagged` is expected to fit in 1–3 batched calls, not per-term
calls. The proofreading-only `whole_doc_pass` adds one more evidence sweep (deterministic) and
typically one further batched call over its flagged keys.

**Estimated per-project LLM spend** (typical ~70-term post-editing project): 1 small title call
(~1k tokens), 1 resolve call (today's ~15–30k-token input, unchanged), 1–3 audit calls (~5–15k
tokens each with evidence bundles), 0–1 lemma-derivation call (existing) ⇒ roughly 2–4× today's
single-call cost at DeepSeek/Luna pricing — cents per project — while replacing a manual audit
session that costs far more in Claude usage and user time.

**Model defaults (decision, 2026-08-24, clarified same day):** **every LLM node in the agent —
`check_epo_title`, `resolve_inconsistent`, `audit_flagged`, `whole_doc_pass` — defaults to
Luna 5** (the review agent's validated model), nothing less. DeepSeek V3 stays only where it
already is: the legacy fallback path's `llm_glossary_cleanup.py` call (flag off), where it
remains the validated choice for that standalone batch prompt. Since `resolve_inconsistent`
inherits that prompt's lineage but runs on a different model, Phase 1's parity diff and Phase 2's
historical-project runs must explicitly check Luna 5 against the known model-swap regressions
(dropped consistent terms, broken compound consistency, standard-glossary preference — the
documented test criteria for ever changing the model on this prompt). Per-node env overrides
(`GLOSSARY_AGENT_MODEL_TITLE` / `_RESOLVE` / `_AUDIT`) remain for testing, but the shipped
default is Luna 5 across the board.

**Other config-driven guardrails** (env-overridable): `MAX_TOOL_CALLS_PER_NODE`,
`NODE_TIMEOUT_SECONDS`, `LLM_CALL_TIMEOUT_SECONDS` (inner httpx-level timeout smaller than the
node bound — defense-in-depth, same as review), `MAX_PARSE_RETRIES`, `MAX_AUDIT_BATCH_TERMS`, and
an overall `MAX_RUN_LLM_CALLS` budget that trips a `budget_exceeded` stop_reason.

**OpenRouter `session_id`:** every call passes `extra_body={"session_id": project_id}` via a
`_session_kwargs()` helper, reusing the pattern proven in `review_agent/graph.py`, so a whole
run groups in the OpenRouter dashboard.

---

## 8. Operational robustness

All five items below are transfers of real incidents from the review-agent build, designed in from
the start:

1. **LLM JSON parsing: bounded retries + lenient repair + explicit failure routing.** Every LLM
   node parses through the shared `glossary_lib.validate.parse_json_lenient` (fence stripping,
   bracket-scan, trailing-comma repair — the exact glitch that crashed the review agent twice in
   production). On failure: up to `MAX_PARSE_RETRIES` re-prompts (each echoing the parse error),
   then `stop_reason = "error"` with the raw response preserved in `report`. **Non-negotiable:**
   each LLM node is followed by a conditional edge checking its own reported status and routing
   to END on failure — no failure may fall through into `apply_verdicts`/`report_node`, which
   would otherwise summarize an empty verdict list into a plausible "nothing to change" success.
   The empty-input case is additionally guarded: `apply_verdicts` treats zero verdicts *with*
   flagged rows outstanding as an error state, not a clean pass.
2. **Stall watchdog.** The graph's background tasks go through the same scheduled-at bookkeeping
   as review tasks: `faulthandler.register(SIGUSR1)` already exists at startup; the
   `_review_task_watchdog` loop is generalized to watch both task families — WARNING at ≥3s
   pending, automatic `faulthandler.dump_traceback()` at ≥8s, once per stall. (The 8-minute
   silent scheduling stall this exists for was real and remains unexplained; the watchdog is the
   instrument that will finally catch it if it recurs.)
3. **Finalize retry-on-conflict.** `/glossary-agent/finish` re-checks graph status independently
   of whatever the polling client just saw; the frontend retries a 409 up to 5× at 1.5s before
   reporting failure honestly (never silently stranding a completed run's step at `IN_PROGRESS`
   — the exact incident the review agent shipped with and fixed live).
4. **Polling discipline.** No fixed short poll caps anywhere; status re-fetched from the live
   checkpointer on every page load / step render, preferred over any cached "is it running" flag
   — two independently-tracked copies of run state (workflow DB vs. graph checkpoint) are assumed
   to drift, and the human-visible one reads the live source.
5. **Concurrency theories get verified against library source before workarounds.** The
   `SqliteSaver` thread-safety suspicion was disproven in ten minutes by reading the installed
   `langgraph-checkpoint-sqlite` source (real `threading.Lock()` on both reads and writes); the
   same discipline applies here — the checkpointer setup copies review's
   (`sqlite3.connect(check_same_thread=False)` + `SqliteSaver`), which is a validated non-issue.

---

## 9. Testing plan

**Existing suites stay green at every phase** (309 tests: `test_llm_glossary_cleanup.py`,
`test_glossary_compare_revised_translation.py`, `test_verb_lemma_sync.py`, `test_linter.py`):

1. **Phase-0 gate (glossary_lib move):** full suite passes with legacy modules as re-exporting
   wrappers, before any import is rewritten. A small import-equivalence test asserts each moved
   symbol is the same object through both paths.
2. **Lemma-overlay tests (Phase 0b):** `load_lemma_tables` merge semantics (baseline-only,
   overlay-only, conflict), sync writing only the overlay, checker resolving an overlay-only
   paradigm (`anzuzeigen`-class regression case), and the existing `test_verb_lemma_sync.py`
   suite retargeted at overlay paths.
3. **Node unit tests** (new `test_glossary_agent.py`, review-agent style): deterministic nodes
   against fixture CSVs; `resolve_range` reading the Lara column; triage-bucket assignment (each
   flag criterion gets a positive and negative case); `_route_after_llm` failure routing (a parse
   failure must reach END with its stop_reason intact — the fabricated-success regression test);
   `confirm_scope` resume routing; workflow-kind conditional edge (post-editing skips
   `whole_doc_pass`); `write_glossary` output byte-compared against a golden file (BOM, sections,
   cleaned title row).
4. **Replay tests for LLM nodes:** captured real responses (including one with a trailing comma,
   one truncated, one echoing the title row) driven through parse/validate/apply without network.
5. **Historical-project regression checks** — the decisive validation, using projects whose
   correct outcomes are documented:
   - **RTC_2608_P1331:** agent must override the 7/8 `Prüfvorrichtung` majority with
     `Testvorrichtung`/`testen` from the EPO title.
   - **FRKE_2608_P0736:** must not let `exhibit`/`provide` share a DE verb; `provide→bereitstellen`
     (standard hard requirement) and a distinct third verb for `exhibit`; `have/having→aufweisen`
     shared (not `besitzen`).
   - **MICTCH_2608_P0124** (a proofreading-shape job — also exercises `whole_doc_pass`): must
     delete `using,mithilfe` and `enable,in die Lage versetzen`, add `chip enable pin`, keep
     minority-correct `Datentransaktion`, keep claims-attested `write`/`perform`, and surface
     `memory sub-system` as a bucket-3 addition with claims-priority sourcing.
   - **HALA_2608_P0655:** ordinal merges reproduced (`image data,Bilddaten` etc. — now upstream,
     must not regress), Eingang/Eingabe drift surfaced, `anzuzeigen`-class lemma gap caught by
     the live-checker sweep at draft time.
   Each runs against the archived project folder; assertions target the specific rows above plus
   "no row lost relative to the human-approved final glossary," not byte-identity (LLM nodes are
   non-deterministic in wording; row-level outcomes are the contract). These run on demand
   (real LLM spend), not in CI.
6. **Live parity run (Phase-1 gate):** agent path vs. old path on one fresh real project,
   diffed row-by-row, before the flag is enabled by default.

---

## 10. Incremental delivery plan

Each phase ships something usable on its own; no big-bang cutover; the old path stays runnable
throughout. (Per house practice: nothing here implies pushing or deploying without explicit
go-ahead at each phase.)

- **Phase 0 — `glossary_lib/` extraction.** Pure refactor + re-exports, full suite green.
  Standalone value: skill scripts and production code stop forking the same logic.
- **Phase 0b — project-scoped lemma overlay (§6b).** Behavior change with its own tests,
  shipped separately from the pure refactor. Standalone value: closes the Railway durability
  hole for the *existing* pipeline immediately, agent or no agent.
- **Phase 1 — graph parity skeleton.** `glossary_agent/` with deterministic nodes +
  `resolve_inconsistent` only (a faithful port of today's batch call), Swagger-only trigger,
  output parity-diffed against the old path on a real project. No workflow wiring yet.
- **Phase 2 — the judgment stage.** `gather_evidence`, `check_epo_title`, triage,
  `audit_flagged`, `whole_doc_pass` (proofreading conditional), `apply_verdicts` hard gate,
  report. Validated against the four historical projects (§9.5), which doubles as the Luna 5
  default-model validation. Still Swagger-triggered; the user can already run it manually on
  live jobs as an audit-skill replacement — this is the phase that retires the manual skill
  session.
- **Phase 3 — workflow integration.** `GLOSSARY_ANALYZED` → REPEATABLE; feature flag; run-path
  split; status polling + `confirm_scope` UI in the step panel; the shared "step awaiting input"
  project-list badge (covers `TRANSLATION_REVIEW` too); `/finish` with retry; log streaming;
  watchdog generalization. Rollout: flag on for new projects, old path one env var away.
- **Phase 4 — hardening + cleanup.** Live incidents folded back in; once N consecutive real
  projects need no fallback, `llm_glossary_cleanup.py`'s LLM call path is deprecated (file stays
  as the library wrapper + standalone entry point); SKILL.md gets a header pointing at the agent
  for the parts it automates.
- **Companion, phase-independent:** the `mehr*` linter check (§6c) — small, self-contained
  `linter.py` addition with tests, can ship any time.

---

## 11. Decisions resolved 2026-08-24 (formerly open questions)

1. **Benchmark range via fallback chain, never re-asked:** the `Lara` marker column of
   `*_translated.xlsx` (the pretranslation range) → else the `seg_range` this `GLOSSARY_ANALYZED`
   run was triggered with (the step already requires one for >50-segment documents) → else the
   whole document (safe: an empty range only passes the gate at ≤50 segments). Covers
   description-only jobs too, since pretranslation starts at the document's beginning (claims
   arrive via TMX→Lara upstream); external-reference support dropped. Proofreading workflow
   additionally runs the whole-document pass.
2. **Models:** Luna 5 for **every** agent LLM node (as in the review agent) — nothing less.
   DeepSeek V3 remains only in the legacy fallback path (`llm_glossary_cleanup.py`, flag off).
   Config-driven overrides retained; Luna 5 on the resolve prompt gets the model-swap regression
   checks in Phases 1–2.
3. **Step-7 whole-document mode is conditional on workflow:** post-editing → skipped (corpus is
   raw MT, findings meaningless pre-correction); proofreading → runs (`whole_doc_pass`, §3.7b).
4. **`GLOSSARY_ANALYZED` becomes REPEATABLE.**
5. **Lemma durability fixed now, in this PRD:** project-level lemma overlay files stored with the
   pre-processing data (§6b, Phase 0b).
6. **"Step awaiting input" badge** added to the project list for both agents (Phase 3).
7. **`standard_glossary.csv` ceiling stays report-only.** The client dictates it and it can be
   contradictory; the agent proposes fixes in its report, never edits. The `multiple,multiple`
   row is already deleted; its purpose is replaced by the `mehr*` linter check (§6c).

## 12. Remaining open items / risks

1. **Claims-identification pre-step (future work, explicitly out of scope here).** The real
   long-term fix for range selection is a step *before pretranslation* that analyzes the source
   text, locates the claims, and picks the non-repetitive part of them (long claim sets are
   usually system-claims + method-claims restating the same terminology; description-only
   sources repeat the claims early, often after the prior art, e.g. "an objective of the present
   invention is therefore..."; the detailed description must never enter pretranslation or
   glossary analysis). This would extend `segment_info` and benefit token cost across the whole
   pipeline, not just this agent. Recorded as a TODO — most current use cases are short claims,
   so the Lara-column approach in §3.3 is sufficient for now.
2. **Proofreading workflow is itself not yet implemented** (17-step plan approved 2026-08-17,
   unbuilt). `whole_doc_pass` and the `workflow_kind` conditional are designed and testable
   against archived proofreading-shape projects (MICTCH) now, but the live wiring waits on that
   workflow existing; the conditional defaults to post-editing behavior.
3. **The `Lara` column as the range source needs one verification pass** — confirm the marker
   (written to column 4 of `*_translated.xlsx` by `lara_translate.py` per successfully-translated
   segment) is stable across recent projects, and whether XTM-TM-pre-filled segments inside the
   pretranslation range lack the marker (they aren't Lara-translated — if so, derive the range
   as min..max of marked ids, not the exact marked set). Low-stakes either way: the §3.3
   fallback chain (run `seg_range`, then whole-document) backstops any gap.
4. **Luna 5 on the resolve prompt is the one model bet needing validation.** Luna 5 is proven
   for judgment-with-tools (review agent) but unproven on the batch-consolidation prompt, whose
   documented model-swap failure modes (dropped consistent terms, broken compound consistency,
   ignored standard-glossary preference) were exactly why DeepSeek V3 was chosen there
   originally. Phase 1's row-by-row parity diff against the old path answers this cheaply; the
   config-driven model knobs are the escape hatch if it disappoints.
