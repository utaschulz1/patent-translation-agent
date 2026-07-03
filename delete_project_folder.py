"""
delete_project_folder.py — Delete the entire job folder for a project.

Usage:
    python delete_project_folder.py SAGI_2604_P0039
"""

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HERE = Path(__file__).parent
WORK_DIR = Path(os.environ.get("WORK_DIR", str(HERE / "projects"))).resolve()


def main():
    if len(sys.argv) < 2:
        print("Usage: delete_project_folder.py <project_id>")
        sys.exit(1)
    project_id = sys.argv[1]

    matches = [p for p in WORK_DIR.iterdir() if p.is_dir() and project_id in p.name]
    if not matches:
        print(f"ERROR: No job folder containing '{project_id}' found in {WORK_DIR}")
        sys.exit(1)

    job_folder = matches[0]
    print(f"Deleting {job_folder} ...")
    shutil.rmtree(job_folder)
    print(f"Done — deleted {job_folder.name}")


if __name__ == "__main__":
    main()
