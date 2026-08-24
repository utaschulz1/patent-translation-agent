"""
test_glossary_lib_lemma.py — Phase 0b exit-gate tests for the project-scoped
lemma overlay (TEST_glossary_agent.md §Phase 0b, PRD §6b).

Proves: load_lemma_tables merges baseline + overlay (overlay wins),
sync_verb_lemma_tables in proj_dir mode writes ONLY the overlay files, and
the overlay is what fixes the anzuzeigen-class production gap (a document's
separable zu-infinitive surface form missing from the shared tables).

Run with:  pytest test_glossary_lib_lemma.py -v
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import glossary_lib.lemma_sync as lemma_sync
import glossary_lib.matching as matching

_EN_BASELINE = {"display": "display", "displays": "display", "displayed": "display"}
_DE_BASELINE = {"anzeigen": "anzeigen", "anzeigt": "anzeigen", "angezeigt": "anzeigen"}


@pytest.fixture
def baselines(tmp_path, monkeypatch):
    """Point the module-level baseline paths at small tmp fixtures so tests
    control table contents and can prove the baseline is never written."""
    en_p = tmp_path / "EN_baseline.json"
    de_p = tmp_path / "DE_baseline.json"
    en_p.write_text(json.dumps(_EN_BASELINE), encoding="utf-8")
    de_p.write_text(json.dumps(_DE_BASELINE), encoding="utf-8")
    monkeypatch.setattr(matching, "EN_BASELINE_PATH", en_p)
    monkeypatch.setattr(matching, "DE_BASELINE_PATH", de_p)
    return en_p, de_p


@pytest.fixture
def proj_dir(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return d


def _write_overlay(proj_dir: Path, en: dict | None = None, de: dict | None = None):
    if en is not None:
        (proj_dir / matching.EN_OVERLAY_NAME).write_text(json.dumps(en), encoding="utf-8")
    if de is not None:
        (proj_dir / matching.DE_OVERLAY_NAME).write_text(json.dumps(de), encoding="utf-8")


class TestLoadLemmaTables:
    def test_baseline_only_when_no_proj_dir(self, baselines):
        en, de = matching.load_lemma_tables(None)
        assert en == _EN_BASELINE
        assert de == _DE_BASELINE

    def test_missing_overlay_files_no_error(self, baselines, proj_dir):
        en, de = matching.load_lemma_tables(proj_dir)
        assert en == _EN_BASELINE
        assert de == _DE_BASELINE

    def test_overlay_merged_on_top(self, baselines, proj_dir):
        _write_overlay(proj_dir, de={"anzuzeigen": "anzeigen"})
        en, de = matching.load_lemma_tables(proj_dir)
        assert de["anzuzeigen"] == "anzeigen"
        assert de["anzeigen"] == "anzeigen"  # baseline entries intact
        assert en == _EN_BASELINE

    def test_overlay_wins_on_key_conflict(self, baselines, proj_dir):
        _write_overlay(proj_dir, de={"anzeigen": "OVERLAY-WINS"})
        _, de = matching.load_lemma_tables(proj_dir)
        assert de["anzeigen"] == "OVERLAY-WINS"


class TestSyncWritesOverlayOnly:
    def _mock_client(self, payload: dict) -> MagicMock:
        client = MagicMock()
        msg = MagicMock()
        msg.content = json.dumps(payload)
        client.chat.completions.create.return_value.choices = [MagicMock(message=msg)]
        return client

    def test_new_forms_land_in_overlay_baseline_untouched(self, baselines, proj_dir):
        en_p, de_p = baselines
        en_before = en_p.read_bytes()
        de_before = de_p.read_bytes()

        client = self._mock_client({
            "en": [{"surface": "dissolve", "infinitive": "dissolve",
                    "forms": ["dissolve", "dissolves", "dissolving", "dissolved"]}],
            "de": [{"surface": "auflösen", "infinitive": "auflösen",
                    "forms": ["auflösen", "auflöst", "aufgelöst", "aufzulösen"]}],
        })
        en_added, de_added = lemma_sync.sync_verb_lemma_tables(
            clean_rows=[("dissolve", "auflösen")],
            consistent_verbs={"dissolve": "auflösen"},
            inconsistent_verbs=[],
            client=client, model="test-model",
            proj_dir=proj_dir,
        )
        assert "dissolve" in en_added and "aufzulösen" in de_added
        # Overlay files created with exactly the new forms
        en_overlay = json.loads((proj_dir / matching.EN_OVERLAY_NAME).read_text(encoding="utf-8"))
        de_overlay = json.loads((proj_dir / matching.DE_OVERLAY_NAME).read_text(encoding="utf-8"))
        assert en_overlay["dissolving"] == "dissolve"
        assert de_overlay["aufzulösen"] == "auflösen"
        assert "anzeigen" not in de_overlay, "baseline content must not leak into the overlay"
        # Baseline files byte-identical
        assert en_p.read_bytes() == en_before
        assert de_p.read_bytes() == de_before

    def test_detection_sees_existing_overlay(self, baselines, proj_dir):
        """A form already in the overlay counts as known — no LLM call needed."""
        _write_overlay(proj_dir,
                       en={"dissolve": "dissolve"},
                       de={"auflösen": "auflösen"})
        client = MagicMock()
        en_added, de_added = lemma_sync.sync_verb_lemma_tables(
            clean_rows=[("dissolve", "auflösen")],
            consistent_verbs={"dissolve": "auflösen"},
            inconsistent_verbs=[],
            client=client, model="test-model",
            proj_dir=proj_dir,
        )
        assert en_added == [] and de_added == []
        client.chat.completions.create.assert_not_called()

    def test_legacy_mode_unchanged(self, tmp_path):
        """proj_dir=None keeps the historical read/write-in-place behavior."""
        en_p = tmp_path / "en.json"
        de_p = tmp_path / "de.json"
        en_p.write_text(json.dumps({}), encoding="utf-8")
        de_p.write_text(json.dumps({}), encoding="utf-8")
        client = self._mock_client({
            "en": [{"surface": "melt", "infinitive": "melt", "forms": ["melt", "melts"]}],
            "de": [],
        })
        lemma_sync.sync_verb_lemma_tables(
            clean_rows=[("melt", "schmelzen")],
            consistent_verbs={"melt": "schmelzen"},
            inconsistent_verbs=[],
            client=client, model="test-model",
            en_lemma_path=en_p, de_lemma_path=de_p,
        )
        assert json.loads(en_p.read_text(encoding="utf-8"))["melts"] == "melt"


class TestAnzuzeigenRegression:
    """The HALA_2608_P0655 live miss (2026-08-22): 'display,anzeigen' passed a
    bare-key table check, but the document's actual separable zu-infinitive
    'anzuzeigen' was not a table key, so the production checker flagged the
    segment as missing the verb. The overlay is what closes this."""

    _VERB_LOOKUP = {"display": "anzeigen"}
    _EN = "display the first output image data"
    _DE = "um die ersten Ausgangsbilddaten anzuzeigen"

    def _notes(self, tables):
        return matching.check_segment_glossary(
            self._EN, self._DE, self._VERB_LOOKUP, {}, [], lemma_tables=tables,
        )

    def test_without_overlay_flags_missing(self, baselines, proj_dir):
        notes = self._notes(matching.load_lemma_tables(proj_dir))
        assert any("missing" in n and "anzeigen" in n for n in notes), (
            "pre-overlay behavior must reproduce the original false flag — "
            "otherwise this test proves nothing about the overlay"
        )

    def test_with_overlay_no_flag(self, baselines, proj_dir):
        _write_overlay(proj_dir, de={"anzuzeigen": "anzeigen"})
        notes = self._notes(matching.load_lemma_tables(proj_dir))
        assert notes == []
