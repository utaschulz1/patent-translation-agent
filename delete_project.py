"""
delete_project.py — Remove all app state for a fetched project.

Clears:
  - current_project.json  (reset to {})
  - project_log.json      (removes the entry keyed by xtrf_job_id)
  - workflow.db           (deletes project + workflow_steps rows)

Usage (local):
    python delete_project.py <project_id> [xtrf_job_id]

Usage (Railway — run from patent-translation-app/ in PowerShell):
    ~/.railway/bin/railway.exe run `
        --project 198f1cb5-1b9e-461b-af3a-7e6256c88b2a `
        --environment dfa296aa-9f7d-4d9a-8b2d-76230454bc79 `
        --service 9cefa5f3-4212-4127-8978-61fd79680590 `
        python agent/delete_project.py <project_id> [xtrf_job_id]

If xtrf_job_id is omitted, it is read from current_project.json or
workflow.db. If it cannot be determined, the project_log.json step is
skipped with a warning.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
_CTX_FILE = HERE / "current_project.json"
_LOG_FILE = Path(os.environ.get("PROJECT_LOG_PATH", str(HERE / "project_log.json")))
_DB_FILE = Path(os.environ.get("DB_PATH", os.environ.get("WORKFLOW_DB", str(HERE.parent / "patent-translation-app" / "workflow.db"))))


def _resolve_xtrf_job_id(project_id: str, given: str | None) -> str | None:
    if given:
        return given
    # Try current_project.json first
    if _CTX_FILE.exists():
        ctx = json.loads(_CTX_FILE.read_text(encoding="utf-8"))
        if ctx.get("project_id") == project_id and ctx.get("xtrf_job_id"):
            return str(ctx["xtrf_job_id"])
    # Fall back to workflow.db
    if _DB_FILE.exists():
        conn = sqlite3.connect(_DB_FILE)
        row = conn.execute(
            "SELECT xtrf_job_id FROM projects WHERE project_id=?", (project_id,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            return str(row[0])
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete all app state for a project.")
    parser.add_argument("project_id", help="e.g. LABI_2605_P0015")
    parser.add_argument("xtrf_job_id", nargs="?", help="XTRF job ID (inferred if omitted)")
    args = parser.parse_args()

    project_id = args.project_id
    xtrf_job_id = _resolve_xtrf_job_id(project_id, args.xtrf_job_id)

    # 1. current_project.json
    _CTX_FILE.write_text("{}", encoding="utf-8")
    print(f"current_project.json: cleared")

    # 2. project_log.json
    if xtrf_job_id:
        if _LOG_FILE.exists():
            log = json.loads(_LOG_FILE.read_text(encoding="utf-8"))
            if xtrf_job_id in log:
                del log[xtrf_job_id]
                _LOG_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"project_log.json: removed entry '{xtrf_job_id}'")
            else:
                print(f"project_log.json: entry '{xtrf_job_id}' not found — skipped")
        else:
            print("project_log.json: file not found — skipped")
    else:
        print(f"WARNING: could not determine xtrf_job_id for '{project_id}' — project_log.json not modified")

    # 3. workflow.db
    if _DB_FILE.exists():
        conn = sqlite3.connect(_DB_FILE)
        steps_deleted = conn.execute(
            "DELETE FROM workflow_steps WHERE project_id=?", (project_id,)
        ).rowcount
        project_deleted = conn.execute(
            "DELETE FROM projects WHERE project_id=?", (project_id,)
        ).rowcount
        conn.commit()
        conn.close()
        if project_deleted:
            print(f"workflow.db: deleted project row + {steps_deleted} step row(s)")
        else:
            print(f"workflow.db: project '{project_id}' not found — skipped")
    else:
        print(f"workflow.db: not found at {_DB_FILE} — skipped")


if __name__ == "__main__":
    main()
