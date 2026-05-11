# ============================================================
# matecat_upload.py
# ============================================================
# Creates a MateCat project from the current XTM project's XLF:
#   1. Pre-processes the XLF — clears MT and <93% fuzzy targets
#      so they go to Lara; keeps 100% TM and >=93% fuzzy targets
#   2. Uploads clean_glossary CSV as terminology to the client TM key
#      (stored inside the TM with glos=true; drives underline/highlight in editor)
#   3. Creates a MateCat project (Lara engine, client TM key,
#      Lara glossary ID passed to Lara)
#   4. Polls until the project is created
#   5. Saves the project record to matecat_projects.json
#   6. Prints the project URL
#
# USAGE   python matecat_upload.py [--pid <project_id>]
#           --pid   project folder name under projects/;
#                   defaults to current project context
#
# SETUP
#   MATECAT_API_KEY=yourkey-yoursecret  in ../.env
#   TM keys and client mappings in matecat_projects.json
# ============================================================

import argparse
import csv
import json
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl
import requests
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from project_log import project_dir as _pdir

# ── Config ────────────────────────────────────────────────────────────────────

MIN_FUZZY_QUALITY = 93   # clear targets below this % before upload

BASE             = "https://www.matecat.com"
PROJECTS_FILE    = HERE / "matecat_projects.json"
LARA_GLOSSARIES  = ROOT / "lara_glossaries.json"

# ── Auth ──────────────────────────────────────────────────────────────────────
# MATECAT_COOKIE takes precedence (browser session cookie, e.g. matecat_login_v6=...).
# Falls back to x-matecat-key if no cookie is set.

load_dotenv(dotenv_path=ROOT / ".env")
_cookie = os.environ.get("MATECAT_COOKIE", "").strip()
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

# ── Load or discover client config ───────────────────────────────────────────

def _fetch_template_for_client(name: str) -> dict | None:
    """Query GET /api/v3/project-template and return the template matching name."""
    r = requests.get(f"{BASE}/api/v3/project-template", headers=HEADERS)
    if not r.ok:
        print(f"  Warning: could not fetch templates ({r.status_code}) — {r.text[:120]}")
        return None
    for tmpl in r.json().get("items", []):
        if tmpl.get("name", "").upper() == name.upper():
            return tmpl
    return None


def _find_glossary_tm_key(tm_entries: list[dict]) -> str | None:
    """Return the key of the first TM entry whose fields mention 'glossary'."""
    for entry in tm_entries:
        for v in entry.values():
            if isinstance(v, str) and "glossary" in v.lower():
                return entry.get("key")
    return None


_registry   = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
client_data = _registry.get("clients", {}).get(client)

_needs_template = not client_data or (
    not client_data.get("template_id") and not client_data.get("tm_key")
)

if _needs_template:
    print(f"  Client '{client}' has no TM config — querying MateCat templates...")
    tmpl = _fetch_template_for_client(client)
    if tmpl:
        # TM keys sorted by penalty ascending; first = primary, second = fallback
        tm_entries = sorted(tmpl.get("tm", []), key=lambda x: x.get("penalty", 0))
        tm_key_val      = tm_entries[0]["key"] if tm_entries else None
        tm_key_2_val    = tm_entries[1]["key"] if len(tm_entries) > 1 else None
        glos_tm_key_val = _find_glossary_tm_key(tm_entries)
        existing_projects = (client_data or {}).get("projects", [])
        client_data = {
            "template_id":     tmpl["id"],
            "tm_key":          tm_key_val,
            "tm_key_2":        tm_key_2_val,
            "glossary_tm_key": glos_tm_key_val,
            "projects":        existing_projects,
        }
        _registry.setdefault("clients", {})[client] = client_data
        PROJECTS_FILE.write_text(json.dumps(_registry, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Found template '{tmpl['name']}' (id={tmpl['id']}) — saved to {PROJECTS_FILE.name}")
        if tm_key_val:
            print(f"  TM key: {tm_key_val[:6]}...")
    else:
        print(f"  No MateCat template found for client '{client}'.")
        ans = input("  Continue without TM? [y/N] ").strip().lower()
        if ans != "y":
            print("  Aborted.")
            sys.exit(0)
        client_data = {"template_id": None, "tm_key": None, "tm_key_2": None, "projects": []}
        _registry.setdefault("clients", {})[client] = client_data

template_id = client_data.get("template_id")
print(f"Template: {template_id or 'none'}  ({client})")

# ── XLIFF namespace handling ──────────────────────────────────────────────────

_XLF_NS = "urn:oasis:names:tc:xliff:document:1.2"

def _ns(tag: str) -> str:
    return f"{{{_XLF_NS}}}{tag}"


def _register_all_namespaces(path: Path) -> None:
    """Register every namespace declared in the file so ET doesn't mangle them on write."""
    for _event, pair in ET.iterparse(str(path), events=["start-ns"]):
        prefix, uri = pair
        ET.register_namespace(prefix, uri)


def _clear_target(target: ET.Element) -> None:
    """Remove text and child elements from a <target> and reset its state."""
    target.text = None
    for child in list(target):
        target.remove(child)
    target.set("state-qualifier", "")
    target.set("state", "new")


# ── Step 1: Pre-process XLF ──────────────────────────────────────────────────

print("\nStep 1 — Pre-processing XLF...")

xlf_files = list(proj_dir.glob("*.xlf"))
if not xlf_files:
    print(f"ERROR: No .xlf file found in {proj_dir}")
    sys.exit(1)
if len(xlf_files) > 1:
    print(f"  Multiple .xlf files found, using: {xlf_files[0].name}")
xlf_path = xlf_files[0]
print(f"  Source: {xlf_path.name}")

_register_all_namespaces(xlf_path)
tree = ET.parse(xlf_path)
root_elem = tree.getroot()

kept = cleared = 0
for tu in root_elem.iter(_ns("trans-unit")):
    target = tu.find(_ns("target"))
    if target is None:
        continue

    sq = target.get("state-qualifier", "")

    if sq == "leveraged-tm":
        kept += 1
        continue

    if sq == "mt-suggestion":
        _clear_target(target)
        cleared += 1
        continue

    if sq == "fuzzy-match":
        best_q = 0.0
        for alt in tu.findall(_ns("alt-trans")):
            if "MACHINE" in alt.get("extype", "").upper():
                continue
            try:
                best_q = max(best_q, float(alt.get("match-quality", "0").rstrip("%")))
            except ValueError:
                pass
        if best_q >= MIN_FUZZY_QUALITY:
            kept += 1
        else:
            _clear_target(target)
            cleared += 1
        continue

    kept += 1  # unknown state-qualifier — keep to be safe

print(f"  Targets kept: {kept}   Cleared (MT / <{MIN_FUZZY_QUALITY}% fuzzy): {cleared}")

filtered_xlf = proj_dir / f"{project_id}_{xlf_path.name}"
tree.write(str(filtered_xlf), encoding="unicode", xml_declaration=True)
print(f"  Saved:  {filtered_xlf.name}")

# ── Step 2: Upload glossary to MateCat TM ────────────────────────────────────

print("\nStep 2 — Uploading glossary to MateCat glossary TM...")

_clean_csv       = proj_dir / f"clean_glossary_{project_id}.csv"
_raw_csv         = proj_dir / f"glossary_{project_id}.csv"
_glos_csv        = _clean_csv if _clean_csv.exists() else (_raw_csv if _raw_csv.exists() else None)
_glossary_tm_key = client_data.get("glossary_tm_key", "")

if not _glos_csv:
    print("  No glossary CSV found — skipping.")
elif not _glossary_tm_key:
    print("  No glossary_tm_key configured — skipping glossary upload.")
    print(f"  Create a 'Glossary' memory in MateCat, add it to the client template,")
    print(f"  then re-run (template will be re-fetched) or add 'glossary_tm_key' manually to {PROJECTS_FILE.name}.")
else:
    # Convert CSV → XLSX (MateCat requires XLSX; row 1 = language codes)
    _wb = openpyxl.Workbook()
    _ws = _wb.active
    _ws.append(["en-US", "de-DE", ""])
    _terms_added = _skipped = 0
    with open(_glos_csv, newline="", encoding="utf-8-sig") as _f:
        _lines = [_l for _l in _f if not _l.startswith("#")]
    for _row in csv.DictReader(_lines):
        _en = _row.get("EN", "").strip()
        _de = _row.get("DE", "").strip()
        if not _en or not _de:
            _skipped += 1
            continue
        _ws.append([_en, _de, ""])
        _terms_added += 1
    _tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    _tmp.close()
    _wb.save(_tmp.name)
    print(f"  {_terms_added} terms from {_glos_csv.name}  ({_skipped} skipped)")

    with open(_tmp.name, "rb") as _f:
        _r = requests.post(
            f"{BASE}/api/v3/glossaries/import/",
            headers=HEADERS,
            data={"tm_key": _glossary_tm_key},
            files={"file": (f"glossary_{project_id}.xlsx", _f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    os.unlink(_tmp.name)

    if _r.ok:
        print(f"  Upload started: {_r.status_code} — {_r.text[:200]}")
        # 202 = accepted; status endpoint is unreliable — trust the 202.
        print("  Glossary upload accepted (202).")
    else:
        print(f"  Warning: glossary upload failed ({_r.status_code}) — {_r.text[:200]}")
        print("  Continuing without glossary in TM.")

# ── Step 3: Create MateCat project ───────────────────────────────────────────

print("\nStep 3 — Creating MateCat project (Lara engine + Lara glossary)...")

lara_glossary_id = None
if LARA_GLOSSARIES.exists():
    _lara_reg = json.loads(LARA_GLOSSARIES.read_text(encoding="utf-8"))
    lara_glossary_id = _lara_reg.get(f"glossary_{project_id}")
    if lara_glossary_id:
        print(f"  Lara glossary: {lara_glossary_id}")

# POST /api/v1/new does NOT support project_template_id — all params inline.
# Auth via x-matecat-key header; if that is not activated on the account,
# set MATECAT_COOKIE in .env (browser session cookie) as a fallback.
tm_key          = client_data.get("tm_key") or ""
tm_key_2        = client_data.get("tm_key_2") or ""
glossary_tm_key = client_data.get("glossary_tm_key") or ""

if not tm_key:
    print("  Note: no tm_key configured — project will have no private TM.")
    print(f"  Create a TM in MateCat (My memories → + New), then add it to {PROJECTS_FILE.name}.")

if tm_key:
    print(f"  TM key: {tm_key[:6]}...")
if glossary_tm_key:
    print(f"  Glossary TM key: {glossary_tm_key[:6]}...")

form_data: dict = {
    "project_name":            project_id,
    "source_lang":             "en-US",
    "target_lang":             "de-DE",
    "mt_engine":               "12687",
    "pretranslate_100":        "1",
    "pretranslate_101":        "1",
    "get_public_matches":      "0",
    "qa_model_template_id":    "0",
    "payable_rate_template_id":"0",
    "filters_template_id":     "0",
    "xliff_config_template_id":"0",
}
# Pass TM keys as plain strings — multiple keys via repeated field (list of tuples)
_extra_fields: list[tuple[str, str]] = []
if tm_key:
    _extra_fields.append(("private_tm_key", tm_key))
if tm_key_2:
    _extra_fields.append(("private_tm_key", tm_key_2))
if glossary_tm_key:
    _extra_fields.append(("private_tm_key", glossary_tm_key))
if lara_glossary_id:
    form_data["lara_glossaries"] = json.dumps([lara_glossary_id])

with open(filtered_xlf, "rb") as f:
    r = requests.post(
        f"{BASE}/api/v1/new",
        headers=HEADERS,
        data=list(form_data.items()) + _extra_fields,
        files={"files[]": (filtered_xlf.name, f, "application/x-xliff+xml")},
    )

if not r.ok:
    print(f"ERROR: Project creation failed ({r.status_code}):\n{r.text[:500]}")
    sys.exit(1)

resp = r.json()
print(f"  Raw response: {json.dumps(resp, ensure_ascii=False)[:300]}")

id_project   = resp.get("id_project")
project_pass = resp.get("project_pass")

if not id_project or not project_pass:
    print("ERROR: Could not extract id_project / project_pass from response.")
    sys.exit(1)

print(f"  id_project={id_project}  pass={str(project_pass)[:6]}...")

# ── Step 5: Poll creation_status ──────────────────────────────────────────────

print("\nStep 4 — Polling creation status...")
for attempt in range(30):
    time.sleep(4)
    r = requests.get(
        f"{BASE}/api/v3/projects/{id_project}/{project_pass}/creation_status",
        headers=HEADERS,
    )
    if not r.ok:
        print(f"  Poll {attempt+1}: HTTP {r.status_code}")
        continue
    status = r.json().get("status", "?")
    print(f"  Poll {attempt+1}: {status}")
    if status in (200, "DONE", "CREATED", "OK"):
        print("  Project ready.")
        break
else:
    print("  Warning: project not ready after 30 polls — check MateCat manually.")

# ── Step 6: Save record & report ──────────────────────────────────────────────

project_url = (
    f"https://www.matecat.com/?action=editProject"
    f"&id_project={id_project}&password={project_pass}"
)

_proj_list = _registry["clients"][client].setdefault("projects", [])
_existing  = [p for p in _proj_list if p["project_id"] == project_id]
if _existing:
    print(f"\nWARNING: '{project_id}' already has {len(_existing)} record(s) in {PROJECTS_FILE.name}:")
    for _e in _existing:
        print(f"  mc_id={_e['mc_id']}  {_e['url']}")
    _ans = input("  Keep old record(s) and add new? [y/N] ").strip().lower()
    if _ans != "y":
        for _e in _existing:
            _proj_list.remove(_e)
        print("  Old record(s) removed — replacing with new upload.")
_proj_list.append({
    "project_id": project_id,
    "mc_id":      id_project,
    "mc_pass":    project_pass,
    "url":        project_url,
})
PROJECTS_FILE.write_text(
    json.dumps(_registry, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"\nRecord saved to {PROJECTS_FILE.name}")
print(f"\nDone.")
print(f"  {project_url}")


