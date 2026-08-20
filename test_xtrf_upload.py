"""
test_xtrf_upload.py — Unit tests for xtrf_upload.py's issue-resolution file
collection.

Run with:  pytest test_xtrf_upload.py -v
"""
import json

from xtrf_upload import _find_files_issue_resolution


def _write_manifest(pre_folder, xbench_upload_name):
    pre_folder.mkdir(parents=True)
    docx_path = pre_folder / "Document (Issue Resolution).docx"
    docx_path.write_text("stub")
    manifest = {
        "parts": [{"part": "Document", "renamed_docx": str(docx_path)}],
        "xbench_file": None if xbench_upload_name is None else str(pre_folder / "xbench.xlsx"),
        "xbench_kind": None if xbench_upload_name is None else "xlsx",
        "xbench_upload_name": xbench_upload_name,
    }
    (pre_folder / "issue_resolution_manifest.json").write_text(json.dumps(manifest))
    (pre_folder / "issue_resolution_status.json").write_text(json.dumps({
        "all_clean": True,
        "parts": [{"part": "Document", "clean": True, "problems": []}],
    }))
    return docx_path


def test_no_xbench_report_is_skipped_not_a_crash(tmp_path):
    folder = tmp_path / "project"
    docx_path = _write_manifest(folder / "pre-processing", xbench_upload_name=None)

    files = _find_files_issue_resolution(folder, part=None)

    assert files == [docx_path]


def test_xbench_report_present_is_included(tmp_path):
    folder = tmp_path / "project"
    xbench_path = folder / "pre-processing" / "xbench_checked.xlsx"
    docx_path = _write_manifest(folder / "pre-processing", xbench_upload_name=str(xbench_path))

    files = _find_files_issue_resolution(folder, part=None)

    assert files == [docx_path, xbench_path]
