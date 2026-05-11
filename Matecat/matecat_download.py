# ============================================================
# matecat_download.py
# ============================================================
# Downloads the translated XLF from a MateCat project and
# saves it to projects/<pid>/.
#
# USAGE   python matecat_download.py [--pid <project_id>]
#           --pid   project folder name under projects/;
#                   defaults to current project context
#
# SETUP
#   MATECAT_COOKIE=...  in ../.env  (browser session cookie)
# ============================================================

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from project_log import project_dir as _pdir

BASE          = "https://www.matecat.com"
PROJECTS_FILE = HERE / "matecat_projects.json"

# ── Auth ──────────────────────────────────────────────────────────────────────

load_dotenv(dotenv_path=ROOT / ".env")
_cookie  = os.environ.get("MATECAT_COOKIE", "").strip()
_api_key = os.environ.get("MATECAT_API_KEY", "").strip()

if _cookie:
    HEADERS = {"Cookie": _cookie}
    print(f"Auth: session cookie ({_cookie[:20]}...)")
elif _api_key:
    HEADERS = {"x-matecat-key": _api_key}
    print(f"Auth: x-matecat-key")
else:
    print("ERROR: set MATECAT_COOKIE or MATECAT_API_KEY in .env")
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────

_ap = argparse.ArgumentParser()
_ap.add_argument("--pid", default=None,
                 help="Project ID (folder under projects/). Defaults to current context.")
_args = _ap.parse_args()

# ── Resolve project ───────────────────────────────────────────────────────────

if _args.pid:
    proj_dir = ROOT / "projects" / _args.pid
    if not proj_dir.exists():
        print(f"ERROR: Project folder not found: {proj_dir}")
        sys.exit(1)
else:
    proj_dir = _pdir()

project_id = proj_dir.name
client     = project_id.split("_")[0]
print(f"Project: {project_id}  (client: {client})")

# ── Look up MateCat project record ────────────────────────────────────────────

_registry   = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
client_data = _registry.get("clients", {}).get(client, {})
projects    = client_data.get("projects", [])

record = next((p for p in reversed(projects) if p["project_id"] == project_id), None)
if not record:
    print(f"ERROR: No MateCat record found for '{project_id}' in {PROJECTS_FILE.name}")
    print("  Run matecat_upload.py first.")
    sys.exit(1)

mc_id   = record["mc_id"]
mc_pass = record["mc_pass"]
print(f"MateCat project: id={mc_id}  pass={mc_pass[:6]}...")

# ── Step 1: Get job credentials ───────────────────────────────────────────────

print("\nStep 1 — Fetching job info...")
r = requests.get(
    f"{BASE}/api/v3/projects/{mc_id}/{mc_pass}",
    headers=HEADERS,
)
if not r.ok:
    print(f"ERROR: {r.status_code} — {r.text[:400]}")
    sys.exit(1)

proj_data = r.json()
print(f"  Raw response: {json.dumps(proj_data, ensure_ascii=False)[:400]}")

# Extract first job — response shape: project.analysis.jobs[]
jobs = proj_data.get("project", {}).get("analysis", {}).get("jobs", [])
if not jobs:
    print("ERROR: No jobs found in project response. Full response:")
    print(json.dumps(proj_data, indent=2, ensure_ascii=False)[:1000])
    sys.exit(1)

job      = jobs[0]
id_job   = job.get("id") or job.get("id_job")
# Password lives inside chunks[0], not on the job itself
chunks   = job.get("chunks", [])
job_pass = chunks[0].get("password") if chunks else None
print(f"  Job: id={id_job}  pass={str(job_pass)[:6] if job_pass else 'NOT FOUND'}")

# ── Step 2: Download translated file ──────────────────────────────────────────

print("\nStep 2 — Downloading translated file...")
r = requests.get(
    f"{BASE}/api/v3/translation/{id_job}/{job_pass}",
    headers=HEADERS,
)
print(f"  HTTP {r.status_code}  Content-Type: {r.headers.get('content-type', '?')}")

if not r.ok:
    print(f"ERROR: Download failed — {r.text[:400]}")
    sys.exit(1)

# Determine output filename — add _matecat suffix to distinguish from
# the filtered upload file which has the same base name.
content_disp = r.headers.get("content-disposition", "")
out_name = None
if "filename=" in content_disp:
    raw = content_disp.split("filename=")[-1].strip().strip('"').strip("'")
    stem, _, ext = raw.rpartition(".")
    out_name = f"{stem}_GERMAN.{ext}" if stem else f"{raw}_GERMAN"
if not out_name:
    out_name = f"{project_id}_GERMAN.xlf"

out_path = proj_dir / out_name
out_path.write_bytes(r.content)
print(f"  Saved: {out_path.name}  ({len(r.content):,} bytes)")

print(f"\nDone.  {out_path}")
