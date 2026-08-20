"""
test_xtrf_post_comment.py — Unit tests for xtrf_post_comment.py.

Run with:  pytest test_xtrf_post_comment.py -v
"""
import json
from unittest.mock import MagicMock, patch

import pytest

import xtrf_post_comment as xpc


def _write_status(pre_folder, all_clean, any_needed_work):
    pre_folder.mkdir(parents=True, exist_ok=True)
    (pre_folder / "issue_resolution_status.json").write_text(json.dumps({
        "all_clean": all_clean,
        "any_needed_work": any_needed_work,
        "parts": [],
    }))


@pytest.mark.parametrize("any_needed_work, has_corrections, expected", [
    (False, False, "no_action"),
    (True, False, "resolved_no_xtm"),
    (True, True, "resolved_with_xtm"),
])
def test_determine_outcome(tmp_path, monkeypatch, any_needed_work, has_corrections, expected):
    pre_folder = tmp_path / "pre-processing"
    _write_status(pre_folder, all_clean=True, any_needed_work=any_needed_work)
    if has_corrections:
        (pre_folder / "Final_x_revised_translation_checks_issue_resolution.xlsx").write_text("stub")

    monkeypatch.setattr(xpc.project_log, "find_project_dir", lambda pid: pre_folder)
    assert xpc.determine_outcome("PID") == expected


def test_determine_outcome_refuses_when_not_all_clean(tmp_path, monkeypatch):
    pre_folder = tmp_path / "pre-processing"
    _write_status(pre_folder, all_clean=False, any_needed_work=True)
    monkeypatch.setattr(xpc.project_log, "find_project_dir", lambda pid: pre_folder)
    with pytest.raises(ValueError, match="not all parts are resolved"):
        xpc.determine_outcome("PID")


def test_dry_run_does_not_call_put(tmp_path, monkeypatch, capsys):
    pre_folder = tmp_path / "pre-processing"
    _write_status(pre_folder, all_clean=True, any_needed_work=False)
    monkeypatch.setattr(xpc.project_log, "find_project_dir", lambda pid: pre_folder)

    fake_session = MagicMock()
    with patch.object(xpc, "_load_creds", return_value={}), \
         patch.object(xpc, "_make_session", return_value=fake_session), \
         patch.object(xpc, "_login"), \
         patch.object(xpc, "_find_job_id", return_value=374882):
        xpc.run("PID", dry_run=True)

    fake_session.put.assert_not_called()
    out = capsys.readouterr().out
    assert "[DRY RUN]" in out
    assert "374882" in out


def test_live_put_sends_raw_text_body_no_json_wrapping(tmp_path, monkeypatch):
    """Regression test for the confirmed real request shape: PUT with the raw
    comment text as the body (Content-Type: text/plain), not a JSON object —
    confirmed 2026-08-20 via a captured browser request where a 17-character
    comment produced exactly Content-Length: 17."""
    pre_folder = tmp_path / "pre-processing"
    _write_status(pre_folder, all_clean=True, any_needed_work=False)
    monkeypatch.setattr(xpc.project_log, "find_project_dir", lambda pid: pre_folder)

    fake_session = MagicMock()
    fake_session.put.return_value = MagicMock(raise_for_status=lambda: None)

    with patch.object(xpc, "_load_creds", return_value={}), \
         patch.object(xpc, "_make_session", return_value=fake_session), \
         patch.object(xpc, "_login"), \
         patch.object(xpc, "_find_job_id", return_value=374882):
        xpc.run("PID", dry_run=False)

    fake_session.put.assert_called_once()
    args, kwargs = fake_session.put.call_args
    assert args[0] == f"{xpc.BASE_URL}/jobs/classic/374882/comments"
    assert kwargs["data"] == xpc.TEMPLATES["no_action"].encode("utf-8")
    assert kwargs["headers"]["Content-Type"] == "text/plain; charset=utf-8"
