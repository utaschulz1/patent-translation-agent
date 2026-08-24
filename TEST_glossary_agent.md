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
  | **FRKE_2608_P0736** | `provide→bereitstellen` (standard hard requirement); `exhibit` gets a distinct third verb (`zeigen`-class), never shares with `provide` or `have`; `have`/`having→aufweisen` shared and NOT "resolved" to `besitzen`; bonus: `place→einbringen` over majority `geben` |
  | **MICTCH_2608_P0124** (proofreading-shape → also exercises `whole_doc_pass`) | `using,mithilfe` deleted; `enable,in die Lage versetzen` deleted + `chip enable pin,Chipaktivierungspin` added; `data transaction→Datentransaktion` (minority) kept; `write,schreiben` + `perform,durchführen` kept (claims-attested verbs); whole-doc: `memory sub-system,Speichersubsystem` added (bucket 3), `utilize,nutzen` added; SCA-protocol description defect + `memory sub-system controller` violations in report only |
  | **HALA_2608_P0655** | ordinal merges present (`image data,Bilddaten` / `output…` / `intermediate…` — upstream `_merge_ordinal_siblings` not regressed); Eingang/Eingabe ↔ Ausgang/Ausgabe drift surfaced in report; `anzuzeigen` lemma gap caught at draft time (overlay gains the form); title row label-free in output |

- [ ] **Cost guardrails**: with `MAX_RUN_LLM_CALLS=1` a normal fixture run stops with
  `budget_exceeded` (not a crash, not a fabricated result); per-node timeout and tool-call
  limits produce their named stop_reasons (stubbed clients, no real waiting).
- [ ] **`session_id` wiring**: assert every stubbed client call received
  `extra_body={"session_id": project_id}`.

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
