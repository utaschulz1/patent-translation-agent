"""
test_xtm_segment_match.py — Unit tests for xtm_segment_match.py's match_corrections().

Run with:  pytest test_xtm_segment_match.py -v
"""
import pytest

from xtm_segment_match import match_corrections


def test_match_corrections_single_occurrence_succeeds():
    rows = [(1, "source a", "the first sensor detects pressure")]
    corrections = [{"old_text": "detects", "new_text": "measures"}]
    assert match_corrections(rows, corrections) == [(1, "the first sensor measures pressure")]


def test_match_corrections_repeated_occurrence_in_segment_raises():
    """old_text appearing twice within the one matched segment's Target is
    just as ambiguous as matching two different segments — must not
    silently rewrite both occurrences."""
    rows = [(1, "source a", "the sensor connects to the sensor housing")]
    corrections = [{"old_text": "sensor", "new_text": "detector"}]
    with pytest.raises(ValueError, match="ambiguous"):
        match_corrections(rows, corrections)


def test_match_corrections_zero_segment_matches_raises():
    rows = [(1, "source a", "the first sensor detects pressure")]
    corrections = [{"old_text": "nonexistent phrase", "new_text": "x"}]
    with pytest.raises(ValueError, match="No segment found"):
        match_corrections(rows, corrections)


def test_match_corrections_multiple_segment_matches_raises():
    rows = [
        (1, "source a", "the sensor detects pressure"),
        (2, "source b", "the sensor detects temperature"),
    ]
    corrections = [{"old_text": "the sensor detects", "new_text": "x"}]
    with pytest.raises(ValueError, match="Multiple segments"):
        match_corrections(rows, corrections)
