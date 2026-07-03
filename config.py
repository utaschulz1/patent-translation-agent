"""
config.py — Project-wide path configuration.

All machine-specific paths are read from .env so the codebase runs unchanged
on any OS or storage backend (OneDrive, Google Drive, plain folder).

Optional .env key:
    WORK_DIR   Absolute path to the job storage root. Defaults to agent/projects/.
               Windows+OneDrive:  C:\\Users\\you\\OneDrive\\ArbeitNEU\\Comunica DK
               Linux+GDrive:      /home/you/GoogleDrive/ArbeitNEU/Comunica DK
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Code-side directories — always relative to this file, work on any OS
HERE         = Path(__file__).parent
PROJECTS_DIR = Path(os.environ.get("PROJECTS_DIR", str(HERE / "projects")))

# Storage root — the only value that differs between machines/backends
WORK_DIR      = Path(os.environ.get("WORK_DIR", str(HERE / "projects")))
SCORECARD_DIR = WORK_DIR / "scorecards"

# Client code (2-6 uppercase letters) + YYMM + "P" + job number, e.g.
# "HUAW_2606_P1200". XTRF job type prefixes/suffixes around this core ID
# (e.g. "MT Light of HUAW_2606_P1200", "HBAS_2606_P0022 Issues resolution")
# must not become part of the project_id used for folders/lookups.
_PROJECT_ID_RE = re.compile(r"[A-Z]{2,6}_\d{4}_P\d{3,5}")


def extract_project_id(project_name: str) -> str:
    """Pull the canonical project ID out of an XTRF overview.projectName.

    XTRF projectName is e.g. "Patents | RTC_2604_P0732" or, for Light
    Post-editing / Issues resolution jobs, "Patents | MT Light of
    HUAW_2606_P1200". Only the core ID matters elsewhere (XTM task lookup,
    folder names) — strip everything else around it.
    """
    candidate = project_name.split("|")[-1].strip()
    m = _PROJECT_ID_RE.search(candidate)
    return m.group(0) if m else candidate
