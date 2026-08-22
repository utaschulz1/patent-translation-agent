"""
test_glossary_compare_revised_translation.py — Unit tests for glossary_compare_revised_translation helpers.

The module runs I/O at import time (loads glossary CSV, loads xlsx), so we inject
mocks into sys.modules and patch glob/pandas/openpyxl before the first import.

Run with:  pytest test_glossary_compare_revised_translation.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ── Isolate the module from all external I/O before importing ─────────────────

if "project_log" not in sys.modules:
    _fake_pl = MagicMock()
    _fake_pl.project_dir.return_value = Path("/fake/project")
    sys.modules["project_log"] = _fake_pl

_EMPTY_DF = pd.DataFrame({"EN": pd.Series([], dtype=str), "DE": pd.Series([], dtype=str)})


def _glob_side_effect(pattern):
    s = str(pattern)
    if "glossary" in s:
        return ["/fake/project/glossary_test.csv"]
    if "translated" in s:
        return ["/fake/project/test_translated.xlsx"]
    return []


_mock_ws = MagicMock()
_mock_ws.max_row = 3          # HEADER_ROWS rows only → no data rows processed
_mock_wb = MagicMock()
_mock_wb.active = _mock_ws

with (
    patch("glob.glob", side_effect=_glob_side_effect),
    patch("pandas.read_csv", return_value=_EMPTY_DF),
    patch("openpyxl.load_workbook", return_value=_mock_wb),
    patch("openpyxl.Workbook", return_value=MagicMock()),
):
    from glossary_compare_revised_translation import (
        _count_lemmas,
        _count_noun_in_de,
        _count_en_phrase,
    )


# ── _count_lemmas ─────────────────────────────────────────────────────────────

_EN_LOOKUP = {
    "configure":   "configure",
    "configured":  "configure",
    "configuring": "configure",
    "arrange":     "arrange",
    "arranged":    "arrange",
}

_DE_LOOKUP = {
    "anordnen":    "anordnen",
    "angeordnet":  "anordnen",
    "anordnende":  "anordnen",
    "anordnenden": "anordnen",
    "konfigurieren": "konfigurieren",
    "konfiguriert":  "konfigurieren",
}


class TestCountLemmas:
    def test_basic_match(self):
        assert _count_lemmas("configure the device", _EN_LOOKUP) == {"configure": 1}

    def test_inflected_form_mapped_to_lemma(self):
        assert _count_lemmas("configured and configuring", _EN_LOOKUP) == {"configure": 2}

    def test_case_insensitive(self):
        assert _count_lemmas("CONFIGURED device", _EN_LOOKUP) == {"configure": 1}

    def test_unknown_word_skipped(self):
        assert _count_lemmas("the device", _EN_LOOKUP) == {}

    def test_multiple_lemmas(self):
        result = _count_lemmas("configured and arranged", _EN_LOOKUP)
        assert result == {"configure": 1, "arrange": 1}

    def test_strip_de_adj_finds_partizip_adjective(self):
        # "anordnenden" is not directly in lookup but stripping "-en" → "anordnend"
        # which is also not in lookup; "anordnende" stripped → "anordnend" also not there.
        # Use a form that IS in the lookup after stripping: "anordnende" → strip "e" → "anordnend"
        # Actually "anordnenden" → strip "en" → "anordnend" → not in lookup.
        # Let's use a word that strips to a key that IS present:
        # "konfigurierte" → strip "e" → "konfiguriert" → in DE_LOOKUP → "konfigurieren"
        result = _count_lemmas("konfigurierte Elemente", _DE_LOOKUP, strip_de_adj=True)
        assert result == {"konfigurieren": 1}

    def test_strip_de_adj_off_does_not_find_inflected(self):
        result = _count_lemmas("konfigurierte Elemente", _DE_LOOKUP, strip_de_adj=False)
        assert result == {}

    def test_strip_too_short_not_attempted(self):
        # Word after stripping would be < 4 chars → suffix not stripped
        # "ange" → strip "e" → "ang" (3 chars) → below threshold, not looked up
        assert _count_lemmas("ange", _DE_LOOKUP, strip_de_adj=True) == {}


# ── _count_en_phrase ──────────────────────────────────────────────────────────

class TestCountEnPhrase:
    def test_single_occurrence(self):
        assert _count_en_phrase("illumination source", "the illumination source emits") == 1

    def test_multiple_occurrences(self):
        assert _count_en_phrase("field stop", "the field stop and the field stop") == 2

    def test_not_found(self):
        assert _count_en_phrase("field stop", "the device") == 0

    def test_case_insensitive(self):
        assert _count_en_phrase("field stop", "the Field Stop element") == 1


# ── _count_noun_in_de ─────────────────────────────────────────────────────────

class TestCountNounInDeSingleWord:
    def test_term_shorter_than_5_returns_zero(self):
        assert _count_noun_in_de("kurz", "kurzen kurze") == 0

    def test_exact_match(self):
        assert _count_noun_in_de("Feldblende", "die Feldblende ist") == 1

    def test_inflected_match_plural(self):
        # "Feldblenden" (+1 char) → within +3 → stem-matched
        assert _count_noun_in_de("Feldblende", "die Feldblenden sind") == 1

    def test_compound_word_excluded(self):
        # "Beleuchtungsquelle" is 7 chars longer than "Beleuchtung" → excluded by +3 rule
        assert _count_noun_in_de("Beleuchtung", "die Beleuchtungsquelle") == 0

    def test_compound_word_excluded_long(self):
        assert _count_noun_in_de("Beleuchtung", "das Beleuchtungsoptikteilsystem") == 0

    def test_shorter_token_not_matched(self):
        # "Probe" (5) → token "Pro" (3) is shorter → skipped
        assert _count_noun_in_de("Probe", "eine Pro-Forma") == 0

    def test_count_multiple_tokens(self):
        assert _count_noun_in_de("Probe", "die Probe und die Proben") == 2

    def test_other_de_terms_excludes_longer_match(self):
        # "Vorrichtungsabdeckung" (21) is much longer than "Vorrichtung" (11) — +10 chars,
        # already excluded by the +3 rule.  Test a case within +3: "Proben" (+1) should NOT
        # be excluded when a longer glossary DE term also starts with "Probe".
        # The token "Proben" does not stem-match "Probekörper" (10 chars, len(token)=6 < len(ol)=10).
        assert _count_noun_in_de("Probe", "die Proben", ["Probekörper"]) == 1

    def test_punctuation_stripped_from_token(self):
        assert _count_noun_in_de("Probe", "die Probe, und") == 1

    def test_hyphenated_token_preserved(self):
        # "SL-Kanal" in text should match glossary term "SL-Kanal"
        assert _count_noun_in_de("SL-Kanal", "den SL-Kanals Ende") == 1


class TestCountNounInDeCompoundHead:
    """German compounds are head-final: the last component is what the whole
    word "is". A glossary term appearing as a compound's tail (System ->
    Subsystem) is the same concept, compounded, and must match. A term
    appearing only as a *leading* modifier before a different head noun
    (Beleuchtung -> Beleuchtungsquelle, covered by TestCountNounInDeSingleWord
    above) is a different, more specific concept and must not.

    Regression case: "system,System" flagged ~84 false "missing" positives on
    a real DRAM patent (MICTCH_2608_P0124, 2026-08-20) because every
    occurrence was embedded in Speichersubsystem/Hostsystem/Rechensystem —
    all real, correctly-translated compounds the old prefix+length heuristic
    could not see since it only recognized the term at a token's start.
    """

    def test_term_as_compound_tail_no_prefix(self):
        # "Subsystem" = "sub" + "System" — term is the head noun (no linking element)
        assert _count_noun_in_de("System", "ein Subsystem") == 1

    def test_term_as_compound_tail_long_prefix(self):
        assert _count_noun_in_de("System", "das Speichersubsystem") == 1

    def test_term_as_compound_tail_plural(self):
        # Trailing inflection of the whole compound (+1 char) still counts
        assert _count_noun_in_de("System", "die Speichersubsysteme") == 1

    def test_term_as_leading_modifier_still_excluded(self):
        # System is the modifier, Steuerung ("control") is the head — must
        # NOT match, same principle as the existing Beleuchtungsquelle test.
        assert _count_noun_in_de("System", "die Systemsteuerung") == 0

    def test_multiple_compound_tail_occurrences(self):
        text = "ein Subsystem und ein weiteres Speichersubsystem"
        assert _count_noun_in_de("System", text) == 2

    def test_other_de_terms_still_excludes_longer_compound_tail_match(self):
        # If a longer glossary entry's word is itself a compound-tail match
        # for that longer term, a shorter term's tail-match on the same token
        # must defer to it, same as the existing prefix-based exclusion did.
        assert _count_noun_in_de("System", "ein Subsystem", ["Subsystem"]) == 0


class TestCountNounInDeMultiWord:
    def test_base_form_matched(self):
        assert _count_noun_in_de("interne Feldblende", "die interne Feldblende ist") == 1

    def test_first_word_inflected(self):
        # "intern Feldblende" in glossary, "interne"/"internen" in text
        assert _count_noun_in_de("intern Feldblende", "die interne Feldblende") == 1
        assert _count_noun_in_de("intern Feldblende", "der internen Feldblende") == 1

    def test_specimen_under_measurement(self):
        # "zu messende Probe" in glossary, "zu messenden Probe" in text
        assert _count_noun_in_de("zu messende Probe", "der zu messenden Probe") == 1

    def test_optische_phrase_both_forms(self):
        # "optische Röntgenbeleuchtungselemente" — base and inflected both counted
        text = "optische Röntgenbeleuchtungselemente und optischen Röntgenbeleuchtungselemente"
        assert _count_noun_in_de("optische Röntgenbeleuchtungselemente", text) == 2

    def test_multiword_not_found(self):
        assert _count_noun_in_de("interne Feldblende", "die externe Blende") == 0

    def test_multiword_count(self):
        text = "interne Feldblende und interne Feldblende"
        assert _count_noun_in_de("interne Feldblende", text) == 2

    def test_singular_not_masked_by_plural_sibling_entry(self):
        """Regression, RTC_2608_P1331 (2026-08-22): "discrete output conductor"
        (singular, "diskret Ausgangsleiter") and "discrete output conductors"
        (plural, "diskrete Ausgangsleiter") are separate glossary rows whose DE
        values stem to the *same* two words once the plural "-e" is stripped.
        The old length check (len(other) > len(de_term)) treated the
        1-char-longer plural as "a longer phrase containing this one," masking
        every occurrence and reporting 0 for the singular entry no matter how
        correct and consistent the actual text was.
        """
        text = "der diskreten Ausgangsleiter und des diskreten Ausgangsleiters"
        assert _count_noun_in_de("diskret Ausgangsleiter", text, ["diskrete Ausgangsleiter"]) == 2

    def test_genuinely_longer_phrase_still_masks_component(self):
        """The masking this guards must still work when `other` really does
        have an extra component word (3 stems vs. 2) — the case the code
        comment documents ("organisierte Punktwolke" inside "geglättete
        organisierte Punktwolke").
        """
        text = "die geglättete organisierte Punktwolke"
        assert _count_noun_in_de("organisierte Punktwolke", text, ["geglättete organisierte Punktwolke"]) == 0
