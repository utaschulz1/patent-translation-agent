"""
workflow.py  —  Patent translation workflow runner

Steps
    1 NOT IN THIS SCRIPT BUT IN A GOOGLE SCRIPT: every 5 minutes, check Gmail for "NEW JOB OFFER" by ComunicaDK, check calendar, if time, accept job, wait for start email, then add calendar entry with deadline, move start email to "TODO" label, move NEW JOB EMAIL to "Process" label
    2 NOT IN THIS SCRIPT BUT IN A GOOGLE SHEET: in google sheet, run email2sheet script to get all jobs into my accounting format to be pasted into my real accounting.
    ----------Start of this script:-------------
    3   Read Gmail (ComunicaDK/TODO), pick email with closest deadline
        → XTRF job setup (folders, source files, glossary)
        → XTM Excel download via API (fallback: Downloads folder)
    4   Manual mode: paste XTRF job URL instead of reading email
    5   Pre-translation with Lara Translate API (requires *_lara.xlsx in project folder)
    6   Consistency checks (verb + noun comparison)
    6b  Merge glossaries (review and clean before next run)
    ---------End of this script, then manual steps:---------
    7 After manual glossary cleaning, run lara_glossary_update to load project glossary into lara and to write glossary name into json
    8 Run lara_translate.py again on to update translation with glossary suggestions
    9 Run glossary_compare_revised_translation.py on this _translated.xlsx and revise the translation
    10 Run linter.py and fix issues
    11 Accept job on XTM (role!) and run xtm_upload.py to upload translation to XTM and check manually on the xTM workbench
    12 Download from XTM: xbench file and rund xbench check, download report
    13 Download from XTM:doc target file, biingual pdf preview and xlsx preview
    14 In XTM: assign job back to user group (role!)
    15 In XTRF: Upload files and finalize

Usage:
    python workflow_lara.py                     # step 3 (email, closest deadline) → 5 → 6 → 6b
    python workflow_lara.py SAGI_2604_P0039     # step 3 filtered to that project ID
    python workflow_lara.py --manual            # step 4 (manual URL) → 5 → 6 → 6b
"""

import subprocess
import sys
from pathlib import Path

import project_log
import xtrf_job_setup
import xtm_initial_download as xtm_download

HERE = Path(__file__).parent


def _run(script: Path, *args) -> None:
    result = subprocess.run([sys.executable, str(script), *args])
    if result.returncode != 0:
        raise RuntimeError(f"{script.name} exited with code {result.returncode}")


def step3(target_project_id: str | None = None) -> str:
    import get_XTRF_link
    extracted = get_XTRF_link.run(target_project_id=target_project_id)
    if not extracted:
        raise RuntimeError("Step 3: no project found in email intake.")
    xtrf_url, project_id, msg_id = extracted
    xtrf_job_setup.run(xtrf_url, project_id_override=project_id)
    if not xtm_download.run_workflow(project_id, msg_id=msg_id):
        raise RuntimeError(f"Step 3: could not obtain xlsx/xlf for {project_id}.")
    return project_id


def step4() -> str:
    job = input("Step 4 — Paste XTRF job URL or ID: ").strip()
    result = xtrf_job_setup.run(job)
    project_id = result["project_id"]
    xtm_download.run_workflow(project_id)
    return project_id


def step5():
    print("Step 5 — Pre-translation with Lara")
    ctx = project_log.load_context()
    proj_folder = Path(ctx["project_folder"])
    existing = [f for f in proj_folder.glob("*.xlsx") if not f.name.startswith("~$") and not f.name.endswith("_translated.xlsx")]
    if not existing:
        input(f"  Place XTM Excel in {proj_folder}, then press Enter...")
    else:
        print(f"  Found: {existing[0].name}")
    _run(HERE / "lara_translate.py")


def step6():
    print("Step 6 — Consistency checks")
    _run(HERE / "LLM_verb_comparison_xlsx.py")
    _run(HERE / "LLM_noun_comparison_xlsx.py")


def step6b(project_id: str):
    print("Step 6b — Merge glossaries → review and clean manually before next run")
    _run(HERE / "merge_glossaries.py", project_id)


if __name__ == "__main__":
    manual = "--manual" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else None
    project_id = step4() if manual else step3(target_project_id=target)
    step5()
    step6()
    step6b(project_id)
