"""
project_log.py — shared project context and event log

Public API:
    project_dir()        → Path to active project's working folder in projects/
    load_context()       → full dict from current_project.json
    set_context(...)     → write current_project.json (called by xtrf_job_setup)
    log_event(...)       → append a state event to project_log.json
    get_processed_ids()  → set of Gmail message IDs already in the log
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
_CTX_FILE = HERE / "current_project.json"
_LOG_FILE = Path(os.environ.get("PROJECT_LOG_PATH", str(HERE / "project_log.json")))

def _read_log() -> dict:
    """Read and parse the log file. Raises RuntimeError if the file is corrupted."""
    if not _LOG_FILE.exists():
        return {}
    raw = _LOG_FILE.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        backup = _LOG_FILE.with_suffix(".json.bak")
        backup.write_text(raw, encoding="utf-8")
        raise RuntimeError(
            f"project_log.json is corrupted (backed up to {backup.name}). "
            "Fix or delete the backup before retrying."
        ) from exc


def get_all_logs() -> dict:
    """Returns the raw dictionary of all logged events."""
    return _read_log()
    
def load_context() -> dict:
    if not _CTX_FILE.exists():
        raise RuntimeError(
            "No active project. Run workflow.py to pick up a project from email."
        )
    return json.loads(_CTX_FILE.read_text(encoding="utf-8"))


def project_dir() -> Path:
    return Path(load_context()["project_folder"])


def find_project_dir(project_id: str) -> Path:
    """Scan the projects directory for the pre-processing folder containing project_id."""
    projects_root = Path(os.environ.get("WORK_DIR", str(HERE / "projects")))
    matches = [p for p in projects_root.iterdir() if p.is_dir() and project_id in p.name]
    if not matches:
        raise RuntimeError(f"Project folder not found for {project_id!r} in {projects_root}")
    matches.sort(key=lambda p: len(p.name), reverse=True)
    return matches[0] / "pre-processing"


def set_context(project_id: str, project_folder: Path, **extra) -> None:
    ctx = {
        "project_id": project_id,
        "project_folder": str(project_folder),
        "set_at": datetime.now().isoformat(),
        **extra,
    }
    _CTX_FILE.write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")


def log_event(message_id: str, state: str, detail: str | None = None) -> None:
    log = _read_log()
    existing_keys = set(log.keys())
    if message_id not in log:
        log[message_id] = {"events": []}
    entry: dict = {"state": state, "ts": datetime.now().isoformat()}
    if detail:
        entry["detail"] = detail
    log[message_id]["events"].append(entry)
    # Guardrail: every key that existed before must still be present
    if lost := (existing_keys - log.keys()):
        raise RuntimeError(f"BUG: log_event would silently drop entries {lost} — aborting write")
    # Atomic write: write to .tmp then rename so a crash mid-write never corrupts the log.
    # Retry loop handles transient PermissionError from OneDrive locking the target during sync.
    tmp = _LOG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(6):
        try:
            tmp.replace(_LOG_FILE)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.5)


def get_processed_ids() -> set[str]:
    """Return Gmail message IDs that already have LINK_EXTRACTED logged."""
    log = _read_log()
    return {
        msg_id
        for msg_id, entry in log.items()
        if any(e["state"] == "LINK_EXTRACTED" for e in entry.get("events", []))
    }
