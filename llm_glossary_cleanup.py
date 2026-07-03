# ============================================================
# llm_glossary_cleanup.py
# ============================================================
# Resolves glossary inconsistencies using DeepSeek via OpenRouter.
#
# INPUT
#   projects/<id>/verb_segment_pairs.csv          all verb pairs with context
#   projects/<id>/noun_inconsistency_table.csv    noun conflicts with context
#   projects/<id>/verb_canonical_glossary.csv     consistent/inconsistent verb classification
#   projects/<id>/noun_canonical_glossary.csv     consistent/inconsistent noun classification
#   projects/<id>/capability_segment_pairs.csv    capability-predicate pairs (optional)
#   projects/<id>/capability_canonical_glossary.csv  (optional)
#   projects/<id>/glossary_<id>.csv               EPO title source
#   standard_glossary.csv                         locked anchors
#
# OUTPUT
#   projects/<id>/glossary_<id>.csv            clean, resolved two-column glossary
# ============================================================

import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

import project_log

HERE = Path(__file__).parent
load_dotenv(dotenv_path=HERE / ".env")

MODEL              = "deepseek/deepseek-chat-v3-0324"
# MODEL              = "deepseek/deepseek-v4-flash"

MAX_INSTANCES      = 1   # max example sentences per (en, de) pair in prompt

# EN pairs that legitimately share the same DE in German patent language.
# "have" and "having" both → "aufweisen" is standard EPO practice.
SHARED_DE_ALLOWED: set[frozenset] = {
    frozenset({"have",    "having"}),
    frozenset({"comprise", "comprising"}),
}

# Noun phrase leading words that indicate a sequential/relative variant rather
# than a distinct concept.  A phrase is only filtered when its base (remaining
# words) exists as a standalone entry, ensuring glossary coverage is never lost.
ORDINAL_MODIFIERS: frozenset[str] = frozenset({
    "first", "second", "third", "fourth", "fifth",
    "other", "additional",
})

SYSTEM_PROMPT = """\
You are a German patent translator specialising in EP patent claims and \
descriptions. You follow EPO translation conventions and German patent language \
standards. You produce formal, precise German suitable for legal patent documents.\
"""

USER_PROMPT_TEMPLATE = """\
## Objective

Produce a clean, consistent EN→DE glossary. The output must:
- Assign each German term to exactly one English source term (no DE duplicates)
- Reuse translations the translation engine already got right
- Prefer standard_glossary terms over observed translations
- Use German compound nouns as long as reasonably possible
- Correct NLP artefacts in both EN and DE strings

---

## NLP normalisation note

All terms were extracted by a spaCy pipeline. Recognise and fix these
artefacts — never copy a corrupted string into your output:

  EN artefacts:
  - Hyphens split by spaces:  "watch - item"              → "watch-item"
                               "cloud - base"              → "cloud-based"
  - Incorrect lemmatisation:  "cloud - base rmm platform" → "cloud-based RMM platform"
                               "determine running process" → "running process"

  DE artefacts:
  - Truncated words:    "Rohdat"                                   → "Rohdaten"
                        "IP-Adress"                                → "IP-Adresse"
                        "Ransomware-Überwachungskonfigurationsdat" → "…konfigurationsdaten"
                        "Watch-Item-Datei-Ereignis-Dat"            → "…-Daten"
  - Incorrect lemmatisation:
                        "ermittelt laufend Prozeß"                 → "laufender Vorgang"
                        "voreingestellt zeitbasiert Zeitplan"      → "voreingestellter zeitbasierter Zeitplan"
  - Old German spelling:  "Dateiereigniß" → "Dateiereignis"
                          "Timer-Ereigniß" → "Timer-Ereignis"
  - Spurious quotation marks: "Zustand „ Abbruch "" → "Abbruchzustand"

Always write corrected, natural forms in your output.

---

## Input

{INPUT_JSON}

---

## Input structure

**epo_title**
The official EN and DE patent title. Treat it as the authoritative source for
domain terminology. Key terms in the title set the translation family for the
whole patent.

**standard_glossary**
Preferred EN→DE reference. Give these terms priority over observed translations
where possible. If a standard entry would create a target-side duplicate in the
consolidated list, find the closest acceptable alternative.

  Two frequent cases where the observed majority should be overridden:
  - detect:  majority is often "erkennen" — but the "Detektion" family is
             preferred in technical patent context → prefer "detektieren"
  - include: majority is often "enthalten" — but standard_glossary has
             "beinhalten" → prefer "beinhalten"

**consistent_terms**
Terms the translation engine used uniformly throughout the document. Strong
evidence for the preferred translation — but not fixed: if a consistent term
must shift to resolve a conflict elsewhere in the consolidated list, it may.

**inconsistent_verbs**
Verbs where the engine used more than one DE form. Each entry lists all DE
forms seen with one representative source/target sentence per form. Decide on
exactly one DE form per EN verb.

**inconsistent_nouns**
Noun phrases where the engine used more than one DE form. Shows the canonical
(majority) DE with its count out of total, and each deviant DE with a source
and target sentence. Decide on exactly one DE form per EN phrase.
Compound nouns are sorted shortest-first so you can resolve base terms before
the compounds that contain them.

**inconsistent_capabilities**
Capability predicates ("is configured to", "is adapted for", etc.) where the
engine used more than one DE infinitive. Same format as inconsistent_verbs.
IMPORTANT: the majority DE for these is often wrong — translation engines
render capability predicates inconsistently. Always check standard_glossary
first; if no entry exists, choose the most natural German patent infinitive.

---

## Strategy

### Step 1 — Survey the full picture

Read all four input sections together. For every EN term note all DE forms
observed and whether a standard_glossary preference exists. Identify where
different EN terms are competing for the same DE — those are the conflicts
that need resolution across the whole list.

### Step 2 — Resolve inconsistent verbs

For each entry in inconsistent_verbs, choose the best DE. Priority:
  1. If the EN term has a standard_glossary entry, prefer that DE.
  2. If the EPO title translates this concept, follow the title.
  3. Read the instance sentences. Choose the DE form most appropriate for
     patent register — counts are evidence, not the final decision.
  4. Verify the chosen DE does not duplicate a DE already used elsewhere
     in the consolidated list. If it does, find the closest acceptable
     alternative.

When forced to use a non-ideal DE term, assign it to the EN term with the
fewest total instances. Imperfection costs least where the term appears rarely.

Conflict resolution examples:

  stop / kill / terminate — near-synonyms needing distinct DE terms:
    stop      → stoppen    (reversible halt, direct loanword)
    terminate → beenden    (controlled, definitive end)
    kill      → abbrechen  (forced, immediate abort — OS kill semantics)

  run / execute / perform — perform has a standard_glossary preference:
    perform   → durchführen  (standard preference)
    execute   → ausführen    (deliberate code-level invocation)
    run       → starten if "start" does not appear anywhere in the input;
                otherwise ablaufen lassen
    Always check whether "start" is already used in the consolidated list
    before assigning starten.

  link / associate / map / connect — connect has a standard_glossary
  preference for verbinden. Check whether "connect" appears in the input:
    If connect is absent from the source entirely → verbinden is free:
      associate → verbinden  (most frequent claimant gets the preferred term)
      link      → verknüpfen
      map       → zuordnen
    If connect is present → verbinden is taken:
      associate → verknüpfen
      map       → zuordnen
      link      → verlinken (or verknüpfen if associate is absent)

### Step 2b — Resolve inconsistent capability predicates

For each entry in inconsistent_capabilities:
  1. If the EN term has a standard_glossary entry, use that DE — the majority
     observed translation is unreliable for these constructions.
  2. Otherwise choose the most natural German patent infinitive.
  3. Verify no DE duplicate with the rest of the consolidated list.

### Step 3 — Resolve inconsistent nouns

For each entry in inconsistent_nouns:
  1. If the EN phrase has a standard_glossary entry, use that DE.
  2. Read all instance sentences. Judge which DE fits the source meaning
     and patent register best.
  3. Prefer longer German compound nouns over shorter form + genitive phrase.
  4. Apply compound consistency: if a base term is already resolved (from
     consistent_terms or a prior decision), the compound must use the same
     German base.

     Example:
       watch-item resolved → Wächterelement
       watch-item file-event data        → Wächterelement-Dateiereignisdaten
       metadata watch-item file-event queue
                                         → Metadaten-Wächterelement-Dateiereignis-Warteschlange

  5. Verify the chosen DE does not duplicate a DE already used elsewhere
     in the consolidated list.

### Step 4 — Final scan

Before writing output, verify:
  - No two rows share the same EN term
  - No two rows share the same DE value
  - Every EN term from all input sections appears exactly once
  - Compound nouns use the same base as their resolved base terms
  - No NLP artefacts remain in any EN or DE string

---

## Output

Consolidate consistent_terms, resolved inconsistent_verbs, and resolved
inconsistent_nouns into a single clean glossary — no duplicate EN terms,
no duplicate DE terms. Return the complete consolidated list as a JSON array.
No explanation, no prose, no markdown fences.

[
  {"en": "monitor",                    "de": "überwachen"},
  {"en": "detect",                     "de": "detektieren"},
  {"en": "watch-item",                 "de": "Wächterelement"},
  {"en": "watch-item file-event data", "de": "Wächterelement-Dateiereignisdaten"}
]
"""


# ── Auth ──────────────────────────────────────────────────────────────────────

api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
if not api_key:
    print("ERROR: OPENROUTER_API_KEY not found in .env.")
    exit(1)

client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

# ── Project paths ─────────────────────────────────────────────────────────────

proj_dir   = project_log.project_dir()
project_id = project_log.load_context()["project_id"]
print(f"Project: {project_id}")

verb_pairs_path  = proj_dir / "verb_segment_pairs.csv"
verb_can_path    = proj_dir / "verb_canonical_glossary.csv"
noun_can_path    = proj_dir / "noun_canonical_glossary.csv"
noun_incon_path  = proj_dir / "noun_inconsistency_table.csv"
cap_pairs_path   = proj_dir / "capability_segment_pairs.csv"
glossary_path       = proj_dir / f"glossary_{project_id}.csv"
clean_glossary_path = proj_dir / f"clean_glossary_{project_id}.csv"

for p in [verb_pairs_path, verb_can_path, noun_can_path, noun_incon_path]:
    if not p.exists():
        print(f"ERROR: required file not found: {p.name}")
        print("       Run LLM_verb_comparison_xlsx.py and LLM_noun_comparison_xlsx.py first.")
        exit(1)


# ── Read standard_glossary ────────────────────────────────────────────────────

standard: dict[str, str] = {}   # en_lower → de  (original case)

with open(HERE / "standard_glossary.csv", newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    next(reader, None)
    for row in reader:
        if len(row) >= 2:
            en, de = row[0].strip(), row[1].strip()
            if en and de:
                standard[en.lower()] = de

print(f"Standard glossary: {len(standard)} anchors.")


# ── Filter standard glossary to terms present in this project's source text ───
# Mirrors lara_glossary_upload_standard.py so we only append relevant anchors.

def _appears_in(en_term: str, text: str) -> bool:
    term_lower = en_term.lower()
    if re.search(r"\b" + re.escape(term_lower) + r"\b", text):
        return True
    # Catch inflected forms: "form" → "formed", "forming", "forms".
    # Critical for standard_glossary terms that only appear inflected in patent
    # source text (e.g. "form" never appears bare — only as "formed in the sled").
    # Without this, _appears_in("form", text) returns False and the term is
    # silently excluded from the clean glossary even though it is in the source.
    # Explicit suffix list avoids false matches like "formal" or "former".
    if re.search(r"\b" + re.escape(term_lower) + r"(?:s|d|ed|ing|en|es)\b", text):
        return True
    if term_lower.startswith("to "):
        bare = term_lower[3:].strip()
        if bare and re.search(r"\b" + re.escape(bare) + r"\w*\b", text):
            return True
    return False


_xlsx_files = sorted(
    f for f in proj_dir.glob("*.xlsx")
    if not f.name.startswith("~$")
    and not f.name.endswith("_translated.xlsx")
    and not f.name.endswith("_checks.xlsx")
)

source_text: str = ""          # full source text, used to filter all terms
relevant_standard: dict[str, str] = {}
if _xlsx_files:
    _raw   = pd.read_excel(_xlsx_files[0], header=None, engine="openpyxl")
    _data  = _raw.iloc[3:].reset_index(drop=True)
    _data.columns = ["ID", "Source", "Target"] + list(_data.columns[3:])
    source_text       = " ".join(_data["Source"].dropna().astype(str).tolist()).lower()
    relevant_standard = {en: de for en, de in standard.items() if _appears_in(en, source_text)}
    print(f"  → {len(relevant_standard)}/{len(standard)} standard terms present in source text.")
else:
    relevant_standard = dict(standard)
    print("  Warning: no XTM Excel found — appending full standard glossary.")


# ── Read EPO title from project glossary ──────────────────────────────────────

epo_en, epo_de = "", ""

if glossary_path.exists():
    with open(glossary_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row]
            if any(c.upper().startswith("EPO EN:") or c.upper().startswith("EPO DE:") for c in cells):
                for c in cells:
                    if c.upper().startswith("EPO EN:"):
                        epo_en = c[7:].strip()
                    elif c.upper().startswith("EPO DE:"):
                        epo_de = c[7:].strip()
                break

print(f"EPO title EN: {epo_en[:70]}" + ("..." if len(epo_en) > 70 else ""))


# ── Read verb_segment_pairs ───────────────────────────────────────────────────
# columns: segment_id, en_verb, de_verb, source_text, target_text

verb_groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

vdf = pd.read_csv(verb_pairs_path, encoding="utf-8-sig")
for _, row in vdf.iterrows():
    en  = str(row.get("en_verb",      "")).strip().lower()
    de  = str(row.get("de_verb",      "")).strip()
    src = str(row.get("source_text",  "")).strip()
    tgt = str(row.get("target_text",  "")).strip()
    if en and de:
        if len(verb_groups[en][de]) < MAX_INSTANCES:
            verb_groups[en][de].append({"source": src, "target": tgt})

print(f"Verb pairs: {len(verb_groups)} EN verbs.")


# ── Read capability_segment_pairs (optional) ──────────────────────────────────
# columns: segment_id, en_verb, de_verb, source_text, target_text

cap_groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

if cap_pairs_path.exists():
    cdf = pd.read_csv(cap_pairs_path, encoding="utf-8-sig")
    for _, row in cdf.iterrows():
        en  = str(row.get("en_verb",      "")).strip().lower()
        de  = str(row.get("de_verb",      "")).strip()
        src = str(row.get("source_text",  "")).strip()
        tgt = str(row.get("target_text",  "")).strip()
        if en and de:
            if len(cap_groups[en][de]) < MAX_INSTANCES:
                cap_groups[en][de].append({"source": src, "target": tgt})
    print(f"Capability pairs: {len(cap_groups)} EN capability verbs.")
else:
    print("Capability pairs: not found — skipped.")


# ── Read noun_canonical_glossary ──────────────────────────────────────────────
# columns: EN Phrase, DE Phrase, Count, Total EN Occurrences, Canonical

noun_can: dict[str, dict[str, dict]] = defaultdict(dict)
# noun_can[en_lower][de] = {"count": N, "total": N, "canonical": bool}

ndf = pd.read_csv(noun_can_path, encoding="utf-8-sig")
for _, row in ndf.iterrows():
    en       = str(row.get("EN Phrase",              "")).strip().lower()
    de       = str(row.get("DE Phrase",              "")).strip()
    count    = int(row.get("Count",                   0))
    total    = int(row.get("Total EN Occurrences",    0))
    canonical = str(row.get("Canonical", "no")).strip().lower() == "yes"
    if en and de:
        noun_can[en][de] = {"count": count, "total": total, "canonical": canonical}

print(f"Noun canonical: {len(noun_can)} EN phrases.")


# ── Read noun_inconsistency_table ─────────────────────────────────────────────
# columns: Segment ID, EN Phrase, Expected DE, Actual DE,
#          Expected Count, Actual Count, Total Occurrences, Source Text, Target Text

noun_deviations: dict[str, list[dict]] = defaultdict(list)
# one entry per unique (en, deviant_de) pair

idf = pd.read_csv(noun_incon_path, encoding="utf-8-sig")
for _, row in idf.iterrows():
    en        = str(row.get("EN Phrase",    "")).strip().lower()
    actual_de = str(row.get("Actual DE",    "")).strip()
    src       = str(row.get("Source Text",  "")).strip()
    tgt       = str(row.get("Target Text",  "")).strip()
    if en and actual_de:
        existing_de = {d["de"] for d in noun_deviations[en]}
        if actual_de not in existing_de:
            noun_deviations[en].append({"de": actual_de, "source": src, "target": tgt})

print(f"Noun inconsistencies: {len(noun_deviations)} EN phrases with deviations.")


# ── Classify verbs ────────────────────────────────────────────────────────────

consistent_verbs:   dict[str, str] = {}   # en → de
inconsistent_verbs: list[dict]     = []

for en_verb, de_dict in sorted(verb_groups.items()):
    if len(de_dict) == 1:
        consistent_verbs[en_verb] = next(iter(de_dict))
    else:
        instances = []
        for de, examples in de_dict.items():
            for ex in examples[:MAX_INSTANCES]:
                instances.append({"de": de, "source": ex["source"], "target": ex["target"]})
        inconsistent_verbs.append({"en": en_verb, "instances": instances})

print(f"Verbs  — consistent: {len(consistent_verbs)}, inconsistent: {len(inconsistent_verbs)}.")


# ── Classify capability predicates ────────────────────────────────────────────

consistent_capabilities:   dict[str, str] = {}
inconsistent_capabilities: list[dict]     = []

for en_verb, de_dict in sorted(cap_groups.items()):
    if len(de_dict) == 1:
        consistent_capabilities[en_verb] = next(iter(de_dict))
    else:
        instances = []
        for de, examples in de_dict.items():
            for ex in examples[:MAX_INSTANCES]:
                instances.append({"de": de, "source": ex["source"], "target": ex["target"]})
        inconsistent_capabilities.append({"en": en_verb, "instances": instances})

print(f"Capabilities — consistent: {len(consistent_capabilities)}, inconsistent: {len(inconsistent_capabilities)}.")


# ── Classify nouns (shortest phrase first for compound consistency) ────────────

consistent_nouns:   dict[str, str] = {}
inconsistent_nouns: list[dict]     = []

_noun_phrases = set(noun_can.keys())


def _is_ordinal_variant(en_phrase: str, known_phrases: set[str]) -> bool:
    """Return True if en_phrase starts with an ordinal/relative modifier AND
    its base phrase (modifier removed) exists as a standalone entry.
    Only filter when the base is present so glossary coverage is never lost."""
    words = en_phrase.split()
    if len(words) < 2 or words[0] not in ORDINAL_MODIFIERS:
        return False
    base = " ".join(words[1:])
    return base in known_phrases


for en_phrase in sorted(noun_can.keys(), key=len):
    if _is_ordinal_variant(en_phrase, _noun_phrases):
        continue
    de_map         = noun_can[en_phrase]
    has_deviations = en_phrase in noun_deviations

    # Consistent: single DE form, count == total, no deviations recorded
    if not has_deviations and len(de_map) == 1:
        de_info = next(iter(de_map.values()))
        if de_info["count"] == de_info["total"]:
            consistent_nouns[en_phrase] = next(iter(de_map))
            continue

    # Inconsistent — find canonical (majority) entry
    canonical_de, canonical_info = max(
        de_map.items(), key=lambda kv: kv[1]["count"]
    )

    deviations = [
        d for d in noun_deviations.get(en_phrase, [])
        if d["de"] != canonical_de
    ]

    inconsistent_nouns.append({
        "en":              en_phrase,
        "canonical_de":    canonical_de,
        "canonical_count": canonical_info["count"],
        "total":           canonical_info["total"],
        "deviations":      deviations,
    })

print(f"Nouns  — consistent: {len(consistent_nouns)}, inconsistent: {len(inconsistent_nouns)}.")


# ── Assemble JSON input ───────────────────────────────────────────────────────

input_data = {
    "epo_title": {
        "en": epo_en,
        "de": epo_de,
    },
    "standard_glossary": [
        {"en": en, "de": de} for en, de in relevant_standard.items()
    ],
    "consistent_terms": [
        {"en": en, "de": de}
        for en, de in {**consistent_verbs, **consistent_nouns, **consistent_capabilities}.items()
    ],
    "inconsistent_verbs": inconsistent_verbs,
    "inconsistent_nouns": inconsistent_nouns,
    "inconsistent_capabilities": inconsistent_capabilities,
}

input_json_str = json.dumps(input_data, ensure_ascii=False, indent=2)
estimated_tokens = len(input_json_str) // 4
print(f"\nJSON input: ~{estimated_tokens:,} tokens estimated.")


# ── Helpers: parse and validate LLM response ─────────────────────────────────

def parse_response(raw: str) -> list[dict]:
    # Strip markdown fence wherever it appears (LLM sometimes adds prose before it)
    fence = raw.find("```")
    if fence != -1:
        raw = raw[fence:]
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # Fallback: find the JSON array start in case there is still leading prose
    bracket = raw.find("[")
    if bracket > 0:
        raw = raw[bracket:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\nERROR: Could not parse LLM response as JSON: {e}")
        print(f"Raw response (first 600 chars):\n{raw[:600]}")
        exit(1)
    if not isinstance(parsed, list):
        print("ERROR: LLM response is not a JSON array.")
        exit(1)
    return parsed


def validate_result(items: list[dict]) -> tuple[list[tuple[str, str]], list[str]]:
    """Returns (clean_rows, errors). errors is empty iff the result is valid."""
    de_seen:    dict[str, str]        = {}
    en_seen:    dict[str, str]        = {}
    errors:     list[str]             = []
    clean_rows: list[tuple[str, str]] = []

    for item in items:
        en = str(item.get("en", "")).strip()
        de = str(item.get("de", "")).strip()
        if not en or not de:
            errors.append(f"Skipped empty entry: {item!r}")
            continue
        de_lower = de.lower()
        en_lower = en.lower()

        # Skip exact duplicates (same EN and same DE already seen) silently.
        if en_lower in en_seen and en_seen[en_lower].lower() == de_lower:
            continue

        if de_lower in de_seen:
            pair = frozenset({de_seen[de_lower].lower(), en_lower})
            if pair not in SHARED_DE_ALLOWED:
                errors.append(
                    f'DE duplicate: "{de}" assigned to both "{de_seen[de_lower]}" and "{en}"'
                )
        else:
            de_seen[de_lower] = en

        if en_lower in en_seen:
            if en_seen[en_lower].lower() != de_lower:
                errors.append(
                    f'EN duplicate: "{en}" appears with both "{en_seen[en_lower]}" and "{de}"'
                )
        else:
            en_seen[en_lower] = de

        if en_lower in relevant_standard:
            expected = relevant_standard[en_lower]
            if expected.lower() != de_lower:
                errors.append(
                    f'Standard glossary conflict: "{en}" → "{de}" '
                    f'(standard requires "{expected}")'
                )

        clean_rows.append((en, de))

    return clean_rows, errors


# ── Call API ──────────────────────────────────────────────────────────────────

user_message = USER_PROMPT_TEMPLATE.replace("{INPUT_JSON}", input_json_str)

print(f"Calling {MODEL}...")
response = client.chat.completions.create(
    model=MODEL,
    max_tokens=4096,
    temperature=0,
    timeout=620,
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message},
    ],
)
first_raw = response.choices[0].message.content.strip()
print("Response received.")

result     = parse_response(first_raw)
clean_rows, errors = validate_result(result)

if errors:
    print(f"\n⚠  Validation errors ({len(errors)}) — sending back for a second run:")
    for e in errors:
        print(f"   {e}")

    error_lines = "\n".join(f"- {e}" for e in errors)
    retry_user_msg = (
        f"Your response contains {len(errors)} error(s) that violate the rules.\n\n"
        f"Errors:\n{error_lines}\n\n"
        "Rules:\n"
        "- Each DE value must appear in exactly one row (no DE duplicates).\n"
        "- Each EN term must appear exactly once (no EN duplicates).\n\n"
        f"Return the complete corrected JSON array — all rows, not just the changed ones. "
        "No explanation, no prose, no markdown fences."
    )
    retry_resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        timeout=120,
        messages=[
            {"role": "system",    "content": SYSTEM_PROMPT},
            {"role": "user",      "content": user_message},
            {"role": "assistant", "content": first_raw},
            {"role": "user",      "content": retry_user_msg},
        ],
    )
    retry_raw = retry_resp.choices[0].message.content.strip()
    print("Retry response received.")

    result     = parse_response(retry_raw)
    clean_rows, errors = validate_result(result)

    if errors:
        print(f"\n⚠  {len(errors)} error(s) persist after retry — output will be written with warnings:")
        for e in errors:
            print(f"   {e}")
    else:
        print("Retry successful — all errors resolved.")


# ── Drop any LLM-echoed title row ─────────────────────────────────────────────
# epo_title is sent as reference context only ("the EPO title" is not one of
# consistent_terms/inconsistent_verbs/inconsistent_nouns), but the model
# sometimes returns it anyway with its own (possibly non-official) translation.
# The authoritative pair is written separately below — drop any LLM row that
# duplicates the title's EN so it can't override/conflict with the real one.
if epo_en:
    _epo_en_norm = epo_en.strip().lower()
    _dropped_title_rows = [(en, de) for en, de in clean_rows if en.strip().lower() == _epo_en_norm]
    if _dropped_title_rows:
        clean_rows = [(en, de) for en, de in clean_rows if en.strip().lower() != _epo_en_norm]
        for en, de in _dropped_title_rows:
            print(f"  Dropped LLM-echoed title row: {en!r} → {de!r} (using authoritative EPO DE instead)")


# ── Restore consistent terms dropped by the LLM ───────────────────────────────
# Some models only return the inconsistent terms they resolved and omit the
# consistent ones. Fill any gaps from the original classification.

def _norm_en(en: str) -> str:
    return re.sub(r"\s*-\s*", "-", en.lower())

output_en = {_norm_en(en) for en, _ in clean_rows}
filled: list[tuple[str, str]] = []

for en, de in {**consistent_verbs, **consistent_nouns, **consistent_capabilities}.items():
    if _norm_en(en) not in output_en:
        filled.append((en, de))
        clean_rows.append((en, de))

if filled:
    print(f"\n↩  Restored {len(filled)} consistent term(s) omitted by LLM:")
    for en, de in filled:
        print(f"   {en} → {de}")


# ── Print decision summary ────────────────────────────────────────────────────

# Build a canonical reference map to highlight LLM overrides
canonical_ref: dict[str, str] = {}
for en, de_dict in verb_groups.items():
    if de_dict:
        canonical_ref[en] = max(de_dict, key=lambda d: len(de_dict[d]))
for noun_entry in inconsistent_nouns:
    canonical_ref[noun_entry["en"]] = noun_entry["canonical_de"]

print(f"\n{'EN term':<42} {'Chosen DE':<35} {'Note'}")
print("-" * 90)
for en, de in clean_rows:
    canonical = canonical_ref.get(en.lower(), de)
    note = "← overrode majority" if canonical.lower() != de.lower() else ""
    print(f"  {en:<40} {de:<35} {note}")


# ── Write clean glossary ──────────────────────────────────────────────────────
# Writes two sections:
#   1. LLM-resolved project terms (consistent + inconsistency decisions)
#   2. Standard glossary terms present in this project's source text — appended
#      so they survive the step-7 upload that replaces the step-5a Lara glossary.

# Standard terms already in the LLM output (because they were in consistent_terms)
# must not be written a second time in the standard section.
llm_en_set = {en.lower() for en, _ in clean_rows}
extra_standard = [(en, de) for en, de in relevant_standard.items() if en.lower() not in llm_en_set]

with open(clean_glossary_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["EN", "DE"])
    if epo_en and epo_de:
        writer.writerow([f"EPO EN: {epo_en}", f"EPO DE: {epo_de}"])
    writer.writerow([])
    for en, de in clean_rows:
        writer.writerow([en, de])
    if extra_standard:
        writer.writerow([])
        for en_lo, de in extra_standard:
            writer.writerow([en_lo, de])

total = len(clean_rows) + len(extra_standard)
print(f"\nGlossary written → {clean_glossary_path.name}  "
      f"({len(clean_rows)} project terms + {len(extra_standard)} extra standard terms = {total} total)")
print("Next step: lara_glossary_upload.py")
