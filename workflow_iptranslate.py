"""
workflow_iptranslate.py  —  Patent translation workflow runner (IP.appify pre-translation)

Steps
    3   Query XTRF vendor API for IN_PROGRESS jobs, pick job with earliest deadline
        → XTRF job setup (folders, source files, glossary)
        → XTM Excel download via API
    4   Manual mode: paste XTRF job URL instead of querying API
    5   Pre-translation with IP.appify (requires xlsx in project folder)
    6   Consistency checks (verb + noun comparison)
    6b  Merge glossaries (review and clean before next run)

Usage:
    python workflow_iptranslate.py                     # step 3 (XTRF API, earliest deadline) → 5 → 6 → 6b
    python workflow_iptranslate.py SAGI_2604_P0039     # step 3 filtered to that project ID
    python workflow_iptranslate.py --manual            # step 4 (manual URL) → 5 → 6 → 6b
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
    import get_XTRF_job
    extracted = get_XTRF_job.run(target_project_id=target_project_id)
    if not extracted:
        raise RuntimeError(
            "Step 3: no unprocessed IN_PROGRESS job found on XTRF.\n"
            "  → Check that the job is IN_PROGRESS on the XTRF vendor portal."
        )
    xtrf_url, project_id, job_id = extracted
    xtrf_job_setup.run(xtrf_url, project_id_override=project_id)
    if not xtm_download.run_workflow(project_id, msg_id=job_id):
        raise RuntimeError(f"Step 3: could not obtain xlsx/xlf for {project_id}.")
    return project_id


def step4() -> str:
    job = input("Step 4 — Paste XTRF job URL or ID: ").strip()
    result = xtrf_job_setup.run(job)
    project_id = result["project_id"]
    xtm_download.run_workflow(project_id)
    return project_id


def step5():
    print("Step 5 — Pre-translation with IP.appify")
    ctx = project_log.load_context()
    proj_folder = Path(ctx["project_folder"])
    existing = [f for f in proj_folder.glob("*.xlsx") if not f.name.startswith("~$")]
    if not existing:
        input(f"  Place XTM Excel in {proj_folder}, then press Enter...")
    else:
        print(f"  Found: {existing[0].name}")
    _run(HERE / "ipappify_translate_apikey.py")


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
