"""
test_issue_resolution_locate.py — Unit tests for issue_resolution_locate.py's
Xbench report filename matching and locate()'s missing-report handling.

Run with:  pytest test_issue_resolution_locate.py -v
"""
from pathlib import Path

import docx
import pytest

from issue_resolution_locate import XBENCH_XLSX_RE, XBENCH_TXT_RE, locate


@pytest.mark.parametrize("name", [
    "Xbench_QA_Report_German.xlsx",
    "Xbench_QA_Report.xlsx",
    # Real filename confirmed on a live job (FRKE_2608_P0736) — a double
    # extension left over from the report being re-saved through an older
    # Excel format after Xbench generated it.
    "Xbench_QA_Report_German.xlsx.xls",
])
def test_xbench_xlsx_matches(name):
    assert XBENCH_XLSX_RE.match(name)


@pytest.mark.parametrize("name", [
    "Xbench_QA_Report_German_checked.xlsx",  # this script's own prior output
    "Xbench_QA_Report_German.xls",  # no real .xlsx component — must not match
    "SomeOtherFile.xlsx",
])
def test_xbench_xlsx_does_not_match(name):
    assert not XBENCH_XLSX_RE.match(name)


def test_xbench_txt_matches():
    assert XBENCH_TXT_RE.match("No error found in Xbench report.txt")


def test_locate_proceeds_without_an_xbench_report(tmp_path):
    """Not every Issue Resolution deliverable includes an Xbench report — locate()
    must not raise when one isn't found, just leave the xbench_* fields None."""
    work_dir = tmp_path / "FRKE_0000_P0000" / "EN to DE" / "Task Files" / "Work Files"
    work_dir.mkdir(parents=True)

    docx.Document().save(work_dir / "Document_German (UT Issues).docx")
    # deliberately no Xbench_QA_Report*.xlsx or "No error found" txt in work_dir

    result = locate(tmp_path)

    assert result["xbench_file"] is None
    assert result["xbench_kind"] is None
    assert result["xbench_upload_name"] is None
    assert len(result["parts"]) == 1
