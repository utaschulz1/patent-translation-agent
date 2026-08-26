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


# ── _find_translated_xlsx ───────────────────────────────────────────────────

class TestFindTranslatedXlsx:
    def test_finds_translated_file(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated.xlsx", [(1, "a widget", "ein Widget")])
        assert rev._find_translated_xlsx(proj_dir) == proj_dir / "Doc_translated.xlsx"

    def test_ignores_checks_file(self, proj_dir):
        _write_translated_xlsx(proj_dir / "Doc_translated_checks.xlsx", [(1, "a", "b")])
        assert rev._find_translated_xlsx(proj_dir) is None

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
            assert rev._appears_in(row["en"], "the device comprises a widget")

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

    def test_model_and_project_id_threaded_through(self, proj_dir):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                             "openai/gpt-5.6-luna", "TEST_0001")
        assert client.chat.completions.create.call_args.kwargs["model"] == "openai/gpt-5.6-luna"

    def test_session_id_defaults_from_project_id(self, proj_dir):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                             "openai/gpt-5.6-luna", "TEST_0001")
        extra_body = client.chat.completions.create.call_args.kwargs["extra_body"]
        assert extra_body == {"session_id": "TEST_0001_GlossaryLLM"}

    def test_session_id_override(self, proj_dir):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]))
        rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                             "openai/gpt-5.6-luna", "TEST_0001", session_id="custom-session")
        extra_body = client.chat.completions.create.call_args.kwargs["extra_body"]
        assert extra_body == {"session_id": "custom-session"}


class TestReviseGlossaryTruncationGuard:
    """A response cut off before any real content (Luna 5's reasoning eating
    the token budget — the real bug hit live during the one-shot test, see
    memory) must raise a clear error, not silently proceed with garbage."""

    def test_truncated_empty_response_raises(self, proj_dir):
        client = _mock_client("", finish_reason="length")
        with pytest.raises(ValueError, match="truncated"):
            rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                                 "openai/gpt-5.6-luna", "TEST_0001")

    def test_normal_stop_with_content_proceeds(self, proj_dir):
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]), finish_reason="stop")
        result = rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                                      "openai/gpt-5.6-luna", "TEST_0001")
        assert "widget,Widget" in result

    def test_length_finish_reason_with_content_still_parses(self, proj_dir):
        # A response can hit the token cap after emitting complete, valid
        # JSON (e.g. right at the boundary) — only empty content + non-stop
        # is treated as the truncation failure.
        client = _mock_client(json.dumps([{"en": "widget", "de": "Widget"}]), finish_reason="length")
        result = rev.revise_glossary("EN,DE\nwidget,Widget\n", "{INPUT_JSON}", proj_dir, client,
                                      "openai/gpt-5.6-luna", "TEST_0001")
        assert "widget,Widget" in result
