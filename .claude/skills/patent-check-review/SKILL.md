# Patent Check Review Skill

Review a project's `*_revised_translation_checks.xlsx` (linter + glossary flags) against the house styleguide and manual judgment: classify every automated flag as a true or false positive, and surface issues no automated check catches (grammar, cross-claim consistency, spelling).

## Key Files

| File | Purpose |
|---|---|
| `agent/_styleguide.md` | **The authoritative house style rulebook — read this in full before reviewing a single segment.** |
| `<name>_revised_translation_checks.xlsx` | Per-segment table: ID, Source (EN), Target (DE), Linter flags, Glossary Checks flags. In the project's `pre-processing/` folder. |
| `clean_glossary_<PROJECT>.csv` | Approved EN→DE term list for this project. Same folder. |
| `agent/linter.py` | Linter check implementations — read the relevant function if a flag's exact trigger condition is unclear from the styleguide/tables below. |
| `agent/glossary_compare_revised_translation.py` | Glossary check implementation — same reason. |
| `dump_checks.py` (this skill folder) | Extracts the checks xlsx into a clean JSON list — use instead of writing ad hoc openpyxl code each time. |
| `build_annotated.py` (this skill folder) | Builds the final `*_checks_ANNOTATED.xlsx` from the original checks xlsx + a verdicts JSON — bakes in the formatting rules (wrap text, widths, **no color fills**) so they can't drift or get hand-reintroduced by accident. |

Output goes in the same `pre-processing/` folder as `<name>_checks_ANNOTATED.xlsx`.

## Workflow

### Step 1 — Read the styleguide first, always
Read `agent/_styleguide.md` in full before touching any segment. Skipping this step produces confidently wrong verdicts — the two rules that most often get misjudged from general patent-translation knowledge alone are §5.1 (contraction exception for nominalized verbs) and §4.1 "any" (preamble exception). Both look like plain style violations/inconsistencies until you check the styleguide's actual carve-outs.

### Step 2 — Load the check file and glossary
The xlsx can't be read with a text tool. Run:
```
python dump_checks.py <name>_revised_translation_checks.xlsx
```
This writes `<name>_..._checks.dump.json` next to it — a plain list of `{id, source, target, linter, glossary}`, title/header/subheader rows already stripped. Read that JSON with the Read tool (don't have the check script print rows into the chat — truncation causes exactly the kind of misclassification the scorecard-analysis skill already learned to avoid).

Read the glossary CSV directly. Note the checks file normally contains **every** segment, not just flagged ones — unflagged rows still need a manual pass (Step 4).

### Step 3 — Ground uncertain flags in the actual check code (optional but recommended)
If a flag's exact trigger condition isn't obvious from the styleguide or the reference tables below, read the relevant function in `agent/linter.py` or `agent/glossary_compare_revised_translation.py`. Prior session notes about these checks can be stale — the source is ground truth.

### Step 4 — Classify every flag
For each row with a Linter and/or Glossary flag, decide **TRUE POSITIVE** / **FALSE POSITIVE** / **MIXED** (a cell has ≥2 flags with different verdicts — write out each one) / **PARTIAL** (some sub-parts of one flag's message are right, some wrong). Ground every verdict in the styleguide section or reasoning, not just intuition. See the reference tables below for patterns that recur across projects.

**Cross-claim mirroring** is the single most useful consistency check available: EP patents commonly restate the same limitation as both a device/system claim and a corresponding method claim (e.g. claim 1 vs. claim 11). If the same EN phrase is translated two different ways across the mirrored pair, that's a strong true-positive signal regardless of what the automated check says — and conversely, agreement across the pair is good evidence a flagged choice is actually fine.

### Step 5 — Manual pass over unflagged rows
No automated check catches: German case/gender/number agreement, spelling, consistency of a translation choice for the same EN construction across the whole document (not just within one flag type), or whether a source error was correctly mirrored vs. incorrectly "fixed" (styleguide §1). Read every row's DE text, not just the flagged ones.

### Step 6 — Verify systematic-pattern claims computationally
Before writing "this happens N times" or "only row X differs," check it with a short script (grep the relevant substring across all rows) rather than trusting a manual read-through. A miscount here undermines the whole review.

### Step 7 — Build the annotated output
Write a `verdicts.json` — a list of objects **keyed by `id`** (the stable ID column value, not the spreadsheet row number, which shifts and is easy to mis-key by hand):
```json
[
  {"id": 3, "linter_verdict": "FALSE POSITIVE — ...", "glossary_verdict": "TRUE POSITIVE — ...", "additional": "..."},
  {"id": 13, "additional": "TRUE POSITIVE (found manually) — ..."}
]
```
Any of the three fields may be omitted. Verdict/additional text should start with the capitalized marker (`TRUE POSITIVE`, `FALSE POSITIVE`, `MIXED`, `PARTIAL`, `SUMMARY`) as the first word(s) — that marker is the only signal used, deliberately: **no cell background color-coding**, Excel handles fill colors badly in dark mode.

Before writing the full file, spot-check a handful of `id`s in `verdicts.json` against the dump JSON's `source` text (grep/read a few) to catch a mis-keyed id before it propagates — this is the single most likely place to introduce a silent error.

Then build:
```
python build_annotated.py <name>_..._checks.xlsx verdicts.json <name>_checks_ANNOTATED.xlsx
```
This produces the 8-column output (`ID | Source | Target | Linter | Linter Verdict | Glossary Checks | Glossary Verdict | Additional Issues Found`) with wrap text and column widths already set, no fills. Put issues found manually (not tied to an automated flag) in `additional` — including a cross-reference note on the id(s) whose flag/absence-of-flag caused the finding (e.g. "see claim 6's preamble").

### Step 8 — Self-QA the output before handing it over
Read the generated file back and spot-check that each row's verdict text actually matches that row's source/target text (not just that a cell is non-empty) — a mis-keyed id in `verdicts.json` produces confident-looking wrong output that reads fine in isolation.

### Step 9 — Report to the user
Rank findings by importance: systematic/repeated issues first, then one-off true positives, then a brief false-positive summary (so the user knows the noise was triaged, without re-reading every line). Cite styleguide section numbers where applicable.

### Step 10 — Record new rules
If the user corrects a verdict and the underlying reason is a house-style rule not yet in `agent/_styleguide.md`, add it there (with an example) rather than treating the correction as one-off. Say explicitly where you recorded it.

---

## Reference: recurring false-positive patterns

### Linter check quirks

| Check | Fires on | Known false-positive pattern |
|---|---|---|
| `werden`/`wird` double-check (static/dynamic) | any wird/werden | Often correct in method claims when the source  reflects a dynamic capability — compare against sibling occurrences of the same construction elsewhere in the document. Not correct when static capability in subject claim like `is configured to be disposed at X` correct translation is static: `ist konfiguriert, an X angebracht zu sein`. |
| Prp + article contraction (zum/zur/im/etc.) | any contracted form | **Allowed** before a nominalized verb (Testen, Zählen, Erleichtern...) per styleguide §5.1 — very common in method claims/purpose clauses. **Not allowed** before a regular noun that is a part/a specific instance. Check what follows the contraction, not just whether one exists. |

### Glossary check quirks

| Pattern | Why it's usually a false positive |
|---|---|
| Term is a noun in this segment but the glossary entry is a verb (or vice versa) | The checker doesn't disambiguate part of speech — e.g. "switch" (physical switches, noun) matched against glossary's switch→schalten (verb). |
| "Missing" flag on a term that's actually present but declined/conjugated differently | The checker's lemma/inflection matching has gaps (e.g. nominalized genitive "Zählens" not recognized as zählen; a bare present-tense conjugation missing from `DE_verb_lemma_lookup.json`). Real translation is correct; the lemma table has a coverage gap worth reporting to the maintainer separately from the review verdict. |
| Glossary term forced into an idiom slot where it doesn't fit | E.g. by→durch is correct generally, but "increase by a factor of two" is idiomatically "um den Faktor zwei", not "durch den Faktor zwei". |
| "any" flagged missing beliebig | Check whether "any" sits in the claim's own preamble (styleguide §4.1 exception) — "of any preceding claim" / "of any of claims X to Y" omits beliebig; anywhere else in the claim body, beliebig is expected. |
| Fixed multi-word technical term (e.g. "device under test") | Free-preposition glossary entries (like under→unterhalb) shouldn't be forced into idiomatic fixed-term translations. |
| Count-only flag (EN count N, DE count M, no "missing"/"expected") | Informational, not an error — DE count can legitimately exceed EN count due to participle/attributive forms. |

These tables are a starting cheat sheet, not exhaustive — extend them as new patterns are confirmed across projects.