"""
workflow.py  —  Patent translation workflow runner

Steps
    1 NOT IN THIS SCRIPT BUT IN A GOOGLE SCRIPT: every 5 minutes, check XTRF for "NEW JOB OFFER" by ComunicaDK, check calendar, if time, accept job, wait for start email, then add calendar entry with deadline, move start email to "TODO" label, move NEW JOB EMAIL to "Process" label
    2 NOT IN THIS SCRIPT BUT IN A GOOGLE SHEET: in google sheet, run email2sheet script to get all jobs into my accounting format to be pasted into my real accounting.
    ----------Start of this script:-------------
    3   Query XTRF vendor API for IN_PROGRESS jobs, pick job with earliest deadline
        → XTRF job setup (folders, source files, glossary)
        → XTM Excel download via API
    4   Manual mode: paste XTRF job URL instead of querying API
    5a  Upload standard glossary (filtered to source terms) to Lara (requires .xlsx in project folder)
    5b  Pre-translation with Lara Translate API (requires *.xlsx in project folder)
    6   Consistency checks (verb + noun + capability-predicate comparison)
    6b  Merge glossaries
    6c  LLM glossary cleanup → produces clean_glossary_<id>.csv
    --- MANUAL REVIEW: check clean_glossary_<id>.csv, edit if needed, press Enter ---
    7   Upload clean glossary to Lara
    8   Convert clean glossary to TMX + XLSX (Matecat/CSV2TMX-XLSX.py --xlsx)
    9   Pause → translate in Matecat (manual setup: upload glossary .xlsx via swagger)
    10  Export XLF → Excel (matecat_xlf_to_excel.py), glossary check, linter check
        → Pause → fix issues in Matecat, accept job on XTM (role!), re-export XLF
    11  Upload revised Matecat XLF to XTM (matecat_xtm_upload.py) — check manually in XTM workbench
    ---------End of this script, then manual steps:---------
    12 Manual: Download from XTM: xbench file and run xbench check, correct issues, download clean, create Xbench report in xbench
    12b re-check  running matecat_xtm_verify.py (will use the downloaded xbench file) to make shure that XTM and Matecat are identical, fix any discrepancies
    13 Run xtm_final_download.py to download from XTM:doc target file, biingual pdf preview and xlsx preview
    14 In XTM: manually assign job back to user group (role!)
    15 Run xtrf_upload.py to upload delivery files to XTRF, finalize manually in XTRF

Usage:
    python workflow_lara.py                     # step 3 (XTRF API, earliest deadline) → 5 → 6 → 6b → 6c → pause → 7 → 8
    python workflow_lara.py SAGI_2604_P0039     # same, filtered to that project ID
    python workflow_lara.py --manual            # step 4 (manual URL, prompts for URL) → same
    python workflow_lara.py --manual <url>      # step 4, URL passed directly (no prompt)
    python workflow_lara.py --from-5a                        # resume from step 5a (source doc already in project folder)
    python workflow_lara.py --from-5b                        # resume from step 5b (glossary uploaded, retry pre-translation)
    python workflow_lara.py --from-6                         # resume from step 6 (re-run LLM checks + merge + cleanup)
    python workflow_lara.py --from-6 --seg-range 421-488    # example, claims only
    python workflow_lara.py --from-6b                        # resume from step 6b (LLM checks done, merge glossaries)
    python workflow_lara.py --from-6c                        # resume from step 6c (glossary merged, run LLM cleanup)
    python workflow_lara.py --from-7                         # resume from step 7 (after manual review)
    python workflow_lara.py --from-9                         # resume from step 9 (Matecat translation done, run export + checks + upload)
    python workflow_lara.py --from-10                        # resume from step 10 (re-run export + checks)
    python workflow_lara.py --from-11                        # resume from step 11 (upload XLF to XTM)
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


def _crash(step_label: str, err: RuntimeError, seg_range: str | None) -> None:
    range_part = f" --seg-range {seg_range}" if seg_range else ""
    print(f"\n{'─' * 60}")
    print(f"CRASH at step {step_label}: {err}")
    print(f"Fix the problem, then resume with:")
    print(f"  python workflow_lara.py --from-{step_label}{range_part}")
    print(f"{'─' * 60}")
    sys.exit(1)


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


def step4(url: str | None = None) -> str:
    job = url or input("Step 4 — Paste XTRF job URL or ID: ").strip()
    result = xtrf_job_setup.run(job)
    project_id = result["project_id"]
    xtm_download.run_workflow(project_id)
    return project_id


def step5a():
    print("Step 5a — Upload standard glossary (filtered to source terms)")
    _run(HERE / "lara_glossary_upload_standard.py")


def step5b(seg_range: str | None = None):
    print("Step 5 — Pre-translation with Lara")
    ctx = project_log.load_context()
    proj_folder = Path(ctx["project_folder"])
    existing = [f for f in proj_folder.glob("*.xlsx") if not f.name.startswith("~$") and not f.name.endswith("_translated.xlsx")]
    if not existing:
        input(f"  Place XTM Excel in {proj_folder}, then press Enter...")
    else:
        print(f"  Found: {existing[0].name}")
    range_args = ["--seg-range", seg_range] if seg_range else []
    _run(HERE / "lara_translate.py", *range_args)


def step6(seg_range: str | None = None):
    range_args = seg_range.replace("-", " ").split() if seg_range else []
    label = f" (segments {seg_range})" if seg_range else ""
    print(f"Step 6 — Consistency checks{label}")
    _run(HERE / "LLM_verb_comparison_xlsx.py",        *range_args)
    _run(HERE / "LLM_noun_comparison_xlsx.py",        *range_args)
    _run(HERE / "LLM_capability_comparison_xlsx.py",  *range_args)



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
    print("Edit the clean glossary if needed, then press Enter to upload and convert to xlsx.")
    print(f"{'─' * 60}")
    input()


def step7():
    print("Step 7 — Upload clean glossary to Lara")
    _run(HERE / "lara_glossary_upload.py")


def step8(project_id: str):
    print("Step 8 — Convert clean glossary to TMX + XLSX")
    proj_dir = Path(project_log.project_dir())
    clean_path = proj_dir / f"clean_glossary_{project_id}.csv"
    _run(HERE / "Matecat" / "CSV2TMX-XLSX.py", "--xlsx", str(clean_path))


def step9():
    print(f"\n{'─' * 60}")
    print("Step 9 — Translate in Matecat")
    print("Set up Matecat project (upload glossary .xlsx via swagger if needed)")
    print("and complete the translation, then press Enter to run export and checks.")
    print(f"{'─' * 60}")
    input()


def step10(project_id: str):
    print("Step 10 — Export XLF → Excel, glossary check, linter check")
    _run(HERE / "Matecat" / "matecat_xlf_to_excel.py", "--pid", project_id)
    _run(HERE / "glossary_compare_revised_translation.py", "--pid", project_id)
    _run(HERE / "linter.py", "--pid", project_id)
    print(f"\n{'─' * 60}")
    print("Step 10 done — review the checks above, fix any issues in Matecat,")
    print("then: (1) accept the job on XTM (role!), (2) re-export the XLF from Matecat,")
    print("then press Enter to upload the revised XLF to XTM.")
    print(f"{'─' * 60}")
    input()


def step11(project_id: str):
    print("Step 11 — Upload revised Matecat XLF to XTM")
    answer = input(f'  Upload translation for project "{project_id}"? [Y/N]: ').strip().upper()
    if answer != "Y":
        print("  Aborted.")
        sys.exit(0)
    _run(HERE / "Matecat" / "matecat_xtm_upload.py", project_id)


if __name__ == "__main__":
    manual     = "--manual"  in sys.argv
    from_5a    = "--from-5a" in sys.argv
    from_5b    = "--from-5b" in sys.argv
    from_6     = "--from-6"  in sys.argv
    from_6b    = "--from-6b" in sys.argv
    from_6c    = "--from-6c" in sys.argv
    from_7     = "--from-7"  in sys.argv
    from_9     = "--from-9"  in sys.argv
    from_10    = "--from-10" in sys.argv
    from_11    = "--from-11" in sys.argv
    seg_range  = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--seg-range" and i + 1 < len(sys.argv)),
        None,
    )
    args       = [a for a in sys.argv[1:] if not a.startswith("--")]
    target     = args[0] if args and not manual else None
    manual_url = args[0] if args and manual else None

    if from_5a or from_5b or from_6 or from_6b or from_6c or from_7 or from_9 or from_10 or from_11:
        project_id = project_log.project_dir().name
        label = ("5a" if from_5a else "5b" if from_5b else "6" if from_6
                 else "6b" if from_6b else "6c" if from_6c else "7" if from_7
                 else "9" if from_9 else "10" if from_10 else "11")
        print(f"Resuming from step {label} — project: {project_id}")
    else:
        try:
            project_id = step4(manual_url) if manual else step3(target_project_id=target)
        except RuntimeError as e:
            _crash("3/4", e, seg_range)

    skip_to_6  = from_6  or from_6b or from_6c or from_7 or from_9 or from_10 or from_11
    skip_to_6b = from_6b or from_6c or from_7 or from_9 or from_10 or from_11
    skip_to_6c = from_6c or from_7 or from_9 or from_10 or from_11
    skip_to_9  = from_9  or from_10 or from_11
    skip_to_10 = from_10 or from_11
    skip_to_11 = from_11

    if not skip_to_6:
        if not from_5b:
            try:
                step5a()
            except RuntimeError as e:
                _crash("5a", e, seg_range)
        try:
            step5b(seg_range)
        except RuntimeError as e:
            _crash("5b", e, seg_range)

    if not skip_to_6b:
        try:
            step6(seg_range)
        except RuntimeError as e:
            _crash("6", e, seg_range)

    if not skip_to_6c:
        try:
            step6b(project_id)
        except RuntimeError as e:
            _crash("6b", e, seg_range)

    if not from_7 and not skip_to_9:
        try:
            step6c()
        except RuntimeError as e:
            _crash("6c", e, seg_range)
        manual_review(project_id)

    if not skip_to_9:
        try:
            step7()
        except RuntimeError as e:
            _crash("7", e, seg_range)

        try:
            step8(project_id)
        except RuntimeError as e:
            _crash("8", e, seg_range)

    if not skip_to_10:
        step9()

    if not skip_to_11:
        try:
            step10(project_id)
        except RuntimeError as e:
            _crash("10", e, seg_range)

    try:
        step11(project_id)
    except RuntimeError as e:
        _crash("11", e, seg_range)
