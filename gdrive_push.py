"""
gdrive_push.py — Push current project folder to Google Drive.

Reads the active project from current_project.json (written by xtrf_job_setup).
Uploads all files in projects/{project_id}/ to GDRIVE_BASE_PATH/project_id/ on Drive.

Usage:
    python gdrive_push.py                   # uses current project from context
    python gdrive_push.py SAGI_2604_P0039   # specify project ID explicitly

Requires in .env (or Codespaces secrets):
    GDRIVE_CLIENT_ID
    GDRIVE_CLIENT_SECRET
    GDRIVE_REFRESH_TOKEN
    GDRIVE_BASE_PATH   (optional, default: patent-translation-app/ComunicaDK)
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

load_dotenv(Path(__file__).parent / ".env")

import project_log
from gdrive import gdrive_sync

HERE = Path(__file__).parent
GDRIVE_BASE_PATH = os.environ.get("GDRIVE_BASE_PATH", "patent-translation-app/ComunicaDK")


def main():
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        project_id = sys.argv[1]
        proj_folder = HERE / "projects" / project_id
    else:
        ctx = project_log.load_context()
        project_id = ctx["project_id"]
        proj_folder = Path(ctx["project_folder"])

    if not proj_folder.exists():
        print(f"ERROR: Project folder not found: {proj_folder}")
        sys.exit(1)

    print(f"Pushing {project_id} → Google Drive: {GDRIVE_BASE_PATH}/{project_id}/")
    gdrive_sync(proj_folder, GDRIVE_BASE_PATH, project_id)
    print("Done.")


if __name__ == "__main__":
    main()
