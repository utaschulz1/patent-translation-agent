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

## Calibration lessons (from real user corrections — HALA_2608_P0659, SNSW_2608_P0018)

The user has twice hand-corrected Claude's Part Two/Three and asked Claude to learn from the differences. This is an ongoing, living calibration — more rounds will be added over time. Priority order, most important first:

- **Documented rule violations first.** A missing article, a misplaced reference number, an inconsistent component name — these are concrete, checkable, and what reviewers actually spend their time on. Lead with these before reaching for a subtler semantic/pragmatic argument.
- **What reviewers are actually obsessed with** (use this to gauge what's worth a slot):
  - **Word forms not matching the source's grammatical construction** — e.g. source uses an infinitive purpose-clause, translation uses a nominalization instead.
  - **Added, omitted, or wrong articles.**
  - **Numbers wrong or in the wrong place** — reference numerals must sit directly after the noun/part they refer to.
  - **A claimed component/part translated inconsistently across the document** — the split that matters: if the inconsistent rendering makes the part **unrecognizable**, that's a **Mistranslation, Major/Critical**; if it's still recognizable as the same part (just an inconsistent term), that's a **Terminology inconsistency, Minor**.
- **Omissions are Accuracy, not Fluency** — a dropped indefinite article, a missing word, anything that's technically an omission files under Accuracy per the category rubric's own definition ("omission" is explicitly listed there), even when it *reads* like a plain grammar slip.
- **Word-form drift from the source's grammatical construction is an Accuracy question, not just style** — e.g. an English infinitive purpose-clause ("a mount **to couple** X to Y") rendered as a German nominalization ("eine Fassung **zur Befestigung**...") is "too far off the word form in the source" even when both are grammatical and mean the same thing. Don't wave this off as a preferential/consistency-only change per §9 without first asking whether it's actually a fidelity problem.
- **When a diff bundles a structural rewrite with word substitutions, check the word substitutions for outright mistranslation first — the structure is rarely the real defect.** A dense rewrite that also happens to convert a "dass"-clause into the preferred nominalized-verb construction (§2.2/2.3) can be hiding an actual wrong-verb mistranslation inside it (e.g. "Durchführen" used where the source said "transmitting"/"Übertragen"). Classify what the diff is a symptom of, not its surface syntactic shape.
- **A styleguide "wrong: X / correct: Y" table entry is not automatically slot-worthy.** Even a documented rule (missing "Folgendes" before a colon-introduced list; dass-clause vs. nominalized "umfassend") can lose out to real Accuracy findings when slots are scarce — the user has dropped both entirely in favor of Accuracy-caliber issues. Weigh documented style rules against what's actually consequential for this delivery; don't let them crowd out Accuracy findings.
- **Reference-numeral placement is a real, slot-worthy Compliance issue** — a numeral displaced away from the noun it refers to (e.g. "...anzuzeigen (115)" instead of "...(115) anzuzeigen") deserves its own slot, not just a mention in General Comments.
- **Bundle the long tail aggressively.** Small recurring grammar/word-choice issues (contracted prepositions, gender agreement, passive-voice agent prepositions, glossary word-choice, article-on-nominalization) should go into a single catch-all slot under one pragmatic category, even when they're technically different phenomena — this frees the remaining slots for Accuracy/Major-caliber findings. Don't split these across 2-3 slots just to keep categories taxonomically clean.
- **Don't dwell on a subtle scope/timing/pragmatic nuance call that has no documented rule behind it.** ("sobald" vs. "während" for "as X is modified" — is that really a scope change, or just a nuance? Genuinely hard to say, and not worth spending time on either way.) These calls are inherently hard to weigh, right or wrong, and time is better spent on the documented-rule-violation categories above. If one surfaces, it's fine to mention it with appropriately low confidence rather than slotting it as a confident Major finding — see the Certainty rule.

### Worked example (SNSW_2608_P0018, 2026-08-26) — Claude's draft vs. the user's correction

| # | Claude's draft (wrong) | User's correction (right) | Why |
|---|---|---|---|
| 1 | Claim 8, "sobald"→"während": **Major/Accuracy**, argued as a scope/timing change | **Dropped entirely** — does not appear anywhere in the corrected version | A genuinely close call ("as"="während", "as soon as"="sobald" — Claude's grammar was right) but whether it's actually a scope change is legitimately unclear, and this kind of nuance call isn't where reviewer time goes. Not a mistake to have noticed it — just not worth a confident Major slot or much time either way. Documented-rule violations (below) are the better use of the 5 slots |
| 2 | Claims 11/13/14, dass-clause vs. required nominalized "umfassend" construction: **Major/Compliance** | Segment 34 specifically, "Durchführen" used for "transmitting" instead of "Übertragen": **Major/Accuracy** — "Mistranslation" | Claude classified the sentence's *restructuring* (which happens to match a styleguide-preferred pattern); the user ignored the structure entirely and found the actual wrong-verb error buried inside the same diff |
| 3 | Claims 1/11, missing "Folgendes" before colon: **Minor/Compliance** | **Dropped entirely** | A documented styleguide rule, but not consequential enough to out-compete Accuracy findings for a scarce slot |
| 4 | Claims 12/14, missing dative articles in Markush "eines von X": **Minor/Fluency** | Same segments: **Minor/Accuracy** — "5 indefinite articles omitted" | Omission is an Accuracy subtype per the category rubric, not a Fluency/grammar-completeness issue |
| 5 | Claims 9/12, "das Empfangen"→"Empfangen": **Minor/Compliance** (one of two separate slots for recurring items) | One single slot bundling six unrelated recurring items (im→in dem, gender, von/durch, an/auf, darstellen/anzeigen, Empfang/Empfangen): **Minor/Terminology** | The long tail of small issues gets bundled into one slot regardless of how taxonomically different each item is, to keep slots free for higher-value findings |
| — | Claim 7's "zur Befestigung" vs. "um...zu befestigen" word-form drift: found, but dismissed as preferential/consistency-only, not slotted | Given its own slot: **Minor/Accuracy** — "too far off the word form in the source" | See the word-form-drift lesson above |
| — | Claim 7 reference-numeral placement fix: found, but left unslotted (mentioned only in General Comments) | Given its own slot: **Minor/Compliance** | A real, distinct defect class (numeral displaced from its noun) — don't downgrade it to a footnote just because it seems small |

Net pattern: **3 of Claude's 5 original slots were dropped entirely**, replaced by two items Claude had found but declined to slot. Zero Compliance-only findings survived. Lesson: lead with documented-rule violations (missing articles, misplaced reference numbers, inconsistent component names, word-form drift from source) — they're what fill a scorecard's slots in practice. A semantic/scope nuance call with no rule behind it is fine to mention, but don't spend much effort on it or expect it to hold a slot against rule-clear findings.

### Worked example (HALA_2608_P0659, 2026-08-25) — Claude's draft vs. the user's correction

Reconstructed from the user's corrections at the time (exact original wording not preserved, but the categorization mismatch is):

| # | Claude's draft (wrong) | User's correction (right) | Why |
|---|---|---|---|
| 1 | Not slotted / under-weighted | Claim 6, "at least one of the first portion and the second portion" mistranslated with an unsourced explanatory dash-clause and "oder" instead of "und": **Major/Accuracy** | The client's hyper-literal Markush rule ("at least one of X and Y" → "von dem A und dem B") wasn't applied |
| 2 | Claim 9, "Datensignal-Signalleitungen" (wrong/redundant compound) inconsistent with the term used elsewhere: **Minor/Terminology** | Same finding: **Major/Terminology** | Wrong/inconsistent naming for a claim-defining component hurts claim definiteness even when a human reader can infer intent — don't under-rate just because it's inferable from context |
| 3 | A recurring "an"→"auf" preposition swap: **Terminology/register** | Same finding, reframed: **Accuracy** — the real defect is modifier-attachment ambiguity (which noun "faces away from the substrate" attaches to) | Classify what the diff is a symptom of (an ambiguity that changes what's being claimed), not the surface word choice |
| 4 | "zweiten Drain"→"zweite Drain": **Fluency** (adjective-ending slip) | Bundled into a "Inconsistencies" slot: **Minor/Terminology**, flagged internally as a fuzzy-TM-match mixup confusing the Drain/Source referents | A grammar-looking fix can be flagging a real mistranslation — check what got mixed up, not just what changed form |
| 5 | One isolated grammar fix given its own slot | Six distinct recurring inconsistencies bundled into one "Inconsistencies" slot | Bundling beats cherry-picking a single instance when slots are scarce |

### What good looks like — verbatim text from the user's finished cards

The comparisons above are Claude's own paraphrase. The actual phrasing the user writes is terser and more clipped than Claude's default style — match this register, not a fuller explanatory prose style, when filling Part Two/Three.

SNSW_2608_P0018, Part Two (5 slots, verbatim):

```
1. Segement 7: to couple => zur Befestigung instead of "um zu befestigen"
   That is too far off the word form in the source.
   Error: Minor | Categorization: Accuracy

2. Seg. 10: Darstellungsvorrichtung anzuzeigen (115);
   Reference number is not directly after the part.
   Error: Minor | Categorization: Compliance

3. Seg. 12/14: 5 indefinite articles omitted in the translation
   Error: Minor | Categorization: Accuracy

4. Recurrently:
   - "im" instead of "in dem"
   -  wrong gender
   - by => von/durch
   - an/auf der Darstellungsvorrichtung
   - present => darstellen/anzeigen
   - receiving => Empfang (wrong)/Empfangen (correct)
   - added definite article for "receiving" where no addition would also work in German and no prior mention of this exact step can be found
   Error: Minor | Categorization: Terminology

5. segment 34: Mistranslation
   and/or periodically transmitting the one or more signals => und/oder das regelmäßige Durchführen der Signale
   Error: Major | Categorization: Accuracy
```

SNSW_2608_P0018, Part Three (verbatim):

```
Pass/Fail: Fail
General Comments: Over all a good translation.
   But because it is short, only the minors would probably have accumulated into a fail,
   and then there is still the major from segment 34.
```

HALA_2608_P0659, Part Two (5 slots, verbatim):

```
1. Claim 6: "...electrically connected to at least one of the first portion (141) and the second
   portion (142)" — mistranslated as "mindestens einem der beiden Abschnitte – dem ersten
   Abschnitt (141) oder dem zweiten Abschnitt (142) –"
   Wrong: added "beiden, Abschnitt" and "oder" instead of "und", plus an unsourced explanatory
   dash-clause; missed the Markush-like 'at least one of X and Y' construction.
   Error: Major | Categorization: Accuracy

2. Claim 7 (id 77): "the first sub-layer ... are in the same layer as the source" —
   'Teilschicht' (sub-layer) mistranslated as the non-existent/wrong word 'Teilsicht' (partial
   view), repeated 4x for all five sub-layer instances in the same segment, and also as "Schicht".
   Error: Major | Categorization: Terminology

3. Claim 9 (id 88): "the first data signal input lines ... are in the same layer as the gate" —
   'Datensignal-Signalleitungen' (wrong/redundant compound) corrected to the term used
   consistently elsewhere in the claim, 'Datensignaleingangsleitungen'.
   Error: Major | Categorization: Terminology

4. Inconsistencies:
   - Zeitintervalle/Zeitabschnitte
   - Signalanschlussgruppe/Signalzugangsanschlussgruppe
   - die Drain/der Drain
   - jeweils/beziehungsweise (introduced ambiguitiy where there was none in the source)
   - in dem Randbereich/in dem Randbereich der Region
   - "zweiten" modifying "Drain" instead of "Source" => Mistranslation (mixed up fuzzy match)
   Error: Minor | Categorization: Terminology

5. Recurring throughout the claims:
   "at a side, away from the substrate (01; 10), of the active layer" or similar
   Wrong: "auf einer von dem Substrat der aktiven Schicht abgewandten Seite"
   meaning: the side of the active layer that faces away from substrate,
   not the substrate is possesive of the acitve layer, but the side is
   Correct: auf einer von dem Substrat abgewandten Seite der aktiven Schicht
   Error: Minor | Categorization: Accuracy
```

HALA_2608_P0659, Part Three (verbatim):

```
Pass/Fail: Fail
General Comments: Because there where major errors and many smaler ones, this would have
   accululated into a Fail.
```

Note the register in both: short, telegraphic, `source phrase => wrong translation` or `Wrong: X / Correct: Y` shorthand, no hedging, General Comments is 1-2 sentences that just states the volume/severity logic behind Pass/Fail — not a recap of every slot.
