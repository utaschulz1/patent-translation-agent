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

TestFindUnknownVerbs uses a small frozen fixture table (not the real,
shared one) — the real EN/DE lemma tables keep growing via
verb_lemma_sync.py's own auto-growth, so a test asserting some verb like
"establish" or "know" is "not yet known" would silently start failing
whenever that verb later got added for real.

TestLiveRoundTrip still copies the real tables into tmp_path (it needs to
prove sync_verb_lemma_tables() never writes back to the real, shared
EN_verb_lemma_lookup.json / DE_verb_lemma_lookup.json — see its
real_en_before/after assertions) — but always writes through the tmp_path
copy, never the real files.

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


_SYNTHETIC_EN_TABLE = {"comprise": "comprise"}
_SYNTHETIC_DE_TABLE = {"umfassen": "umfassen", "eingerichtet": "einrichten"}


@pytest.fixture
def tmp_lemma_tables(tmp_path):
    """Small frozen tables, not the real ever-growing ones — see the module
    docstring. Covers exactly what TestFindUnknownVerbs needs: "comprise"/
    "umfassen" already known (must not be flagged), "eingerichtet" known as
    the base participle with "eingerichtete" deliberately absent (exercises
    the adjective-suffix-stripping fallback), and none of the verbs any test
    treats as "not yet known" (flabbergast/verblüffen, establish, know)."""
    en_path = tmp_path / "EN_verb_lemma_lookup.json"
    de_path = tmp_path / "DE_verb_lemma_lookup.json"
    en_path.write_text(json.dumps(_SYNTHETIC_EN_TABLE), encoding="utf-8")
    de_path.write_text(json.dumps(_SYNTHETIC_DE_TABLE, ensure_ascii=False), encoding="utf-8")
    return en_path, de_path


@pytest.fixture
def tmp_real_lemma_tables(tmp_path):
    """Isolated copies of the real, shared lemma tables — for
    TestLiveRoundTrip, which needs to prove sync_verb_lemma_tables() never
    writes back to them."""
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


class TestFindUnknownVerbs:
    def test_invented_verb_detected_as_new(self, tmp_lemma_tables):
        en_path, de_path = tmp_lemma_tables
        en_table, de_table = _load(en_path), _load(de_path)
        assert TEST_EN_VERB not in en_table, "test verb must not already be in the real table"
        assert TEST_DE_VERB not in de_table, "test verb must not already be in the real table"

        unknown_en, unknown_de = vls.find_unknown_verbs(
            clean_rows=[(TEST_EN_VERB, TEST_DE_VERB), ("comprise", "umfassen")],
            consistent_verbs={TEST_EN_VERB: TEST_DE_VERB, "comprise": "umfassen"},
            inconsistent_verbs=[],
            en_lemma_table=en_table,
            de_lemma_table=de_table,
        )
        assert unknown_en == [TEST_EN_VERB], (
            "comprise is already fully covered and must not be flagged; "
            "only the invented verb should come back as new"
        )
        assert unknown_de == [TEST_DE_VERB], (
            "umfassen is already fully covered and must not be flagged; "
            "only the invented verb should come back as new"
        )

    def test_known_verb_recognized_via_de_adjective_truncation(self, tmp_lemma_tables):
        """A DE surface form need not be an exact key — if the checker would
        resolve it by stripping an adjective suffix (_count_lemmas'
        strip_de_adj fallback), find_unknown_verbs must recognize it as
        already-known too, without ever calling the LLM for it."""
        en_path, de_path = tmp_lemma_tables
        en_table, de_table = _load(en_path), _load(de_path)
        assert "eingerichtet" in de_table, "fixture assumption: base participle already registered"
        assert "eingerichtete" not in de_table, "fixture assumption: adjective-inflected form is NOT a key"

        unknown_en, unknown_de = vls.find_unknown_verbs(
            clean_rows=[("establish", "eingerichtete")],
            consistent_verbs={"establish": "eingerichtete"},
            inconsistent_verbs=[],
            en_lemma_table=en_table,
            de_lemma_table=de_table,
        )
        assert unknown_en == ["establish"]
        assert unknown_de == [], (
            "eingerichtete strips to eingerichtet, an existing key — must not be "
            "treated as a new verb needing derivation"
        )

    def test_non_verb_de_term_excluded(self, tmp_lemma_tables):
        en_path, de_path = tmp_lemma_tables
        en_table, de_table = _load(en_path), _load(de_path)

        unknown_en, unknown_de = vls.find_unknown_verbs(
            clean_rows=[("know", "bekannt")],
            consistent_verbs={"know": "bekannt"},
            inconsistent_verbs=[],
            en_lemma_table=en_table,
            de_lemma_table=de_table,
        )
        assert unknown_en == ["know"], "know is a real verb and should still get EN forms"
        assert unknown_de == [], "bekannt is a fixed non-verb patent term, must never reach the LLM"


class TestMergeDerivationsDeFormCleanup:
    """merge_derivations must reduce two-word DE forms to a single matchable
    token — and must not confuse a separable-prefix split ("spart ein") with
    a free zu-infinitive ("zu verblüffen"), where the meaningful word is on
    the opposite side. Getting this backwards for the zu-case would register
    the bare particle "zu" as a lemma key and misfire on every occurrence of
    that word in running text — caught by the live round-trip test below."""

    def test_separable_prefix_split_keeps_first_word(self):
        table: dict[str, str] = {}
        vls.merge_derivations(
            {"en": [], "de": [{"infinitive": "einsparen", "forms": ["spart ein"]}]},
            {}, table,
        )
        assert table == {"spart": "einsparen"}

    def test_zu_infinitive_keeps_second_word(self):
        table: dict[str, str] = {}
        vls.merge_derivations(
            {"en": [], "de": [{"infinitive": "verblüffen", "forms": ["zu verblüffen"]}]},
            {}, table,
        )
        assert table == {"verblüffen": "verblüffen"}
        assert "zu" not in table, "must never register the bare particle 'zu' as a lemma key"


class TestLiveRoundTrip:
    """Makes a real LLM call. Requires OPENROUTER_API_KEY."""

    def test_sync_adds_plausible_forms_without_touching_real_files(
        self, tmp_real_lemma_tables, real_client
    ):
        en_path, de_path = tmp_real_lemma_tables
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

    def test_second_sync_is_idempotent_no_llm_call_needed(self, tmp_real_lemma_tables, real_client, capsys):
        """Once a verb is covered, re-running sync must not re-request it —
        this also verifies find_new_verb_pairs recognizes forms just added."""
        en_path, de_path = tmp_real_lemma_tables

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
