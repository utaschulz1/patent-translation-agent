# Test guide: Glossary Agent

Companion to `PRD_glossary_agent.md` — maps every feature the PRD promises to the test that
proves it. Organized by delivery phase; **each phase's tests are that phase's exit gate** — a
phase isn't done until its section here is all green. Check items off (`[x]`) as they land, and
add the test file/function name next to each item so this doc stays the index into the suite.

Conventions:

- Submodule-level tests (glossary_lib, linter) live in `agent/test_*.py`, next to the existing
  suites. Outer-repo tests (graph, API, integration) live in `tests/` next to
  `test_review_agent.py` / `test_review_integration.py`, reusing `tests/conftest.py` and
  `tests/fixtures/`.
- **The full pre-existing suite must stay green at every phase**: `test_llm_glossary_cleanup.py`,
  `test_glossary_compare_revised_translation.py`, `test_verb_lemma_sync.py`, `test_linter.py`
  (309 tests at time of writing), plus the outer `tests/` suite. Run all of it, not just the new
  files — `test_linter.py` imports from the checker module and has caught cross-module breakage
  before.
- Tests that spend real LLM tokens (historical regression runs, live parity) are **on-demand,
  never CI/default**: mark them `@pytest.mark.llm_live` and skip unless `RUN_LLM_TESTS=1`. Same
  pattern as `test_verb_lemma_sync.py`'s `TestLiveRoundTrip`.
- Fixture data: use archived real project folders (paths below) read-only; anything a test
  writes goes to `tmp_path` copies. Never point a test at the live `agent/_styleguide.md`,
  `standard_glossary.csv`, or shared lemma tables — copy them (the review agent's
  `tests/test_styleguide/` scratch-copy precedent).

---

## Phase 0 — `glossary_lib/` extraction (PRD §4)

Proves: the refactor is behavior-neutral and nothing forks.

- [ ] **Import equivalence** (`agent/test_glossary_lib.py`): for every migrated symbol in the
  PRD §4 table, assert the legacy module's re-export *is* the `glossary_lib` object
  (`llm_glossary_cleanup._merge_ordinal_siblings is glossary_lib.classify._merge_ordinal_siblings`,
  etc. — identity, not equality).
- [ ] **Full existing suite green, unmodified** — run before any test imports are rewritten.
  This is the "behavior-neutral" proof; no new assertions needed beyond it passing.
- [ ] **CSV round-trip golden test**: `csv_io.write_clean_glossary` → `parse_clean_glossary` →
  byte-compare against a golden `clean_glossary` fixture: utf-8-sig BOM present, literal
  `EN,DE` header, title row cleaned via `clean_epo_title_row` (no `EPO EN:` labels, no inner
  commas), blank-line section structure (title / project terms / standard terms) intact.
- [ ] **Library takes explicit args**: grep-level check (can be a test) that no `glossary_lib`
  module imports `project_log` or reads `current_project.json` — context resolution stays in
  the script wrappers.
- [ ] **Entry points still run**: smoke-invoke each legacy wrapper's `main()`/`__main__` path
  against a fixture project dir (`glossary_compare_revised_translation.py --pid`,
  `llm_glossary_cleanup.py` up to but not including the LLM call — factor the pre-LLM loading
  so it's testable without network).

## Phase 0b — project-scoped lemma overlay (PRD §6b)

Proves: lemma writes survive deploys, checks see project paradigms, shared baseline is never
written at runtime.

- [ ] **Merge semantics** (`agent/test_glossary_lib_lemma.py`): `load_lemma_tables(proj_dir)`
  with (a) baseline only, (b) overlay only, (c) both with a key conflict → overlay wins,
  (d) missing overlay files → baseline result, no error.
- [ ] **Sync writes overlay only**: run `sync_verb_lemma_tables` (mocked LLM response) against a
  tmp project dir; assert the overlay JSONs gained the forms and the baseline files'
  mtime/content are untouched.
- [ ] **`anzuzeigen`-class regression**: overlay contains `anzuzeigen → anzeigen`, baseline does
  not; `check_segment_glossary` on the real HALA seg-22 text pair with `display,anzeigen` in
  the glossary must produce **no** missing-verb note. Then the inverse (no overlay entry) must
  produce the note — proving the overlay is what fixes it.
- [ ] **Every checker path loads through the merge**: CAT UI check endpoint, standalone checker
  script, review agent's `_build_lint_checks`, and the agent's `gather_evidence` all resolve an
  overlay-only paradigm (one integration-style test per caller is enough).
- [ ] **Retargeted existing suite**: `test_verb_lemma_sync.py` updated to overlay paths, still
  green; `TestLiveRoundTrip` still passes on-demand.

## Phase 1 — graph parity skeleton (PRD §3 deterministic nodes + `resolve_inconsistent`)

Proves: the graph reproduces today's output before any new behavior is added, and Luna 5 holds
up on the batch-resolve prompt.

- [ ] **Node unit tests** (`tests/test_glossary_agent.py`):
  - `load_inputs` against a fixture project dir: all tables loaded; **missing xlsx →
    `stop_reason="error"` routed to END** (the contamination hard-fail — assert no standard
    glossary was appended anywhere).
  - `classify_terms` parity: same consistent/inconsistent split and ordinal merges as
    `llm_glossary_cleanup` produces on the same fixture (import both paths, compare).
  - `resolve_range` fallback chain, one test per level: (1) Lara column present → marked-id
    range; (2) no Lara column, run seg_range given → that range; (3) neither, ≤50 segments →
    whole document; (4) degenerate (neither, >50) → routes to `confirm_scope`. Plus:
    section-boundary row (`ABSTRACT` header) inside the range is recorded in state, not dropped.
  - `write_glossary` golden-file byte comparison (same golden as Phase 0) + backup file created
    when output already exists.
- [ ] **`confirm_scope` resume routing**: interrupt fires with the documented payload; resume
  with `{"range": [a,b]}` continues to `gather_evidence`; graph never re-enters the interrupt
  (assert the node appears at most once in the execution path).
- [ ] **Failure routing** (the fabricated-success regression test): stub `resolve_inconsistent`
  to return unparseable output → run ends with `stop_reason="error"`, `report` contains the raw
  response, and **no** `clean_glossary_*.csv` was written. Repeat for timeout and
  tool-call-limit stop reasons.
- [ ] **Status vocabulary**: `get_status` on a fresh thread → `not_started`; mid-run (paused at
  `confirm_scope`) → `awaiting_input` with payload; after completion → `completed` with
  `output_path`; after stubbed failure → the failure stop_reason. Interrupts checked before
  `state.next` (the review agent's in_progress/awaiting_input distinction — copy its test).
- [ ] **Luna 5 model-swap regression** (`@llm_live`): run `resolve_inconsistent` on one archived
  project's real input JSON with Luna 5 and assert the three documented failure modes are
  absent: (1) no consistent term dropped (every input consistent term present in output, before
  the fill-in safety net — count `filled` separately and assert it's small), (2) compound terms
  intact (no compound split into pieces), (3) standard-glossary preference honored
  (`validate_result` returns no standard-conflict errors).
- [ ] **Live parity diff** (`@llm_live`, protocol not pytest): same fresh project through flag-off
  (old path) and flag-on (agent Phase-1 graph); row-by-row diff of the two CSVs. Expected
  differences: title-row labels stripped (agent) — everything else should match or be an
  explainable LLM-wording difference. Record the diff in the PR.

## Phase 2 — the judgment stage (PRD §3 nodes 4–9, §7 triage)

Proves: the agent actually catches what the manual audit skill caught, cheaply, and never
fabricates success.

- [ ] **`gather_evidence` unit tests** (fixture corpus, no LLM):
  - attestation: a row attested in-range, a row attested only outside the range, a row DE-
    unattested anywhere (the `mithilfe` shape) — each classified correctly.
  - verb lemma sweep: a claims-attested lemma missing from the glossary is surfaced (the
    `perform`/`write` shape); a lemma occurring only inside a tracked compound is filtered (the
    `address`-in-`command address bus` shape).
  - live-checker completeness: a verb row whose document surface form the lemma tables can't
    resolve yields a checker note (the `anzuzeigen` shape, pre-overlay-fix fixture).
  - bidirectional index: two EN entries sharing one DE lemma detected (the `exhibit`/`provide`
    → `führt` shape), `SHARED_DE_ALLOWED` pairs exempted (`have`/`having` → `aufweisen`).
- [ ] **Triage matrix** (`tests/test_glossary_agent.py::TestTriage`): one positive and one
  negative case per flag criterion in the PRD §7 table (DE-unattested, compound-only EN,
  bidirectional collision, title-anchor mismatch, standard tension, checker note, lemma-sweep
  gap, duplicate/stem pair). Assert clean rows **never** reach `audit_flagged`'s input.
- [ ] **`check_epo_title` replay tests**: captured usable-title and garbage-title responses;
  anchors from a usable title are kept only when deterministically attested in the corpus
  (assert an LLM-claimed but unattested anchor is discarded); unusable title → no anchor, run
  continues, errata in report.
- [ ] **`audit_flagged` replay tests**: captured Luna 5 responses driven through
  parse/validate/apply without network, including: a delete verdict, an amend, an add (whole
  compound, not decomposed), a verdict that would reintroduce a DE duplicate → **rejected by
  `apply_verdicts`' hard gate**, and the three malformed-JSON shapes (trailing comma → repaired;
  truncated → retry then error; prose-wrapped → fence-stripped).
- [ ] **`apply_verdicts` guard**: zero verdicts returned while flagged rows outstanding →
  error state, not a clean pass.
- [ ] **`whole_doc_pass` conditional**: post-editing state → node never executes (assert on the
  execution path); proofreading state → executes; bucket-1/bucket-4 findings appear in the
  report and **never** in the CSV; bucket-3 DE sourcing uses the claims rendering when the
  concept is claims-attested even against a whole-document majority (claims-priority test).
- [ ] **Report content**: grouped by kind of fix; contains report-only findings (title errata,
  bucket 4, standard-glossary tension) — assert presence by marker strings on a stubbed run.
- [ ] **Historical-project regression suite** (`@llm_live`, `tests/test_glossary_regression.py`)
  — the decisive proof, one test per project against its archived folder; assertions are
  row-level outcomes, never byte-identity, plus "no row lost relative to the human-approved
  final glossary":

  | Project | Must hold |
  |---|---|
  | **RTC_2608_P1331** | `testing device→Testvorrichtung`, `test→testen` — EPO-title anchor overrides the 7/8 `Prüf*` raw-MT majority |
  | **FRKE_2608_P0736** | `provide→bereitstellen` (standard hard requirement); `exhibit` gets a distinct third verb (`zeigen`-class), never shares with `provide` or `have`; `have`/`having→aufweisen` shared and NOT "resolved" to `besitzen`; bonus: `place→einbringen` over majority `geben`; **masking-compound entries present**, confirmed via the `glossary-range-audit_practice` pre/post diff: `any one of the preceding claims,einem der vorhergehenden Ansprüche` and `for use,zur Verwendung`, added as their own compound rows rather than overwriting the bare `any`/`one of`/`use` defaults |
  | **MICTCH_2608_P0124** (proofreading-shape → also exercises `whole_doc_pass`) | `using,mithilfe` deleted; `enable,in die Lage versetzen` deleted + `chip enable pin,Chipaktivierungspin` added; `data transaction→Datentransaktion` (minority) kept; `write,schreiben` + `perform,durchführen` kept (claims-attested verbs); whole-doc: `memory sub-system,Speichersubsystem` added (bucket 3), `utilize,nutzen` added; SCA-protocol description defect + `memory sub-system controller` violations in report only; **`cause,veranlassen` kept as the sole entry**, NOT split into a separate `cause,veranlass` row — `verb_canonical_glossary.csv`'s `19/24 yes` vs. `5/24 no` split is verb conjugation of one lemma, not a real inconsistency (SKILL.md Step 3's own cited example, confirmed against this project's actual canonical table); **the `including`/`include` claims-priority rule must NOT fire on the description's ~100+ `beinhalten` instances** — `including`/`include` occur only in the abstract (segment 430), never inside the actual claims (369–428), so E23's `verify_trigger_in_claims` must return false for that segment and the rule must not apply (this is the exact three-strikes regression case from SKILL.md Step 7) |
  | **HALA_2608_P0655** | ordinal merges present (`image data,Bilddaten` / `output…` / `intermediate…` — upstream `_merge_ordinal_siblings` not regressed); Eingang/Eingabe ↔ Ausgang/Ausgabe drift surfaced in report; `anzuzeigen` lemma gap caught at draft time (overlay gains the form); title row label-free in output |
  | **FRKE_2604_P0334** (new, added 2026-08-25 — title-rejection case) | `appendage,Gliedmaße` — the client's own official correction (`Appendix A - SourceError_German_...xlsx`, "Corrected"); **NOT** `appendage,Anhang` (the raw MT's own rendering, and what the EPO title itself says, and what the archived `clean_glossary_FRKE_2604_P0334.csv` still has uncorrected on disk today); **NOT** `appendage,Ansatz` either (the raw-MT majority, 2/4 in `noun_canonical_glossary.csv` — also wrong, so this case also proves majority-vote alone doesn't save you). `check_epo_title` must judge the title unusable as an anchor for this term (Step 1b part 2 — "Anhang" is a domain-blind false-friend for "appendage," same failure class as the SKILL.md-cited "Anhang"/"Gliedmaße" pattern, because this project *is* that pattern's real source) and the title must appear as errata in the report. Real stakes, not hypothetical: this exact failure produced a documented client RCA (`RCA_FRKE_2604_P0334_de-DE_Sprogløsninger ApS.docx`) — a Major Accuracy nonconformity on Claim 1, root-caused to the translator privately knowing the correct term but suppressing the fix specifically to stay consistent with the (wrong) title. Small, cheap fixture: 46 rows, claims-only. |

- **Known untested rule, flagged not silently skipped (2026-08-25):** the standard-vs-consistency
  tiebreak (SKILL.md Step 3) / bidirectional-consistency-has-a-legitimate-exception-outside-claims
  principle has no regression coverage. Investigated directly: the candidate MICTCH_2608_P0124
  case (`cause`→`veranlassen` vs. a `führt zu` rendering, segments 56/60) doesn't hold up on
  inspection — segment 56 doesn't contain "cause" at all, and segment 60's `führen` is a
  whole-clause nominalization restructuring ("causing X to be enabled... can result in Y" →
  "...führen"), not a clean lexical `cause`→`führt zu` choice, so it isn't solid enough to assert
  against. The broader, still-real principle (English sometimes has more near-synonyms — e.g.
  `execute`/`perform`/`carry out`, or `include`/`involve`/`incorporate`/`encompass` — than German
  has natural distinct equivalents, so some DE overlap outside claims is acceptable rather than a
  defect) has no confirmed real project attached yet. See
  [[feedback_patent_glossary_bidirectional_consistency_exception]]. **Do not add a test for this
  until a real project surfaces it** — a test built on the MICTCH case specifically would assert
  the wrong thing.
- [ ] **Cost guardrails**: with `MAX_RUN_LLM_CALLS=1` a normal fixture run stops with
  `budget_exceeded` (not a crash, not a fabricated result); per-node timeout and tool-call
  limits produce their named stop_reasons (stubbed clients, no real waiting).
- [ ] **`session_id` wiring**: assert every stubbed client call received
  `extra_body={"session_id": project_id}`.

## Phase 2b — corrected-design closeout (`corrected_PRD_GLOSSARY_AGENT.md`)

Proves: the agent's judgment quality actually matches the manual skill on the points the
Phase 0-2 build was found to have flattened or missed (2026-08-24 HALA Swagger test), and that
the new self-learning mechanism is real, not just plumbing that never gets exercised.

- [x] **C15 — classify-and-drop for widespread unattested rows** — landed:
  `tests/test_glossary_agent_phase2.py::TestClassifyUnattested` (7 tests, pure-function evidence
  level: standard drop, project drop, benchmark-scoped-not-whole-corpus, C14 stays disjoint and
  untouched, lemma_sweep_gap entries never classified, case-insensitive lookup) +
  `::TestTriageNodeC15` (3 tests, graph-level wiring: standard drop → real delete verdict +
  `c15_standard_drop` origin, project drop → `c15_project_drop`, attested row stays clean) +
  `TestReportAndBackfill::test_c15_drops_get_their_own_sections_not_audit_verdicts`. Outer
  `70ef321`.
- [x] **Self-learning loop** (`tests/test_glossary_agent_learning.py`, 23 tests) — landed:
  - `TestConfidenceField`: `_raw_to_verdicts` carries `confidence` through, defaults to "high"
    when missing or invalid (never lets a malformed field silently force a pause).
  - `TestRouteToClarificationOrApply`: low-confidence-and-not-done → clarify; already-done → apply
    even with low-confidence verdicts present; no low-confidence → apply; failure state → end.
  - `TestHandleGlossaryFeedback` (8 tests): no-resolutions → straight to `apply_verdicts`; confirm
    → confidence forced high + "USER CONFIRMED" annotation; override → de/action replaced +
    "USER OVERRIDE: <note>"; rule drafted → routes to `confirm_glossary_rule` with `flagged`
    narrowed to exclude just-resolved rows; no rule → straight to apply; malformed JSON / LLM
    exception → degrades to "no rule" WITHOUT losing the already-applied resolutions (the
    fabricated-success-adjacent case: a rule-proposal failure must never roll back real human
    fixes); an unanswered row in the same batch is untouched byte-for-byte.
  - `TestConfirmGlossaryRuleDecisionLogic`: only a literal `"confirm"` (case-insensitive) counts;
    everything else — reject, missing, `None` — is a no-op reject (the interrupt() call itself is
    only exercised through the real graph, below).
  - `TestAppendToLearningDoc`: writes the entry (trigger/rule/source/project id all present);
    loops back to `audit_flagged` with `learnings_text` refreshed when `flagged` still has rows;
    routes straight to `apply_verdicts` when empty; a second entry appends, doesn't overwrite.
  - `TestLearningsInAuditPrompt`: `learnings_text` reaches `_audit_batch`'s payload under
    `glossary_agent_learnings`; `load_inputs` actually reads `_glossary_agent_learnings.md` (skip
    if the RTC fixture isn't present).
  - **`TestSelfLearningRoundTrip`** (the decisive proof, mocked — not `@llm_live`, see below): a
    full graph run through BOTH new interrupts with mocked LLM responses — one low-confidence
    verdict → `await_clarification` fires → resume with a confirm → `handle_glossary_feedback`
    drafts a rule → `confirm_glossary_rule` fires → resume with `{"decision": "confirm"}` →
    `_glossary_agent_learnings.md` has the entry on disk, `flagged` was empty after the resolve so
    the loop-back correctly skips straight to `apply_verdicts`, and the written
    `clean_glossary_*.csv` contains the row. A second test proves the reject path writes nothing.
  - **Deferred, explicitly not built this session:** the quick-edit-path logging
    (`sourcing_path: "quick-edit"`) has no UI/API surface yet to attach to (Phase 3, not Phase 2b)
    — see the decision log. The real `@llm_live` round-trip (real Luna 5, not mocked responses)
    also isn't built yet — the mocked round-trip above proves the *wiring*; a live one is still
    needed to prove the *prompts* (both `_AUDIT_SYSTEM_PROMPT`'s new confidence rule and
    `_FEEDBACK_SYSTEM_PROMPT`) actually produce sensible real-model behavior before trusting this
    on a real project.
- [ ] **`verify_against_checker` (post-merge)** (`tests/test_glossary_agent.py::TestPostMergeVerify`):
  - Full-range re-check, not touched-rows-only: a delete that changes an *untouched* row's
    matching (the "shorter entry starts absorbing text the deleted longer compound used to own"
    shape) is caught.
  - Failure routing case (a): a note on a row `audit_flagged` just added → routes back with
    failure evidence, capped at 1 retry.
  - Failure routing case (b): a note on an untouched row caused by another row's change →
    same routing, evidence includes what changed nearby.
  - Failure routing case (c): retry still fails → row reverted to pre-merge state,
    `"Could not auto-resolve"` report section contains it, row does **not** carry a checker note
    into `write_glossary`.
  - Hard gate: `write_glossary` never runs while any `final_rows` row has an unresolved note
    (assert on the execution path, mirrors the 2.6 `apply_verdicts` hard-gate test shape).
- [ ] **Rule 8 split regression** (`tests/test_glossary_agent_phase2.py::TestAuditSystemPromptRule8`,
  same file/pattern as `TestAuditSystemPromptRule7`): all four sub-rule markers present in
  `_AUDIT_SYSTEM_PROMPT`; each worked example (`data transaction`, `corresponding value` /
  `memory sub-system`, `have,besitzen` vs `having,aufweisen`) named; no bare "rule 8" dense
  sentence remains.
- [ ] **B6 fold-in**: `gather_evidence`'s checker notes carry a `note_type` field distinguishing
  `missing_lemma_key` from `wrong_stored_value`; a missing-key note routes to `sync_lemmas`
  (overlay write), not to a CSV DE-value edit via `audit_flagged`.
- [ ] **`verify_trigger_in_claims`** (`agent/test_glossary_lib.py` or equivalent):
  segment-in-claims-range → true; segment in an adjacent abstract/header just outside the
  resolved claims boundary → false (the `including`/abstract regression case, named explicitly);
  result reaches `whole_doc_pass`'s bucket-3/4 prompt as a precomputed boolean, never re-derived
  by the LLM.
- [ ] **Structured synthesis log** (F27): golden JSON/CSV sidecar comparison — one row each for
  add/amend/delete/keep, with `bucket`, `sourcing_path` (incl. `"user-clarification"`,
  `"learned-rule:<id>"`, `"quick-edit"`), and `segments` populated; prose report content is
  generated from this structured data (assert equivalence, not two independently-written texts).

- [x] **No-op-amend guard** (`tests/test_glossary_agent_phase2.py::TestNoOpAmendGuard`, 4 tests) —
  live-caught 2026-08-25 (FRKE_2604_P0334, real Luna 5 run): an `"amend"` verdict whose `de` is
  unchanged from the original value is invalid by construction. `_audit_batch` gets one bounded
  retry (naming the specific row, clarifying that a 0-attestation `check_entry` result on the
  model's OWN proposed correction is expected, not a reason to revert) before forcing
  `action: "delete"`, `de: ""`, `confidence: "low"` on persistent failure — reuses the
  self-learning loop rather than a new mechanism. Also: `report_node` now shows
  `(confidence: high|medium|low)` on **every** verdict line, not just "low" ones — corrected from
  a first pass that only flagged "low" as noise-avoidance, per direct user feedback: with a model
  (unlike a human colleague) confidence has no other channel, so it should never be threshold-gated
  out of the output. `TestReportAndBackfill` covers both the always-shown behavior and C15/
  report-only rows carrying it too.
- [x] **`GET /state` (raw checkpoint inspection)** — added 2026-08-25, user-requested: `/status`
  shows an empty payload the entire time a run is `"in_progress"`, no way to actually watch it
  work. `graph.get_full_state(project_id)` returns the complete, unfiltered checkpoint
  (`values`/`next`/`interrupts`) regardless of stop_reason.
  `tests/test_glossary_agent.py::TestGetFullState` (not-started; completed exposing a field
  `/status` never surfaces, e.g. `draft_rows`; paused exposing the raw interrupt payload) +
  `tests/test_glossary_agent_api.py::TestStatePassthrough`. Same gap exists on `/review-agent` —
  not fixed, flagged for later.
- [x] **`await_agreement` HITL gate — the report is not the end state** — architecture correction,
  2026-08-25, user-specified (rejected an earlier out-of-graph proposal): `report` routes to a new
  `await_agreement` interrupt instead of straight to `write_glossary`. Resume `{"decision":
  "agree"}` to finalize, or `{"decision": "feedback", "en", "de", "feedback"}` to comment on a row
  — routed to `handle_agreement_feedback` (one LLM call: propose a corrected `de` or confirm the
  existing one, plus the same one-off-vs-generalizable rule judgment), reusing
  `confirm_glossary_rule`/`append_to_learning_doc`/`apply_verdicts` unchanged, looping back through
  `report` to `await_agreement` again — repeatable indefinitely, the only interrupt here designed
  to fire more than once. `handle_agreement_feedback` always clears `flagged` on exit, since
  `append_to_learning_doc`'s existing "loop back to `audit_flagged` if rows remain" check would
  otherwise misfire against the *original* run's leftover flagged list (nothing else clears it).
  Tests: `TestAwaitAgreementDecisionLogic`; `TestHandleAgreementFeedback` (6 — real correction,
  model reconsiders and confirms existing value, rule-drafted routing, malformed output / LLM
  exception both degrade to a `"keep"` verdict without crashing, `BudgetExceeded` stops the run
  honestly, `flagged` always cleared); `TestAgreementLoopRoundTrip` (two feedback rounds — one
  plain, one that also confirms a rule — then agree; asserts the final CSV has the *latest*
  correction and the rule is on disk). Five pre-existing graph-flow tests updated to resume with
  `{"decision": "agree"}` before asserting `"completed"` (the old, now-wrong direct-completion
  contract, not a regression). Not yet done: an `@llm_live` version of the round-trip.
- [x] **C15 lemma-attestation fix** — live-caught 2026-08-26 reviewing a real thread's raw state
  (`GET /state`) from the FRKE_2604_P0334-2 run: C15 wrongly deleted six genuinely claims-attested
  verbs (`comprise`, `configure`, `connect`, `associate`, `have`, `include`) whose bare-infinitive
  stored key never literally matches their real inflected/irregular occurrences (`comprising`,
  `configured`, `connected`, `associated`, `has`/`having`, `includes`/`including`) — confirmed
  against the real source text directly. Violated the audit's own rule 7 ("claims-attested verbs
  kept by default") since the rows were deleted before the audit ever saw them; plausibly caused a
  second, connected defect the same run (a fabricated `including → "unter Einschluss von"` amend —
  confirmed unattested anywhere in the target text). New `evidence.lemma_attested(en, de, segments,
  benchmark_range, lemma_tables)` reuses the exact `_count_lemmas` counter the production checker
  already uses; `classify_unattested` checks it before deleting a literally-unattested row —
  genuinely lemma-attested rows route to normal audit judgment instead. Deliberately scoped to C15
  only (optional args, `None` skips the check, backward-compatible) — C14 and the rest of `triage`
  still use the plain literal check, since only C15 *deletes* outright and needs the stronger bar.
  Tests: `TestLemmaAttested` (5), `TestClassifyUnattested` +3, `TestTriageNodeC15` +1 (real shipped
  lemma tables, the exact `include`/`including` shape from the live incident).
- [x] **`evidence.lemma_attested` surfaced to the audit LLM itself, not just C15's gate** —
  live-caught 2026-08-26, same day as the C15 fix, re-running the same project: fixing C15 alone
  let `comprise`/`configure`/`connect`/`associate` reach `audit_flagged`, but the audit then
  deleted them anyway with "unattested" reasoning — confirmed all four genuinely attested via
  inflection, the *exact same* evidence gap, just one level up (the audit's own `flagged_rows`
  payload only ever carried the literal `attestation.en_benchmark`/`de_benchmark` counts).
  `triage_node` now annotates every surviving flagged row with `evidence.lemma_attested` (same
  `ev.lemma_attested` call, new call site); `_AUDIT_SYSTEM_PROMPT` rule 7 amended to name the
  literal counts as literal-only and defer to `lemma_attested: true` when set. Also confirmed
  live, real wins from the original C15 fix: the earlier `including → "unter Einschluss von"`
  fabrication is gone (resolves correctly to `einschließlich` now), and the learned
  `appendage → Glied` rule was applied automatically in this separate run — first live proof the
  self-learning loop actually works cross-run, not just that it's wired. Tests: `TestTriageNodeC15`
  +2, `TestLearningsInAuditPrompt` +1 (`_audit_batch` actually forwards the field into the real
  JSON payload). Full outer (241 + 4 llm_live skips) + submodule (405) suites green.
- [x] **Clean rows merged into the audit's scope — the triage split was never in the manual
  skill** — architecture correction, 2026-08-26, user-specified (rejected a bespoke
  compound-consistency check I proposed first): `flags: []` no longer means "never reaches
  `audit_flagged`," only "nothing mechanically detected." Real numbers from the same thread: 57
  draft rows, 38 originally flagged, 19 that would previously have skipped the LLM entirely.
  Reasoning: any single hand-written deterministic check only covers the one pattern it was
  written for; only the LLM, seeing the full picture, can catch what nobody's thought to hardcode
  yet — matching how the manual skill always worked (one holistic read, no cost-driven skip).
  **Batching problem this immediately raises, fixed in the same change**: merging clean into
  flagged without more would silently reintroduce the same blind spot for any two related rows
  landing in *different* `MAX_AUDIT_BATCH_TERMS` batches. New `full_glossary_context` in
  `_audit_batch`'s payload — every current `draft_rows` entry (en/de only), sent in *every* batch
  alongside `flagged_rows`; the model may emit a verdict for a context row too, but only on a
  real, evidence-based inconsistency, never as a second batch to re-litigate. `_AUDIT_SYSTEM_PROMPT`
  intro + rule 8 updated to explain the two-tier payload and name the shared-component pattern
  explicitly (the `guard`/`guard actuator` case). No-op-amend guard's `original_de` baseline moved
  from batch-only to full `draft_rows`, so a context-sourced amend gets the same "did this
  actually change" check a same-batch amend already had. Tests: `full_glossary_context` payload
  test; a no-op-amend test for a context-sourced (not-in-batch) amend; three pre-existing tests
  updated for the new contract (clean rows now appear in `flagged` with `flags: []`, two
  `NoOpAmendGuard` fixtures needed `draft_rows` to include the row under test). Full outer
  (243 + 4 llm_live skips) + submodule (405) suites green.

## Phase 3 — workflow integration (PRD §5)

Proves: the step machinery, flag, and UI behave — mostly `tests/test_glossary_integration.py`
(FastAPI TestClient, review-integration style) plus a manual UI script.

- [ ] **Flag off** → `GLOSSARY_ANALYZED` runs the legacy five-command list including
  `llm_glossary_cleanup.py`; no graph thread is created.
- [ ] **Flag on** → command list excludes `llm_glossary_cleanup.py`; graph scheduled after the
  extraction subprocesses succeed; extraction failure → step `FAILED`, graph never scheduled.
- [ ] **Step stays `IN_PROGRESS`** while the graph runs/pauses; `/finish` flips it to `DONE`
  with metadata (verdict-action counts, report path); step type REPEATABLE — a second full run
  increments `run_count` and backs up the previous CSV.
- [ ] **`/finish` retry-on-conflict**: simulate the TOCTOU 409 (status stubbed "completed" to
  the client, graph mid-final-superstep server-side) → frontend retries ≤5×@1.5s, succeeds;
  exhausted retries → honest failure surfaced, step NOT stuck silently.
- [ ] **Route guards**: double `/start` → 409; `/resume` when not awaiting input → 409;
  `/cancel` while actively in_progress → 409; `/cancel` on a paused run → `not_started`
  afterward, fresh `/start` works.
- [ ] **Watchdog generalization**: a glossary task pending >threshold triggers the WARNING/dump
  path (reuse `test_app.py`'s review-watchdog test shape).
- [ ] **Log streaming**: graph `logger` lines with the `{project_id}:` prefix appear in the
  step's SSE log buffer.
- [ ] **"Awaiting input" badge**: project-list payload flags a project whose glossary run (or
  review run) is `awaiting_input`; clears after resume.
- [ ] **Swagger docs review** (manual, checklist item — the PRD's documentation standard):
  every field description readable without code knowledge; every stop_reason documents its
  next action; call sequence in the sub-app description. Reviewer: someone who hasn't read
  `graph.py` (in practice: the user, via `/glossary-agent/docs`).
- [ ] **Manual UI test script** (run once live before enabling the flag by default):
  1. Start a real project's step with flag on; watch logs stream.
  2. Reload the page mid-run → status re-fetched live (no stale cached flag).
  3. Force the `confirm_scope` degenerate case via Swagger (`/start` with explicit
     `project_folder`, no seg_range, >50-seg fixture) → badge appears, panel shows the
     question, resume continues.
  4. Let a run complete → step `DONE`, CSV + report in the project folder, backup present.
  5. `/cancel` a paused run → step re-runnable.

## Companion — `mehr*` linter check (PRD §6c, phase-independent)

- [ ] `agent/test_linter.py::TestMehrMore`: target with 2× `mehr*`, segment source with 1×
  "more", "more" present elsewhere in the claims text → flag `"2 times 'mehr*' in target but
  1 times in source"`; equal counts → no flag; `mehr*` present but "more" nowhere in claims
  text → no flag; document-order statefulness handled like `german_claim_no_article` (and, like
  it, excluded from any out-of-order re-run context — add the exclusion to the review agent's
  `_build_lint_checks` if it lands in `CHECKS`).
- [ ] Confirm `standard_glossary.csv` carries no `multiple` row (regression guard against
  re-adding it instead of relying on this check).

---

## Suite-wide exit criteria (before flag-on-by-default, PRD Phase 4)

- [ ] Full submodule + outer suite green (existing 309 + all new).
- [ ] All four historical regression projects pass on Luna 5 defaults.
- [ ] One fresh live project run end-to-end through the UI with zero manual intervention
  besides normal step triggering.
- [ ] Parity fallback verified one last time: flag off still produces a valid glossary
  (the escape hatch actually works on current code, not just in Phase 1's memory).
