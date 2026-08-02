## Objective

You are reviewing an already-consolidated EN->DE patent glossary for three
specific quality patterns a human reviewer catches by eye when checking the
glossary against `glossary_compare_revised_translation.py`. Apply ONLY the
rules below. Do not re-litigate translations that don't match one of these
patterns, and do not invent new entries.

## Input

{INPUT_JSON}

`current_glossary` — the full list of resolved (en, de) pairs to review.

`verb_frequency_data` — EN verbs that had more than one DE form observed
across the source document, each DE form's occurrence count and the total.
Use this to judge which verb genuinely deserves which German form.

`noun_frequency_data` — the same, for noun phrases.

## Rules

### 1. Collapse ordinal-duplicate entries

If two (or more) entries differ only by a leading ordinal ("first X" /
"second X" / "third X" ...) and there is no independent reason the
ordinal-specific translation must differ, merge them into a single bare
entry: "X" -> the shared DE form, ordinal removed from both sides.

Patent claims routinely write "the first and second X" — one shared noun
phrase covering both ordinals. An ordinal-baked-in glossary entry cannot
match that contiguous-phrase construction and produces a false "missing"
flag downstream; a bare entry matches it correctly regardless of phrasing.

Do not merge if the ordinal genuinely changes the correct DE translation —
only merge when it is the same underlying term written twice.

### 2. Split out generic modifiers fused into a noun-phrase entry

Some entries are [modifier] + [noun] fused into a single glossary phrase
(e.g. "corresponding value"). If the modifier is ordinary, non-technical
vocabulary that could reasonably precede many different nouns, replace
that entry with a bare-noun entry instead: EN = the noun alone, DE = the
noun's translation alone (drop the modifier's translation from the DE
side too). Do not create a separate entry for the modifier itself —
ordinary vocabulary doesn't need its own glossary-tracked translation.

You MUST still output a row for the bare noun — "corresponding value" ->
"entsprechender Wert" becomes "value" -> "Wert", never nothing. Removing
the modifier is not the same as removing the entry: the underlying noun
concept must always survive this rule, whether or not a bare-noun entry
for it already exists elsewhere in the list (merge into that existing
entry if one does; otherwise this becomes its own new bare-noun row).

Only keep a modifier fused to its noun when it is itself a specific,
potentially inconsistency-prone technical or domain term (e.g. a named
chemical element, a specific measurement type). If such a modifier recurs
across several different nouns in the glossary, consider giving it its own
separate entry so its translation is tracked independently.

### 3. Rebalance impractical verb-form assignments

Using `verb_frequency_data`: if a low-occurrence EN verb ended up with a
clean, standard German form while a much higher-occurrence EN verb (a
genuinely different underlying meaning) was assigned an awkward or unusual
form of the same general kind — e.g. an unusual separable-prefix
construction where a standard inseparable form would read more naturally —
and swapping which verb gets which form would be a real improvement in
German patent style overall, reassign them.

Only act when you are confident the swap is a genuine improvement. Leave a
verb's assigned form alone by default.

## Constraints

- No two output rows may share the same EN value.
- No two output rows may share the same DE value, except where both EN
  terms are genuinely valid alternate forms of one concept (e.g.
  "have"/"having" both legitimately mapping to "aufweisen").
- Every distinct underlying concept in `current_glossary` must still be
  represented in your output. Merging (rule 1) or de-fusing a modifier
  (rule 2) is not "dropping" a concept — but don't remove an entry outright
  without applying one of the rules above to justify it.

## Output

Return ONLY a JSON array, no markdown fences, no prose:

[
  {"en": "...", "de": "..."}
]
