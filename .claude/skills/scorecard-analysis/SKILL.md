# Scorecard Analysis Skill

Analyse reviewer corrections from EN→DE patent translation scorecards, add them to the consolidated CSV, and classify each correction using the linter taxonomy.

## Key Files

| File | Purpose |
|---|---|
| `scorecard_consolidated.csv` | All corrections to date — append new rows here |
| `linter_categories.json` | **The taxonomy** — load this before classifying any row |
| `consolidate_scorecards.py` | Extracts rows from xlsx files and runs the linter; use `--reprocess` to redo all |
| `scorecard_log.json` | Tracks which xlsx files have been processed |
| Scorecards folder | `C:\Users\utasc\OneDrive\ArbeitNEU\Comunica DK\scorecards\` |

## Workflow

### Step 1 — Add the new scorecard
Copy the xlsx file into the scorecards folder, then run:
```
python consolidate_scorecards.py
```
This appends the new rows (sheet 2 "QA comments") to `scorecard_consolidated.csv` with `linter_fires` already populated. It skips files already in `scorecard_log.json`.

### Step 2 — Identify new rows
The new rows will have `comment_classification` empty. Find them:
```python
rows = [r for r in csv_rows if not r['comment_classification'].strip()]
```

### Step 3 — Classify each new row

**Read the CSV directly — do not print rows into the chat.** Use the Read tool on `scorecard_consolidated.csv` to access the full cell content. Reasoning about truncated chat output caused classification errors in the past (rows left empty because the diff was beyond the print cutoff). The data is in the file; use the file.

For each row, read:
- `en_source` — the English source text
- `de_translation` — the DE translation (contains the error)
- `de_correction` — the reviewer's corrected version
- `error_category` — reviewer's category (Accuracy, Consistency, Language, etc.)
- `feedback_reviewer` — reviewer's comment
- `linter_fires` — which existing checks already fire on this row

Then reason: **what is the actual difference between `de_translation` and `de_correction`?** The feedback helps but the diff is the ground truth. Classify into one or more tags from the taxonomy below.

### Step 4 — Write classifications back
Update `comment_classification` column in the CSV. Use semicolons to separate multiple tags.

### Step 5 — Suggest new checks
If a pattern appears that fits no existing tag, propose `linter_new:descriptive_name` and add it to `linter_categories.json` with `scorecard_occurrences`, `description`, `pattern`, `example_error`, `example_correction`, `implementation_note`.

### Step 6 — Report findings
After all rows are classified, produce a short summary:

1. **Counts by category** — how many rows per top-level category (linter:, linter_new:, glossary:, manual:) and per tag.
2. **New `linter_new:` tags** — list any tags proposed in this batch that did not exist before, with their occurrence count and a one-line description of what check would implement them.
3. **Linter false positives observed** — any rows where `linter_fires` fired on something unrelated to the actual correction.
4. **Recommended next actions** — e.g. "implement linter_new:X (N occurrences)", "add term Y to glossary", "update exception list for check Z".

Keep the report concise — a table for counts and a bullet list for actions is enough.

---

## Classification Taxonomy

Load `linter_categories.json` for the full list with descriptions, patterns, and occurrence counts. Summary:

### Existing linter checks (use `linter:name`)
These are already implemented in `linter.py`. Use this tag when the linter **would** or **does** correctly fire on the error — even if `linter_fires` shows it didn't (gap in coverage).

| Tag | What it catches | Function in linter.py |
|---|---|---|
| `linter:preposition_contraction` | beim/im/vom/zum/zur → bei dem/in dem etc. | `preposition_contraction` |
| `linter:betraegt_stative` | beträgt/betragen where ist/sind is correct | `betraegt_stative` |
| `linter:werden_dynamic` | wird/wurde for a static state (should be ist) | `werden_dynamic` |
| `linter:welche_relativpronomen` | welche* as relative pronoun (use der/die/das) | `welche_relativpronomen` |
| `linter:in_response_to_mistranslated` | "in Reaktion" instead of "als Reaktion auf" | `in_response_to_mistranslated` |
| `linter:same_selbe` | dieselbe*/derselbe* when EN has "same" (→ gleiche) | `same_selbe` |
| `linter:same_gleich_missing` | EN has "same" but no "gleich*" in DE | `same_gleich_missing` |
| `linter:comprise_umfassen` | umfass* / compris* count mismatch | `comprise_umfassen` |
| `linter:vielzahl_plurality` | Vielzahl without matching plurality in EN | `vielzahl_plurality` |
| `linter:plurality_not_transferred` | plurality in EN without Vielzahl in DE | `plurality_not_transferred` |
| `linter:german_claim_no_article` | article at start of German claim preamble | `german_claim_no_article` |
| `linter:negation_not_transferred` | not/no/none in EN, nicht/kein missing in DE | `negation_not_transferred` |
| `linter:hyphen_in_number_range` | hyphen instead of en dash in number ranges | `hyphen_in_number_range` |
| `linter:regular_space_before_unit` | regular space before unit (needs NBSP) | `regular_space_before_unit` |
| `linter:beide_ambiguous` | beide* ambiguous (zwei vs either vs both) | `beide_ambiguous` |
| `linter:target_punctuation_where_none_in_source` | punctuation added in DE not in EN | `target_punctuation_where_none_in_source` |
| `linter:acronym_in_compound` | (AKR-) or (AKR) - wrong bracket/hyphen placement | `acronym_in_compound` |
| `linter:hyphen_in_long_compound` | hyphen between two 10+ char words (compound should be merged) | `hyphen_in_long_compound` |
| `linter:folgendes_umfasst` | "umfasst:" before a list without "Folgendes" | `folgendes_umfasst` |
| `linter:folgendes_konfiguriert` | "konfiguriert ist:" before a list without "zu Folgendem" | `folgendes_konfiguriert` |
| `linter:abbreviation_not_in_source` | d. h./z. B./bzw. when EN spells it out | `abbreviation_not_in_source` |
| `linter:jeweilig_not_respective` | jeweilig* when EN has no "respective" | `jeweilig_not_respective` |
| `linter:german_quotation_marks` | straight "..." instead of German „..." | `german_quotation_marks` |
| `linter:patent_number_decimal` | decimal comma in patent Nr. when source has point | `patent_number_decimal` |
| `linter:schritt_zum` | "Schritt zum [Infinitiv]" → "Schritt eines [Genitiv-Infinitiv]" | `schritt_zum` |
| `linter:durch_verwendung` | "durch Verwendung" or "durch [X-ung]" when EN has "by [verb]ing" | `durch_verwendung` |

### Proposed new checks (use `linter_new:name`)
Patterns not yet implemented. Use this tag to track occurrence frequency.

| Tag | What it would catch | Occurrences |
|---|---|---|
| `linter_new:article_first_mention` | Definite article on first mention (das Bestimmen → Bestimmen) | 18 |
| `linter_new:nominalization` | Broader result-noun → nominalized-verb not covered by schritt_zum/durch_verwendung | 13 |
| `linter_new:genitive_separation` | Genitive object split from its verb (decided not to implement — recognisable to human reviewers) | 9 |

### Glossary issues (use `glossary:name`)
Require a project glossary or the standard glossary — not pure linting.

| Tag | Term pair |
|---|---|
| `glossary:apparatus_device` | apparatus→Einrichtung, device→Vorrichtung (when both appear) |
| `glossary:comprise` | comprising→umfassend preferred over relative clause |
| `glossary:include` | include→aufweisen/beinhalten (NOT umfassen) |
| `glossary:is_are_value` | is/are for values → ist/sind (not beträgt, liegt, steht) |
| `glossary:configured_to` | configured to → konfiguriert, um |
| `glossary:have_having` | have/having → aufweisen/aufweisend |
| `glossary:said` | said → definite article der/die/das |
| `glossary:form` | form (verb) → bilden/ausbilden |
| `glossary:other` | Any other specific glossary mismatch |

### Manual issues (use `manual:name`)
Cannot be automated — require human judgment.

| Tag | What it covers |
|---|---|
| `manual:accuracy` | Omissions, additions, wrong meaning — requires reading comprehension |
| `manual:consistency` | Term used inconsistently across patent — requires patent-wide context |
| `manual:word_order` | Verb/clause position in subordinate clauses |
| `manual:article` | Wrong article (gender/definiteness) not covered by linter_new:article_first_mention |
| `manual:terminology` | Domain-specific term requiring research |
| `manual:punctuation` | Comma, colon placement per German grammar |
| `manual:other` | Typos, spacing, capitalisation, preferential style |

---

## Certainty rules

- **High certainty** → classify and write immediately.
- **Low certainty** (diff not visible in truncated text, vague feedback, purely preferential) → **leave `comment_classification` empty**. Never guess.
- A row can have **multiple tags** — use all that apply, semicolon-separated.
- If `linter_fires` shows a check firing but the reviewer corrected something **different** → note the linter as a false positive candidate; still classify the actual correction separately.

## Updating linter_categories.json

When a new `linter_new:` tag is proposed:
1. Add it to the `proposed_new_linter_checks` object with all fields.
2. Increment `scorecard_occurrences` when the same pattern appears in subsequent batches.
3. When a proposed check is implemented in `linter.py` and `test_linter.py`, move it to `existing_linter_checks` and set `"status": "implemented"`.
