# Implementation plan: Glossary Agent

Actionable TODO breakdown of `PRD_glossary_agent.md`. Exit gates per phase live in
`TEST_glossary_agent.md` — a phase is done when its checklist there is green, not when its code
compiles. Check TODOs off here as they land, with the commit hash next to substantial items.

**Ground rules for every session working off this doc:**

- **NEVER push without the user's explicit permission — no exceptions, regardless of prior
  approvals.** When permission is given, push in this order: **1) `agent` submodule branch
  `glossary-agent`, 2) outer repo branch `glossary-agent`** — outer pointer commits must
  resolve for anyone checking out the branch.
- Branches: outer repo `glossary-agent` + agent submodule `glossary-agent`. Submodule commits
  land on the submodule branch; each is followed by a pointer-bump commit on the outer branch.
- Full pre-existing suite green after every phase (309 submodule tests + outer `tests/`).
- Old path stays runnable at all times (`GLOSSARY_AGENT_ENABLED` off ⇒ today's behavior,
  byte-for-byte).
- Google-style docstrings on every new function; comments only for non-obvious constraints.

---

## Phase 0 — `agent/glossary_lib/` extraction (PRD §4)

Pure refactor. No behavior change, no new features. Submodule only.

- [x] **0.1 `glossary_lib/csv_io.py`**
  - [x] Move from `llm_glossary_revise.py`: `parse_clean_glossary`, `clean_epo_title_row`,
        the reassembly logic.
  - [x] Extract `write_clean_glossary(path, epo, rows, standard_rows)` from
        `llm_glossary_cleanup.clean_glossary()`'s write block (keep the labeled-title behavior
        for now — the label-stripping delta activates only in the agent's `write_glossary`
        node, Phase 1).
  - [x] Move the EPO-title read (`glossary_<PID>.csv` "EPO EN:"/"EPO DE:" row scan) from
        `llm_glossary_cleanup.py` into `read_epo_title(glossary_path)`.
- [x] **0.2 `glossary_lib/classify.py`** — move from `llm_glossary_cleanup.py`:
      `ORDINAL_MODIFIERS`, `_EN_TO_DE_ORDINAL_STEMS`, `_strip_de_ordinal_word`,
      `_merge_ordinal_siblings`, `_is_ordinal_variant`, `SHARED_DE_ALLOWED`, `_shared_de_note`,
      plus the consistent/inconsistent classification loops factored into callable functions
      (`classify_verbs(verb_groups)`, `classify_nouns(noun_can, noun_deviations)`,
      `classify_capabilities(cap_groups)`).
- [x] **0.3 `glossary_lib/attestation.py`**
  - [x] Move `_appears_in` from `llm_glossary_cleanup.py`.
  - [x] Move `load_segments`, `find_segs`, `load_frequency_tables`, `lookup_in_tables` from
        `.claude/skills/glossary-range-audit/audit_glossary.py`; rewrite that script to import
        from here (its CLI behavior unchanged).
- [x] **0.4 `glossary_lib/matching.py`**
  - [x] Move from `glossary_compare_revised_translation.py`: `_DE_ADJ_SUFFIXES`,
        `_count_lemmas`, `_count_en_phrase`, `_count_noun_in_de`, `_mask_de_noun_phrases`,
        `build_glossary_lookups`, `check_segment_glossary`.
  - [x] Replace the module-level `en_verb_lookup`/`de_verb_lookup` JSON loads with an explicit
        `load_lemma_tables()` function (baseline-only in this phase; `proj_dir` overlay comes
        in 0b). `build_glossary_lookups` calls it; the legacy module keeps its globals as
        re-exports for anything that pokes them directly.
- [x] **0.5 `glossary_lib/lemma_sync.py`** — move the whole public surface of
      `verb_lemma_sync.py` (paths stay the shared-table defaults until 0b).
- [x] **0.6 `glossary_lib/validate.py`** — move `parse_response`, `validate_result`, `_norm_en`
      (`llm_glossary_cleanup.py`) and `parse_json_object_lenient` (`verb_lemma_sync.py`); add
      the shared `parse_json_lenient(raw, expect=list|dict)` with bounded trailing-comma repair.
- [x] **0.7 Legacy wrappers**: `llm_glossary_cleanup.py`, `glossary_compare_revised_translation.py`,
      `verb_lemma_sync.py`, `llm_glossary_revise.py`, `audit_glossary.py` become thin
      re-exporting wrappers keeping their `main()`/`__main__` entry points and public names.
      **No importer outside the submodule changes in this phase** (app.py, review_agent, tests
      keep working untouched).
- [x] **0.8 Testability factor**: split `llm_glossary_cleanup.clean_glossary()` into
      `load_cleanup_inputs(proj_dir, project_id)` (everything before the LLM call) + the call +
      post-processing, so Phase 1's `load_inputs` node and the tests reuse the loading without
      network.
- [x] **0.9 Tests** — `agent/test_glossary_lib.py` per TEST §Phase 0 (import identity, golden
      CSV round-trip, no-`project_log`-imports check, wrapper smoke runs); full suite green
      **before** any test imports are rewritten; then one mechanical commit pointing test
      imports at `glossary_lib`.

## Phase 0b — project-scoped lemma overlay (PRD §6b)

- [x] **0b.1** `load_lemma_tables(proj_dir: Path | None)` in `glossary_lib/matching.py`:
      baseline (`agent/EN_verb_lemma_lookup.json` / `DE_...`) merged with overlay
      (`<proj_dir>/EN_verb_lemma_overlay.json` / `DE_...`), overlay wins on key conflict,
      missing overlay ⇒ baseline only. `build_glossary_lookups(proj_dir)` passes its
      `proj_dir` through.
- [x] **0b.2** `glossary_lib/lemma_sync.py`: default write targets become the overlay paths
      (derived from a `proj_dir` argument); baseline files are never written at runtime.
      `llm_glossary_cleanup`'s call site passes its `proj_dir`.
- [x] **0b.3** Update every checker path to load through the merge and verify each resolves an
      overlay-only paradigm: standalone checker script (`--pid`), app.py CAT UI check endpoint,
      `review_agent/graph.py::_build_lint_checks` (already passes `project_folder`), the future
      agent's `gather_evidence`.
- [x] **0b.4** Retarget `test_verb_lemma_sync.py` to overlay paths; add
      `agent/test_glossary_lib_lemma.py` per TEST §Phase 0b (merge semantics, overlay-only
      writes, `anzuzeigen` regression pair).

## Phase 1 — graph parity skeleton (PRD §3, §5-lite)

Outer repo (`glossary_agent/`) + submodule imports. Swagger-only trigger, no workflow wiring.

- [x] **1.1 Preliminary verification (PRD §12.3):** inspect 2–3 recent projects'
      `*_translated.xlsx` `Lara` column — marker name/position stability, and whether
      XTM-TM-pre-filled segments inside the range lack the marker (if so: range = min..max of
      marked ids). Record findings in this doc.
- [x] **1.2 `glossary_agent/graph.py` scaffolding**: `TermVerdict`/`GlossaryState` TypedDicts
      (PRD §3 schema incl. `run_seg_range`); config constants from env
      (`GLOSSARY_AGENT_MODEL_*` — all defaulting to Luna 5, `MAX_TOOL_CALLS_PER_NODE`,
      `NODE_TIMEOUT_SECONDS`, `LLM_CALL_TIMEOUT_SECONDS`, `MAX_PARSE_RETRIES`,
      `MAX_AUDIT_BATCH_TERMS`, `MAX_RUN_LLM_CALLS`, `GLOSSARY_CHECKPOINT_DB_PATH`
      absent-or-absolute); `_session_kwargs`; reuse `review_agent.get_openrouter_client`
      (import, don't duplicate); `_log_llm_call` clone with the `{project_id}:` log-prefix
      convention.
- [x] **1.3 Deterministic nodes**: `load_inputs` (via `load_cleanup_inputs`; **hard-fail →
      error END when no xlsx**), `classify_terms` (glossary_lib.classify), `resolve_range`
      (the §3.3 three-level fallback chain + ABSTRACT-boundary noting + `workflow_kind` from
      caller), `write_glossary` (csv_io + `clean_epo_title_row` + timestamped backup),
      `finalize`.
- [x] **1.4 `resolve_inconsistent` node**: port the batch prompt from `llm_glossary_cleanup.py`
      (incl. `_shared_de_note()`), `validate_result` + single bounded re-prompt, echoed-title
      drop, consistent-term fill-in — same semantics, Luna 5 default, parse via
      `parse_json_lenient` with `MAX_PARSE_RETRIES`.
- [x] **1.5 `confirm_scope` interrupt node**: degenerate-range + contamination-scale triggers
      only; forward-only resume via `Command(goto="gather_evidence")` (Phase 1: goto the next
      existing node); resume payload per PRD §3.
- [x] **1.6 Graph wiring**: edges per PRD §3 (Phase-1 subset), `_route_after_llm` conditional
      after every LLM node → END on failure; `SqliteSaver` checkpointer; `run_graph` /
      `resume_graph` / `get_status` (interrupts before `state.next`) / `cancel_run` —
      review_agent shapes.
- [x] **1.7 `glossary_agent/api.py`**: sub-app with explicit `project_folder` +
      `seg_range` + `workflow_kind` start body, status/resume/cancel; full Swagger field docs
      to the PRD §5 standard (budgeted — write them with the models, not after).
- [x] **1.8 Mount** in `app.py` (`app.mount("/glossary-agent", glossary_app)`) — sub-app only,
      no workflow-step coupling yet.
- [x] **1.9 Tests**: `tests/test_glossary_agent.py` per TEST §Phase 1 (node units, fallback
      chain ×4, confirm_scope routing, failure routing, status vocabulary, golden write).
- [ ] **1.10 `@llm_live`**: Luna-5 model-swap regression on archived input; then the row-by-row
      **parity diff protocol** vs. the old path on one fresh project — record the diff in this
      doc before proceeding.

## Phase 2 — the judgment stage (PRD §3 nodes 4–9, §7)

- [x] **2.1 `gather_evidence` node** (deterministic, glossary_lib): per-row EN/DE attestation
      (benchmark + whole corpus), frequency-table hits, verb lemma sweep with
      compound-embedded filtering, live-checker completeness run over the benchmark segments,
      bidirectional DE→EN index (draft + standard_glossary, `SHARED_DE_ALLOWED` exempt).
- [x] **2.2 Triage** (deterministic): PRD §7 criteria table → `clean` pass-through vs
      `flagged`; batching by `MAX_AUDIT_BATCH_TERMS`.
- [x] **2.3 `check_epo_title` node**: Step-1b prompt (usable/unusable + anchor pairs);
      deterministic post-check discards unattested anchors; errata → report.
- [x] **2.4 `audit_flagged` node**: prompt encoding SKILL.md Step 3/4 rules (PRD §3.7 list);
      tools `get_segments(ids)` / `count_pattern(regex)` / `check_entry(en, de)` in a bounded
      ReAct loop (review_agent `classify` shape: ThreadPoolExecutor timeout, per-call httpx
      timeout, tool-call cap); outputs `TermVerdict`s with reasoning strings.
- [x] **2.5 `whole_doc_pass` node** + `workflow_kind` conditional edge (proofreading only):
      whole-corpus evidence sweep, 4-bucket triage; buckets 2/3 → verdicts (claims-priority DE
      sourcing enforced deterministically), buckets 1/4 → report only.
- [x] **2.6 `apply_verdicts` node**: merge verdicts; hard gate = `validate_result` +
      bidirectional re-check (violating verdict ⇒ rejected, logged, reported); `extra_standard`
      append; **zero-verdicts-with-flagged-outstanding ⇒ error state**.
- [x] **2.7 `report_node`**: grouped-by-kind summary (Step 9 shape) incl. report-only findings;
      persist `glossary_agent_report_<PID>.md` next to the CSV.
- [x] **2.8 `sync_lemmas` node**: existing sync (overlay) + backfill of live-checker-note
      surface forms with LLM-derived paradigms (additive-only).
- [x] **2.9 Run budget**: `MAX_RUN_LLM_CALLS` counter in state → `budget_exceeded` stop_reason.
- [x] **2.10 Tests**: TEST §Phase 2 — evidence units, triage matrix, replay tests (incl. the
      three malformed-JSON shapes), apply-gate, whole_doc conditional, report markers,
      session_id assertion, guardrail stop_reasons.
- [ ] **2.11 `@llm_live` historical regression suite**: RTC / FRKE / MICTCH / HALA per the
      TEST table — record pass/fail + notes in this doc. **This gate retires the manual
      audit-skill session for new projects.**

## Phase 2b — corrected-design closeout (per `glossary_agent/corrected_PRD_GLOSSARY_AGENT.md`)

Not in the original PRD/TEST docs — added after the 2026-08-24 HALA Swagger test showed the
Phase 0-2 build ran fine mechanically but didn't faithfully transfer the skill's judgment logic
(see that session's findings above and the outer-repo `corrected_PRD_GLOSSARY_AGENT.md`, which
is the source of truth for the *why* behind every item below; this section is just the
actionable breakdown). Numbering here is this doc's own task numbering — it does **not** map
1:1 onto the corrected PRD's skill-point numbering (1.1–1.8, C11, D17–D19, etc.), which is a
separate mapping namespace; each task below cites the corrected-PRD point(s) it implements.

**Build order, per the corrected PRD's own explicit recommendation and the user's stated
priority (2026-08-25): land 2b.1 (the self-learning loop) first**, as a small real live
round-trip, before 2b.2–2b.6. Those five are judgment-quality refinements to a single run; 2b.1
is the mechanism that decides whether quality compounds across runs at all, and it's the one
piece with no proven precedent anywhere in either agent (the review agent's own equivalent,
`confirm_rule`, only got its first live validation on 2026-08-25 itself).

- [x] **2b.0 C15 — classify-and-drop for widespread unattested rows** (corrected PRD C15,
      redesigned 2026-08-24) — submodule `b5dab1b` (`glossary_lib.csv_io.load_standard_glossary`),
      outer `70ef321` (`evidence.classify_unattested`, `triage_node` wiring, `report_node`
      sections, `confirm_scope`'s `drop_unattested` payload removed). Deterministic pre-filter
      inside `triage_node`, no interrupt. Trigger: a row EN-and-DE-both-unattested **within the
      benchmark range** (`en_benchmark`/`de_benchmark`, not whole-corpus — the corrected PRD's
      explicit wording; distinct from C14's DE-only-unattested, untouched, still routed to
      `audit_flagged`). Classified by presence in the full, unfiltered `standard_glossary.csv`:
      present → drop with a real "delete" verdict (`origin: c15_standard_drop`), reported in a
      `"WARNING: standard-glossary terms unattested"` section; absent → drop
      (`c15_project_drop`), reported in a separate, plain `"unattested terms"` section. Neither
      reaches `audit_flagged`. Real verdicts (not just removal from `flagged`) so
      `apply_verdicts`' `extra_standard` fallback can't silently reinstate a dropped
      standard-glossary term — same bug class as the 2026-08-24 `apply_verdicts` fix.
- [x] **2b.1 Self-learning loop** (corrected PRD §5.1–5.5) — landed, submodule `bd44662`
      (`_glossary_agent_learnings.md` seed), outer (graph.py/api.py/tests, see decision log below
      for commit hash):
  - [x] New file `agent/_glossary_agent_learnings.md`, deliberately separate from
        `_styleguide.md` (styleguide = document-wide grammar house rules; this = generalized
        glossary-judgment patterns). Seed empty with a header + entry-format comment.
  - [x] Loader: read alongside `standard_glossary.csv`/`_styleguide.md` in `load_inputs`, fed
        into `audit_flagged`'s prompt at the **same priority tier as C10** (not a weaker hint) —
        `_AUDIT_SYSTEM_PROMPT` rule 2 amended to name it explicitly, not just standard_glossary.
  - [x] `TermVerdict` gains a `confidence: "high" | "medium" | "low"` field; `audit_flagged`'s
        prompt (new rule 9) requires it per verdict; `_raw_to_verdicts` defaults to "high" on a
        missing/mangled value rather than letting a malformed field silently force a pause.
  - [x] `await_clarification` node: batches all `confidence: "low"` verdicts from one
        `audit_flagged` (or `whole_doc_pass`) pass into a single interrupt via a new
        `check_confidence` join node (both upstream exits route there first) — same anti-spam
        discipline as `confirm_scope`; payload shows candidate verdict + evidence summary per row.
        Fires at most once per run (`clarification_done` latches on resume regardless of outcome).
  - [x] `handle_glossary_feedback` node — **only the `await_clarification` entry point built.**
        Applies each resolution (confirm/override) to the matching verdict, then makes one LLM
        call judging one-off vs. generalizable (mirrors `handle_correction`'s judgment — a
        malformed/failed LLM call degrades to "no rule" WITHOUT losing the already-applied
        resolutions, since those came from a human and are worth more than the rule guess).
        **The second entry point — free-text feedback on the ALREADY-FINISHED report — was NOT
        built this session.** It needs its own API design (feeding text into a completed
        checkpoint thread) that wasn't resolved; deferred, not forgotten. See decision log.
  - [x] `confirm_glossary_rule` interrupt (mirrors `confirm_rule` exactly): fires only when
        `handle_glossary_feedback` drafts a `rule_draft`; shows the draft, waits for explicit
        confirm/reject (+ optional `rule_text` edit), never auto-writes. Reject routes straight to
        `apply_verdicts` — nothing changed that would justify spending more LLM budget re-auditing.
  - [x] `append_to_learning_doc` node (mirrors `update_styleguide`): writes the confirmed entry
        (date, trigger, rule, source term, project id, status), then loops back into
        `audit_flagged` over the still-unaddressed `flagged` subset (narrowed by
        `handle_glossary_feedback` to exclude just-resolved rows) so the rest of *this* run
        benefits immediately. New `whole_doc_done` state flag guards `_route_workflow` against
        re-running `whole_doc_pass` a second time on this loop-back.
  - [ ] Quick-edit path (per [[feedback_patent_agent_correction_paths]]) — **not built.** There's
        no fast, no-conversation correction UI/API surface for this agent yet at all (Phase 3,
        workflow/frontend integration, hasn't started) — nothing to attach F27-style
        `sourcing_path: "quick-edit"` logging to. Revisit when Phase 3 adds one.
  - [ ] Live round-trip test (see TEST §Phase 2b): one low-confidence row, one real
        `confirm_glossary_rule` confirm, reload on a second run, confirm the learned rule
        actually loads and gets applied.
- [ ] **2b.2 `verify_against_checker` (post-merge)** (corrected PRD §1.7) — new node between
      `apply_verdicts` and `write_glossary`: re-run `build_glossary_lookups` +
      `check_segment_glossary` over the **entire** audited range against merged `final_rows`
      (not just rows touched this run — checker matching is corpus-relative, per the corrected
      PRD's reasoning). Three-way failure routing: (a) note on a row `audit_flagged` just
      added/amended → route back to `audit_flagged` with the failure evidence, 1 retry cap; (b)
      note on an untouched row caused by another row's delete/amend (interaction effect) → same
      routing, with a note on what changed nearby; (c) retry still fails → revert that row to
      its pre-merge (1.4/2.1-verified) state, add to a new report section "Could not
      auto-resolve." Hard gate: `write_glossary` cannot run while any `final_rows` row has an
      unresolved checker note — same class as `apply_verdicts`' existing hard gate (2.6).
- [ ] **2b.3 `_AUDIT_SYSTEM_PROMPT` rule 8 split** (corrected PRD C11, D17–D19) — same treatment
      rule 7 already got (2026-08-24, see decision log below): split the single dense sentence
      into four explicit sub-rules (minority-can-be-correct / generic-modifier-splitting /
      prefer-intact-compounds / duplicate-with-stem-inconsistency-check), each with its worked
      example (`data transaction`, `corresponding value` vs. `memory sub-system`,
      `have,besitzen` vs. `having,aufweisen`) inlined in the prompt. New regression test class
      mirroring `TestAuditSystemPromptRule7`.
- [ ] **2b.4 B6 — folded into 1.4/2.1, not built separately** (corrected PRD recommendation):
      tag `gather_evidence`'s checker notes with a `note_type` field
      (`missing_lemma_key` | `wrong_stored_value` | `interior_tag` | ...) so `audit_flagged` can
      route a missing-key note to `sync_lemmas`'s overlay-registration path specifically, rather
      than treating every note as "edit the CSV's DE value." No new step.
- [ ] **2b.5 `verify_trigger_in_claims` helper** (corrected PRD E23): deterministic segment-ID
      membership test against the claims boundary resolved in `resolve_range`; called wherever
      `whole_doc_pass` invokes claims-priority for a bucket-3/4 finding; result handed to the
      audit prompt as a precomputed fact, never re-derived by the LLM (this is the fix for the
      `including`/abstract three-strikes failure class).
- [ ] **2b.6 Structured synthesis log** (corrected PRD F27): `report_node` emits a JSON/CSV
      sidecar per changed row (`row_key`, `action`, `bucket`, `sourcing_path`, `segments`,
      `reasoning`) alongside the existing prose report, generated *from* the structured data
      rather than hand-assembled; `sourcing_path` values include `"user-clarification"` and
      `"learned-rule:<id>"` from 2b.1, and `"quick-edit"` from the quick-edit path. Feeds the
      historical-regression table (2.11) so it becomes queryable instead of eyeballed.

## Phase 3 — workflow integration (PRD §5)

- [ ] **3.1** `workflow_definitions.py`: `GLOSSARY_ANALYZED` `ONCE` → `REPEATABLE`.
- [ ] **3.2 Feature flag**: `GLOSSARY_AGENT_ENABLED` env + optional per-run `use_agent` on the
      run body; flag off ⇒ legacy five-command list, untouched.
- [ ] **3.3 Run-path split** in `app.py`: flag on ⇒ command list without
      `llm_glossary_cleanup.py`; on extraction-subprocess success schedule the graph (carrying
      `seg_range` + `workflow_kind` from the run body into initial state); step stays
      `IN_PROGRESS` until `/finish`; extraction failure ⇒ `FAILED`, no graph.
- [ ] **3.4 Routes**: `/api/projects/{pid}/glossary-agent/start|status|resume|finish|cancel`
      with the review-agent guard set (409s per TEST §Phase 3); `/finish` →
      `db.complete_step(..., metadata=...)`.
- [ ] **3.5 Task machinery generalization**: `_schedule_review_task` → `_schedule_agent_task`
      keyed `(project_id, step_name)`; watchdog loop watches both task families; log-streaming
      handler for the `glossary_agent.graph` logger into `_log_buffers` under the step key.
- [ ] **3.6 Frontend** (`frontend.html`): step-panel status polling (indefinite, live re-fetch
      on load), `confirm_scope` inline question + resume, `finalizeReviewStep`-style finish
      retry (≤5×@1.5s, honest failure), log stream reopen after finish.
- [ ] **3.7 "Awaiting input" badge**: project-list endpoint aggregates both agents'
      `get_status()`; badge renders on `awaiting_input`, clears on resume. Covers
      `TRANSLATION_REVIEW` too.
- [ ] **3.8** Swagger doc review pass (manual gate, TEST §Phase 3) + the manual UI test script
      run once live.
- [ ] **3.9 Tests**: `tests/test_glossary_integration.py` per TEST §Phase 3.
- [ ] **3.10 Rollout**: flag on for new projects only after 1.10's parity diff and 2.11's
      regression suite are recorded green here.

## Phase 4 — hardening + cleanup (PRD §10)

- [ ] **4.1** Fold back anything the first live-flag-on projects surface (append incidents +
      fixes to this doc).
- [ ] **4.2** After N clean consecutive projects (pick N with the user): deprecate
      `llm_glossary_cleanup.py`'s LLM path (file remains wrapper + entry point); header note in
      `glossary-range-audit/SKILL.md` pointing at the agent for the automated parts.
- [ ] **4.3** Re-verify the flag-off escape hatch still works on final code (TEST suite-wide
      exit criteria).

## Companion (phase-independent)

- [ ] **C.1 `mehr*` linter check** (PRD §6c): `linter.py` check + `test_linter.py::TestMehrMore`;
      document-order-stateful like `german_claim_no_article` — remember the same exclusion in
      `review_agent/graph.py::_build_lint_checks` if it joins `CHECKS`.
- [ ] **C.2** Regression guard: no `multiple` row re-added to `standard_glossary.csv`.
- **(idea, not scheduled)** Loop in the *project-scoped* `proofreading-scorecard` output as
  regression ground truth + rule candidates for 2b.1's learning loop — corrected PRD §5.6.
  Explicitly NOT the general cross-project `scorecard-analysis`/`consolidate_scorecards.py`
  pipeline, which stays excluded per the 2026-08-22 ruling ([[feedback_patent_scorecard_scope_distinction]]).
  Needs a project with both a glossary-agent run and a later proofreading scorecard to test
  against, and needs 2b.1 validated first.

---

## Decision log / findings while implementing

(append here: 1.1 Lara-column findings, 1.10 parity diff, 2.11 regression results, live
incidents — so the next session doesn't re-derive them)

**2026-08-24 — Phases 0, 0b, 1, 2 implemented** (submodule `40441b7`/`b0261bb`/`6f5a8ce`,
outer `226bfa6`/`6158483`/`9f82364`). All non-`@llm_live` gates green: agent suites 398
per-file, outer suite 169 + 4 llm_live skips. Findings:

1. **Task 1.1 — Lara column verified against real archives.** The marker is the literal
   lowercase string `"lara"` in **column 4** of the file written by `lara_translate.py`
   (typically the `<PID>_..._translated.xlsx`); the `*_GERMAN_translated.xlsx` Matecat export
   has **no** marker column. Samples: RTC_2606_P1098 ids 1–25 marked, RTC_2608_P1331 ids 1–34,
   both contiguous; MICTCH (proofreading-shape, no pretranslation) has no markers anywhere —
   as expected. Range derived as **min..max of marked ids** per PRD §12.3.
   `_scan_lara_range` prefers the marker-bearing file as corpus; falls back to the first
   `*_translated.xlsx`.
2. **Node-order correction vs. the PRD's §3 edge list**: `check_epo_title` runs BEFORE
   `resolve_inconsistent` (its attested anchors feed the resolve prompt — the title-outranks-
   majority rule needs to act at resolve time), and `gather_evidence` runs AFTER resolve
   (evidence is gathered per *draft row*, which doesn't exist pre-resolve). This matches the
   PRD's intent; the §3 diagram listed gather before resolve.
3. **confirm_scope trigger (b) (contamination-scale) simplified**: the missing-xlsx cause
   hard-fails in `load_inputs`; residual large-scale unattestation flows through triage →
   audit as ordinary per-row judgment, and a `drop_unattested` resume decision (when the range
   question was asked) pre-deletes rows attested nowhere without LLM spend. A second interrupt
   entry point would have broken confirm_scope's fixed forward-only `goto` — not worth it.
4. **check_epo_title parse failure degrades, doesn't kill the run** (verdict "title check
   failed — no anchor used", warning in report). Honest degraded mode like review's
   missing-XLF, not a fabricated success; the §8 hard-failure rule applies to nodes whose
   output downstream nodes would otherwise silently trust.
5. **zu-infinitive backfill is deterministic, no LLM**: `evidence.zu_infinitive_gaps` finds
   tokens where deleting one internal "zu" yields a known DE-table key (`anzuzeigen` →
   `anzeigen`) and `sync_lemmas` writes them straight to the project overlay.
6. **Pre-existing test-infra quirk (not ours)**: running `test_llm_glossary_cleanup.py` and
   `test_verb_lemma_sync.py` in ONE pytest process fails the two `TestLiveRoundTrip` tests —
   the cleanup suite's module-level `sys.modules["openai"]` mock poisons the live test's real
   client. Present on unchanged pre-Phase-0 code; suites pass per-file, which is how they're
   run. `test_glossary_lib.py` imports `test_llm_glossary_cleanup` first, deliberately, to
   share its canonical mock rather than racing it.
7. **Baseline DE lemma table already contains `anzuzeigen`** (added after the HALA incident),
   so HALA-shape regression tests must fabricate their own unknown forms rather than rely on
   that gap still existing.

**Still open (the two `@llm_live` gates):**
- **1.10 parity diff** — run flag-off vs. Phase-1 graph on one fresh project, record here.
- **2.11 historical regression suite** — `RUN_LLM_TESTS=1 pytest tests/test_glossary_regression.py -v -s`
  (copies each archive to tmp; real Luna 5 spend; asserts the RTC/FRKE/MICTCH/HALA row-level
  outcomes). Record pass/fail per project here. **This is the gate that retires the manual
  audit-skill session.**

**2026-08-24, later — first live Swagger run (HALA_2608_P0655, real project folder, real Luna 5
spend, user-triggered), 2 real bugs found and fixed:**

Run completed successfully (57 rows, 7 LLM calls, ~90s) and, compared row-by-row against the
2026-08-22 human-audited original, matched or improved on nearly everything: ordinal merges
intact, EPO-title anchors correctly overrode nothing incorrectly, ordinary DE-form differences
(genitive vs. nominative on `effective display area`/`horizontal direction`) are both
acceptable per SKILL.md Step 4's own doctrine, and `multiple,mehrere`'s absence is *expected*
(the user deleted that standard_glossary.csv row earlier this session — PRD §6c). But two
**structural** bugs surfaced, both now fixed in `apply_verdicts` (`glossary_agent/graph.py`)
with regression tests in `tests/test_glossary_agent.py::TestApplyVerdicts`:

1. **A `delete` verdict got silently undone by the standard-glossary fallback.** The audit
   correctly deleted `processing,Verarbeiten` (fabricated bare entry — the real content is
   compounds like `image processing unit`) and `any,beliebig` (masking-compound rule: both
   occurrences are inside the fixed claim-preamble `any of the preceding claims`, which the
   audit correctly added as its own compound entry instead). Both terms *also* have a
   `standard_glossary.csv` row, and `extra_standard`'s old computation
   (`relevant_standard − final_en`) only knew what *survived* into `final_rows`, not what had
   been deliberately cut — so both reappeared in the output's standard-terms tail, defeating
   the audit's own judgment. Fix: track `deleted_en` from `delete` verdicts and exclude it from
   `extra_standard` too.
2. **The "hard gate" didn't actually gate.** `validate_result` (shared with
   `resolve_inconsistent`'s retry loop) only ever drops empty entries and exact en+de
   duplicates — a standard-glossary-conflict or real DE/EN-duplicate row is reported as an
   *error* but still returned in `clean_rows` (by design, for the retry flow). `apply_verdicts`
   has no retry, so calling `validate_result` there and only logging the errors meant a verdict
   that reintroduced a conflict shipped anyway. Concretely: the audit amended
   `including,einschließlich` → `including,schließt ein` — a conjugated, multi-word form,
   chosen to satisfy the include/including stem-consistency house rule but violating the
   `standard_glossary.csv` hard requirement (`einschließlich`) *and*, mechanically, invisible to
   the production checker afterward (`build_glossary_lookups`/`build_lookups_from_rows` route
   verb-lemma EN keys with a space in DE into neither `verb_lookup` nor `noun_lookup` — the row
   would sit in the CSV but never be checked again). The gate logged a warning
   (`"Standard glossary conflict..."`) and shipped it regardless. Fix: new `_enforce_hard_gate`
   in `apply_verdicts` — (a) any EN with a `relevant_standard` entry gets that DE value
   unconditionally (self-heals this exact case, since `einschließlich` is also single-word and
   checker-compatible), (b) real duplicate collisions (the `exhibit`/`provide`→`führen` shape)
   are now actually dropped, not merely logged.

Open, not auto-fixed (flagged for a decision, not a mechanical bug): the same run added
`be,ist` as a `lemma_sweep_gap` "add" candidate — a bare copula/auxiliary verb, whose DE lemma
table coverage is partial (`is`→`be`/`ist`→`sein` registered; `are`/`was`/`were` are not), and
which is likely to misfire broadly on future checks of this project (a generic function word,
not domain vocabulary). No rule currently excludes generic/auxiliary verbs from
`lemma_sweep_gap` candidates or tells the audit prompt not to add them — unlike
`verb_lemma_sync.NON_VERB_DE_TERMS`, there's no equivalent stoplist here. Options: (a) a small
stoplist in `evidence.lemma_sweep` (mirrors `NON_VERB_DE_TERMS`), (b) an explicit rule in
`_AUDIT_SYSTEM_PROMPT`'s category-rules section. Needs a decision, not urgent — didn't undo it
manually since it's a content judgment call, not a mechanical defect.

Separately observed, not a bug: the audit kept bare `device,Vorrichtung` and `process,Vorgang`
via the standard+title-outranks-majority rule even though both are admittedly unattested as
bare words in this document (the LLM's own reasoning says so) — where the 2026-08-22 human
audit instead traced `device` to the real compound `display device,Anzeigevorrichtung` (the
`chip enable pin` pattern) and dropped bare `process` entirely. `_count_noun_in_de`'s
compound-head matching (2026-08-20/21 fix) likely still recognizes bare `Vorrichtung` inside
`Anzeigevorrichtung` going forward, so this is probably checker-safe, just less precise than
the human pass — a content-quality data point for future audit-prompt tuning, not something
fixed here.

**2026-08-24, later still — `_AUDIT_SYSTEM_PROMPT` rule 7 rewritten (user-driven, traced from
the live `be,ist` incident above), full history worth keeping:**

The user traced the `be,ist` addition all the way through — confirmed it came from a real
`_styleguide.md` line (113: `be (is/are) expressing a value or state | ist / sind | NOT:
"beträgt"`), read via `state["styleguide_text"]` (loaded once in `load_inputs`, used **only** by
`_audit_batch` — `resolve_inconsistent` and `check_epo_title` never see it), and correctly
pointed out that this exact rule is **already enforced target-side** by `linter.py`'s
`betraegt_stative` check (`_BETRAEGT_RE` flags `beträgt|betragen|liegt|liegen` in the DE output
directly) — a fundamentally better fit than a glossary entry, since "be"/"is" is far too
generic on the source side for count-matching to work without noise. The audit LLM had no rule
telling it that "this house rule is important" and "this belongs in the glossary" are different
questions, so it dutifully encoded the styleguide line as a new row.

Separately, the user also found rule 7's original `use` clause genuinely unclear — `"use"
keeps its entry unless the finite-verb instances themselves drift"` doesn't say which surface
forms count as "finite-verb instances," doesn't name the `using`/`by using` exclusion (the
actual point of the original SKILL.md rule — those render as a bare noun phrase, not a finite
verb, so a flag on them is expected noise), and "drift" itself is undefined jargon. Traced back
to `SKILL.md`'s Step 7 `use` bullet, which has the missing content but never made it into the
compressed prompt.

**Rule 7 rewritten** (word "drift" removed per direct instruction; `be`-exception added):
`by`/`at least` stay unconditional keeps; `use` is kept/added only when attested in finite form
(`use`/`uses`/`used`) — dropped if only `using`/`by using`/`for use` occur; `be` (or any finite
form: `is`/`are`/`am`) never enters the glossary at all, no further check, with the
`betraegt_stative` cross-reference stated explicitly in the prompt so the model (and any future
reader) knows the mechanism is covered elsewhere. New regression tests,
`tests/test_glossary_agent_phase2.py::TestAuditSystemPromptRule7` (4 tests: `drift` absent, all
six `use`-family forms named, `be`/`betraegt_stative` present, `by`/`at least` still
unconditional). Full outer suite: 177 passed, 4 llm_live skipped.

**Process note for future prompt edits:** this incident is a good argument for keeping a
regression test on every named exception in `_AUDIT_SYSTEM_PROMPT` going forward, not just
ad-hoc ones added after something breaks — a compressed system prompt is exactly the kind of
text that silently loses meaning under editing pressure with nothing to catch it.

**2026-08-25 — TEST doc gap audit + real fixture investigation for Phase 2b.** Reviewing
Phase 2b's own tests against `SKILL.md` found two real problems: (1) C15 (the redesigned
classify-and-drop step) had a task in the corrected PRD but no task/test anywhere in this doc's
Phase 2b — added above as 2b.0. (2) most of Phase 2b's tests (rule-8 marker checks, replay
tests) prove the scaffolding around an LLM call behaves, not that the LLM's actual judgment is
correct — the historical regression table is the only place that proves real outcomes, and
several real SKILL.md rules with live worked examples had zero representation there. Investigated
and resolved (data already in the project archives, no synthetic fixtures needed):

- **FRKE_2604_P0334 added as a 5th historical regression project** — the real source of
  SKILL.md's own "Anhang"/"Gliedmaße" title-domain-blindness example (confirmed by reading
  `RCA_FRKE_2604_P0334_de-DE_Sprogløsninger ApS.docx` and
  `Appendix A - SourceError_German_[Patent_FRKE_2606_P0334].xlsx` in the project folder). The
  archived `clean_glossary_FRKE_2604_P0334.csv` still carries the uncorrected `appendage,Anhang`
  row — a real, non-synthetic "before" fixture. Client's official correction is `Gliedmaße`;
  neither the raw MT (`Anhang`) nor the raw-MT majority (`Ansatz`, 2/4 per
  `noun_canonical_glossary.csv`) is right, so this case also proves majority-vote alone doesn't
  save you. RCA root cause, worth remembering as the real-world stakes case: the translator
  privately knew the correct term but suppressed the fix specifically to stay consistent with the
  bad title — the exact failure mode Step 1b part 2 exists to prevent, with a documented client
  Major Accuracy nonconformity as the consequence. Small (46 rows, claims-only), cheap to run.
- **FRKE_2608_P0736's existing row extended, no new project needed**: confirmed via
  `pre-processing/glossary-range-audit_practice/clean_glossary_FRKE_2608_P0736.csv.bak_preaudit`
  vs. the post-audit file that `any one of the preceding claims,einem der vorhergehenden
  Ansprüche` and `for use,zur Verwendung` were really added as masking compounds.
- **MICTCH_2608_P0124's existing row extended, no new project needed**: `verb_canonical_glossary.csv`
  confirms `cause,veranlassen,19,24,yes` / `cause,veranlass,5,24,no` — the exact split SKILL.md
  cites for "yes/no split is conjugation, not inconsistency." Also confirmed `including`/`include`
  really only occur at segment 430 (abstract) in this project, never in claims 369–428 — added as
  an explicit E23 assertion (the three-strikes regression case).
- **Standard-vs-consistency tiebreak — investigated, deliberately left untested.** User recalled
  a candidate MICTCH case (`cause`→`veranlassen` vs. a `führt zu` rendering, segments 56/60).
  Checked directly against the real translated xlsx: segment 56 doesn't contain "cause" at all;
  segment 60's `führen` is a whole-clause nominalization restructuring ("causing X to be
  enabled... can result in Y" → "...führen"), not a clean lexical choice — too ambiguous to
  assert against, matching the user's own hedge on it. The broader principle the user described
  (English sometimes has more near-synonyms — `execute`/`perform`/`carry out`, or
  `include`/`involve`/`incorporate`/`encompass` — than German has natural distinct equivalents,
  so DE overlap outside claims is acceptable rather than a defect) is real and worth keeping —
  see [[feedback_patent_glossary_bidirectional_consistency_exception]] — but has no confirmed
  real project attached. Do not build a test for this from the MICTCH case; wait for a real
  project that actually surfaces the pattern.

**2026-08-25, later — 2b.1 self-learning loop implemented.** Outer commit (see `git log` on
`glossary-agent` for the hash — this entry written pre-commit), submodule `bd44662` (learnings
file seed). Full outer + submodule test suites green (211 outer + 4 llm_live skips, 405 submodule)
throughout, including the pre-existing suite which never had to change.

Key design decisions made while building, beyond what the corrected PRD specified:

1. **`check_confidence` join node.** LangGraph conditional edges route to node names, not to an
   inline check shared by two upstream sources — `audit_flagged`'s direct exit and
   `whole_doc_pass`'s exit both used to point straight at `apply_verdicts`. Rather than duplicate
   the low-confidence routing check in two places, both now route to a new no-op `check_confidence`
   node first, which has the single `_route_to_clarification_or_apply` conditional edge.
2. **`whole_doc_done` flag, not in the corrected PRD.** The loop-back
   (`append_to_learning_doc → audit_flagged`) re-enters `_route_workflow`, which would otherwise
   re-run `whole_doc_pass` a second time on any proofreading-workflow run — Step 7 is a one-shot
   pass, unrelated to whether a new rule was just learned. `whole_doc_pass` now sets
   `whole_doc_done: True` on every return path; `_route_workflow` checks it.
3. **Loop-back only follows a CONFIRMED rule, never a rejection or "no rule."** Considered looping
   back after every `handle_glossary_feedback` call regardless of outcome, to give unaddressed
   low-confidence rows a second look — rejected: with nothing new in context (no rule, or a
   rejected one), a re-audit would just reproduce the same verdicts for real LLM cost. Only a
   genuinely new rule justifies spending the budget again.
4. **`flagged` narrowing, not a separate tracking field.** `handle_glossary_feedback` computes
   `remaining_flagged` (this run's `flagged` minus the EN keys the user just resolved) and passes
   it forward in the `Command` update; `append_to_learning_doc` reads it straight from state. This
   reuses the exact mechanism `audit_flagged` already batches over, so the loop-back call is
   just "call `audit_flagged` again" — no new re-audit code path needed.
5. **LLM failures in `handle_glossary_feedback` degrade, never fabricate a stop.** A malformed or
   failed rule-proposal call still returns `Command(goto="apply_verdicts", update=base_update)` —
   the user's explicit resolutions (already applied to `verdicts` before the LLM call) are never
   lost because a *secondary*, lower-stakes judgment (does this generalize?) failed. Distinct from
   `audit_flagged`'s own failures, which correctly DO stop the run — there the LLM call *is* the
   primary work; here it's optional enrichment on top of already-real human input.
6. **Deferred, not built:** the free-text "feedback on an already-finished report" entry point
   (corrected PRD §5.4's second entry point) needs its own API shape (posting into a *completed*
   checkpoint thread, which the current `/resume` guard explicitly rejects) that wasn't designed
   this session — `await_clarification` (the mid-run entry point) is what got built and tested.
   The quick-edit-path logging has no UI/API surface to attach to yet at all (Phase 3 territory).
   Both are real gaps, not oversights — see the TEST doc's Phase 2b section for the same caveat.
7. **Round-trip test is mocked, not `@llm_live`.** `TestSelfLearningRoundTrip` proves the graph
   wiring end-to-end through both new interrupts (confirm and reject paths) with scripted LLM
   responses — the cheap, fast proof that the *mechanism* works. It does NOT prove Luna 5 actually
   produces sensible `confidence` ratings or rule proposals on real content — that needs a real
   `@llm_live` run against an archived project (e.g. the small FRKE_2604_P0334 fixture) before
   trusting this on a live project. Not yet done.

**2026-08-25, later still — first real Swagger run against FRKE_2604_P0334, real Luna 5 spend
(user-triggered).** `project_folder` needs to be absolute (Swagger field already says so, but the
first attempt used a relative path and hit `load_inputs`' hard-fail — not a bug, a usage error).
Once corrected, the run completed successfully end-to-end and validated real, previously
untested-live behavior:

1. **`check_epo_title` correctly rejected this project's actual title.** `usable=False` — "Anhang"
   judged domain-inappropriate for "appendage." This is the live confirmation that the exact
   worked example this fixture was chosen for (SKILL.md's Anhang/Gliedmaße pattern, and this
   project's own RCA) actually works in the built agent, not just in mocked tests.
2. **C15 fired for real**: `21 clean, 30 flagged, 6 standard-glossary unattested (C15), 1
   project-term unattested (C15)` — first live confirmation of the whole 2b.0 mechanism.
3. **No `await_clarification` pause this run** — the audit didn't rate anything "low" confidence.
   Expected, not a bug: confirms the risk already flagged above (confidence is the model's own
   call, not guaranteed to fire on any given document) — this run just didn't happen to hit it.
4. **A real, live-caught bug: the no-op-amend defect.** The audit's report reasoning for
   `appendage` correctly argued "Anhang" must become "Gliedmaße" (echoing the title-check finding)
   — but the verdict's own `de` field still said "Anhang," unchanged, and the written CSV shipped
   the wrong value under an `### amend` label that implied it had been fixed. Root cause,
   traced from the surrounding log: the audit's `check_entry` tool call on its own proposed
   "Gliedmaße" correctly returned 0 attestation (expected — this is a post-editing job, the raw MT
   never used the correct term), but nothing told the model that a 0-count result on its OWN
   correction is fine, not a reason to quietly revert. **This is a different failure class than
   node 1.7 (post-merge checker verification) was designed to catch** — 1.7 checks attestation,
   and "Anhang" *is* attested in the still-uncorrected raw MT; the bug is reasoning-vs-output
   inconsistency, not an attestation gap.
5. **Fixed same session**, per the user's explicit design (not my first proposal — I suggested a
   silent revert-to-"keep" + report-only flag; the user asked for something that stays actionable
   within the run instead): extended `_audit_batch`'s existing parse-failure retry loop with a
   second validation layer — any `"amend"` verdict whose `de` is identical to the row's original
   value is invalid by construction (amend implies a change), gets one bounded retry with the
   specific offending row named and an explicit note that a 0-attestation check_entry result on
   the model's own correction is expected and not a reason to revert. If it's *still* unresolved
   after `MAX_PARSE_RETRIES` attempts, the verdict is forced to `action: "delete"`, `de: ""`,
   `confidence: "low"`, reasoning prefixed `COULD NOT AUTO-RESOLVE:` (original diagnosis
   preserved) — this reuses the already-built self-learning loop rather than inventing a new
   mechanism: the row surfaces at `await_clarification` (if that hasn't already fired this run) or
   in the final report's `[low confidence]` marker (new — see below), and a human can override it
   with the real corrected value through the existing resolution path.
6. **Confidence was invisible in the finished report — fixed alongside this, then corrected again
   per direct user feedback.** First pass: `report_node` appended `[low confidence]` only to
   verdicts where `confidence == "low"`, silent for "medium"/"high" — reasoned as "not worth the
   noise." **The user pushed back, and the pushback is right**: with a human colleague you can
   perceive confidence through the interaction itself; with a model, the only way is to say it
   explicitly, and every row in the glossary is a real judgment call, not just the ones that cross
   an alarm threshold. Changed to show confidence on EVERY verdict line, unconditionally —
   `(confidence: high|medium|low)` — across all sections: C15 drops, delete/amend/add, confirmed
   kept, and report-only findings. This is a real design principle for this whole agent going
   forward, not a one-off report tweak: don't design output as "surface it only past a threshold"
   when the underlying thing (a model's own confidence) has no other channel a human can read it
   through.
7. **Tests**: `tests/test_glossary_agent_phase2.py::TestNoOpAmendGuard` (4 tests — retry-then-
   resolves, retry-exhausted-then-deleted, a genuine amend is never flagged, "keep" is never
   flagged) and `TestReportAndBackfill` (confidence shown on every verdict, not just low; C15/
   report-only rows carry it too). Full outer (217+ llm_live skips) + submodule (405) suites
   green throughout.

**2026-08-25, later still — `GET /state` added, a real gap the user caught.** Watching the live
runs above, the user asked directly whether there's an endpoint for the checkpoint thread itself —
there wasn't (checked: the review agent has the identical gap). `/status` is deliberately curated
by `stop_reason` and shows an empty payload the entire time a run is `"in_progress"` — no way to
actually watch verdicts accumulate, evidence get gathered, or the report build, while it's
happening. New `graph.get_full_state(project_id)` returns the complete raw checkpoint
(`values`/`next`/`interrupts`, unfiltered) regardless of stop_reason; `GET /projects/{id}/state`
exposes it. Documented in the sub-app's top-level description under a new "Watching a run live"
section. Tests: `tests/test_glossary_agent.py::TestGetFullState` (not-started, completed exposing
a field `/status` never surfaces at all, paused exposing the raw interrupt payload) +
`tests/test_glossary_agent_api.py::TestStatePassthrough`. Same gap likely exists on
`/review-agent` — not fixed here, flagged for whenever that agent is next touched.

**2026-08-25, later still — architecture correction: the report is not the end state.** After
watching the live runs, the user pointed out a real design flaw in the original 2b.1 build (and in
my own first proposal for post-report feedback, which I'd deliberately taken OUT of the graph as a
stateless side mechanism): the run completing right after `report_node` means the model decides
when learning happens (via its own confidence rating), when it should be the human's call. **The
user's correction, implemented as specified:** `report` no longer routes straight to
`write_glossary`. It now routes to a new `await_agreement` interrupt — the one interrupt in this
graph explicitly designed to be re-entered any number of times, not fire-once. Resume with
`{"decision": "agree"}` to actually finalize (only now does `write_glossary` run), or
`{"decision": "feedback", "en", "de", "feedback"}` to comment on a specific row — routed to a new
`handle_agreement_feedback` node (one LLM call: propose a corrected `de` or confirm the existing
one after reconsidering, AND separately judge whether the feedback generalizes into a rule) — which
then reuses `confirm_glossary_rule`/`append_to_learning_doc`/`apply_verdicts` **completely
unchanged**, looping back through `report` to `await_agreement` again. Every round is a real
verdict (`origin: "human_feedback"`), so `apply_verdicts`' existing merge-by-EN-key logic naturally
makes the latest round win if the same term gets feedback twice — no new merge logic needed.

One real bug I had to design around, not just implement: `append_to_learning_doc`'s existing
"loop back to `audit_flagged` if `flagged` remains" check would misfire here — by the time a run
reaches `report`, `state["flagged"]` still holds whatever the *original* audit batch left in it
(nothing clears it after `audit_flagged` processes it; only the *mid-run* clarification path ever
narrows it). `handle_agreement_feedback` explicitly sets `flagged: []` on every exit path, so this
new loop can never accidentally re-trigger a wasteful full re-audit of the original batch.

State: new `pending_report_feedback: dict | None` field. Graph: `report → await_agreement`
(was → `write_glossary` directly); `await_agreement`/`handle_agreement_feedback` both dynamic
(Command), no static edges, same pattern as every other interrupt/feedback node here.
`get_status`/`api.py` extended for the new pause (`payload.agreement_question`) and resume shape
(`ResumeBody.en/de/feedback`); the sub-app's top-level description rewritten since `"completed"`
is now only reachable after an explicit agreement, not automatically.

Five existing graph-flow tests needed a `{"decision": "agree"}` resume added before their
`"completed"` assertion (they were asserting the old, now-wrong terminal behavior) — not
regressions, just the test fixture catching up to the new contract. New:
`TestAwaitAgreementDecisionLogic`, `TestHandleAgreementFeedback` (6 tests — real correction,
model-confirms-existing-is-fine, rule-drafted routing, malformed-output/exception/BudgetExceeded
all degrade or stop correctly, `flagged` always cleared), `TestAgreementLoopRoundTrip` (two
feedback rounds — one plain, one that also learns a rule — then agree; asserts the CSV reflects
the *latest* correction and the rule landed on disk). Full outer (230 + 4 llm_live skips) +
submodule (405) suites green.
