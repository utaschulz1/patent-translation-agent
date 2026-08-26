"""
test_llm_glossary_revise.py

Unit tests for llm_glossary_revise.py's context-assembly (load_raw_context,
load_frequency_data, _find_translated_xlsx) and the revise_glossary contract
(mocked LLM). Rewritten 2026-08-26 alongside the prompt's expansion into a
grounded single-pass consolidation+audit review — see glossary_revise_prompt.md
and the memory entry it links for why raw segment context was added.

Per-project data (segments, EPO title, standard-glossary filtering) is built
as small synthetic fixtures in tmp_path — hermetic and fast. The module's
own STYLEGUIDE_PATH/LEARNINGS_PATH/standard_glossary.csv are shared,
agent-level files, not project-scoped, so these tests read the real ones —
same as production.

Run with: pytest test_llm_glossary_revise.py -v
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import openpyxl
import pytest

sys.modules.setdefault("dotenv", MagicMock())
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

import llm_glossary_revise as rev
from glossary_lib.attestation import _appears_in


def _write_translated_xlsx(path: Path, rows: list[tuple[int, str, str]]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Id", "Source", "Target"])
    for sid, en, de in rows:
        ws.append([sid, en, de])
    wb.save(path)


@pytest.fixture
def proj_dir(tmp_path) -> Path:
    d = tmp_path / "proj"
    d.mkdir()
    return d


@pytest.fixture
def proj_dir_with_segments(proj_dir) -> Path:
    """proj_dir with a minimal *_translated.xlsx already present. revise_glossary
    requires at least one segment to run (see TestReviseGlossaryRequiresSegments)
    — tests that only care about other behavior use this fixture so the
    segments-required guard doesn't get in the way."""
    _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [
        (1, "the device comprises a widget", "die Vorrichtung umfasst ein Widget"),
    ])
    return proj_dir


# ── _find_translated_xlsx ───────────────────────────────────────────────────

class TestFindTranslatedXlsx:
    def test_finds_translated_file(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [(1, "a widget", "ein Widget")])
        assert rev._find_translated_xlsx(proj_dir) == proj_dir / "Doc_translated.xlsx"

    def test_checks_file_name_never_matches_the_glob(self, proj_dir):
        # A "*_checks.xlsx" file (e.g. produced by glossary_compare_revised_
        # translation.py) never ends in "_translated.xlsx", so it's already
        # excluded by the glob pattern itself — no separate filter needed.
        _write_translated_xlsx(proj_dir / "Doc_translated_checks.xlsx", [(1, "a", "b")])
        assert rev._find_translated_xlsx(proj_dir) is None

    def test_multiple_matches_picks_first_and_warns(self, proj_dir, capsys):
        _write_translated_xlsx(proj_dir / "A_translated.xlsx", [(1, "a", "b")])
        _write_translated_xlsx(proj_dir / "B_translated.xlsx", [(1, "c", "d")])
        result = rev._find_translated_xlsx(proj_dir)
        assert result == proj_dir / "A_translated.xlsx"
        assert "Multiple translated files found" in capsys.readouterr().out

    def test_ignores_lock_file(self, proj_dir):
        (proj_dir / "~$Doc_translated.xlsx").write_bytes(b"")
        assert rev._find_translated_xlsx(proj_dir) is None

    def test_none_when_absent(self, proj_dir):
        assert rev._find_translated_xlsx(proj_dir) is None


# ── load_frequency_data ──────────────────────────────────────────────────────

class TestLoadFrequencyData:
    def test_returns_three_lists_including_capability(self, proj_dir):
        (proj_dir / "verb_canonical_glossary.csv").write_text(
            "EN Verb,DE Verb,Count,Total EN Occurrences,Canonical\ncomprise,umfassen,3,3,yes\n",
            encoding="utf-8")
        (proj_dir / "noun_canonical_glossary.csv").write_text(
            "EN Phrase,DE Phrase,Count,Total EN Occurrences,Canonical\nbody,Gehäuse,2,2,yes\n",
            encoding="utf-8")
        (proj_dir / "capability_canonical_glossary.csv").write_text(
            "EN Verb,DE Verb,Count,Total EN Occurrences,Canonical\nconfigure,konfigurieren,1,1,yes\n",
            encoding="utf-8")
        verb, noun, cap = rev.load_frequency_data(proj_dir)
        assert verb == [{"en": "comprise", "de": "umfassen", "count": 3, "total": 3}]
        assert noun == [{"en": "body", "de": "Gehäuse", "count": 2, "total": 2}]
        assert cap == [{"en": "configure", "de": "konfigurieren", "count": 1, "total": 1}]

    def test_missing_files_return_empty_lists(self, proj_dir):
        assert rev.load_frequency_data(proj_dir) == ([], [], [])


# ── load_raw_context ─────────────────────────────────────────────────────────

class TestLoadRawContext:
    def test_segments_loaded_from_translated_xlsx(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [
            (1, "a widget", "ein Widget"),
            (2, "the widget rotates", "das Widget dreht sich"),
        ])
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        assert ctx["segments"] == [
            {"id": 1, "en": "a widget", "de": "ein Widget"},
            {"id": 2, "en": "the widget rotates", "de": "das Widget dreht sich"},
        ]

    def test_no_translated_xlsx_gives_empty_segments(self, proj_dir):
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        assert ctx["segments"] == []

    def test_epo_title_read_and_cleaned(self, proj_dir):
        (proj_dir / "glossary_TEST_0001.csv").write_text(
            'EN,DE\n"EPO EN: A Widget, Compact","EPO DE: Ein Widget, Kompakt"\n', encoding="utf-8")
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        assert ctx["epo_title"] == {"en": "A Widget Compact", "de": "Ein Widget Kompakt"}

    def test_no_glossary_file_gives_blank_title(self, proj_dir):
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        assert ctx["epo_title"] == {"en": "", "de": ""}

    def test_standard_glossary_filtered_to_attested_terms(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [
            (1, "the device comprises a widget", "die Vorrichtung umfasst ein Widget"),
        ])
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        std = {row["en"]: row["de"] for row in ctx["standard_glossary"]}
        # both are real standard_glossary.csv anchors and both are attested
        # in the one segment above — must survive the relevance filter.
        assert std.get("device") == "Vorrichtung"
        assert std.get("comprise") == "umfassen"
        # every returned term must genuinely be attested in that segment
        for row in ctx["standard_glossary"]:
            assert _appears_in(row["en"], "the device comprises a widget")

    def test_standard_glossary_empty_when_nothing_attested(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [
            (1, "xyzzyplonk frobnicates", "xyzzyplonk frobnifiziert"),
        ])
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        assert ctx["standard_glossary"] == []

    def test_styleguide_and_learnings_are_strings(self, proj_dir):
        ctx = rev.load_raw_context(proj_dir, "TEST_0001")
        assert isinstance(ctx["styleguide_text"], str) and len(ctx["styleguide_text"]) > 0
        assert isinstance(ctx["learnings_text"], str)


# ── revise_glossary (mocked LLM) ─────────────────────────────────────────────

def _mock_client(content: str, finish_reason: str = "stop"):
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = finish_reason
    client.chat.completions.create.return_value = resp
    return client


class TestReviseGlossaryContext:
    """The prompt's {INPUT_JSON} payload must carry the new grounding fields,
    not just current_glossary + frequency tables."""

    def test_input_json_carries_full_context(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [
            (1, "the device comprises a widget", "die Vorrichtung umfasst ein Widget"),
        ])
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        glossary_text = "EN,DE\nwidget,Widget\n"
        rev.revise_glossary(glossary_text, "PROMPT: {INPUT_JSON}", proj_dir, client,
                             "openai/gpt-5.6-luna", "TEST_0001")

        sent_prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        payload = json.loads(sent_prompt[len("PROMPT: "):])
        assert payload["current_glossary"] == [{"en": "widget", "de": "Widget"}]
        assert "capability_frequency_data" in payload
        assert payload["segments"] == [
            {"id": 1, "en": "the device comprises a widget", "de": "die Vorrichtung umfasst ein Widget"}
        ]
        assert "epo_title" in payload
        assert "standard_glossary" in payload
        assert "styleguide_text" in payload
        assert "learnings_text" in payload

    def test_model_and_project_id_threaded_through(self, proj_dir_with_segments):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments, client,
                             "openai/gpt-5.6-luna", "TEST_0001")
        assert client.chat.completions.create.call_args.kwargs["model"] == "openai/gpt-5.6-luna"

    def test_session_id_defaults_from_project_id(self, proj_dir_with_segments):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments, client,
                             "openai/gpt-5.6-luna", "TEST_0001")
        extra_body = client.chat.completions.create.call_args.kwargs["extra_body"]
        assert extra_body == {"session_id": "TEST_0001_GlossaryLLM"}

    def test_session_id_override(self, proj_dir_with_segments):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments, client,
                             "openai/gpt-5.6-luna", "TEST_0001", session_id="custom-session")
        extra_body = client.chat.completions.create.call_args.kwargs["extra_body"]
        assert extra_body == {"session_id": "custom-session"}


class TestReviseGlossaryRequiresSegments:
    """Rule 5 of the prompt tells the LLM every DE value must be attested in
    `segments`, no exceptions. Without a *_translated.xlsx there are zero
    segments, which would make rule 5 unsatisfiable for every existing row —
    so revise_glossary must refuse to run rather than silently reviewing
    ungrounded and risking a mass wipeout that only a print()ed warning would
    catch (see TestReviseGlossaryWarning)."""

    def test_raises_when_no_translated_xlsx(self, proj_dir):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        with pytest.raises(ValueError, match="segment corpus"):
            rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                                 "openai/gpt-5.6-luna", "TEST_0001")
        client.chat.completions.create.assert_not_called()


class TestReviseGlossaryWarning:
    """The <70%-of-original-row-count safety net must reach the caller as a
    return value, not just a server-side print(), so the frontend can show it."""

    def test_warning_none_when_row_count_stable(self, proj_dir_with_segments):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        _, warning = rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments,
                                          client, "openai/gpt-5.6-luna", "TEST_0001")
        assert warning is None

    def test_warning_set_when_row_count_drops_sharply(self, proj_dir_with_segments):
        glossary_text = "EN,DE\n" + "\n".join(f"term{i},Begriff{i}" for i in range(10))
        client = _mock_client(json.dumps([{"en": "term0", "de": "Begriff0"}]))
        _, warning = rev.revise_glossary(glossary_text, "{INPUT_JSON}", proj_dir_with_segments,
                                          client, "openai/gpt-5.6-luna", "TEST_0001")
        assert warning is not None and "down from 10" in warning


class TestReviseGlossaryTruncationGuard:
    """A response cut off before any real content (Luna 5's reasoning eating
    the token budget — the real bug hit live during the one-shot test, see
    memory) must raise a clear error, not silently proceed with garbage."""

    def test_truncated_empty_response_raises(self, proj_dir_with_segments):
        client = _mock_client("", finish_reason="length")
        with pytest.raises(ValueError, match="truncated"):
            rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments, client,
                                 "openai/gpt-5.6-luna", "TEST_0001")

    def test_truncated_partial_content_raises(self, proj_dir_with_segments):
        # The more common truncation shape: max_tokens cuts the response off
        # mid-array, so content is non-empty but not valid/complete JSON.
        # This must still raise the truncation-specific error, not fall
        # through to the generic "could not be parsed" error.
        client = _mock_client('[{"en": "widget", "de": "Wid', finish_reason="length")
        with pytest.raises(ValueError, match="truncated"):
            rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments, client,
                                 "openai/gpt-5.6-luna", "TEST_0001")

    def test_normal_stop_with_content_proceeds(self, proj_dir_with_segments):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]), finish_reason="stop")
        result, _ = rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments,
                                         client, "openai/gpt-5.6-luna", "TEST_0001")
        assert "widget,Widget" in result

    def test_length_finish_reason_with_content_still_parses(self, proj_dir_with_segments):
        # A response can hit the token cap after emitting complete, valid
        # JSON (e.g. right at the boundary) — only a non-stop finish that
        # fails to parse into a JSON array is treated as truncation.
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]), finish_reason="length")
        result, _ = rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir_with_segments,
                                         client, "openai/gpt-5.6-luna", "TEST_0001")
        assert "widget,Widget" in result
