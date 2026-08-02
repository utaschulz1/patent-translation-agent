# ============================================================
# verb_lemma_sync.py
# ============================================================
# Grows the shared EN_verb_lemma_lookup.json / DE_verb_lemma_lookup.json
# tables with verbs a project's cleaned glossary introduces that neither
# table recognizes yet.
#
# Those two JSON files map every inflected surface form of a verb to its
# infinitive lemma (e.g. "aufweist" -> "aufweisen") — that's what lets
# glossary_compare_revised_translation.py's _count_lemmas() recognize any
# conjugation of a glossary verb in running target text. A verb missing from
# EN_verb_lemma_lookup.json doesn't just fail silently: build_glossary_lookups()
# falls back to routing it through noun-phrase matching instead, which uses a
# length-heuristic that assumes inflected forms are the same length or longer
# than the base form — true for German noun inflection, false for verb
# conjugation (aufweisen -> aufweist is *shorter*). That misrouting is exactly
# what caused the "having" false positive fixed on 2026-07-31 — this module
# exists to catch the next one automatically instead of by manual QA.
#
# Detection always runs against the *cleaned* (en, de) pairs a project's
# glossary consolidation produces — never the raw spaCy-lemmatized
# verb_canonical_glossary.csv, which can contain artefacts (e.g. "ausgestalt"
# for "ausgestalten") that must never leak into the shared tables.
#
# Public API:
#   sync_verb_lemma_tables(clean_rows, consistent_verbs, inconsistent_verbs,
#                           client, model, en_lemma_path=EN_LEMMA_PATH,
#                           de_lemma_path=DE_LEMMA_PATH) -> (en_added, de_added)
# ============================================================

import json
from pathlib import Path

HERE = Path(__file__).parent

EN_LEMMA_PATH = HERE / "EN_verb_lemma_lookup.json"
DE_LEMMA_PATH = HERE / "DE_verb_lemma_lookup.json"

SYSTEM_PROMPT = """\
You are a German patent translator specialising in EP patent claims and \
descriptions. You follow EPO translation conventions and German patent language \
standards. You produce formal, precise German suitable for legal patent documents.\
"""

NEW_VERB_PROMPT_TEMPLATE = """\
## Objective

For each NEW verb pair below, produce the small set of inflected surface \
forms used in EPO patent claim/description language, so each form can be \
added to a lookup table mapping surface form → infinitive lemma. Follow the \
exact pattern of the EXAMPLE families — do not invent forms.

## Example families (already in the table — for pattern reference only)

{EXAMPLES_JSON}

## New verb pairs — produce forms for these

{NEW_PAIRS_JSON}

## Rules

- EN forms: base infinitive, 3rd-person singular (-s), gerund (-ing), \
  past/past participle (irregular if applicable, else -ed). Usually 4 forms.
- DE forms: infinitive, present participle (-end) and its adjective \
  inflections actually plausible in patent text (-ende, -enden), 3rd-person \
  singular present, zu-infinitive (mind separable prefixes: "auszugestalten" \
  not "zu ausgestalten"), past participle (mind separable prefixes: \
  "ausgestaltet" not "geausgestaltet"). Usually 6-8 forms.
- Every form must be a real, correctly spelled, patent-register word for \
  that verb. Never invent a form you are not confident is correct — omit it \
  instead of guessing.
- "en_lemma"/"de_lemma" in your output must exactly echo the input pair.

## Output

Return a JSON array, one entry per input pair. No prose, no markdown fences.

[
  {"en_lemma": "design", "de_lemma": "ausgestalten",
   "en_forms": ["design", "designs", "designing", "designed"],
   "de_forms": ["ausgestalten", "ausgestaltend", "ausgestaltende", "ausgestaltenden", "ausgestaltet", "auszugestalten"]}
]
"""

# A few real families already in the tables, used as few-shot pattern examples.
VERB_FORM_EXAMPLES = {
    "aufweisen": ["aufweisen", "aufweisend", "aufweist", "aufzuweisen", "aufgewiesen"],
    "anliegen":  ["anliegen", "anliegend", "anliegende", "anliegenden", "anliegender", "anliegt"],
    "ableiten":  ["ableiten", "ableitend", "ableitende", "ableitenden", "ableitet", "abzuleiten"],
}


def parse_json_array_lenient(raw: str) -> list[dict]:
    """Parse an LLM's JSON-array response, tolerant of markdown fences.

    Returns [] on any failure instead of raising — callers treat this as a
    non-fatal "nothing to add", never as a reason to abort a larger pipeline.
    """
    fence = raw.find("```")
    if fence != -1:
        raw = raw[fence:]
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    bracket = raw.find("[")
    if bracket > 0:
        raw = raw[bracket:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def find_new_verb_pairs(
    clean_rows: list[tuple[str, str]],
    consistent_verbs: dict[str, str],
    inconsistent_verbs: list[dict],
    en_lemma_table: dict[str, str],
    de_lemma_table: dict[str, str],
) -> list[tuple[str, str]]:
    """Final (en, de) verb pairs from a project not fully covered by either
    lemma table — i.e. the EN lemma or the DE lemma (or both) is missing as a
    key. Restricted to single-word pairs; the lemma tables don't hold phrases.
    """
    verb_en_set = {en.lower() for en in consistent_verbs}
    verb_en_set |= {d["en"].lower() for d in inconsistent_verbs}
    final_verb_pairs = [(en, de) for en, de in clean_rows if en.lower() in verb_en_set]
    return [
        (en, de) for en, de in final_verb_pairs
        if " " not in en and " " not in de
        and (en.lower() not in en_lemma_table or de.lower() not in de_lemma_table)
    ]


def request_new_verb_forms(new_pairs: list[tuple[str, str]], client, model: str) -> list[dict]:
    """One LLM call: for each new (en, de) infinitive pair, get its small set
    of inflected surface forms. `client` is an OpenAI-compatible chat client
    (e.g. OpenAI(base_url="https://openrouter.ai/api/v1")).
    """
    pairs_json = json.dumps(
        [{"en_lemma": en, "de_lemma": de} for en, de in new_pairs],
        ensure_ascii=False, indent=2,
    )
    examples_json = json.dumps(
        [{"lemma": lemma, "forms": forms} for lemma, forms in VERB_FORM_EXAMPLES.items()],
        ensure_ascii=False, indent=2,
    )
    prompt = (
        NEW_VERB_PROMPT_TEMPLATE
        .replace("{EXAMPLES_JSON}", examples_json)
        .replace("{NEW_PAIRS_JSON}", pairs_json)
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        temperature=0,
        timeout=120,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    )
    return parse_json_array_lenient(resp.choices[0].message.content.strip())


def merge_verb_forms(
    items: list[dict], en_lemma_table: dict[str, str], de_lemma_table: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Add any forms not already present as keys, in place. Never overwrites
    an existing key — an existing mapping always wins over a freshly
    generated one. Returns the (en_added, de_added) surface forms."""
    en_added: list[str] = []
    de_added: list[str] = []
    for item in items:
        en_lemma = str(item.get("en_lemma", "")).strip().lower()
        de_lemma = str(item.get("de_lemma", "")).strip().lower()
        if not en_lemma or not de_lemma:
            continue
        for form in item.get("en_forms") or [en_lemma]:
            form = str(form).strip().lower()
            if form and " " not in form and form not in en_lemma_table:
                en_lemma_table[form] = en_lemma
                en_added.append(form)
        for form in item.get("de_forms") or [de_lemma]:
            form = str(form).strip().lower()
            if form and " " not in form and form not in de_lemma_table:
                de_lemma_table[form] = de_lemma
                de_added.append(form)
    return en_added, de_added


def write_lemma_table(path: Path, table: dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(table.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")


def sync_verb_lemma_tables(
    clean_rows: list[tuple[str, str]],
    consistent_verbs: dict[str, str],
    inconsistent_verbs: list[dict],
    client,
    model: str,
    en_lemma_path: Path = EN_LEMMA_PATH,
    de_lemma_path: Path = DE_LEMMA_PATH,
) -> tuple[list[str], list[str]]:
    """Detect + fill verb lemma-table gaps for one project's cleaned glossary.
    Writes en_lemma_path/de_lemma_path in place, only when something new was
    actually added. Returns the (en_added, de_added) surface forms."""
    with open(en_lemma_path, encoding="utf-8") as f:
        en_lemma_table = json.load(f)
    with open(de_lemma_path, encoding="utf-8") as f:
        de_lemma_table = json.load(f)

    new_pairs = find_new_verb_pairs(
        clean_rows, consistent_verbs, inconsistent_verbs, en_lemma_table, de_lemma_table
    )

    if not new_pairs:
        print("\nVerb lemma tables: no new verbs found in this project's glossary.")
        return [], []

    print(f"\nVerb lemma tables: {len(new_pairs)} new verb(s) found — "
          f"requesting inflected forms: {', '.join(en for en, _ in new_pairs)}")
    items = request_new_verb_forms(new_pairs, client, model)
    if not items:
        print("  WARNING: could not parse inflected-forms response — lemma tables left unchanged.")
        return [], []

    en_added, de_added = merge_verb_forms(items, en_lemma_table, de_lemma_table)
    if en_added:
        write_lemma_table(en_lemma_path, en_lemma_table)
        print(f"  EN_verb_lemma_lookup.json: added {len(en_added)} form(s) — {', '.join(sorted(en_added))}")
    if de_added:
        write_lemma_table(de_lemma_path, de_lemma_table)
        print(f"  DE_verb_lemma_lookup.json: added {len(de_added)} form(s) — {', '.join(sorted(de_added))}")
    if not en_added and not de_added:
        print("  No new lemma forms to add (all forms already present).")

    return en_added, de_added
