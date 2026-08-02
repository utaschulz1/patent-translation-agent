"""
test_verb_lemma_sync.py — Live round-trip test for verb_lemma_sync.py.

Unlike the other test_*.py files here, this one makes a REAL call to the
LLM (OpenRouter, model from config.LLM_MODEL) — there is no useful way to
mock "does the model produce plausible German verb inflections" other than
asking it for real. Requires OPENROUTER_API_KEY in .env.

Scenario: take a real patent sentence and swap its verb for something no
patent would ever use ("flabbergast" / naive DE gloss "verblüffen") — this
guarantees the pair is genuinely new to both lemma tables, so the test
exercises the exact "having"-class gap this module exists to catch
(2026-07-31), without depending on the tables' current contents.

All reads/writes go through tmp_path copies of the real lemma tables —
this test must never modify the real, shared EN_verb_lemma_lookup.json /
DE_verb_lemma_lookup.json.

Run with:  pytest test_verb_lemma_sync.py -v -s
(-s to see the sync_verb_lemma_tables() progress prints)
"""
import json
import os
import shutil
from pathlib import Path

import pytest
from openai import OpenAI

from config import LLM_MODEL
import verb_lemma_sync as vls

HERE = Path(__file__).parent

# A real patent sentence (EP4165642 claims, seen in the CHEP_2607_P0042
# project) with its verb swapped out — models "exchanging a verb in the
# patent for something improbable to be present" as discussed.
TEST_EN_SENTENCE = (
    "(a) selecting n input variables I1, I2, … In, each input variable "
    "corresponding to a structural property or an electronic property of "
    "one or more ground state model structures, the method configured to "
    "flabbergast a heteroatomic ligand-metal compound complex;"
)
TEST_DE_SENTENCE = (
    "(a) Auswählen von n Eingabevariablen I1, I2, … In, wobei jede "
    "Eingabevariable einer strukturellen Eigenschaft oder einer "
    "elektronischen Eigenschaft einer oder mehrerer Grundzustandsmodell"
    "strukturen entspricht, wobei das Verfahren dazu konfiguriert ist, "
    "einen Heteroatom-Ligand-Metall-Verbindungskomplex zu verblüffen;"
)
TEST_EN_VERB = "flabbergast"
TEST_DE_VERB = "verblüffen"


@pytest.fixture
def tmp_lemma_tables(tmp_path):
    """Isolated copies of the real lemma tables — safe to read AND write."""
    en_path = tmp_path / "EN_verb_lemma_lookup.json"
    de_path = tmp_path / "DE_verb_lemma_lookup.json"
    shutil.copy(HERE / "EN_verb_lemma_lookup.json", en_path)
    shutil.copy(HERE / "DE_verb_lemma_lookup.json", de_path)
    return en_path, de_path


@pytest.fixture
def real_client():
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set — skipping live LLM test")
    return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestFindNewVerbPairs:
    def test_invented_verb_detected_as_new(self, tmp_lemma_tables):
        en_path, de_path = tmp_lemma_tables
        en_table, de_table = _load(en_path), _load(de_path)
        assert TEST_EN_VERB not in en_table, "test verb must not already be in the real table"
        assert TEST_DE_VERB not in de_table, "test verb must not already be in the real table"

        new_pairs = vls.find_new_verb_pairs(
            clean_rows=[(TEST_EN_VERB, TEST_DE_VERB), ("comprise", "umfassen")],
            consistent_verbs={TEST_EN_VERB: TEST_DE_VERB, "comprise": "umfassen"},
            inconsistent_verbs=[],
            en_lemma_table=en_table,
            de_lemma_table=de_table,
        )
        assert new_pairs == [(TEST_EN_VERB, TEST_DE_VERB)], (
            "comprise/umfassen is already fully covered and must not be flagged; "
            "only the invented verb should come back as new"
        )


class TestLiveRoundTrip:
    """Makes a real LLM call. Requires OPENROUTER_API_KEY."""

    def test_sync_adds_plausible_forms_without_touching_real_files(
        self, tmp_lemma_tables, real_client
    ):
        en_path, de_path = tmp_lemma_tables
        real_en_before = (HERE / "EN_verb_lemma_lookup.json").read_text(encoding="utf-8")
        real_de_before = (HERE / "DE_verb_lemma_lookup.json").read_text(encoding="utf-8")

        assert TEST_EN_VERB in TEST_EN_SENTENCE
        assert TEST_DE_VERB in TEST_DE_SENTENCE

        en_added, de_added = vls.sync_verb_lemma_tables(
            clean_rows=[(TEST_EN_VERB, TEST_DE_VERB)],
            consistent_verbs={TEST_EN_VERB: TEST_DE_VERB},
            inconsistent_verbs=[],
            client=real_client,
            model=LLM_MODEL,
            en_lemma_path=en_path,
            de_lemma_path=de_path,
        )

        # ── The model produced something, and it's self-consistent ──
        assert en_added, "expected at least the bare EN lemma to be added"
        assert de_added, "expected at least the bare DE lemma to be added"
        assert TEST_EN_VERB in en_added, "bare EN infinitive must be among the added forms"
        assert TEST_DE_VERB in de_added, "bare DE infinitive must be among the added forms"

        en_table_after, de_table_after = _load(en_path), _load(de_path)
        for form in en_added:
            assert en_table_after[form] == TEST_EN_VERB, f"{form!r} must map to the lemma {TEST_EN_VERB!r}"
        for form in de_added:
            assert de_table_after[form] == TEST_DE_VERB, f"{form!r} must map to the lemma {TEST_DE_VERB!r}"

        # ── Persisted to the tmp files (not just left in memory) ──
        assert TEST_EN_VERB in en_table_after
        assert TEST_DE_VERB in de_table_after

        # ── Untouched: the real, shared tables this whole module protects ──
        assert (HERE / "EN_verb_lemma_lookup.json").read_text(encoding="utf-8") == real_en_before
        assert (HERE / "DE_verb_lemma_lookup.json").read_text(encoding="utf-8") == real_de_before
        real_en_after, real_de_after = _load(HERE / "EN_verb_lemma_lookup.json"), _load(HERE / "DE_verb_lemma_lookup.json")
        assert TEST_EN_VERB not in real_en_after
        assert TEST_DE_VERB not in real_de_after

    def test_second_sync_is_idempotent_no_llm_call_needed(self, tmp_lemma_tables, real_client, capsys):
        """Once a verb is covered, re-running sync must not re-request it —
        this also verifies find_new_verb_pairs recognizes forms just added."""
        en_path, de_path = tmp_lemma_tables

        # First sync — establishes coverage (real LLM call).
        vls.sync_verb_lemma_tables(
            clean_rows=[(TEST_EN_VERB, TEST_DE_VERB)],
            consistent_verbs={TEST_EN_VERB: TEST_DE_VERB},
            inconsistent_verbs=[],
            client=real_client,
            model=LLM_MODEL,
            en_lemma_path=en_path,
            de_lemma_path=de_path,
        )
        capsys.readouterr()  # discard first-call output

        # Second sync — must short-circuit before ever calling the client.
        en_added, de_added = vls.sync_verb_lemma_tables(
            clean_rows=[(TEST_EN_VERB, TEST_DE_VERB)],
            consistent_verbs={TEST_EN_VERB: TEST_DE_VERB},
            inconsistent_verbs=[],
            client=real_client,
            model=LLM_MODEL,
            en_lemma_path=en_path,
            de_lemma_path=de_path,
        )
        out = capsys.readouterr().out
        assert en_added == [] and de_added == []
        assert "no new verbs found" in out
