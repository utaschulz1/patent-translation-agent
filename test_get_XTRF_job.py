"""
test_get_XTRF_job.py — Unit tests for get_XTRF_job.py's unusual-job-type handling.

Run with:  pytest test_get_XTRF_job.py -v
"""
from unittest.mock import MagicMock

import get_XTRF_job as gxj

_PROOFREADING_JOB = {
    "id": 373610,
    "overview": {
        "projectName": "Patents | MICTCH_2608_P0124",
        "type": "Proofreading",
        "deadline": "21-08-2026 11:00",
    },
}


def _mock_run(monkeypatch, jobs, isatty):
    """Wires run() up against fake jobs without any real network/log I/O."""
    monkeypatch.setattr(gxj, "_load_creds", lambda: {"email": "x", "password": "y"})
    monkeypatch.setattr(gxj, "_login", lambda session, creds: None)
    monkeypatch.setattr(gxj.project_log, "get_all_logs", lambda: {})
    logged = []
    monkeypatch.setattr(gxj.project_log, "log_event", lambda *a, **k: logged.append((a, k)))

    mock_session = MagicMock()
    mock_session.get.return_value.json.return_value = jobs
    mock_session.get.return_value.raise_for_status.return_value = None
    monkeypatch.setattr(gxj.requests, "Session", lambda: mock_session)
    monkeypatch.setattr(gxj.sys, "stdin", MagicMock(isatty=lambda: isatty))
    return logged


def test_unknown_job_type_auto_proceeds_when_non_interactive(monkeypatch):
    """Regression test for the Railway EOFError: a job type with no dedicated
    workflow must not block on input() when there's no terminal attached —
    it should proceed with the standard workflow (same as answering "Y" by
    hand), matching app.py's fetch_job route defaulting any unrecognized
    task_type to "post-editing"."""
    logged = _mock_run(monkeypatch, [_PROOFREADING_JOB], isatty=False)

    result = gxj.run()

    assert result is not None
    assert result[1] == "MICTCH_2608_P0124"
    assert logged  # LINK_EXTRACTED was logged — job was actually selected


def test_unknown_job_type_prompts_when_interactive(monkeypatch):
    """CLI usage (real terminal attached) keeps the original interactive
    Y/N confirmation behavior."""
    _mock_run(monkeypatch, [_PROOFREADING_JOB], isatty=True)
    monkeypatch.setattr("builtins.input", lambda *_: "Y")

    result = gxj.run()

    assert result is not None
    xtrf_url, project_id, job_id = result
    assert project_id == "MICTCH_2608_P0124"
    assert job_id == "373610"


def test_unknown_job_type_declined_interactively_is_skipped(monkeypatch):
    _mock_run(monkeypatch, [_PROOFREADING_JOB], isatty=True)
    monkeypatch.setattr("builtins.input", lambda *_: "N")

    result = gxj.run()

    assert result is None


def test_post_editing_job_never_prompts(monkeypatch):
    """A known type (post-editing) must proceed without touching input() at
    all, interactive or not — input() isn't mocked here, so this would raise
    if the code path were reached."""
    job = {
        "id": 111,
        "overview": {
            "projectName": "Patents | MICTCH_2608_P0125",
            "type": "Post-editing",
            "deadline": "21-08-2026 11:00",
        },
    }
    _mock_run(monkeypatch, [job], isatty=False)

    result = gxj.run()

    assert result is not None
    assert result[1] == "MICTCH_2608_P0125"
