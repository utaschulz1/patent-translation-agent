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
# glossary consolidation produces. That input is expected to be imperfect —
# e.g. a "consistent" verb (2026-08-05, "work" -> "ausgeführt") never passes
# through any infinitive check upstream, since "consistent" only means the MT
# engine rendered it the same way every time, not that the rendering is a
# dictionary infinitive. So this module can't trust en/de as already-correct
# lemmas; it treats every verb candidate as a surface form to be resolved
# against the tables (or, failing that, derived from scratch) on its own.
#
# EN and DE are checked, and requested from the LLM, independently — pairing
# only matters for picking which clean_rows rows are verbs at all (via
# consistent_verbs/inconsistent_verbs), never for deciding whether a given
# side already has a known lemma.
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

# Same suffixes glossary_compare_revised_translation.py's _count_lemmas()
# strips at check time when a DE word isn't found directly (Partizip-II
# adjective inflection, e.g. "eingerichtete" -> "eingerichtet"). A form the
# checker can already resolve this way counts as "known" here too — we don't
# need a table entry for every adjective ending of every participle.
DE_ADJ_SUFFIXES = ("em", "er", "es", "en", "e")

# Patent-glossary terms that surface as "unmatched verbs" but aren't verbs at
# all — the DE side is a fixed adjectival/predicate usage, not a conjugated
# form of any verb. Excluded up front rather than left to the LLM: asked to
# derive an infinitive for "bekannt", it correctly finds the real word
# "bekennen" (confess) — genuinely the right participle-to-infinitive
# mapping in isolation, just semantically unrelated to why "know" put
# "bekannt" here (the "ist bekannt" patent construction).
NON_VERB_DE_TERMS = {"bekannt"}

SYSTEM_PROMPT = """\
You are a German patent translator specialising in EP patent claims and \
descriptions. You follow EPO translation conventions and German patent language \
standards. You produce formal, precise German suitable for legal patent documents.\
"""

DERIVATION_PROMPT_TEMPLATE = """\
## Objective

Each surface form below was seen in a patent glossary but is not yet in our \
verb lemma lookup tables. For each one, identify the correct dictionary \
infinitive it belongs to, and produce a small set of additional inflected \
forms for that infinitive's paradigm, in EPO patent claim/description register.

The surface form given may already BE the infinitive, or may be some other \
inflected form (e.g. a past participle used adjectivally) — determine the \
true infinitive yourself, do not assume the surface form is already correct.

## EN surface forms (unmatched)

{EN_JSON}

For each: infinitive, 3rd-person singular (-s), gerund (-ing), past/past \
participle (irregular if applicable, else -ed).

## DE surface forms (unmatched)

{DE_JSON}

For each: infinitive, 3rd-person singular present, past participle (Partizip \
II — mind separable prefixes: "ausgeführt" not "geausführt"), zu-infinitive \
(mind separable prefixes: "auszuführen" not "zu ausführen").

## Rules

- Every form must be a real, correctly spelled, patent-register word.
- Never invent a form you are not confident is correct — omit it instead of guessing.
- The "forms" list for each entry must include the original surface form itself.
- If a list above is empty, return an empty array for that side.

## Output

Return JSON with two arrays, no prose, no markdown fences:

{{
  "en": [{{"surface": "work", "infinitive": "work", "forms": ["work", "works", "working", "worked"]}}],
  "de": [{{"surface": "ausgeführt", "infinitive": "ausführen", "forms": ["ausführen", "ausführt", "ausgeführt", "auszuführen"]}}]
}}
"""


def parse_json_object_lenient(raw: str) -> dict:
    """Parse an LLM's JSON-object response, tolerant of markdown fences.

    Returns {} on any failure instead of raising — callers treat this as a
    non-fatal "nothing to add", never as a reason to abort a larger pipeline.
    """
    fence = raw.find("```")
    if fence != -1:
        raw = raw[fence:]
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    brace = raw.find("{")
    if brace > 0:
        raw = raw[brace:]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_de(word: str, de_lemma_table: dict[str, str]) -> str | None:
    """Resolve a DE surface form to its known infinitive: exact key match,
    or — mirroring _count_lemmas' strip_de_adj fallback — one adjective
    suffix stripped off and retried."""
    word = word.lower()
    if word in de_lemma_table:
        return de_lemma_table[word]
    for suffix in DE_ADJ_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            base = de_lemma_table.get(word[: -len(suffix)])
            if base:
                return base
    return None


def find_unknown_verbs(
    clean_rows: list[tuple[str, str]],
    consistent_verbs: dict[str, str],
    inconsistent_verbs: list[dict],
    en_lemma_table: dict[str, str],
    de_lemma_table: dict[str, str],
) -> tuple[list[str], list[str]]:
    """EN and DE verb surface forms from a project not yet covered by their
    respective lemma table, checked independently of each other. Restricted
    to single-word entries; the lemma tables don't hold phrases.
    """
    verb_en_set = {en.lower() for en in consistent_verbs}
    verb_en_set |= {d["en"].lower() for d in inconsistent_verbs}
    verb_rows = [
        (en, de) for en, de in clean_rows
        if en.lower() in verb_en_set and " " not in en and " " not in de
    ]
    unknown_en = sorted({en.lower() for en, de in verb_rows if en.lower() not in en_lemma_table})
    unknown_de = sorted({
        de.lower() for en, de in verb_rows
        if de.lower() not in NON_VERB_DE_TERMS and _resolve_de(de, de_lemma_table) is None
    })
    return unknown_en, unknown_de


def request_verb_derivations(
    unknown_en: list[str], unknown_de: list[str], client, model: str
) -> dict[str, list[dict]]:
    """One LLM call: for each unmatched EN/DE surface form, determine its
    true infinitive and a small set of inflected forms. `client` is an
    OpenAI-compatible chat client (e.g. OpenAI(base_url=".../openrouter.ai")).
    """
    prompt = (
        DERIVATION_PROMPT_TEMPLATE
        .replace("{EN_JSON}", json.dumps(unknown_en, ensure_ascii=False, indent=2))
        .replace("{DE_JSON}", json.dumps(unknown_de, ensure_ascii=False, indent=2))
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
    return parse_json_object_lenient(resp.choices[0].message.content.strip())


def _clean_de_form(form: str) -> str | None:
    """Reduce a DE form to the single token the checker can actually match
    (\\b\\w+\\b, no phrases). Two known two-word shapes:
      - separable-prefix main-clause split ("spart ein" for einsparen) — the
        finite stem alone is enough to catch the form wherever it appears,
        so keep the first word and drop the separated prefix.
      - free zu-infinitive of a non-separable verb ("zu verblüffen") — here
        the first word is the literal particle "zu"; keeping it would
        register "zu" itself as a lemma key and misfire on every occurrence
        of that common word. Keep the second word instead.
    Anything else (more than two words) is unexpected — skip it rather than guess.
    """
    parts = form.split()
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[1] if parts[0] == "zu" else parts[0]
    return None


def merge_derivations(
    data: dict[str, list[dict]], en_lemma_table: dict[str, str], de_lemma_table: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Add any forms not already present as keys, in place. Never overwrites
    an existing key. Returns the (en_added, de_added) surface forms."""
    en_added: list[str] = []
    de_added: list[str] = []
    for item in data.get("en") or []:
        infinitive = str(item.get("infinitive", "")).strip().lower()
        if not infinitive:
            continue
        for form in item.get("forms") or [infinitive]:
            form = str(form).strip().lower()
            if form and " " not in form and form not in en_lemma_table:
                en_lemma_table[form] = infinitive
                en_added.append(form)
    for item in data.get("de") or []:
        infinitive = str(item.get("infinitive", "")).strip().lower()
        if not infinitive:
            continue
        for raw_form in item.get("forms") or [infinitive]:
            form = _clean_de_form(str(raw_form).strip().lower())
            if form and form not in de_lemma_table:
                de_lemma_table[form] = infinitive
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

    unknown_en, unknown_de = find_unknown_verbs(
        clean_rows, consistent_verbs, inconsistent_verbs, en_lemma_table, de_lemma_table
    )

    if not unknown_en and not unknown_de:
        print("\nVerb lemma tables: no new verbs found in this project's glossary.")
        return [], []

    print(f"\nVerb lemma tables: {len(unknown_en)} new EN verb(s), {len(unknown_de)} new DE verb(s) — "
          f"requesting derivations: EN[{', '.join(unknown_en)}] DE[{', '.join(unknown_de)}]")
    data = request_verb_derivations(unknown_en, unknown_de, client, model)
    if not data:
        print("  WARNING: could not parse derivation response — lemma tables left unchanged.")
        return [], []

    en_added, de_added = merge_derivations(data, en_lemma_table, de_lemma_table)
    if en_added:
        write_lemma_table(en_lemma_path, en_lemma_table)
        print(f"  EN_verb_lemma_lookup.json: added {len(en_added)} form(s) — {', '.join(sorted(en_added))}")
    if de_added:
        write_lemma_table(de_lemma_path, de_lemma_table)
        print(f"  DE_verb_lemma_lookup.json: added {len(de_added)} form(s) — {', '.join(sorted(de_added))}")
    if not en_added and not de_added:
        print("  No new lemma forms to add (all forms already present).")

    return en_added, de_added
