# Proofreading Scorecard Skill

Fill the client's DQF-MQM `Translator Scorecard 5.14.26.xlsx` for a Proofreading/Copy Edit job: diff the translator's and proofreader's xlsx exports, judge which changes are real errors (vs. preferential), and write up Part Two (Errors) and Part Three (Overall Summary).

## Key files

| File | Purpose |
|---|---|
| `build_scorecard.py` | Mechanical stage — run this first, always |
| `finalize_scorecard.py` | Reasoning-stage write — run this to fill Part Two/Three, **never** write those cells with an ad-hoc openpyxl snippet (see Step 4 for why) |
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

For each row, reason about what actually changed (the diff is ground truth, more so than any pattern-matching).

**The proofreader's corrected text is authoritative.** This scorecard grades the translator against the proofreader's judgment call, not the other way around — do not second-guess whether the proofreader's phrasing was itself the best possible German, and do not mark something "not really an error" because you'd have translated it differently yourself. Your only judgment call per row is the one below.

1. **Is it a real error, or a preferential/stylistic improvement with no error?** Per the Criteria sheet: *"Preferential changes: Do NOT log any preferential changes on the scorecard."* This is about whether the *translator's original* was objectively wrong (an error) vs. merely different-but-also-acceptable from the proofreader's choice (preferential) — it is not a re-review of the proofreader's work. Skip preferential ones — don't count them toward the 5 slots or the Pass/Fail math.
2. **Category** — one of exactly 6 (from the `Criteria` sheet in the scorecard):
   - `Accuracy` — mistranslation, wrong meaning, omission, addition, untranslated text, ambiguous translation
   - `Fluency` — grammar, punctuation, spelling, inconsistency
   - `Terminology` — wrong/inconsistent term vs. company or client glossary
   - `Country Standards` — dates, units, currency, delimiters, addresses, phone/zip formats
   - `Compliance` — non-adherence to legal/patent/regulatory or client-specific guidelines
   - `Style` — literal translation, tone, unidiomatic phrasing, inconsistent register
   - If you've run the `scorecard-analysis` skill before, you can reuse its finer taxonomy (`linter_categories.json` in the patent-translation-agent folder) as a stepping stone, then collapse to one of the 6 above — e.g. `manual:word_order`/`manual:article`/`manual:punctuation` → Fluency; `glossary:*`/`manual:terminology` → Terminology; `manual:accuracy` → Accuracy.
3. **Severity** — one of `Critical` / `Major` / `Minor`, per the Criteria sheet definitions (loaded from the `Criteria` sheet — health/safety/legal/crash-causing = Critical; meaning-changing or in a visible/important spot = Major; noticeable but no loss of meaning = Minor).

## Step 4 — Decide Part Two (Errors) — 5 slots only

The template has exactly 5 error slots (confirmed with the user — do not extend it). Pick the top 5 by severity (Critical first, then Major; only include Minor if slots remain and nothing more severe exists), ordered per the template's own instruction: **Title → Claims → Abstract → Specifications** (if Title/Abstract/Specifications are missing, focus on Claims).

**Frequency is not severity.** A change pattern that recurs many times across the document (the same preposition or spelling fix applied 20 times) is still exactly as severe as one instance of it — it does not out-rank a rarer but more consequential issue (one that changes claim scope, technical meaning, or legal compliance) just because it has a higher count. When ranking same-severity candidates for the remaining slots, prioritize by real-world consequence of the error, not by how often it occurs. If a recurring pattern does belong in a slot, log it once and note the frequency in the phrase text — don't let the count itself be the reason it beat something else.

Each error needs: **Affected phrase** (source snippet, **with the location prefixed**, e.g. `"Claim 5: ..."` — there's no separate location column), **Error severity** (`Critical`/`Major`/`Minor`), **Categorization** (one of the 6 above).

## Step 5 — Decide Part Three (Overall Summary)

- **Pass/Fail**: apply the Instructions sheet's guideline — using `E8` (reviewed weighted word count, already filled):
  - >1 Major error or >3 Minor accuracy errors per 1000 WWC → Fail
  - For >1000 WWC: >1 Major error per 1000 WWC → generally Fail
  - For 20k+ WWC: >1 Major error per 2000 WWC → generally Fail
  - 1+ Critical error → almost always Fail
  - If `E8` wasn't filled (no `--job-id` given and XTRF lookup unavailable), ask the user for the weighted word count before computing this — don't guess.
- **General Comments**: a short paragraph on overall quality — mention the total change count and document(s), any recurring pattern among the errors, and anything that didn't fit into the 5 slots.

## Step 6 — Write Part Two/Three with finalize_scorecard.py

**Never fill these cells with an ad-hoc openpyxl `load_workbook()` → set cells → `save()` snippet.** openpyxl reliably *writes* the Tracked Changes sheet's rich text (strikethrough/underline runs) but does not reconstruct it when *reading* a saved file back — a plain load-then-resave silently collapses that sheet to flat plain-text strings, even though nothing about it was touched. This happened on a real run (2026-08-25): the Tracked Changes sheet displayed correctly in Excel right after `build_scorecard.py`, then lost all strikethrough/underline formatting after an inline snippet filled Part Two/Three.

Instead, write a small JSON file and pass it to `finalize_scorecard.py`, which re-derives the diff from the source xlsx pair and rewrites Tracked Changes fresh in the same save call that writes Part Two/Three — never relying on rich text surviving a round-trip:

```json
{
  "errors": [
    {"phrase": "Claim 5: ...", "severity": "Major", "category": "Accuracy"}
  ],
  "pass_fail": "Pass",
  "comments": "..."
}
```

```
python finalize_scorecard.py <project_dir> <path_to_json>
```

`F35` is already set to `"FL"` by `build_scorecard.py` and needs no further action.

## Certainty rule

Same as `scorecard-analysis`: if a diff's classification is genuinely ambiguous (vague, could be either category, or you can't tell if it's preferential vs. an actual error), say so to the user rather than guessing — a wrong Critical/Major call has real consequences for the translator's record.

## Calibration example — a real correction (HALA_2608_P0659, 2026-08-25)

Severity/category judgment here resists being reduced to clean rules — the user reworked a first attempt at Part Two/Three by hand and called out several misses. These aren't rules to apply mechanically, but patterns to weigh next time:

- **Terminology errors on claim-defining component names lean Major, not Minor.** Claude rated a wrong/inconsistent compound noun for a claimed component ("Datensignal-Signalleitungen" instead of the term used everywhere else, "Datensignaleingangsleitungen") as Minor because a reader could infer intent from context. The user corrected it to Major: wrong naming for a claimed component affects claim definiteness even when it's locally inferable.
- **Classify what the diff is a symptom of, not just the visible delta.** Claude filed a recurring "an"→"auf" preposition swap as Terminology/register preference. The user's read: the real defect is modifier-attachment ambiguity — "von dem Substrat der aktiven Schicht abgewandten Seite" reads as if the *active layer* faces away from the substrate, when it's *the side* (of the active layer) that does. That's Accuracy, not word choice — and it was mis-set as Terminology throughout. Before categorizing a recurring pattern, ask what's grammatically/logically wrong, not just which two words swapped.
- **A grammar-looking fix can flag a real mistranslation underneath.** "zweiten Drain" → "zweite Drain" looks like an adjective-ending slip (Fluency). The user identified it as a fuzzy-TM-match mixup that confused the Drain/Source referents in that claim — a real Accuracy risk, not cosmetic agreement. When a correction touches a component-reference word (Drain/Source/Gate/etc.), check whether the *referent* changed, not just the ending.
- **"At least one of X and Y" (Markush and Markush-like constructions) renders hyper-literally as "von dem A und dem B"** — even where a more natural alternative ("A oder B") would be legally/semantically fine and even EPO-acceptable. This client's reviewers apply a hyper-literal check; any addition or paraphrase that isn't strictly literal fails it regardless of whether it changes meaning. Related: [[feedback_patent_glossary_verb_and_category_rules]].
- **When slots are scarce and there are several small, real, recurring issues, bundle them into one itemized slot rather than cherry-picking a single isolated instance.** Claude used a slot on one isolated grammar fix ("jeder eine"→"jede"). The user's replacement bundled six distinct recurring inconsistencies into one "Inconsistencies" list (Zeitintervalle/Zeitabschnitte, Signalanschlussgruppe/Signalzugangsanschlussgruppe, die/der Drain, jeweils/beziehungsweise, Randbereich/Randbereich der Region, the zweiten-Drain-vs-Source mixup) — more informative than one arbitrary single-instance pick.
- **Pass/Fail is a qualitative call, not just the WWC-per-1000 arithmetic.** The Instructions sheet's numeric thresholds are explicitly guidelines — "the overall severity of the errors, their location, and the additional effort required during the CE step will also be considered." On this job the strict per-1000-WWC math stayed under the Fail line even after reclassifying one error to Major, but the user's verdict was Fail: "Because there where major errors and many smaller ones, this would have accumulated into a Fail." Don't default to Pass just because the arithmetic clears — weigh accumulated volume and CE effort the way a human copy editor would, and lean Fail when in doubt rather than Pass.
