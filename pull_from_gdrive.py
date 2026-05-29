"""
pull_from_gdrive.py — Pull a Railway-synced project folder from Google Drive into
projects/ and set it as the active project.

Usage:
    python pull_from_gdrive.py <project_id>

.env keys (both optional, shown with defaults):
    RCLONE_REMOTE      rclone remote name configured via 'rclone config'  (default: gdrive)
    GDRIVE_BASE_PATH   GDrive folder that Railway syncs into               (default: patent-translation-app/ComunicaDK)

One-time setup (run once in a terminal):
    rclone config   → follow prompts to add a Google Drive remote named 'gdrive'
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

import project_log
from config import PROJECTS_DIR

load_dotenv(Path(__file__).parent / ".env")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python pull_from_gdrive.py <project_id>")
        sys.exit(1)

    project_id = sys.argv[1].strip()
    remote    = os.environ.get("RCLONE_REMOTE", "gdrive")
    base_path = os.environ.get("GDRIVE_BASE_PATH", "patent-translation-app/ComunicaDK")
    rclone    = os.environ.get("RCLONE_EXE", "rclone")

    src = f"{remote}:{base_path}/{project_id}"
    dst = PROJECTS_DIR / project_id
    dst.mkdir(parents=True, exist_ok=True)

    print(f"Pulling {src}  →  {dst}")
    result = subprocess.run(
        [rclone, "copy", src, str(dst), "--progress"],
    )

    if result.returncode != 0:
        print(f"ERROR: rclone exited with code {result.returncode}")
        sys.exit(result.returncode)

    files = sorted(f.name for f in dst.iterdir() if f.is_file())
    print(f"\n{len(files)} file(s) in {dst}:")
    for name in files:
        print(f"  {name}")

    project_log.set_context(project_id, dst)
    print(f"\nActive project set to: {project_id}")


if __name__ == "__main__":
    main()
