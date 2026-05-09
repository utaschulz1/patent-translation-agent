"""
test_llm_glossary_cleanup.py

Unit tests for helper functions and a pipeline integration test using the real
HALA_2605_P0418 CSV files with a mocked LLM response.

Run with:  pytest test_llm_glossary_cleanup.py -v
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Pre-import mocks ──────────────────────────────────────────────────────────
# The module runs top-level code (reads CSVs, calls the LLM API) on import.
# All external dependencies must be patched before the import statement.

HERE     = Path(__file__).parent
PROJ_DIR = HERE / "projects" / "HALA_2605_P0418"

_mock_project_log = MagicMock()
_mock_project_log.project_dir.return_value = PROJ_DIR
sys.modules.setdefault("project_log", _mock_project_log)

_mock_client     = MagicMock()
_mock_openai_mod = MagicMock()
_mock_openai_mod.OpenAI.return_value = _mock_client
sys.modules.setdefault("openai", _mock_openai_mod)

sys.modules.setdefault("dotenv", MagicMock())
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

# Minimal valid LLM response built from the known-good DeepSeek V3 output.
# "analyze" is deliberately omitted to exercise the consistent-term fill-in.
_LLM_RESPONSE = json.dumps([
    {"en": "adjust",      "de": "anpassen"},
    # "analyze" omitted — fill-in step must restore it
    {"en": "carry",       "de": "ausführen"},
    {"en": "cluster",     "de": "Cluster"},
    {"en": "compare",     "de": "vergleichen"},
    {"en": "comprise",    "de": "umfassen"},
    {"en": "comprising",  "de": "umfassend"},
    {"en": "compute",     "de": "berechnen"},
    {"en": "connect",     "de": "verbinden"},
    {"en": "decompose",   "de": "zerlegen"},
    {"en": "define",      "de": "definieren"},
    {"en": "detect",      "de": "detektieren"},
    {"en": "determine",   "de": "bestimmen"},
    {"en": "estimate",    "de": "schätzen"},
    {"en": "generate",    "de": "erzeugen"},
    {"en": "have",        "de": "aufweisen"},
    {"en": "having",      "de": "aufweisen"},
    {"en": "include",     "de": "beinhalten"},
    {"en": "indicate",    "de": "angeben"},
    {"en": "at least",    "de": "mindestens"},
    {"en": "obtain",      "de": "erhalten"},
    {"en": "occur",       "de": "auftreten"},
    {"en": "perform",     "de": "durchführen"},
    {"en": "predict",     "de": "prognostizieren"},
    {"en": "select",      "de": "auswählen"},
    {"en": "use",         "de": "verwenden"},
    {"en": "anomaly",                  "de": "Anomalie"},
    {"en": "anomaly threshold",        "de": "Anomalieschwelle"},
    {"en": "average emission",         "de": "durchschnittliche Emission"},
    {"en": "average speed",            "de": "Durchschnittsgeschwindigkeit"},
    {"en": "correlation",              "de": "Korrelation"},
    {"en": "deviation",                "de": "Abweichung"},
    {"en": "emission",                 "de": "Emission"},
    {"en": "emission amount",          "de": "Emissionsmenge"},
    # ordinal variants filtered when base exists: first/second noise component,
    # first/second traffic forecast, other geographical region, other seasonal *
    {"en": "first seasonal component", "de": "erste Saisonkomponente"},   # kept: base absent
    {"en": "first time period",        "de": "erster Zeitraum"},          # kept: base absent
    {"en": "geographical area",        "de": "geografischer Bereich"},
    {"en": "geographical region",      "de": "geografisches Gebiet"},
    {"en": "mobility flow",            "de": "Mobilitätsfluss"},
    {"en": "noise component",          "de": "Rauschkomponente"},
    {"en": "number of vehicle",        "de": "Anzahl von Fahrzeugen"},
    {"en": "plurality of vehicle",     "de": "Vielzahl von Fahrzeugen"},
    {"en": "region",                   "de": "Region"},
    {"en": "regressor",                "de": "Regressor"},
    {"en": "representative set of traffic data", "de": "repräsentativer Satz von Verkehrsdaten"},
    {"en": "seasonal aspect",          "de": "saisonaler Aspekt"},
    {"en": "seasonal forecast",        "de": "saisonale Prognose"},
    {"en": "seasonal traffic forecast","de": "saisonale Verkehrsprognose"},
    {"en": "second seasonal component","de": "zweite Saisonkomponente"},  # kept: base absent
    {"en": "second time period",       "de": "zweiter Zeitraum"},         # kept: base absent
    {"en": "sensor",                   "de": "Sensor"},
    {"en": "set of traffic data",      "de": "Verkehrsdatenmenge"},
    {"en": "speed",                    "de": "Geschwindigkeit"},
    {"en": "target geographical region","de": "geografisches Zielgebiet"},
    {"en": "target region",            "de": "Zielgebiet"},
    {"en": "traffic",                  "de": "Verkehr"},
    {"en": "traffic data",             "de": "Verkehrsdaten"},
    {"en": "traffic forecast",         "de": "Verkehrsprognose"},
    {"en": "traffic forecasting process","de": "Verkehrsprognosevorgang"},
    {"en": "trend component",          "de": "Trendkomponente"},
    {"en": "vehicle",                  "de": "Fahrzeug"},
    {"en": "additional time period",   "de": "weiterer Zeitraum"},
    {"en": "impact",                   "de": "Auswirkung"},
    {"en": "computer-implement method","de": "computerimplementiertes Verfahren"},
    {"en": "number of each of a plurality of type of vehicle",
     "de": "Anzahl jedes Fahrzeugtyps aus einer Vielzahl von Fahrzeugtypen"},
])

_mock_api_resp = MagicMock()
_mock_api_resp.choices[0].message.content = _LLM_RESPONSE
_mock_client.chat.completions.create.return_value = _mock_api_resp

import llm_glossary_cleanup as glc  # noqa: E402 — must follow mock setup


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

    def test_invalid_json_exits(self):
        with pytest.raises(SystemExit):
            glc.parse_response("not valid json {{ }")

    def test_non_list_response_exits(self):
        with pytest.raises(SystemExit):
            glc.parse_response('{"en": "detect", "de": "detektieren"}')


# ── validate_result ───────────────────────────────────────────────────────────

class TestValidateResult:
    def test_clean_input_no_errors(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {})
        items = [
            {"en": "detect",  "de": "detektieren"},
            {"en": "include", "de": "beinhalten"},
        ]
        rows, errors = glc.validate_result(items)
        assert errors == []
        assert len(rows) == 2

    def test_de_duplicate_flagged(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {})
        items = [
            {"en": "area",   "de": "Gebiet"},
            {"en": "region", "de": "Gebiet"},
        ]
        _, errors = glc.validate_result(items)
        assert any("DE duplicate" in e for e in errors)

    def test_allowed_shared_de_not_flagged(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {})
        items = [
            {"en": "have",   "de": "aufweisen"},
            {"en": "having", "de": "aufweisen"},
        ]
        _, errors = glc.validate_result(items)
        assert errors == []

    def test_true_duplicate_silently_dropped(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {})
        items = [
            {"en": "connect", "de": "verbinden"},
            {"en": "connect", "de": "verbinden"},  # exact repeat
        ]
        rows, errors = glc.validate_result(items)
        assert errors == []
        assert len(rows) == 1

    def test_en_duplicate_different_de_flagged(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {})
        items = [
            {"en": "connect", "de": "verbinden"},
            {"en": "connect", "de": "verknüpfen"},
        ]
        _, errors = glc.validate_result(items)
        assert any("EN duplicate" in e for e in errors)

    def test_standard_conflict_flagged(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {"include": "beinhalten"})
        items = [{"en": "include", "de": "enthalten"}]
        _, errors = glc.validate_result(items)
        assert any("Standard glossary conflict" in e for e in errors)

    def test_standard_match_no_error(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {"include": "beinhalten"})
        items = [{"en": "include", "de": "beinhalten"}]
        _, errors = glc.validate_result(items)
        assert errors == []

    def test_empty_entry_reported(self, monkeypatch):
        monkeypatch.setattr(glc, "relevant_standard", {})
        items = [{"en": "", "de": ""}, {"en": "detect", "de": "detektieren"}]
        rows, errors = glc.validate_result(items)
        assert len(rows) == 1
        assert any("Skipped empty" in e for e in errors)


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


# ── Integration: pipeline state after module execution ────────────────────────

class TestPipeline:
    def test_analyze_restored_by_fill_in(self):
        """'analyze' was omitted from the mock LLM response; fill-in must add it."""
        filled_en = {en.lower() for en, _ in glc.filled}
        assert "analyze" in filled_en

    def test_no_en_duplicates_in_output(self):
        en_list = [en.lower() for en, _ in glc.clean_rows]
        assert len(en_list) == len(set(en_list)), "Duplicate EN terms in clean_rows"

    def test_no_de_duplicates_in_output(self):
        de_list = [de.lower() for _, de in glc.clean_rows
                   if de.lower() != "aufweisen"]   # allowed shared DE excluded
        assert len(de_list) == len(set(de_list)), "Duplicate DE terms in clean_rows"

    def test_extra_standard_does_not_overlap_clean_rows(self):
        clean_en = {en.lower() for en, _ in glc.clean_rows}
        for en, _ in glc.extra_standard:
            assert en.lower() not in clean_en

    def test_have_having_both_map_to_aufweisen(self):
        output = {en.lower(): de for en, de in glc.clean_rows}
        assert output.get("have")   == "aufweisen"
        assert output.get("having") == "aufweisen"

    def test_llm_received_only_relevant_standard(self):
        """LLM input must be a strict subset of the full standard glossary."""
        data = json.loads(glc.input_json_str)
        llm_en = {item["en"] for item in data["standard_glossary"]}
        assert llm_en <= set(glc.standard.keys())
        assert len(llm_en) < len(glc.standard)

    def test_output_csv_written(self):
        assert glc.clean_glossary_path.exists()

    def test_output_csv_has_header(self):
        import csv
        with open(glc.clean_glossary_path, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        assert header == ["EN", "DE"]

    def test_ordinal_variants_with_base_not_in_consistent_nouns(self):
        # These have bases in noun_can → must be filtered before LLM input.
        filtered = {"other geographical region", "other seasonal forecast",
                    "other seasonal traffic forecast",
                    "first noise component", "second noise component",
                    "first traffic forecast", "second traffic forecast"}
        assert filtered.isdisjoint(glc.consistent_nouns)
        assert all(
            e["en"] not in filtered for e in glc.inconsistent_nouns
        )

    def test_ordinal_variants_without_base_survive(self):
        # "time period" not in noun_can → first/second/additional time period kept.
        all_nouns = set(glc.consistent_nouns) | {e["en"] for e in glc.inconsistent_nouns}
        assert "first time period"  in all_nouns
        assert "second time period" in all_nouns
