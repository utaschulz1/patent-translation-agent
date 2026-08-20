"""
test_config.py — Unit tests for config.py's is_issue_resolution_job.

Run with:  pytest test_config.py -v
"""
import pytest

from config import is_issue_resolution_job


def test_hourly_tasks_zero_value_is_issue_resolution():
    # Real overview shape confirmed live against a real XTRF job — the case
    # the old "issue" in type.lower() check would have missed entirely.
    overview = {
        "type": "Hourly tasks",
        "jobValue": {"value": 0, "currency": 1, "currencyISOCode": "EUR"},
    }
    assert is_issue_resolution_job(overview) is True


@pytest.mark.parametrize("label", ["Issue Resolution", "Issues resolution", "ISSUE RESOLUTION"])
def test_issue_resolution_label_any_case(label):
    overview = {"type": label, "jobValue": {"value": 0, "currencyISOCode": "EUR"}}
    assert is_issue_resolution_job(overview) is True


def test_issue_resolution_label_with_nonzero_price_still_detected():
    # Shouldn't happen in practice, but the keyword match is independent of price.
    overview = {"type": "Issue Resolution", "jobValue": {"value": 10, "currencyISOCode": "EUR"}}
    assert is_issue_resolution_job(overview) is True


def test_normal_paid_post_editing_job_not_flagged():
    overview = {"type": "Post-editing", "jobValue": {"value": 45.5, "currencyISOCode": "EUR"}}
    assert is_issue_resolution_job(overview) is False


def test_paid_hourly_tasks_job_not_flagged():
    # Confirmed with the user: "Hourly tasks" is also used at Comunica for
    # genuinely paid work unrelated to Issue Resolution, so "hourly" must
    # NOT be a blanket keyword match — only the 0-price signal should catch
    # the Issue-Resolution-flavored "Hourly tasks" jobs (see the
    # test_hourly_tasks_zero_value_is_issue_resolution case above). A future
    # edit adding "hourly" to the keyword list would misroute jobs like this
    # one through the free/no-glossary Issue Resolution path.
    overview = {"type": "Hourly tasks", "jobValue": {"value": 60, "currencyISOCode": "EUR"}}
    assert is_issue_resolution_job(overview) is False


def test_missing_job_value_does_not_crash():
    overview = {"type": "Revision"}
    assert is_issue_resolution_job(overview) is False


def test_missing_type_does_not_crash():
    overview = {"jobValue": {"value": 0}}
    assert is_issue_resolution_job(overview) is True  # price alone is enough
