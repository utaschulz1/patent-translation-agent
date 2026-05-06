"""
test_linter.py — Unit tests for linter check functions.

Run with:  pytest test_linter.py -v
"""
import pytest

from linter import (
    GermanClaimNoArticle,
    missing_leading_number,
    different_end_punctuation,
    source_punctuation_where_none_in_target,
    target_punctuation_where_none_in_source,
    leading_trailing_spaces,
    negation_not_transferred,
    regular_space_before_unit,
    hyphen_in_number_range,
    in_response_to_mistranslated,
    plurality_not_transferred,
    beide_ambiguous,
    preposition_contraction,
)

NBSP = " "  # non-breaking space (Alt+0160)


# ── GermanClaimNoArticle ─────────────────────────────────────────────────────

class TestGermanClaimNoArticle:
    def fresh(self):
        return GermanClaimNoArticle()

    # self-contained claim line: "1. The device" → "1. Das Gerät"
    def test_claim_with_text_article_das(self):
        assert self.fresh()("1. The device", "1. Das Gerät") is not None

    def test_claim_with_text_article_die(self):
        assert self.fresh()("1. The method", "1. Die Methode") is not None

    def test_claim_with_text_article_der(self):
        assert self.fresh()("1. The process", "1. Der Prozess") is not None

    def test_claim_with_text_article_ein(self):
        assert self.fresh()("1. A method", "1. Ein Verfahren") is not None

    def test_claim_with_text_article_eine(self):
        assert self.fresh()("1. A device", "1. Eine Vorrichtung") is not None

    def test_claim_with_text_no_article(self):
        assert self.fresh()("1. The device", "1. Vorrichtung gemäß Anspruch") is None

    def test_claim_with_text_target_missing_number(self):
        # Translator omitted leading number — article still caught
        assert self.fresh()("1. The device", "Das Gerät") is not None

    # preceded by standalone marker: "1." then "The device" → "Das Gerät"
    def test_preceded_by_marker_article(self):
        check = self.fresh()
        check("1.", "1.")               # advance state: prev_was_marker = True
        assert check("The device", "Das Gerät") is not None

    def test_preceded_by_marker_no_article(self):
        check = self.fresh()
        check("1.", "1.")
        assert check("The device", "Vorrichtung gemäß Anspruch") is None

    def test_standalone_marker_itself_not_flagged(self):
        assert self.fresh()("1.", "1.") is None

    def test_non_claim_segment_not_flagged(self):
        assert self.fresh()("The device", "Das Gerät") is None

    def test_state_resets_after_non_marker(self):
        check = self.fresh()
        check("1.", "1.")                  # prev_was_marker = True
        check("The device", "Vorrichtung") # consumes marker state → prev_was_marker = False
        assert check("A method", "Das Verfahren") is None  # no longer a claim context

    def test_message_contains_article(self):
        result = self.fresh()("1. The device", "1. Das Gerät")
        assert '"Das"' in result

    def test_case_insensitive_article(self):
        assert self.fresh()("1. The device", "1. das Gerät") is not None

    def test_higher_claim_number(self):
        assert self.fresh()("10. The device", "10. Das Gerät") is not None


# ── missing_leading_number ────────────────────────────────────────────────────

class TestMissingLeadingNumber:
    def test_paragraph_number_present(self):
        assert missing_leading_number("[0003] The device", "[0003] Das Gerät") is None

    def test_paragraph_number_absent(self):
        assert missing_leading_number("[0003] The device", "Das Gerät") is not None

    def test_paragraph_number_message(self):
        result = missing_leading_number("[0003] The device", "Das Gerät")
        assert "[0003]" in result

    def test_sub_number_present(self):
        assert missing_leading_number("1.2 The feature", "1.2 Das Merkmal") is None

    def test_sub_number_absent(self):
        assert missing_leading_number("1.2 The feature", "Das Merkmal") is not None

    def test_list_number_present(self):
        assert missing_leading_number("2. The step", "2. Der Schritt") is None

    def test_list_number_absent(self):
        assert missing_leading_number("2. The step", "Der Schritt") is not None

    def test_list_number_not_matched_as_sub_number(self):
        # "2." should not be confused with "2.5" — target starting with "2." is fine
        assert missing_leading_number("2. The step", "2. Der Schritt") is None

    def test_no_leading_number_in_source(self):
        assert missing_leading_number("The device", "Das Gerät") is None

    def test_leading_whitespace_ignored(self):
        assert missing_leading_number("  [0003] The device", "[0003] Das Gerät") is None


# ── different_end_punctuation ─────────────────────────────────────────────────

class TestDifferentEndPunctuation:
    def test_matching_period(self):
        assert different_end_punctuation("The device.", "Das Gerät.") is None

    def test_matching_colon(self):
        assert different_end_punctuation("as follows:", "wie folgt:") is None

    def test_period_vs_colon(self):
        result = different_end_punctuation("The device.", "Das Gerät:")
        assert result is not None
        assert '"."' in result and '":"' in result

    def test_period_vs_none(self):
        result = different_end_punctuation("The device.", "Das Gerät")
        assert result is not None
        assert "(none)" in result

    def test_no_punct_in_source_skipped(self):
        assert different_end_punctuation("The device", "Das Gerät") is None

    def test_no_punct_in_source_with_punct_in_target_skipped(self):
        # different_end_punctuation only fires when SOURCE has trailing punct
        assert different_end_punctuation("The device", "Das Gerät.") is None


# ── source_punctuation_where_none_in_target ───────────────────────────────────

class TestSourcePunctuationWhereNoneInTarget:
    def test_period_in_source_missing_in_target(self):
        result = source_punctuation_where_none_in_target("The device.", "Das Gerät")
        assert result is not None
        assert '"."' in result

    def test_period_present_in_both(self):
        assert source_punctuation_where_none_in_target("The device.", "Das Gerät.") is None

    def test_no_punct_in_source(self):
        assert source_punctuation_where_none_in_target("The device", "Das Gerät") is None

    def test_colon_in_source_missing_in_target(self):
        result = source_punctuation_where_none_in_target("as follows:", "wie folgt")
        assert result is not None


# ── target_punctuation_where_none_in_source ───────────────────────────────────

class TestTargetPunctuationWhereNoneInSource:
    def test_period_added_in_target(self):
        result = target_punctuation_where_none_in_source("The device", "Das Gerät.")
        assert result is not None
        assert '"."' in result

    def test_no_punct_in_either(self):
        assert target_punctuation_where_none_in_source("The device", "Das Gerät") is None

    def test_source_also_has_punct_skipped(self):
        assert target_punctuation_where_none_in_source("The device.", "Das Gerät.") is None

    def test_trailing_space_does_not_hide_punct(self):
        result = target_punctuation_where_none_in_source("The device", "Das Gerät. ")
        assert result is not None


# ── leading_trailing_spaces ───────────────────────────────────────────────────

class TestLeadingTrailingSpaces:
    def test_leading_space(self):
        result = leading_trailing_spaces("", " Das Gerät")
        assert result is not None
        assert "leading" in result

    def test_trailing_space(self):
        result = leading_trailing_spaces("", "Das Gerät ")
        assert result is not None
        assert "trailing" in result

    def test_leading_and_trailing(self):
        result = leading_trailing_spaces("", " Das Gerät ")
        assert result is not None
        assert "leading" in result and "trailing" in result

    def test_no_spaces(self):
        assert leading_trailing_spaces("", "Das Gerät") is None

    def test_source_ignored(self):
        # source arg is unused — leading space in source must not trigger
        assert leading_trailing_spaces(" ignored source ", "Das Gerät") is None


# ── negation_not_transferred ──────────────────────────────────────────────────

class TestNegationNotTransferred:
    def test_not_with_nicht(self):
        assert negation_not_transferred("not allowed", "nicht erlaubt") is None

    def test_not_without_nicht(self):
        assert negation_not_transferred("not allowed", "erlaubt") is not None

    def test_no_with_kein(self):
        assert negation_not_transferred("no problem", "kein Problem") is None

    def test_no_with_keine_inflected(self):
        assert negation_not_transferred("no connections", "keine Verbindungen") is None

    def test_none_without_kein(self):
        assert negation_not_transferred("none found", "gefunden") is not None

    def test_two_negations_one_nicht(self):
        result = negation_not_transferred(
            "not this and not that", "nicht dies und das"
        )
        assert result is not None
        assert "2x" in result
        assert "1x" in result

    def test_two_negations_two_nicht(self):
        assert negation_not_transferred(
            "not this and not that", "nicht dies und nicht das"
        ) is None

    def test_no_negation_in_source(self):
        assert negation_not_transferred("the device", "das Gerät") is None

    def test_zero_target_message(self):
        result = negation_not_transferred("not allowed", "erlaubt")
        assert '"nicht"/"kein" not found' in result

    def test_partial_target_message(self):
        result = negation_not_transferred("not this and not that", "nicht dies und das")
        assert 'only 1x "nicht"/"kein"' in result


# ── regular_space_before_unit ─────────────────────────────────────────────────

class TestRegularSpaceBeforeUnit:
    @pytest.mark.parametrize("unit", ["MHz", "kHz", "GHz", "Hz",
                                       "°C", "°F", "K",
                                       "ms", "μs", "ns", "s", "min",
                                       "mm", "cm", "km", "m",
                                       "kg", "mg", "g",
                                       "kPa", "MPa", "Pa",
                                       "kW", "MW", "W",
                                       "mA", "A", "V", "mV",
                                       "dB", "rpm", "ppm", "%"])
    def test_regular_space_flagged(self, unit):
        assert regular_space_before_unit("", f"100 {unit}") is not None

    @pytest.mark.parametrize("unit", ["MHz", "°C", "ms", "kg", "%"])
    def test_nbsp_not_flagged(self, unit):
        assert regular_space_before_unit("", f"100{NBSP}{unit}") is None

    def test_no_space_not_flagged(self):
        assert regular_space_before_unit("", "100MHz") is None

    def test_word_not_unit_not_flagged(self):
        # digit + space + word that is not a unit
        assert regular_space_before_unit("", "3 Elemente") is None


# ── hyphen_in_number_range ────────────────────────────────────────────────────

class TestHyphenInNumberRange:
    def test_plain_hyphen_range(self):
        assert hyphen_in_number_range("", "10-20") is not None

    def test_spaced_hyphen_range(self):
        assert hyphen_in_number_range("", "10 - 20") is not None

    def test_en_dash_range_ok(self):
        assert hyphen_in_number_range("", "10–20") is None

    def test_word_hyphen_not_flagged(self):
        assert hyphen_in_number_range("", "Schritt-für-Schritt") is None

    def test_no_range(self):
        assert hyphen_in_number_range("", "Das Gerät") is None


# ── in_response_to_mistranslated ──────────────────────────────────────────────

class TestInResponseToMistranslated:
    def test_in_reaktion_flagged(self):
        result = in_response_to_mistranslated(
            "in response to the signal", "in Reaktion auf das Signal"
        )
        assert result is not None
        assert "als Reaktion auf" in result

    def test_als_reaktion_auf_ok(self):
        assert in_response_to_mistranslated(
            "in response to the signal", "als Reaktion auf das Signal"
        ) is None

    def test_in_reaktion_without_trigger_in_source_ignored(self):
        assert in_response_to_mistranslated("the device", "in Reaktion") is None

    def test_case_insensitive_source(self):
        result = in_response_to_mistranslated(
            "In Response To the signal", "in Reaktion auf das Signal"
        )
        assert result is not None


# ── plurality_not_transferred ─────────────────────────────────────────────────

class TestPluralityNotTransferred:
    def test_plurality_without_vielzahl(self):
        result = plurality_not_transferred(
            "a plurality of elements", "eine Gruppe von Elementen"
        )
        assert result is not None
        assert "Vielzahl" in result

    def test_plurality_with_vielzahl(self):
        assert plurality_not_transferred(
            "a plurality of elements", "eine Vielzahl von Elementen"
        ) is None

    def test_two_plurality_one_vielzahl(self):
        result = plurality_not_transferred(
            "a plurality of elements and a plurality of nodes",
            "eine Vielzahl von Elementen und eine Gruppe von Knoten",
        )
        assert result is not None
        assert "2x" in result
        assert "1x" in result

    def test_no_plurality_in_source(self):
        assert plurality_not_transferred("some elements", "einige Elemente") is None

    def test_pluralities_matched(self):
        assert plurality_not_transferred(
            "a plurality of A and a plurality of B",
            "eine Vielzahl von A und eine Vielzahl von B",
        ) is None


# ── beide_ambiguous ───────────────────────────────────────────────────────────

class TestBeideAmbiguous:
    @pytest.mark.parametrize("word", ["beide", "beiden", "beides", "beider", "beidem"])
    def test_forms_flagged(self, word):
        result = beide_ambiguous("", f"die {word} Elemente")
        assert result is not None
        assert word in result

    def test_no_beide(self):
        assert beide_ambiguous("", "die Elemente") is None

    def test_message_contains_hint(self):
        result = beide_ambiguous("", "beide Seiten")
        assert "zwei" in result
        assert "either" in result
        assert "both" in result


# ── preposition_contraction ───────────────────────────────────────────────────

class TestPrepositionContraction:
    @pytest.mark.parametrize("contraction,context", [
        ("im",   "im Gehäuse"),
        ("vom",  "vom Gerät"),
        ("am",   "am Ende"),
        ("beim", "beim Verbinden"),
        ("zum",  "zum Einsatz"),
        ("zur",  "zur Verfügung"),
    ])
    def test_contractions_flagged(self, contraction, context):
        result = preposition_contraction("", context)
        assert result is not None
        assert f'"{contraction}"' in result

    def test_im_wesentlichen_exception(self):
        assert preposition_contraction("", "im Wesentlichen gleich") is None

    def test_zur_verwendung_exception(self):
        assert preposition_contraction("", "zur Verwendung geeignet") is None

    def test_zum_beispiel_exception(self):
        assert preposition_contraction("", "zum Beispiel ein Gerät") is None

    def test_no_contraction(self):
        assert preposition_contraction("", "in dem Gehäuse") is None

    def test_exception_plus_real_contraction(self):
        # "im Wesentlichen" is excepted but the second "im" must still be caught
        result = preposition_contraction("", "Das ist im Wesentlichen im Gehäuse")
        assert result is not None
        assert '"im"' in result
