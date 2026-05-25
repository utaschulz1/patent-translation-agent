# XTRF skill

You are helping with the two XTRF vendor portal scripts:
- `xtrf_job_setup.py` — step 4: download source files, create project folder, write glossary
- `xtrf_upload.py` — final step: upload 3 deliverable files to XTRF after translation is done

## Step 1 — Load context

Before answering, read:
1. The relevant script (`xtrf_job_setup.py` and/or `xtrf_upload.py`)
2. Memory file: `C:\Users\utasc\.claude\projects\c--Users-utasc-OneDrive-Dokumente-Code-Python-patent-translation-agent\memory\xtrf_upload.md`

## Step 2 — Domain knowledge

### Authentication

POST `https://comunicadk.s.xtrf.eu/vendors/sign-in` with `{"email": ..., "password": ...}`
→ 204, sets `VP_PLAY_SESSION` session cookie (handled automatically by `requests.Session`).

Credentials from `.env`: `COMUNICA_JOBLIST_USERNAME` / `COMUNICA_JOBLIST_PASSWORD`.

### Key API endpoints

| Method | Endpoint | Used in |
|--------|----------|---------|
| POST | `/vendors/sign-in` | both scripts |
| GET | `/vendors/job/classic/{job_id}` | xtrf_job_setup.py (singular "job") |
| GET | `/vendors/jobs?statuses=IN_PROGRESS,...` | xtrf_upload.py (plural "jobs") |
| GET | `/vendors/jobs/classic/{job_id}/source-files/{file_id}` | xtrf_job_setup.py |
| POST | `/vendors/jobs/classic/{job_id}/target-files` | xtrf_upload.py |
| GET | `/vendors/jobs/classic/{job_id}/target-files` | xtrf_upload.py (verify) |

Note: the job-detail endpoint uses singular `/job/classic/` while the jobs-list and target-files
endpoints use plural `/jobs/classic/`. This asymmetry is intentional and matches the live API.

### xtrf_upload.py — file matching rules

The script searches the ComunicaDK project folder (matched by `project_id` substring in folder name
within `WORK_DIR`) for exactly:
- One `*_German*.docx` — translated claims/description docx
- One `*_German*.pdf` — bilingual PDF
- One `project_QA_Report_*.xlsx` — QA report

Errors loudly if any is missing or ambiguous. Upload is one file per POST request (not batched).

### Job lookup

`xtrf_upload.py` searches `IN_PROGRESS,IN_PROGRESS_AWAITING_CORRECTIONS,PENDING` jobs and matches
by `overview.projectName` containing the given `project_id`. The projectName may have a
`"Patents | "` prefix (e.g. `"Patents | HALA_2605_P0454"`) — the `in` check handles both forms.

## Step 3 — Typical tasks this skill is invoked for

- **Debugging upload failures**: check that the job status is IN_PROGRESS (not PENDING or done);
  check file naming matches `*_German*` pattern; check XTRF session cookie is fresh.
- **File not found errors**: verify `WORK_DIR` folder name contains the project_id; check that
  `xtm_final_download.py` has been run and files are in the ComunicaDK folder (not the code folder).
- **Job not found**: the job may be in a different status — temporarily broaden the statuses list,
  or pass the numeric job ID directly if known.
- **Extending xtrf_job_setup.py**: reuse `_login` and `_make_session` patterns; always use
  singular `/job/classic/` for job detail fetches.
