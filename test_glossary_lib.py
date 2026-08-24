"""
test_glossary_lib.py — Phase 0 exit-gate tests for the glossary_lib extraction
(TEST_glossary_agent.md §Phase 0).

Proves the refactor is behavior-neutral: every legacy module re-exports the
*same objects* glossary_lib defines (identity, not equality), the CSV writer
round-trips through the parser byte-faithfully, and no glossary_lib module
reaches for ambient project context (project_log / current_project.json).

Run with:  pytest test_glossary_lib.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

HERE = Path(__file__).parent

# llm_glossary_cleanup imports openai/dotenv at module import time.
# test_llm_glossary_cleanup.py owns the canonical, response-wired mocks for
# those — import it first so ITS sys.modules mocks are the ones in place
# before llm_glossary_cleanup is imported here. Installing a second,
# unconfigured mock in this file instead would win the sys.modules race when
# this file loads first (alphabetical collection order) and silently break
# that suite's mocked-LLM pipeline fixture.
import test_llm_glossary_cleanup  # noqa: F401

import glossary_lib.attestation as attestation
import glossary_lib.classify as classify
import glossary_lib.csv_io as csv_io
import glossary_lib.lemma_sync as lemma_sync
import glossary_lib.matching as matching
import glossary_lib.validate as validate

import glossary_compare_revised_translation as gcrt
import llm_glossary_cleanup as glc
import llm_glossary_revise as glr
import verb_lemma_sync as vls


# ── Import identity: legacy modules must re-export glossary_lib's objects ────

class TestImportIdentity:
    def test_cleanup_reexports(self):
        assert glc._appears_in is attestation._appears_in
        assert glc._merge_ordinal_siblings is classify._merge_ordinal_siblings
        assert glc._is_ordinal_variant is classify._is_ordinal_variant
        assert glc._strip_de_ordinal_word is classify._strip_de_ordinal_word
        assert glc._shared_de_note is classify._shared_de_note
        assert glc.SHARED_DE_ALLOWED is validate.SHARED_DE_ALLOWED
        assert glc.parse_response is validate.parse_response
        assert glc.validate_result is validate.validate_result
        assert glc._norm_en is validate._norm_en

    def test_checker_reexports(self):
        assert gcrt._count_lemmas is matching._count_lemmas
        assert gcrt._count_en_phrase is matching._count_en_phrase
        assert gcrt._count_noun_in_de is matching._count_noun_in_de
        assert gcrt._mask_de_noun_phrases is matching._mask_de_noun_phrases
        assert gcrt.build_glossary_lookups is matching.build_glossary_lookups
        assert gcrt.check_segment_glossary is matching.check_segment_glossary
        assert gcrt._DE_ADJ_SUFFIXES is matching._DE_ADJ_SUFFIXES

    def test_checker_lemma_table_globals_are_shared_objects(self):
        # The wrapper's module globals must BE matching's baseline tables —
        # a copy would silently decouple test patches and future overlay work.
        assert gcrt.en_verb_lookup is matching.en_verb_lookup
        assert gcrt.de_verb_lookup is matching.de_verb_lookup

    def test_lemma_sync_reexports(self):
        assert vls.sync_verb_lemma_tables is lemma_sync.sync_verb_lemma_tables
        assert vls.find_unknown_verbs is lemma_sync.find_unknown_verbs
        assert vls.merge_derivations is lemma_sync.merge_derivations
        assert vls._clean_de_form is lemma_sync._clean_de_form
        assert vls._resolve_de is lemma_sync._resolve_de
        assert vls.write_lemma_table is lemma_sync.write_lemma_table
        assert vls.parse_json_object_lenient is validate.parse_json_object_lenient
        assert vls.EN_LEMMA_PATH == lemma_sync.EN_LEMMA_PATH
        assert vls.DE_LEMMA_PATH == lemma_sync.DE_LEMMA_PATH

    def test_revise_reexports(self):
        assert glr.parse_clean_glossary is csv_io.parse_clean_glossary
        assert glr.clean_epo_title_row is csv_io.clean_epo_title_row
        assert glr.reassemble_glossary is csv_io.reassemble_glossary

    def test_baseline_paths_point_at_agent_dir(self):
        assert lemma_sync.EN_LEMMA_PATH == HERE / "EN_verb_lemma_lookup.json"
        assert matching.EN_BASELINE_PATH == HERE / "EN_verb_lemma_lookup.json"
        assert matching.DE_BASELINE_PATH == HERE / "DE_verb_lemma_lookup.json"


# ── No ambient context inside the library ────────────────────────────────────

class TestNoAmbientContext:
    def test_no_project_log_import_in_glossary_lib(self):
        lib_dir = HERE / "glossary_lib"
        offenders = []
        for py in lib_dir.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            if "project_log" in src or "current_project.json" in src:
                offenders.append(py.name)
        assert not offenders, f"glossary_lib must take explicit paths, found ambient context in: {offenders}"


# ── CSV writer/parser round trip ─────────────────────────────────────────────

_ROWS = [("monitor", "überwachen"), ("watch-item", "Wächterelement")]
_STANDARD = [("comprise", "umfassen")]
_EPO = ("METHOD, AND DEVICE", "VERFAHREN, UND VORRICHTUNG")


class TestCsvRoundTrip:
    def test_labeled_write_matches_legacy_format(self, tmp_path):
        """Byte-level check of the legacy (llm_glossary_cleanup) convention:
        utf-8-sig BOM, EN,DE header, labeled title row, blank line, project
        terms, blank line, standard terms."""
        out = tmp_path / "clean_glossary_TEST.csv"
        csv_io.write_clean_glossary(out, _EPO, _ROWS, _STANDARD, labeled_title=True)
        raw = out.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), "utf-8-sig BOM missing"
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        assert lines[0] == "EN,DE"
        assert lines[1].startswith('"EPO EN: METHOD')
        assert lines[2] == ""
        assert "monitor,überwachen" in lines
        assert "comprise,umfassen" in lines

    def test_labeled_write_round_trips_through_parser(self, tmp_path):
        out = tmp_path / "clean_glossary_TEST.csv"
        csv_io.write_clean_glossary(out, _EPO, _ROWS, _STANDARD, labeled_title=True)
        epo_row, main_rows, standard_rows = csv_io.parse_clean_glossary(
            out.read_text(encoding="utf-8-sig")
        )
        assert epo_row == (f"EPO EN: {_EPO[0]}", f"EPO DE: {_EPO[1]}")
        assert main_rows == _ROWS
        assert standard_rows == _STANDARD

    def test_clean_title_write_has_no_labels_and_no_commas(self, tmp_path):
        """The agent's output contract (PRD §6): title passed through
        clean_epo_title_row, written as a normal first data row."""
        out = tmp_path / "clean_glossary_TEST.csv"
        cleaned = csv_io.clean_epo_title_row(f"EPO EN: {_EPO[0]}", f"EPO DE: {_EPO[1]}")
        csv_io.write_clean_glossary(out, cleaned, _ROWS, _STANDARD, labeled_title=False)
        text = out.read_text(encoding="utf-8-sig")
        assert "EPO EN:" not in text and "EPO DE:" not in text
        lines = text.splitlines()
        assert lines[0] == "EN,DE"
        assert lines[1] == "METHOD AND DEVICE,VERFAHREN UND VORRICHTUNG"
        # cleaned title is a normal row: parser must NOT extract an epo_row
        epo_row, main_rows, standard_rows = csv_io.parse_clean_glossary(text)
        assert epo_row is None
        assert main_rows[0] == ("METHOD AND DEVICE", "VERFAHREN UND VORRICHTUNG")
        assert standard_rows == _STANDARD

    def test_no_title_still_writes_section_blank(self, tmp_path):
        # Legacy behavior: the blank separator line is written even when no
        # title row exists (see llm_glossary_cleanup's historical write block).
        out = tmp_path / "clean_glossary_TEST.csv"
        csv_io.write_clean_glossary(out, None, _ROWS, [], labeled_title=True)
        lines = out.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0] == "EN,DE"
        assert lines[1] == ""
        assert lines[2] == "monitor,überwachen"

    def test_read_epo_title(self, tmp_path):
        g = tmp_path / "glossary_TEST.csv"
        g.write_text('term,de\n"EPO EN: A TITLE","EPO DE: EIN TITEL"\n', encoding="utf-8-sig")
        assert csv_io.read_epo_title(g) == ("A TITLE", "EIN TITEL")

    def test_read_epo_title_missing_file(self, tmp_path):
        assert csv_io.read_epo_title(tmp_path / "nope.csv") == ("", "")


# ── parse_json_lenient (new shared parser, PRD §8) ───────────────────────────

class TestParseJsonLenient:
    def test_plain_array(self):
        assert validate.parse_json_lenient('[{"a": 1}]') == [{"a": 1}]

    def test_fenced_array(self):
        assert validate.parse_json_lenient('```json\n[{"a": 1}]\n```') == [{"a": 1}]

    def test_leading_prose(self):
        assert validate.parse_json_lenient('Here you go:\n[{"a": 1}]') == [{"a": 1}]

    def test_trailing_comma_repaired(self):
        # The exact glitch observed twice in review-agent production use.
        assert validate.parse_json_lenient('[{"a": 1,}]') == [{"a": 1}]
        assert validate.parse_json_lenient('{"a": [1, 2,],}', expect=dict) == {"a": [1, 2]}

    def test_truncated_raises_value_error(self):
        with pytest.raises(ValueError):
            validate.parse_json_lenient('[{"a": 1}')

    def test_wrong_container_raises(self):
        with pytest.raises(ValueError):
            validate.parse_json_lenient('{"a": 1}', expect=list)


# ── load_cleanup_inputs (the 0.8 factor) ─────────────────────────────────────

PROJ_DIR = HERE / "test_fixtures" / "RTC_2606_P1098"


@pytest.mark.skipif(not PROJ_DIR.exists(), reason="RTC_2606_P1098 fixture folder not present")
class TestLoadCleanupInputs:
    def test_loads_without_network(self):
        inputs = glc.load_cleanup_inputs(PROJ_DIR, "RTC_2606_P1098")
        assert inputs.consistent_verbs, "expected consistent verbs from the fixture"
        assert inputs.relevant_standard
        assert set(inputs.relevant_standard) <= set(inputs.standard)
        assert inputs.xlsx_found

    def test_build_input_json_shape(self):
        import json
        inputs = glc.load_cleanup_inputs(PROJ_DIR, "RTC_2606_P1098")
        data = json.loads(inputs.build_input_json())
        assert set(data) == {
            "epo_title", "standard_glossary", "consistent_terms",
            "inconsistent_verbs", "inconsistent_nouns", "inconsistent_capabilities",
        }
