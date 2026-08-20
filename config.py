"""
config.py — Project-wide path configuration.

All machine-specific paths are read from .env so the codebase runs unchanged
on any OS or storage backend (OneDrive, Google Drive, plain folder).

Optional .env key:
    WORK_DIR   Absolute path to the job storage root. Defaults to agent/projects/.
               Windows+OneDrive:  C:\\Users\\you\\OneDrive\\ArbeitNEU\\Comunica DK
               Linux+GDrive:      /home/you/GoogleDrive/ArbeitNEU/Comunica DK
    LLM_MODEL  OpenRouter model id used by the LLM glossary/verb-cleanup
               scripts. Defaults to "deepseek/deepseek-chat-v3-0324".
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

# OpenRouter model id shared by the LLM glossary/verb-cleanup scripts.
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat-v3-0324")

# Name the docx-comment-reply skill authors Issue Resolution reply comments
# as — check_docx_resolved.py uses this to tell "we replied" from "someone
# else's pre-existing reply" when checking whether a comment is resolved.
TRANSLATOR_NAME = os.environ.get("TRANSLATOR_NAME", "Uta Schulz")

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


def is_issue_resolution_job(overview: dict) -> bool:
    """True if an XTRF job overview is Issue Resolution / Issues Resolution work.

    XTRF's overview.type label for this isn't consistent — seen as "Issue
    Resolution" and, confirmed live against XTRF job #374882, "Hourly tasks"
    (case varies on both). A keyword match on the type field alone would have
    silently misrouted #374882 through the normal post-editing path instead
    of the Issue Resolution one. The one constant across every label variant
    seen so far is that these jobs are priced at 0 — job #374882's
    overview.jobValue was {"value": 0, "currency": 1, "currencyISOCode": "EUR"}.

    Checked as an OR with the "issue" keyword match, not a replacement for
    it: the price is the more reliable signal (doesn't depend on guessing
    XTRF's label of the day), but keeping the keyword match too means a
    clearly-labeled "Issue Resolution" job still gets caught even if a future
    job of that type is priced above 0 for some reason. The failure mode to
    avoid is a real Issue Resolution job going undetected, not the reverse —
    so either signal alone is enough.

    Args:
        overview: an XTRF job's overview dict (job["overview"] from
            GET /vendors/jobs/classic/{job_id}, or one entry of GET
            /vendors/jobs).

    Returns:
        True if the job's type label mentions "issue", or its jobValue is 0.
    """
    task_type = (overview.get("type") or "").lower()
    keyword_match = "issue" in task_type
    zero_value = (overview.get("jobValue") or {}).get("value") == 0
    return keyword_match or zero_value
