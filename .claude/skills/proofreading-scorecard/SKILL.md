# Proofreading Scorecard Skill

Fill the client's DQF-MQM `Translator Scorecard 5.14.26.xlsx` for a Proofreading/Copy Edit job: diff the translator's and proofreader's xlsx exports, judge which changes are real errors (vs. preferential), and write up Part Two (Errors) and Part Three (Overall Summary).

## Key files

| File | Purpose |
|---|---|
| `build_scorecard.py` | Mechanical stage — run this first, always |
| `Translator Scorecard 5.14.26.xlsx` (in this skill folder) | Blank client template, colocated with the skill so it survives Railway redeploys (the `agent/` submodule is re-downloaded fresh from GitHub on every deploy — see `project_patent_railway.md`). The script copies this into the project folder as `Translator Scorecard 5.14.26_<project number>.xlsx` if the project doesn't already have a scorecard. |
| `tracked_changes.csv` | Written by the script next to the scorecard — **read this with the Read tool**, never print full rows into chat (truncated printing caused ~31 wrong classifications in the older `scorecard-analysis` skill) |
| Project's `Translator Scorecard 5.14.26*.xlsx` | The file you write Part Two/Three into (already has Tracked Changes sheet + Task Details filled by the script) |

## Step 1 — Run the mechanical stage

```
python build_scorecard.py <project_dir> [--job-id <XTRF job id>]
```

`<project_dir>` is the project's folder under `agent/projects/` (the one holding `Translated_*.xlsx`/`Proofread_*.xlsx` pairs, or `Final_*.xlsx`). Pass `--job-id` when you know the XTRF job id (check `project_log.json` for the project, or ask the user) — it auto-fills project number, weighted word count, content specialty, and budgeted time. Without it, those four cells (E5/E8/E9/E12) are left for you to fill by asking the user.

**If the script warns the scorecard file is locked** (open in LibreOffice/Word), tell the user and wait for them to close it before saving anything real — don't silently overwrite over an open file.

This step fills, without judgment: `Tracked Changes` worksheet (rich-text tracked changes — deleted text struck through red, inserted text underlined blue), and Task Details `E5/E7/E9/E10/E11/E12/E13`, `F35`. It does **not** touch Part Two (Errors) or Part Three (Overall Summary) — that's your job below.

## Step 2 — Read the diffs

Read `tracked_changes.csv` (next to the scorecard file) with the Read tool. Columns: `doc, id, source, translated_target, corrected_target_plain`. The last column uses `[-deleted-]{+inserted+}` markup — e.g. `[-Fig.-]{+FIG.+} 1A` means "Fig." was changed to "FIG.".

**Do not re-read the rich-text column from the xlsx itself** — openpyxl doesn't round-trip rich text back into structured runs (it collapses to a plain concatenated string on read, even though the file displays correctly in Excel/LibreOffice). The CSV is the reliable source for reasoning.

## Step 3 — Classify each diff

For each row, reason about what actually changed (the diff is ground truth, more so than any pattern-matching):

1. **Is it a real error, or a preferential/stylistic improvement with no error?** Per the Criteria sheet: *"Preferential changes: Do NOT log any preferential changes on the scorecard."* Skip these — don't count them toward the 5 slots or the Pass/Fail math.
2. **Category** — one of exactly 6 (from the `Criteria` sheet in the scorecard):
   - `Accuracy` — mistranslation, wrong meaning, omission, addition, untranslated text, ambiguous translation
   - `Fluency` — grammar, punctuation, spelling, inconsistency
   - `Terminology` — wrong/inconsistent term vs. company or client glossary
   - `Country Standards` — dates, units, currency, delimiters, addresses, phone/zip formats
   - `Compliance` — non-adherence to legal/patent/regulatory or client-specific guidelines
   - `Style` — literal translation, tone, unidiomatic phrasing, inconsistent register
   - If you've run the `scorecard-analysis` skill before, you can reuse its finer taxonomy (`linter_categories.json` in the patent-translation-agent folder) as a stepping stone, then collapse to one of the 6 above — e.g. `manual:word_order`/`manual:article`/`manual:punctuation` → Fluency; `glossary:*`/`manual:terminology` → Terminology; `manual:accuracy` → Accuracy.
3. **Severity** — one of `Critical` / `Major` / `Minor`, per the Criteria sheet definitions (loaded from the `Criteria` sheet — health/safety/legal/crash-causing = Critical; meaning-changing or in a visible/important spot = Major; noticeable but no loss of meaning = Minor).

## Step 4 — Fill Part Two (Errors) — 5 slots only

The template has exactly 5 error slots (confirmed with the user — do not extend it). Pick the top 5 by severity (Critical first, then Major; only include Minor if slots remain and nothing more severe exists), ordered per the template's own instruction: **Title → Claims → Abstract → Specifications** (if Title/Abstract/Specifications are missing, focus on Claims).

Cell mapping — block *n* (n=1..5) starts at row `17 + 3*(n-1)`:
| Field | Cell | Value |
|---|---|---|
| Affected phrase | `F<base>` | Source snippet, **with the location prefixed** (e.g. `"Claim 5: ..."`) — there's no separate location column, so it must go here |
| Error severity | `F<base+1>` | `Critical` / `Major` / `Minor` |
| Categorization | `F<base+2>` | one of the 6 categories above |

Write these with a short inline Python/openpyxl snippet (the file is binary, not Edit-tool-editable) — load the scorecard workbook, set the cells, save in place. Preserve everything else in the file (don't rebuild the workbook).

## Step 5 — Fill Part Three (Overall Summary)

- **Pass/Fail (`F33`)**: apply the Instructions sheet's guideline — using `E8` (reviewed weighted word count, already filled):
  - >1 Major error or >3 Minor accuracy errors per 1000 WWC → Fail
  - For >1000 WWC: >1 Major error per 1000 WWC → generally Fail
  - For 20k+ WWC: >1 Major error per 2000 WWC → generally Fail
  - 1+ Critical error → almost always Fail
  - If `E8` wasn't filled (no `--job-id` given and XTRF lookup unavailable), ask the user for the weighted word count before computing this — don't guess.
- **General Comments (`F34`)**: a short paragraph on overall quality — mention the total change count and document(s), any recurring pattern among the errors, and anything that didn't fit into the 5 slots.
- `F35` is already set to `"FL"` by the script.

## Certainty rule

Same as `scorecard-analysis`: if a diff's classification is genuinely ambiguous (vague, could be either category, or you can't tell if it's preferential vs. an actual error), say so to the user rather than guessing — a wrong Critical/Major call has real consequences for the translator's record.
