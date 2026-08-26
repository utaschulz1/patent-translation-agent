# Glossary agent — learned rules

Append-only. Each entry was confirmed by a human via the confirm_glossary_rule
interrupt — never written automatically. Loaded into audit_flagged's prompt
at the same priority tier as standard_glossary.csv/_styleguide.md.

## General checker-mechanics rules (manually curated, not per-term/not agent-appended)

These aren't `confirm_glossary_rule` entries — they're not about one EN term's
translation choice, they're about how any noun-shaped CSV row should be
stored so `glossary_lib/matching.py`'s exact-string cross-entry checks don't
misfire. Kept here rather than in the per-term log below, and documented in
full in the glossary-range-audit skill's Step 4.

- **Store noun entries in singular form** (EN key and DE value, both as a
  bare entry and as a component word inside a multi-word phrase). Doesn't
  apply to verb entries — those already normalize to the infinitive via the
  separate EN/DE verb-lemma lookup tables. Found 2026-08-26 on
  SNSW_2608_P0018: `signal,Signal` over-counted every segment containing
  `discrete signal interface,Schnittstelle für diskrete Signale` because the
  phrase-masking check needs an exact word match and `signal` ≠ `signale`;
  separately, `processor,Prozessor` and `processors,Prozessoren` as two
  bare entries both counted the same "Prozessoren" occurrences because the
  sibling-length-exclusion threshold doesn't trigger for a 2-char plural
  suffix. **Exception:** nouns with a stem-internal vowel change in the
  plural (`Vorgang`→`Vorgänge`, `Anspruch`→`Ansprüche`) — suffix-stripping
  can't bridge a vowel change either direction, so use whichever form is
  actually attested and verify siblings match it, rather than trusting the
  singular convention alone. Also exempt mass/collective nouns with no
  natural singular (`Daten`, `Vielzahl`).

## 2026-08-26 — FRKE_2604_P0334-2
- **Trigger:** The English term “appendage” refers to an anatomical body part rather than a mechanical attachment, projection, or connection point.
- **Rule:** Translate anatomical “appendage” as “Glied” (or the anatomically specific body-part term when context provides one), not as “Ansatz”.
- **Source term:** appendage
- **Status:** confirmed
