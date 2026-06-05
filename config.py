"""
config.py — Project-wide path configuration.

All machine-specific paths are read from .env so the codebase runs unchanged
on any OS or storage backend (OneDrive, Google Drive, plain folder).

Required .env key:
    WORK_DIR   Absolute path to the job storage root, e.g.
               Windows+OneDrive:  C:\\Users\\you\\OneDrive\\ArbeitNEU\\Comunica DK
               Linux+GDrive:      /home/you/GoogleDrive/ArbeitNEU/Comunica DK
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Code-side directories — always relative to this file, work on any OS
HERE         = Path(__file__).parent
PROJECTS_DIR = Path(os.environ.get("PROJECTS_DIR", str(HERE / "projects")))

# Storage root — the only value that differs between machines/backends
WORK_DIR      = Path(os.environ["WORK_DIR"])
SCORECARD_DIR = WORK_DIR / "scorecards"
