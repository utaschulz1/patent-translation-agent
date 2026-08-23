"""
test_llm_glossary_cleanup.py

Unit tests for helper functions and a pipeline integration test using real
RTC_2606_P1098 CSV files (copied into test_fixtures/, never the live
projects/ folder — see test_fixtures/RTC_2606_P1098/) with a mocked LLM
response.

Run with:  pytest test_llm_glossary_cleanup.py -v
"""
import json
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Pre-import mocks ──────────────────────────────────────────────────────────
# llm_glossary_cleanup imports `openai`/`dotenv` and calls load_dotenv() at
# module import time, so those must be faked before the import statement.
# The actual pipeline (reading CSVs, calling the LLM) only runs when
# clean_glossary() is called explicitly — see the cleanup_result fixture below.

HERE       = Path(__file__).parent
PROJ_DIR   = HERE / "test_fixtures" / "RTC_2606_P1098"
PROJECT_ID = "RTC_2606_P1098"

_mock_client     = MagicMock()
_mock_openai_mod = MagicMock()
_mock_openai_mod.OpenAI.return_value = _mock_client
sys.modules.setdefault("openai", _mock_openai_mod)

sys.modules.setdefault("dotenv", MagicMock())
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

# Response built from RTC_2606_P1098's real classification (verb/noun/capability
# CSVs in test_fixtures/RTC_2606_P1098/) — an oven-configuration patent, not a
# fabricated example. Covers all 5 consistent verbs + 2 consistent capabilities
# + 12 consistent nouns except "oven" (omitted deliberately to exercise the
# consistent-term fill-in), plus one resolved DE per inconsistent verb/noun.
# "configure" and "include" have standard_glossary entries for this project
# (konfigurieren / einschließen) — resolved to match, per the prompt's rule
# that standard_glossary overrides the observed majority.
_LLM_RESPONSE = json.dumps([
    # consistent verbs
    {"en": "alter",    "de": "verändert"},
    {"en": "identify", "de": "identifizieren"},
    {"en": "read",     "de": "lesen"},
    {"en": "set",      "de": "einstellen"},
    {"en": "store",    "de": "speichern"},
    # consistent capabilities
    {"en": "arrange",   "de": "anordnen"},
    {"en": "configure", "de": "konfigurieren"},
    # consistent nouns ("oven" omitted — fill-in step must restore it)
    {"en": "door",                      "de": "Tür"},
    {"en": "memory",                    "de": "Speicher"},
    {"en": "method",                    "de": "Verfahren"},
    {"en": "system",                    "de": "System"},
    {"en": "rfid tag",                  "de": "RFID-Tag"},
    {"en": "temperature",               "de": "Temperatur"},
    {"en": "meal carrier",              "de": "Speisenträger"},
    {"en": "menu settings",             "de": "Menüeinstellungen"},
    {"en": "temperature setting",       "de": "Temperatureinstellung"},
    {"en": "cooking/heating time",      "de": "Gar-/Erhitzungszeit"},
    {"en": "central programming unit",  "de": "zentrale Programmiereinheit"},
    # resolved inconsistent verbs
    {"en": "comprise",  "de": "umfassen"},
    {"en": "determine", "de": "bestimmen"},
    {"en": "include",   "de": "einschließen"},   # standard_glossary override
    {"en": "locate",    "de": "angeordnet"},
    {"en": "provide",   "de": "bereitgestellt"},
    {"en": "receive",   "de": "empfangen"},
    # resolved inconsistent nouns
    {"en": "meal card",    "de": "Speisekarte"},
    {"en": "rfid reader",  "de": "RFID-Lesegerät"},
    {"en": "type of meal", "de": "Art der Speise"},
])

_mock_api_resp = MagicMock()
_mock_api_resp.choices[0].message.content = _LLM_RESPONSE
_mock_client.chat.completions.create.return_value = _mock_api_resp

import llm_glossary_cleanup as glc  # noqa: E402 — must follow mock setup


@pytest.fixture(scope="module")
def cleanup_result():
    """Run the real pipeline once (LLM call mocked) and share the result
    across every TestPipeline assertion — same cost profile as the old
    run-once-at-import approach, but as an explicit call instead of an
    import side effect. Writes clean_glossary_RTC_2606_P1098.csv into
    test_fixtures/RTC_2606_P1098/ (gitignored) — never touches projects/."""
    return glc.clean_glossary(PROJ_DIR, PROJECT_ID)


# ── _appears_in ───────────────────────────────────────────────────────────────

class TestAppearsIn:
    def test_single_word_present(self):
        assert glc._appears_in("detect", "the system can detect anomalies")

    def test_single_word_absent(self):
        assert not glc._appears_in("upstream", "the system detects anomalies")

    def test_word_boundary_respected(self):
        # "detect" must not match inside "detection"
        assert not glc._appears_in("detect", "the detection process runs")

    def test_uppercase_term_lowercased_internally(self):
        # The term is lowercased inside _appears_in; the text is pre-lowercased by the caller.
        assert glc._appears_in("Detect", "the system can detect anomalies")

    def test_to_prefix_stripped(self):
        assert glc._appears_in("to detect", "the system can detect anomalies")

    def test_multiword_phrase_present(self):
        assert glc._appears_in("at least", "select at least one sensor")

    def test_multiword_phrase_absent(self):
        assert not glc._appears_in("at most", "select at least one sensor")


# ── _norm_en ──────────────────────────────────────────────────────────────────

class TestNormEn:
    def test_spaces_around_hyphen_collapsed(self):
        assert glc._norm_en("computer - implement method") == "computer-implement method"

    def test_multiple_spaced_hyphens(self):
        assert glc._norm_en("watch - item - data") == "watch-item-data"

    def test_clean_hyphen_unchanged(self):
        assert glc._norm_en("computer-implement method") == "computer-implement method"

    def test_lowercased(self):
        assert glc._norm_en("Detect") == "detect"

    def test_no_hyphen(self):
        assert glc._norm_en("Traffic Data") == "traffic data"


# ── parse_response ────────────────────────────────────────────────────────────

class TestParseResponse:
    def test_clean_json_array(self):
        raw = '[{"en": "detect", "de": "detektieren"}]'
        assert glc.parse_response(raw) == [{"en": "detect", "de": "detektieren"}]

    def test_markdown_fenced_json(self):
        raw = '```json\n[{"en": "detect", "de": "detektieren"}]\n```'
        assert glc.parse_response(raw) == [{"en": "detect", "de": "detektieren"}]

    def test_markdown_fenced_no_lang(self):
        raw = '```\n[{"en": "detect", "de": "detektieren"}]\n```'
        assert glc.parse_response(raw) == [{"en": "detect", "de": "detektieren"}]

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            glc.parse_response("not valid json {{ }")

    def test_non_list_response_raises(self):
        with pytest.raises(ValueError):
            glc.parse_response('{"en": "detect", "de": "detektieren"}')


# ── validate_result ───────────────────────────────────────────────────────────

class TestValidateResult:
    def test_clean_input_no_errors(self):
        items = [
            {"en": "detect",  "de": "detektieren"},
            {"en": "include", "de": "beinhalten"},
        ]
        rows, errors = glc.validate_result(items, {})
        assert errors == []
        assert len(rows) == 2

    def test_de_duplicate_flagged(self):
        items = [
            {"en": "area",   "de": "Gebiet"},
            {"en": "region", "de": "Gebiet"},
        ]
        _, errors = glc.validate_result(items, {})
        assert any("DE duplicate" in e for e in errors)

    def test_allowed_shared_de_not_flagged(self):
        items = [
            {"en": "have",   "de": "aufweisen"},
            {"en": "having", "de": "aufweisen"},
        ]
        _, errors = glc.validate_result(items, {})
        assert errors == []

    def test_true_duplicate_silently_dropped(self):
        items = [
            {"en": "connect", "de": "verbinden"},
            {"en": "connect", "de": "verbinden"},  # exact repeat
        ]
        rows, errors = glc.validate_result(items, {})
        assert errors == []
        assert len(rows) == 1

    def test_en_duplicate_different_de_flagged(self):
        items = [
            {"en": "connect", "de": "verbinden"},
            {"en": "connect", "de": "verknüpfen"},
        ]
        _, errors = glc.validate_result(items, {})
        assert any("EN duplicate" in e for e in errors)

    def test_standard_conflict_flagged(self):
        items = [{"en": "include", "de": "enthalten"}]
        _, errors = glc.validate_result(items, {"include": "beinhalten"})
        assert any("Standard glossary conflict" in e for e in errors)

    def test_standard_match_no_error(self):
        items = [{"en": "include", "de": "beinhalten"}]
        _, errors = glc.validate_result(items, {"include": "beinhalten"})
        assert errors == []

    def test_empty_entry_reported(self):
        items = [{"en": "", "de": ""}, {"en": "detect", "de": "detektieren"}]
        rows, errors = glc.validate_result(items, {})
        assert len(rows) == 1
        assert any("Skipped empty" in e for e in errors)


# ── _shared_de_note / prompt wiring ────────────────────────────────────────────
# Regression coverage for the FRKE_2608_P0736 (2026-08-22) bug: SHARED_DE_ALLOWED
# was only ever consulted post-hoc in validate_result(), never communicated to
# the LLM, so it invented "have" → "besitzen" to dodge a DE-duplicate collision
# validate_result would have accepted anyway. These tests pin the fix: the
# prompt actually sent to the LLM must name every sanctioned pair.

class TestSharedDeNote:
    def test_note_lists_every_allowed_pair(self):
        note = glc._shared_de_note()
        for pair in glc.SHARED_DE_ALLOWED:
            assert all(term in note for term in pair)

    def test_note_nonempty_when_pairs_exist(self):
        assert glc.SHARED_DE_ALLOWED  # would silently pass the next test if empty
        assert glc._shared_de_note().strip() != ""

    def test_placeholder_resolved_in_rendered_prompt(self):
        rendered = glc.USER_PROMPT_TEMPLATE.replace("{INPUT_JSON}", "<json>")
        rendered = rendered.replace("{SHARED_DE_NOTE}", glc._shared_de_note())
        assert "{SHARED_DE_NOTE}" not in rendered
        assert "have" in rendered and "having" in rendered
        assert "comprise" in rendered and "comprising" in rendered


# ── _is_ordinal_variant ───────────────────────────────────────────────────────

class TestIsOrdinalVariant:
    KNOWN = {"noise component", "traffic forecast", "geographical region",
             "seasonal forecast", "seasonal traffic forecast"}

    def test_filtered_when_base_present(self):
        assert glc._is_ordinal_variant("first noise component", self.KNOWN)

    def test_kept_when_base_absent(self):
        # "time period" not in KNOWN → "first time period" must survive
        assert not glc._is_ordinal_variant("first time period", self.KNOWN)

    def test_other_modifier_filtered(self):
        assert glc._is_ordinal_variant("other geographical region", self.KNOWN)

    def test_additional_modifier_filtered(self):
        known = self.KNOWN | {"time period"}
        assert glc._is_ordinal_variant("additional time period", known)

    def test_no_modifier_not_filtered(self):
        assert not glc._is_ordinal_variant("noise component", self.KNOWN)

    def test_target_not_a_modifier(self):
        # "target" is not in ORDINAL_MODIFIERS
        assert not glc._is_ordinal_variant("target geographical region", self.KNOWN)

    def test_second_variant_filtered(self):
        assert glc._is_ordinal_variant("second traffic forecast", self.KNOWN)

    def test_single_word_not_filtered(self):
        assert not glc._is_ordinal_variant("first", self.KNOWN)


# ── _strip_de_ordinal_word ──────────────────────────────────────────────────

class TestStripDeOrdinalWord:
    def test_bare_stem(self):
        assert glc._strip_de_ordinal_word("erst Bilddaten", "first") == "Bilddaten"

    def test_declined_stem(self):
        assert glc._strip_de_ordinal_word("ersten Bilddaten", "first") == "Bilddaten"
        assert glc._strip_de_ordinal_word("zweiten Bilddaten", "second") == "Bilddaten"

    def test_multi_word_remainder_preserved(self):
        assert glc._strip_de_ordinal_word("erste Ausgangsbilddaten", "first") == "Ausgangsbilddaten"

    def test_modifier_with_multiple_de_stems(self):
        assert glc._strip_de_ordinal_word("zusätzliche Daten", "additional") == "Daten"
        assert glc._strip_de_ordinal_word("weitere Daten", "additional") == "Daten"

    def test_unexpected_leading_word_returns_none(self):
        # DE doesn't actually lead with a translation of "first" at all
        assert glc._strip_de_ordinal_word("initiale Bilddaten", "first") is None

    def test_single_word_de_value_returns_none(self):
        assert glc._strip_de_ordinal_word("Bilddaten", "first") is None

    def test_unknown_modifier_returns_none(self):
        assert glc._strip_de_ordinal_word("dritte Bilddaten", "unknown") is None


# ── _merge_ordinal_siblings ──────────────────────────────────────────────────

class TestMergeOrdinalSiblings:
    def test_agreeing_siblings_merged(self):
        """Regression, HALA_2608_P0655 (2026-08-23): "image data" never
        occurs unmodified in the source, so _is_ordinal_variant's own
        base-must-be-independently-attested guard never fires and
        "first image data"/"second image data" survive as fully separate
        entries. Comparing the siblings to each other instead of requiring
        a third, bare occurrence catches this.
        """
        noun_can = {
            "first image data":  {"ersten Bilddaten": {"count": 3, "total": 4, "canonical": True}},
            "second image data": {"zweiten Bilddaten": {"count": 3, "total": 3, "canonical": True}},
        }
        merged, consumed = glc._merge_ordinal_siblings(noun_can)
        assert merged == {"image data": "Bilddaten"}
        assert consumed == {"first image data", "second image data"}

    def test_disagreeing_siblings_not_merged(self):
        # Ordinal genuinely changes the correct DE translation — must not merge.
        noun_can = {
            "first electrode":  {"erste Elektrode": {"count": 5, "total": 5, "canonical": True}},
            "second electrode": {"Gegenelektrode":  {"count": 5, "total": 5, "canonical": True}},
        }
        merged, consumed = glc._merge_ordinal_siblings(noun_can)
        assert merged == {}
        assert consumed == set()

    def test_single_sibling_not_merged(self):
        noun_can = {
            "first image data": {"ersten Bilddaten": {"count": 3, "total": 3, "canonical": True}},
        }
        merged, consumed = glc._merge_ordinal_siblings(noun_can)
        assert merged == {}
        assert consumed == set()

    def test_unexpected_de_form_bails_out_safely(self):
        # One sibling's canonical DE doesn't actually lead with a
        # translation of its own modifier — bail rather than guess.
        noun_can = {
            "first image data":  {"vorherige Bilddaten": {"count": 3, "total": 3, "canonical": True}},
            "second image data": {"zweiten Bilddaten":   {"count": 3, "total": 3, "canonical": True}},
        }
        merged, consumed = glc._merge_ordinal_siblings(noun_can)
        assert merged == {}
        assert consumed == set()

    def test_three_way_group_all_agree(self):
        noun_can = {
            "first image data":  {"ersten Bilddaten":  {"count": 2, "total": 2, "canonical": True}},
            "second image data": {"zweiten Bilddaten": {"count": 2, "total": 2, "canonical": True}},
            "third image data":  {"dritten Bilddaten": {"count": 2, "total": 2, "canonical": True}},
        }
        merged, consumed = glc._merge_ordinal_siblings(noun_can)
        assert merged == {"image data": "Bilddaten"}
        assert consumed == {"first image data", "second image data", "third image data"}

    def test_uses_canonical_majority_de_when_sibling_itself_inconsistent(self):
        # "first image data" has a minority deviant DE too — the majority
        # (higher count) must be what gets compared/stripped, not any form.
        noun_can = {
            "first image data": {
                "ersten Bilddaten": {"count": 3, "total": 4, "canonical": True},
                "erster Bilddaten": {"count": 1, "total": 4, "canonical": False},
            },
            "second image data": {"zweiten Bilddaten": {"count": 3, "total": 3, "canonical": True}},
        }
        merged, consumed = glc._merge_ordinal_siblings(noun_can)
        assert merged == {"image data": "Bilddaten"}


# ── Integration: full pipeline via clean_glossary() ────────────────────────────

class TestPipeline:
    def test_oven_restored_by_fill_in(self, cleanup_result):
        """'oven' was omitted from the mock LLM response; fill-in must add it."""
        filled_en = {en.lower() for en, _ in cleanup_result.filled}
        assert "oven" in filled_en

    def test_no_en_duplicates_in_output(self, cleanup_result):
        en_list = [en.lower() for en, _ in cleanup_result.clean_rows]
        assert len(en_list) == len(set(en_list)), "Duplicate EN terms in clean_rows"

    def test_no_de_duplicates_in_output(self, cleanup_result):
        de_list = [de.lower() for _, de in cleanup_result.clean_rows
                   if de.lower() != "aufweisen"]   # allowed shared DE excluded
        assert len(de_list) == len(set(de_list)), "Duplicate DE terms in clean_rows"

    def test_extra_standard_does_not_overlap_clean_rows(self, cleanup_result):
        clean_en = {en.lower() for en, _ in cleanup_result.clean_rows}
        for en, _ in cleanup_result.extra_standard:
            assert en.lower() not in clean_en

    # Note: the "have"/"having" shared-DE case and ordinal-modifier noun
    # filtering (first/second/other/additional ...) don't occur in this
    # project's real data, so they aren't re-tested at the pipeline level
    # here — both are already covered directly against validate_result and
    # _is_ordinal_variant in TestValidateResult/TestIsOrdinalVariant above.

    def test_llm_received_only_relevant_standard(self, cleanup_result):
        """LLM input must be a strict subset of the full standard glossary."""
        data = json.loads(cleanup_result.input_json_str)
        llm_en = {item["en"] for item in data["standard_glossary"]}
        assert llm_en <= set(cleanup_result.standard.keys())
        assert len(llm_en) < len(cleanup_result.standard)

    def test_output_csv_written(self, cleanup_result):
        assert cleanup_result.path.exists()

    def test_output_csv_has_header(self, cleanup_result):
        import csv
        with open(cleanup_result.path, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        assert header == ["EN", "DE"]
