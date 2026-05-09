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
    5a  Upload standard glossary (filtered to source terms) to Lara (requires .xlsx in project folder)
    5b  Pre-translation with Lara Translate API (requires *.xlsx in project folder)
    6   Consistency checks (verb + noun comparison)
    6b  Merge glossaries
    6c  LLM glossary cleanup → produces clean_glossary_<id>.csv
    --- MANUAL REVIEW: check clean_glossary_<id>.csv, edit if needed, press Enter ---
    7   Upload clean glossary to Lara
    8   Re-translate with clean glossary
    ---------End of this script, then manual steps:---------
    9  Run glossary_compare_revised_translation.py on this _translated.xlsx and revise the translation
    10 Run linter.py and fix issues
    11 Accept job on XTM (role!) and run xtm_upload.py to upload translation to XTM and check manually on the xTM workbench
    12 Download from XTM: xbench file and rund xbench check, download report
    13 Download from XTM:doc target file, biingual pdf preview and xlsx preview
    14 In XTM: assign job back to user group (role!)
    15 In XTRF: Upload files and finalize

Usage:
    python workflow_lara.py                     # step 3 (email) → 5 → 6 → 6b → 6c → pause → 7 → 8
    python workflow_lara.py SAGI_2604_P0039     # same, filtered to that project ID
    python workflow_lara.py --manual            # step 4 (manual URL) → same
    python workflow_lara.py --from-6c           # resume from step 6c (project already in log)
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


def step5a():
    print("Step 5a — Upload standard glossary (filtered to source terms)")
    _run(HERE / "lara_glossary_upload_standard.py")


def step5b():
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
    print("Step 6b — Merge glossaries")
    _run(HERE / "merge_glossaries.py", project_id)


def step6c():
    print("Step 6c — LLM glossary cleanup")
    _run(HERE / "llm_glossary_cleanup.py")


def manual_review(project_id: str):
    proj_dir = Path(project_log.project_dir())
    clean_path = proj_dir / f"clean_glossary_{project_id}.csv"
    print(f"\n{'─' * 60}")
    print(f"MANUAL REVIEW: {clean_path}")
    print("Edit the clean glossary if needed, then press Enter to upload and re-translate.")
    print(f"{'─' * 60}")
    input()


def step7():
    print("Step 7 — Upload clean glossary to Lara")
    _run(HERE / "lara_glossary_upload.py")


def step8():
    print("Step 8 — Re-translate with clean glossary")
    _run(HERE / "lara_translate.py")


if __name__ == "__main__":
    manual    = "--manual"  in sys.argv
    from_6c   = "--from-6c" in sys.argv
    from_7    = "--from-7"  in sys.argv
    args      = [a for a in sys.argv[1:] if not a.startswith("--")]
    target    = args[0] if args else None

    if from_6c or from_7:
        project_id = project_log.project_dir().name
        print(f"Resuming from step {'6c' if from_6c else '7'} — project: {project_id}")
    else:
        project_id = step4() if manual else step3(target_project_id=target)
        step5a()
        step5b()
        step6()
        step6b(project_id)

    if not from_7:
        step6c()
        manual_review(project_id)
    step7()
    step8()
