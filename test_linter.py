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
    betraegt_stative,
    same_selbe,
    same_gleich_missing,
    comprise_umfassen,
    vielzahl_plurality,
    folgendes_umfasst,
    folgendes_konfiguriert,
    dazu_konfiguriert,
    abbreviation_not_in_source,
    jeweilig_not_respective,
    german_quotation_marks,
    patent_number_decimal,
    acronym_in_compound,
    hyphen_in_long_compound,
    durch_verwendung,
    unter_verwendung,
    schritt_zum,
    mindestens_at_least,
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


# ── betraegt_stative ──────────────────────────────────────────────────────────

class TestBetraegt:
    @pytest.mark.parametrize("word", ["beträgt", "Beträgt", "BETRÄGT", "betragen", "Betragen"])
    def test_forms_flagged(self, word):
        result = betraegt_stative("", f"der Wert {word} 5 mm")
        assert result is not None
        assert word.lower() in result.lower()

    def test_message_contains_hint(self):
        result = betraegt_stative("", "die Länge beträgt 10 mm")
        assert "beträgt = ist" in result

    def test_no_match(self):
        assert betraegt_stative("", "die Länge ist 10 mm") is None

    def test_source_ignored(self):
        assert betraegt_stative("the length amounts to 10 mm", "die Länge ist 10 mm") is None


# ── same_selbe ────────────────────────────────────────────────────────────────

class TestSameSelbe:
    @pytest.mark.parametrize("selbe_word", [
        "dieselbe", "dieselben",
        "derselbe", "derselben",
        "dasselbe",
        "demselben", "denselben", "desselben",
    ])
    def test_selbe_forms_flagged(self, selbe_word):
        result = same_selbe("a same polarization", f"{selbe_word} Polarisation")
        assert result is not None
        assert selbe_word in result

    def test_real_world_example(self):
        result = same_selbe(
            "the first light stream and the second light stream have a same polarization",
            "der erste Lichtstrom und der zweite Lichtstrom dieselbe Polarisation aufweisen",
        )
        assert result is not None
        assert "gleiche" in result
        assert "article" in result

    def test_the_same_triggers(self):
        assert same_selbe("the same method", "dasselbe Verfahren") is not None

    def test_bare_same_triggers(self):
        assert same_selbe("same direction", "dieselbe Richtung") is not None

    def test_case_insensitive_source(self):
        assert same_selbe("A Same polarization", "dieselbe Polarisation") is not None

    def test_case_insensitive_target(self):
        assert same_selbe("a same polarization", "Dieselbe Polarisation") is not None

    def test_correct_translation_not_flagged(self):
        assert same_selbe(
            "the first and second streams have a same polarization",
            "der erste und zweite Strom eine gleiche Polarisation aufweisen",
        ) is None

    def test_no_same_in_source_not_flagged(self):
        # "dieselbe" in target but no "same" in source → no flag
        assert same_selbe("the polarization", "dieselbe Polarisation") is None

    def test_message_contains_hint(self):
        result = same_selbe("a same polarization", "dieselbe Polarisation")
        assert result is not None
        assert "gleiche" in result
        assert "article" in result

    def test_no_same_in_source_selbe_not_flagged(self):
        # "dieselbe" in target without "same" in source → no flag (by design)
        assert same_selbe("the polarization", "dieselbe Polarisation") is None


# ── same_gleich_missing ───────────────────────────────────────────────────────

class TestSameGleichMissing:
    def test_same_in_source_gleich_missing(self):
        result = same_gleich_missing(
            "the first and second streams have a same polarization",
            "der erste und zweite Strom dieselbe Polarisation aufweisen",
        )
        assert result is not None
        assert '"gleich"' in result

    def test_same_in_source_gleich_present(self):
        assert same_gleich_missing(
            "the first and second streams have a same polarization",
            "der erste und zweite Strom eine gleiche Polarisation aufweisen",
        ) is None

    def test_gleich_inflected_forms_accepted(self):
        for form in ("gleiche", "gleichen", "gleichem", "gleicher", "gleiches"):
            assert same_gleich_missing("a same value", f"einen {form} Wert") is None

    def test_no_same_in_source_not_flagged(self):
        assert same_gleich_missing("the value", "einen gleichen Wert") is None

    def test_case_insensitive_source(self):
        assert same_gleich_missing("A Same value", "einen anderen Wert") is not None

    def test_both_checks_fire_for_selbe_translation(self):
        # "same → dieselbe" triggers same_selbe (wrong word) AND same_gleich_missing
        src = "a same polarization"
        tgt = "dieselbe Polarisation"
        assert same_selbe(src, tgt) is not None
        assert same_gleich_missing(src, tgt) is not None


# ── comprise_umfassen ─────────────────────────────────────────────────────────

class TestCompriseUmfassen:
    @pytest.mark.parametrize("tgt_word", ["umfasst", "umfassen", "umfassend", "umfasse"])
    def test_target_forms_trigger(self, tgt_word):
        # umfass* in target but no compris* in source → flag
        result = comprise_umfassen("eine Vorrichtung", f"eine Vorrichtung, die einen Sensor {tgt_word}")
        assert result is not None
        assert '"compris*" not found' in result

    def test_counts_match(self):
        assert comprise_umfassen(
            "a device comprising a sensor and comprising a lens",
            "eine Vorrichtung, die einen Sensor umfasst und eine Linse umfasst",
        ) is None

    def test_no_umfassen_in_target_no_flag(self):
        # compris* in source but no umfass* in target → no flag (target is the trigger)
        assert comprise_umfassen("a device comprising a sensor", "eine Vorrichtung mit einem Sensor") is None

    def test_umfassen_without_comprise_in_source(self):
        result = comprise_umfassen("a device with a sensor", "eine Vorrichtung, die einen Sensor umfasst")
        assert result is not None
        assert '"compris*" not found' in result

    def test_count_mismatch(self):
        result = comprise_umfassen(
            "a device comprising a sensor",
            "eine Vorrichtung, die einen Sensor umfasst und eine Linse umfasst",
        )
        assert result is not None
        assert "2x" in result
        assert 'only 1x "compris*"' in result

    def test_no_umfassen_no_comprise(self):
        assert comprise_umfassen("a device with a sensor", "eine Vorrichtung mit einem Sensor") is None

    def test_case_insensitive(self):
        assert comprise_umfassen("A Device Comprising A Sensor", "eine Vorrichtung, die einen Sensor UMFASST") is None


# ── vielzahl_plurality ────────────────────────────────────────────────────────

class TestVielzahlPlurality:
    def test_vielzahl_without_plurality_flagged(self):
        result = vielzahl_plurality("a set of elements", "eine Vielzahl von Elementen")
        assert result is not None
        assert '"plurality" not found' in result

    def test_counts_match(self):
        assert vielzahl_plurality(
            "a plurality of elements", "eine Vielzahl von Elementen"
        ) is None

    def test_no_vielzahl_no_flag(self):
        # plurality in source but no Vielzahl in target → no flag (target is the trigger)
        assert vielzahl_plurality("a plurality of elements", "eine Gruppe von Elementen") is None

    def test_count_mismatch(self):
        result = vielzahl_plurality(
            "a plurality of elements",
            "eine Vielzahl von Elementen und eine Vielzahl von Knoten",
        )
        assert result is not None
        assert "2x" in result
        assert 'only 1x "plurality"' in result

    def test_no_vielzahl_no_plurality(self):
        assert vielzahl_plurality("a set of elements", "eine Gruppe von Elementen") is None

    def test_case_insensitive(self):
        assert vielzahl_plurality("a plurality of elements", "eine VIELZAHL von Elementen") is None


# ── folgendes_umfasst ─────────────────────────────────────────────────────────

class TestFolgendesUmfasst:
    def test_bare_colon_flagged(self):
        result = folgendes_umfasst("", "wobei die Steuerschaltung (22) umfasst:")
        assert result is not None
        assert "Folgendes umfasst" in result

    def test_folgendes_umfasst_ok(self):
        assert folgendes_umfasst("", "wobei die Steuerschaltung (22) Folgendes umfasst:") is None

    def test_umfassend_not_flagged(self):
        # participial form (no colon) should not fire
        assert folgendes_umfasst("", "eine Vorrichtung umfassend einen Sensor") is None

    def test_no_colon_not_flagged(self):
        assert folgendes_umfasst("", "die Steuerschaltung umfasst einen Sensor") is None

    def test_case_insensitive(self):
        assert folgendes_umfasst("", "wobei die Schaltung UMFASST:") is not None

    def test_participial_umfassend_colon_not_flagged(self):
        # "comprising:" → "umfassend:" is the correct participial form — no "Folgendes" needed
        assert folgendes_umfasst("", "das RMM-System umfassend:") is None

    def test_ferner_umfassend_colon_not_flagged(self):
        assert folgendes_umfasst("", "Schritt c) ferner umfassend:") is None


# ── folgendes_konfiguriert ────────────────────────────────────────────────────

class TestFolgendesKonfiguriert:
    def test_bare_colon_flagged(self):
        result = folgendes_konfiguriert("", "die Steuerschaltung (540) dazu konfiguriert ist:")
        assert result is not None
        assert "zu Folgendem" in result

    def test_folgendem_ok(self):
        assert folgendes_konfiguriert(
            "", "die Steuerschaltung (540) zu Folgendem konfiguriert ist:"
        ) is None

    def test_konfiguriert_um_not_flagged(self):
        # "konfiguriert ist, um" — no colon immediately after "ist"
        assert folgendes_konfiguriert("", "konfiguriert ist, um einen Sensor zu steuern") is None

    def test_case_insensitive(self):
        assert folgendes_konfiguriert("", "KONFIGURIERT IST:") is not None


# ── dazu_konfiguriert ─────────────────────────────────────────────────────────

class TestDazuKonfiguriert:
    def test_konfiguriert_without_dazu_flagged(self):
        result = dazu_konfiguriert("", "die Schaltung ist konfiguriert, den Sensor zu steuern")
        assert result is not None
        assert "dazu" in result

    def test_dazu_konfiguriert_ok(self):
        assert dazu_konfiguriert("", "die Schaltung ist dazu konfiguriert, den Sensor zu steuern") is None

    def test_multiple_konfiguriert_all_with_dazu_ok(self):
        assert dazu_konfiguriert("", "A ist dazu konfiguriert und B ist dazu konfiguriert") is None

    def test_mixed_one_missing_dazu_flagged(self):
        result = dazu_konfiguriert("", "A ist dazu konfiguriert und B ist konfiguriert")
        assert result is not None

    def test_no_konfiguriert_not_flagged(self):
        assert dazu_konfiguriert("", "die Schaltung steuert den Sensor") is None

    def test_konfiguriert_ist_comma_not_flagged(self):
        # relative clause: "…der konfiguriert ist, ein Kühlfluid zu führen" — valid, no "dazu" needed
        assert dazu_konfiguriert("", "einen Kühlkanal (60), der konfiguriert ist, ein Kühlfluid zu führen") is None


# ── abbreviation_not_in_source ────────────────────────────────────────────────

class TestAbbreviationNotInSource:
    def test_d_h_without_ie_flagged(self):
        result = abbreviation_not_in_source("that is, the device", "d. h. die Vorrichtung")
        assert result is not None
        assert "d. h." in result

    def test_d_h_with_ie_ok(self):
        assert abbreviation_not_in_source("i.e. the device", "d. h. die Vorrichtung") is None

    def test_z_b_without_eg_flagged(self):
        result = abbreviation_not_in_source("for example a sensor", "z. B. ein Sensor")
        assert result is not None
        assert "z. B." in result

    def test_z_b_with_eg_ok(self):
        assert abbreviation_not_in_source("e.g. a sensor", "z. B. ein Sensor") is None

    def test_bzw_without_resp_flagged(self):
        result = abbreviation_not_in_source("the first and second", "der erste bzw. zweite")
        assert result is not None
        assert "bzw." in result

    def test_bzw_with_respectively_ok(self):
        assert abbreviation_not_in_source(
            "the first and second, respectively", "der erste bzw. zweite"
        ) is None

    def test_no_abbreviation_not_flagged(self):
        assert abbreviation_not_in_source("that is the device", "das heißt die Vorrichtung") is None


# ── jeweilig_not_respective ───────────────────────────────────────────────────

class TestJeweiligNotRespective:
    @pytest.mark.parametrize("word", ["jeweilige", "jeweiligen", "jeweiliger", "jeweiliges"])
    def test_forms_flagged_without_respective(self, word):
        result = jeweilig_not_respective("each of the CDAC units", f"jeder der {word} Einheiten")
        assert result is not None
        assert word in result

    def test_respective_in_source_ok(self):
        assert jeweilig_not_respective(
            "the respective CDAC units", "die jeweiligen Einheiten"
        ) is None

    def test_no_jeweilig_not_flagged(self):
        assert jeweilig_not_respective("each of the units", "jede der Einheiten") is None

    def test_respectively_in_source_ok(self):
        assert jeweilig_not_respective(
            "the first and second, respectively", "die jeweilige erste und zweite"
        ) is None


# ── german_quotation_marks ────────────────────────────────────────────────────

class TestGermanQuotationMarks:
    def test_straight_quotes_flagged(self):
        result = german_quotation_marks("", 'bezogen auf "m" Atome')
        assert result is not None
        assert "„" in result

    def test_german_quotes_ok(self):
        assert german_quotation_marks("", "bezogen auf „m“ Atome") is None

    def test_no_quotes_not_flagged(self):
        assert german_quotation_marks("", "eine Vorrichtung zum Messen") is None

    def test_single_quote_not_flagged(self):
        # unpaired single straight quote should not fire (regex requires a closing quote)
        assert german_quotation_marks("", 'ein "Sensor') is None


# ── patent_number_decimal ─────────────────────────────────────────────────────

class TestPatentNumberDecimal:
    def test_comma_in_de_flagged(self):
        result = patent_number_decimal(
            "Patent Application No. 201711138495.4",
            "Patentanmeldung Nr. 201711138495,4",
        )
        assert result is not None
        assert "decimal point" in result

    def test_point_in_de_ok(self):
        assert patent_number_decimal(
            "Patent Application No. 201711138495.4",
            "Patentanmeldung Nr. 201711138495.4",
        ) is None

    def test_no_patent_number_not_flagged(self):
        assert patent_number_decimal("the device comprises", "die Vorrichtung umfasst") is None

    def test_regular_decimal_not_flagged(self):
        # short number after Nr. — below the 5-digit threshold
        assert patent_number_decimal("claim 1.2", "Anspruch 1,2") is None


# ── acronym_in_compound ───────────────────────────────────────────────────────

class TestAcronymInCompound:
    def test_hyphen_inside_parens_flagged(self):
        # (AKR-) — hyphen must be outside: (AKR)-
        result = acronym_in_compound("", "Uplink-, UL-, Verkehr und (RO-) Ressourcen")
        assert result is not None

    def test_hyphen_inside_parens_direct(self):
        result = acronym_in_compound("", "eine Direktzugriffskanal(RO-)Ressource")
        assert result is not None

    def test_space_before_hyphen_flagged(self):
        # (FL) -Gerät — no space between ) and -
        result = acronym_in_compound("", "Fluides-Plasma (FL) -Gerät")
        assert result is not None

    def test_space_after_hyphen_flagged(self):
        # Word- (AKR) — no space between - and (
        result = acronym_in_compound("", "Eingabe- (E/A-)Steuerlogik")
        assert result is not None

    def test_correct_form_not_flagged(self):
        # (AKR)- immediately after paren — correct
        assert acronym_in_compound("", "Uplink(UL)-Verkehr") is None

    def test_correct_form_no_hyphen_not_flagged(self):
        # Acronym in parens without a following hyphen — correct for standalone
        assert acronym_in_compound("", "eine Netzwerkeinheit (NTN)") is None

    def test_regular_parens_not_flagged(self):
        # Reference numbers in parens — should not fire
        assert acronym_in_compound("", "die Steuereinheit (22) konfiguriert ist") is None

    def test_lowercase_parens_not_flagged(self):
        # Lowercase content in parens is not an acronym
        assert acronym_in_compound("", "eine Methode (siehe oben) -") is None


# ── hyphen_in_long_compound ───────────────────────────────────────────────────

class TestHyphenInLongCompound:
    def test_long_compound_flagged(self):
        result = hyphen_in_long_compound("", "Einwahlpaket-Verarbeitungsverfahren")
        assert result is not None
        assert "Einwahlpaket-Verarbeitungsverfahren" in result

    def test_second_example_flagged(self):
        result = hyphen_in_long_compound("", "Steuerungsebenen-Netzwerkelement")
        assert result is not None

    def test_short_loanword_hyphen_not_flagged(self):
        # Fed-Batch — both parts short, loan word hyphen is legitimate
        assert hyphen_in_long_compound("", "Fed-Batch-Modus") is None

    def test_lock_in_not_flagged(self):
        assert hyphen_in_long_compound("", "Lock-in-Verstärker") is None

    def test_number_range_not_flagged(self):
        # en dash in number range — handled by different check, not relevant here
        assert hyphen_in_long_compound("", "10–20 mm") is None

    def test_no_hyphen_not_flagged(self):
        assert hyphen_in_long_compound("", "Einwahlpaketverarbeitungsverfahren") is None

    def test_one_short_side_not_flagged(self):
        # only one side is long — not a compound hyphen issue
        assert hyphen_in_long_compound("", "Verarbeitungsverfahren-ID") is None


# ── durch_verwendung ──────────────────────────────────────────────────────────

class TestDurchVerwendung:
    def test_durch_verwendung_flagged(self):
        result = durch_verwendung("", "durch Verwendung entsprechender Federn")
        assert result is not None
        assert "Verwenden" in result

    def test_durch_verwenden_ok(self):
        assert durch_verwendung("", "durch Verwenden entsprechender Federn") is None

    def test_by_gerund_triggers_broader_check(self):
        result = durch_verwendung(
            "connected by using respective ferrules",
            "durch Verbindung entsprechender Federn",
        )
        assert result is not None
        assert "[Verb-en]" in result

    def test_by_gerund_no_ung_in_target_ok(self):
        assert durch_verwendung(
            "connected by using respective ferrules",
            "durch Verbinden entsprechender Federn",
        ) is None

    def test_no_gerund_no_ung_not_flagged(self):
        assert durch_verwendung("the device comprises a sensor", "die Vorrichtung umfasst einen Sensor") is None

    def test_zur_verwendung_not_flagged(self):
        # "zur Verwendung" is a fixed expression — not caught by this check
        assert durch_verwendung("", "zur Verwendung geeignet") is None

    def test_case_insensitive_durch_verwendung(self):
        assert durch_verwendung("", "DURCH VERWENDUNG einer Feder") is not None


# ── unter_verwendung ──────────────────────────────────────────────────────────

class TestUnterVerwendung:
    def test_using_mit_unter_verwendung_flagged(self):
        result = unter_verwendung(
            "performing a forecast using traffic data",
            "Durchführen einer Prognose unter Verwendung von Verkehrsdaten",
        )
        assert result is not None
        assert "verwendend" in result

    def test_verwendend_not_flagged(self):
        assert unter_verwendung(
            "performing a forecast using traffic data",
            "Durchführen einer Prognose, Verkehrsdaten verwendend",
        ) is None

    def test_no_using_in_source_not_flagged(self):
        # "unter Verwendung" in target but source doesn't say "using"
        assert unter_verwendung(
            "performing a forecast with traffic data",
            "Durchführen einer Prognose unter Verwendung von Verkehrsdaten",
        ) is None

    def test_case_insensitive_source(self):
        result = unter_verwendung(
            "USING traffic data",
            "unter Verwendung von Verkehrsdaten",
        )
        assert result is not None

    def test_case_insensitive_target(self):
        result = unter_verwendung(
            "using traffic data",
            "UNTER VERWENDUNG von Verkehrsdaten",
        )
        assert result is not None


# ── schritt_zum ───────────────────────────────────────────────────────────────

class TestSchrittZum:
    def test_schritt_zum_flagged(self):
        result = schritt_zum("", "einen Schritt zum Erfassen von Daten")
        assert result is not None
        assert "Schritt eines" in result

    def test_schritt_zum_erzeugen_flagged(self):
        result = schritt_zum("", "einen Schritt zum Erzeugen des Bildes")
        assert result is not None

    def test_schritt_eines_ok(self):
        assert schritt_zum("", "einen Schritt eines Erfassens von Daten") is None

    def test_schritt_zum_lowercase_not_flagged(self):
        # "Schritt zum nächsten" — lowercase after "zum", not an infinitive
        assert schritt_zum("", "ein Schritt zum nächsten Verfahren") is None

    def test_no_schritt_not_flagged(self):
        assert schritt_zum("", "Erfassen von Nutzungsdaten") is None

    def test_schritte_plural_flagged(self):
        result = schritt_zum("", "Schritte zum Bestimmen des Wertes")
        assert result is not None


# ── mindestens_at_least ───────────────────────────────────────────────────────

class TestMindestensAtLeast:
    def test_mindestens_without_at_least_flagged(self):
        result = mindestens_at_least("one sensor", "mindestens einen Sensor")
        assert result is not None
        assert '"at least"' in result

    def test_mindestens_with_at_least_ok(self):
        assert mindestens_at_least("at least one sensor", "mindestens einen Sensor") is None

    def test_no_mindestens_not_flagged(self):
        assert mindestens_at_least("at least one sensor", "einen Sensor") is None

    def test_case_insensitive_target(self):
        assert mindestens_at_least("one sensor", "MINDESTENS einen Sensor") is not None

    def test_case_insensitive_source(self):
        assert mindestens_at_least("AT LEAST one sensor", "mindestens einen Sensor") is None

    def test_message_content(self):
        result = mindestens_at_least("a sensor", "mindestens einen Sensor")
        assert "mindestens" in result
        assert "at least" in result
