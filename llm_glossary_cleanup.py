# ============================================================
# llm_glossary_cleanup.py
# ============================================================
# Resolves glossary inconsistencies using DeepSeek via OpenRouter.
#
# Since Phase 0 of PRD_glossary_agent.md §4 the reusable pieces live in
# agent/glossary_lib/ (classify, attestation, csv_io, validate, lemma_sync)
# and are re-exported here; this module keeps the legacy-path orchestration:
# load_cleanup_inputs() (all reading + deterministic classification, no
# network — also reused by the glossary agent's load_inputs node) and
# clean_glossary() (the LLM call, validation retry, and CSV write).
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
#   projects/<id>/clean_glossary_<id>.csv      clean, resolved two-column glossary
#
# Library entry point: clean_glossary(proj_dir, project_id) -> GlossaryCleanupResult
# Run standalone: python llm_glossary_cleanup.py (uses current_project.json)
# ============================================================

import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

import project_log
from config import LLM_MODEL
from glossary_lib.attestation import _appears_in  # noqa: F401
from glossary_lib.classify import (  # noqa: F401
    ORDINAL_MODIFIERS,
    SHARED_DE_ALLOWED,
    _EN_TO_DE_ORDINAL_STEMS,
    _DE_ADJ_ENDINGS,
    _is_ordinal_variant,
    _merge_ordinal_siblings,
    _shared_de_note,
    _strip_de_ordinal_word,
    classify_nouns,
    classify_pairs,
)
from glossary_lib.csv_io import filter_relevant_standard, resolve_epo_title, write_clean_glossary
from glossary_lib.validate import _norm_en, parse_response, validate_result  # noqa: F401

HERE = Path(__file__).parent
load_dotenv(dotenv_path=HERE / ".env")

MODEL              = LLM_MODEL

MAX_INSTANCES      = 1   # max example sentences per (en, de) pair in prompt

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

{SHARED_DE_NOTE}

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
  - No two rows share the same DE value (except the sanctioned overlaps
    listed under Objective above)
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


# ── Input loading + deterministic classification (no network) ────────────────


@dataclass
class CleanupInputs:
    """Everything the consolidation stage needs, loaded and classified —
    deterministically, with no LLM involved. Produced by load_cleanup_inputs;
    consumed by clean_glossary here and by the glossary agent's load_inputs/
    classify_terms nodes."""
    proj_dir:                  Path
    project_id:                str
    clean_glossary_path:       Path
    standard:                  dict[str, str]
    relevant_standard:         dict[str, str]
    source_text:               str
    xlsx_found:                bool
    epo_en:                    str
    epo_de:                    str
    verb_groups:               dict
    cap_groups:                dict
    noun_can:                  dict
    noun_deviations:           dict
    consistent_verbs:          dict[str, str]
    inconsistent_verbs:        list[dict]
    consistent_capabilities:   dict[str, str]
    inconsistent_capabilities: list[dict]
    consistent_nouns:          dict[str, str]
    inconsistent_nouns:        list[dict]
    merged_bases:              dict[str, str] = field(default_factory=dict)

    def consistent_terms(self) -> dict[str, str]:
        """All consistent terms merged, the shape the prompt consumes."""
        return {**self.consistent_verbs, **self.consistent_nouns, **self.consistent_capabilities}

    def build_input_json(self) -> str:
        """Assemble the LLM input JSON exactly as the batch prompt expects."""
        input_data = {
            "epo_title": {
                "en": self.epo_en,
                "de": self.epo_de,
            },
            "standard_glossary": [
                {"en": en, "de": de} for en, de in self.relevant_standard.items()
            ],
            "consistent_terms": [
                {"en": en, "de": de} for en, de in self.consistent_terms().items()
            ],
            "inconsistent_verbs": self.inconsistent_verbs,
            "inconsistent_nouns": self.inconsistent_nouns,
            "inconsistent_capabilities": self.inconsistent_capabilities,
        }
        return json.dumps(input_data, ensure_ascii=False, indent=2)


def load_cleanup_inputs(proj_dir: Path, project_id: str) -> CleanupInputs:
    """Read every consolidation input and run the deterministic classification.

    No network access — safe to call from tests and from the glossary agent's
    deterministic nodes. Prints progress the same way the legacy pipeline
    always has (captured as step output by the workflow UI).

    Raises:
        FileNotFoundError: if any of the four mandatory extraction CSVs is
            missing.
    """
    print(f"Project: {project_id}")

    verb_pairs_path  = proj_dir / "verb_segment_pairs.csv"
    verb_can_path    = proj_dir / "verb_canonical_glossary.csv"
    noun_can_path    = proj_dir / "noun_canonical_glossary.csv"
    noun_incon_path  = proj_dir / "noun_inconsistency_table.csv"
    cap_pairs_path   = proj_dir / "capability_segment_pairs.csv"
    clean_glossary_path = proj_dir / f"clean_glossary_{project_id}.csv"

    for p in [verb_pairs_path, verb_can_path, noun_can_path, noun_incon_path]:
        if not p.exists():
            raise FileNotFoundError(
                f"required file not found: {p.name}. "
                "Run LLM_verb_comparison_xlsx.py and LLM_noun_comparison_xlsx.py first."
            )

    # ── Read standard_glossary ──────────────────────────────────────────────

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

    _xlsx_files = sorted(
        f for f in proj_dir.glob("*.xlsx")
        if not f.name.startswith("~$")
        and not f.name.endswith("_translated.xlsx")
        and not f.name.endswith("_checks.xlsx")
    )

    source_text: str = ""          # full source text, used to filter all terms
    relevant_standard: dict[str, str] = {}
    xlsx_found = bool(_xlsx_files)
    if _xlsx_files:
        _raw   = pd.read_excel(_xlsx_files[0], header=None, engine="openpyxl")
        _data  = _raw.iloc[3:].reset_index(drop=True)
        _data.columns = ["ID", "Source", "Target"] + list(_data.columns[3:])
        source_text       = " ".join(_data["Source"].dropna().astype(str).tolist()).lower()
        relevant_standard = filter_relevant_standard(standard, source_text)
        print(f"  → {len(relevant_standard)}/{len(standard)} standard terms present in source text.")
    else:
        relevant_standard = dict(standard)
        print("  Warning: no XTM Excel found — appending full standard glossary.")

    # ── Read EPO title from project glossary ────────────────────────────────

    epo_en, epo_de = resolve_epo_title(proj_dir, project_id)
    print(f"EPO title EN: {epo_en[:70]}" + ("..." if len(epo_en) > 70 else ""))

    # ── Read verb_segment_pairs ──────────────────────────────────────────────
    # columns: segment_id, en_verb, de_verb, source_text, target_text

    verb_groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    try:
        vdf = pd.read_csv(verb_pairs_path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        vdf = pd.DataFrame(columns=["en_verb", "de_verb", "source_text", "target_text"])
    for _, row in vdf.iterrows():
        en  = str(row.get("en_verb",      "")).strip().lower()
        de  = str(row.get("de_verb",      "")).strip()
        src = str(row.get("source_text",  "")).strip()
        tgt = str(row.get("target_text",  "")).strip()
        if en and de:
            if len(verb_groups[en][de]) < MAX_INSTANCES:
                verb_groups[en][de].append({"source": src, "target": tgt})

    print(f"Verb pairs: {len(verb_groups)} EN verbs.")

    # ── Read capability_segment_pairs (optional) ─────────────────────────────
    # columns: segment_id, en_verb, de_verb, source_text, target_text

    cap_groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    if cap_pairs_path.exists():
        try:
            cdf = pd.read_csv(cap_pairs_path, encoding="utf-8-sig")
        except pd.errors.EmptyDataError:
            cdf = pd.DataFrame(columns=["en_verb", "de_verb", "source_text", "target_text"])
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

    # ── Read noun_canonical_glossary ─────────────────────────────────────────
    # columns: EN Phrase, DE Phrase, Count, Total EN Occurrences, Canonical

    noun_can: dict[str, dict[str, dict]] = defaultdict(dict)
    # noun_can[en_lower][de] = {"count": N, "total": N, "canonical": bool}

    try:
        ndf = pd.read_csv(noun_can_path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        ndf = pd.DataFrame(columns=["EN Phrase", "DE Phrase", "Count", "Total EN Occurrences", "Canonical"])
    for _, row in ndf.iterrows():
        en       = str(row.get("EN Phrase",              "")).strip().lower()
        de       = str(row.get("DE Phrase",              "")).strip()
        count    = int(row.get("Count",                   0))
        total    = int(row.get("Total EN Occurrences",    0))
        canonical = str(row.get("Canonical", "no")).strip().lower() == "yes"
        if en and de:
            noun_can[en][de] = {"count": count, "total": total, "canonical": canonical}

    print(f"Noun canonical: {len(noun_can)} EN phrases.")

    # ── Read noun_inconsistency_table ────────────────────────────────────────
    # columns: Segment ID, EN Phrase, Expected DE, Actual DE,
    #          Expected Count, Actual Count, Total Occurrences, Source Text, Target Text
    # Optional columns (only present when LLM_noun_comparison_xlsx.py's Phase 5
    # evaluator ran — RUN_EVALUATOR there defaults to False): False Positive, Reason.
    # A row judged a false positive is excluded here the same way Phase 4 already
    # excludes it from the _checks.xlsx annotation — so turning the evaluator on
    # actually changes what reaches this LLM, instead of being computed and ignored.

    noun_deviations: dict[str, list[dict]] = defaultdict(list)
    # one entry per unique (en, deviant_de) pair

    try:
        idf = pd.read_csv(noun_incon_path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        idf = pd.DataFrame(columns=["EN Phrase", "Actual DE", "Source Text", "Target Text"])

    skipped_false_positives = 0
    for _, row in idf.iterrows():
        if str(row.get("False Positive", "")).strip().lower() == "true":
            skipped_false_positives += 1
            continue
        en        = str(row.get("EN Phrase",    "")).strip().lower()
        actual_de = str(row.get("Actual DE",    "")).strip()
        src       = str(row.get("Source Text",  "")).strip()
        tgt       = str(row.get("Target Text",  "")).strip()
        if en and actual_de:
            existing_de = {d["de"] for d in noun_deviations[en]}
            if actual_de not in existing_de:
                noun_deviations[en].append({"de": actual_de, "source": src, "target": tgt})

    print(f"Noun inconsistencies: {len(noun_deviations)} EN phrases with deviations."
          + (f" ({skipped_false_positives} evaluator-judged false positive(s) excluded.)"
             if skipped_false_positives else ""))

    # ── Classify (glossary_lib.classify — same logic both paths) ────────────

    consistent_verbs, inconsistent_verbs = classify_pairs(verb_groups, MAX_INSTANCES)
    print(f"Verbs  — consistent: {len(consistent_verbs)}, inconsistent: {len(inconsistent_verbs)}.")

    consistent_capabilities, inconsistent_capabilities = classify_pairs(cap_groups, MAX_INSTANCES)
    print(f"Capabilities — consistent: {len(consistent_capabilities)}, inconsistent: {len(inconsistent_capabilities)}.")

    consistent_nouns, inconsistent_nouns, merged_bases = classify_nouns(noun_can, noun_deviations)
    print(f"Nouns  — consistent: {len(consistent_nouns)}, inconsistent: {len(inconsistent_nouns)}."
          + (f" ({len(merged_bases)} ordinal-sibling group(s) merged.)" if merged_bases else ""))

    return CleanupInputs(
        proj_dir=proj_dir,
        project_id=project_id,
        clean_glossary_path=clean_glossary_path,
        standard=standard,
        relevant_standard=relevant_standard,
        source_text=source_text,
        xlsx_found=xlsx_found,
        epo_en=epo_en,
        epo_de=epo_de,
        verb_groups=verb_groups,
        cap_groups=cap_groups,
        noun_can=noun_can,
        noun_deviations=noun_deviations,
        consistent_verbs=consistent_verbs,
        inconsistent_verbs=inconsistent_verbs,
        consistent_capabilities=consistent_capabilities,
        inconsistent_capabilities=inconsistent_capabilities,
        consistent_nouns=consistent_nouns,
        inconsistent_nouns=inconsistent_nouns,
        merged_bases=merged_bases,
    )


# ── Main entry point ───────────────────────────────────────────────────────


@dataclass
class GlossaryCleanupResult:
    """Everything a caller (or a test) might want to inspect about one run.

    `path` is the only thing production callers need; the rest surfaces the
    pipeline's intermediate decisions (what the LLM omitted and had to be
    restored, which standard-glossary terms were relevant, how nouns were
    classified) without requiring a caller to re-derive them from the CSV.
    """
    path:               Path
    clean_rows:         list[tuple[str, str]]
    extra_standard:     list[tuple[str, str]]
    filled:             list[tuple[str, str]]
    standard:           dict[str, str]
    input_json_str:     str
    consistent_nouns:   dict[str, str]
    inconsistent_nouns: list[dict] = field(default_factory=list)


def clean_glossary(proj_dir: Path, project_id: str) -> GlossaryCleanupResult:
    """Resolve glossary inconsistencies for one project using DeepSeek via
    OpenRouter, write the clean glossary CSV, and return a result describing
    what happened.

    Takes the project location as explicit arguments rather than reading the
    shared current_project.json context, so it's safe to call for different
    projects from concurrent requests (see llm_glossary_cleanup __main__ for
    the standalone-script entry point that resolves those from context).
    """

    # ── Auth ────────────────────────────────────────────────────────────────

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not found in .env.")

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    # ── Load + classify (no network) ────────────────────────────────────────

    inputs = load_cleanup_inputs(proj_dir, project_id)
    relevant_standard = inputs.relevant_standard
    epo_en, epo_de = inputs.epo_en, inputs.epo_de
    consistent_verbs = inputs.consistent_verbs
    inconsistent_verbs = inputs.inconsistent_verbs
    consistent_capabilities = inputs.consistent_capabilities
    consistent_nouns = inputs.consistent_nouns
    inconsistent_nouns = inputs.inconsistent_nouns

    input_json_str = inputs.build_input_json()
    estimated_tokens = len(input_json_str) // 4
    print(f"\nJSON input: ~{estimated_tokens:,} tokens estimated.")

    # ── Call API ──────────────────────────────────────────────────────────────

    user_message = USER_PROMPT_TEMPLATE.replace("{INPUT_JSON}", input_json_str)
    user_message = user_message.replace("{SHARED_DE_NOTE}", _shared_de_note())

    print(f"Calling {MODEL}...")
    response = client.chat.completions.create(
        model=MODEL,
        # 4096 -> 8192 (2026-08-30): the widened noun-extraction rule grows
        # consistent_terms/inconsistent_nouns, which this call must echo
        # back in full — matches the ceiling glossary_agent/graph.py's
        # resolve_inconsistent (the successor to this same call) already
        # uses for the identical prompt/response shape.
        max_tokens=8192,
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
    clean_rows, errors = validate_result(result, relevant_standard)

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
            max_tokens=8192,  # matches the primary call above, same reasoning
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
        clean_rows, errors = validate_result(result, relevant_standard)

        if errors:
            print(f"\n⚠  {len(errors)} error(s) persist after retry — output will be written with warnings:")
            for e in errors:
                print(f"   {e}")
        else:
            print("Retry successful — all errors resolved.")

    # ── Drop any LLM-echoed title row ────────────────────────────────────────
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

    # ── Restore consistent terms dropped by the LLM ──────────────────────────
    # Some models only return the inconsistent terms they resolved and omit the
    # consistent ones. Fill any gaps from the original classification.

    output_en = {_norm_en(en) for en, _ in clean_rows}
    filled: list[tuple[str, str]] = []

    for en, de in inputs.consistent_terms().items():
        if _norm_en(en) not in output_en:
            filled.append((en, de))
            clean_rows.append((en, de))

    if filled:
        print(f"\n↩  Restored {len(filled)} consistent term(s) omitted by LLM:")
        for en, de in filled:
            print(f"   {en} → {de}")

    # ── Print decision summary ───────────────────────────────────────────────

    # Build a canonical reference map to highlight LLM overrides
    canonical_ref: dict[str, str] = {}
    for en, de_dict in inputs.verb_groups.items():
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

    # ── Write clean glossary ─────────────────────────────────────────────────
    # Writes two sections:
    #   1. LLM-resolved project terms (consistent + inconsistency decisions)
    #   2. Standard glossary terms present in this project's source text — appended
    #      so they survive the step-7 upload that replaces the step-5a Lara glossary.

    # Standard terms already in the LLM output (because they were in consistent_terms)
    # must not be written a second time in the standard section.
    llm_en_set = {en.lower() for en, _ in clean_rows}
    extra_standard = [(en, de) for en, de in relevant_standard.items() if en.lower() not in llm_en_set]

    write_clean_glossary(
        inputs.clean_glossary_path,
        (epo_en, epo_de) if epo_en and epo_de else None,
        clean_rows,
        extra_standard,
        labeled_title=True,
    )

    total = len(clean_rows) + len(extra_standard)
    print(f"\nGlossary written → {inputs.clean_glossary_path.name}  "
          f"({len(clean_rows)} project terms + {len(extra_standard)} extra standard terms = {total} total)")

    # ── Grow this project's verb lemma overlay with any new verbs ────────────
    # See glossary_lib/lemma_sync.py — detects verb pairs (from the *cleaned*
    # rows above, never raw spaCy output) not yet covered by the merged
    # baseline+overlay tables, and writes their inflected forms to the
    # project-scoped overlay files (PRD §6b — the shared baseline is never
    # written at runtime).

    from verb_lemma_sync import sync_verb_lemma_tables

    sync_verb_lemma_tables(clean_rows, consistent_verbs, inconsistent_verbs, client, MODEL, proj_dir=proj_dir)

    print("Next step: lara_glossary_upload.py")

    return GlossaryCleanupResult(
        path=inputs.clean_glossary_path,
        clean_rows=clean_rows,
        extra_standard=extra_standard,
        filled=filled,
        standard=inputs.standard,
        input_json_str=input_json_str,
        consistent_nouns=consistent_nouns,
        inconsistent_nouns=inconsistent_nouns,
    )


if __name__ == "__main__":
    proj_dir   = project_log.project_dir()
    project_id = project_log.load_context()["project_id"]
    clean_glossary(proj_dir, project_id)
