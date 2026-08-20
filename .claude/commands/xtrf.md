# XTRF skill

You are helping with the two XTRF vendor portal scripts:
- `xtrf_job_setup.py` — step 4: download source files, create project folder, write glossary
- `xtrf_upload.py` — final step: upload 3 deliverable files to XTRF after translation is done

## Step 1 — Load context

Before answering, read:
1. The relevant script (`xtrf_job_setup.py` and/or `xtrf_upload.py`)
2. Any project memory files on XTRF upload/comment behavior, if present

## Step 2 — Domain knowledge

### Authentication

POST `https://CLIENT1.s.xtrf.eu/vendors/sign-in` with `{"email": ..., "password": ...}`
→ 204, sets `VP_PLAY_SESSION` session cookie (handled automatically by `requests.Session`).

Credentials from `.env`: `CLIENT1_JOBLIST_USERNAME` / `CLIENT1_JOBLIST_PASSWORD`.

### Key API endpoints

| Method | Endpoint | Used in |
|--------|----------|---------|
| POST | `/vendors/sign-in` | both scripts |
| GET | `/vendors/job/classic/{job_id}` | xtrf_job_setup.py (singular "job") |
| GET | `/vendors/jobs?statuses=IN_PROGRESS,...` | xtrf_upload.py (plural "jobs") |
| GET | `/vendors/jobs/classic/{job_id}/source-files/{file_id}` | xtrf_job_setup.py |
| POST | `/vendors/jobs/classic/{job_id}/target-files` | xtrf_upload.py |
| GET | `/vendors/jobs/classic/{job_id}/target-files` | xtrf_upload.py (verify) |
| PUT | `/vendors/jobs/classic/{job_id}/comments` | xtrf_post_comment.py |

### Posting a job comment (xtrf_post_comment.py)

Confirmed live 2026-08-20 via a captured browser request (Firefox DevTools,
posting a real comment through the XTRF web UI):

```
PUT /vendors/jobs/classic/{job_id}/comments
Content-Type: text/plain; charset=utf-8
Time-Zone-Offset-In-Minutes: 60

<raw comment text, no JSON wrapping, no field name>
```

`GET` on the same path returns 200 with an empty body when a job has no
comments yet (tried on 3 different live jobs, all empty) — there was no
existing comment to inspect the read-side shape from, only the write side
was confirmed. `POST` to the same path returns 404 (not a valid route) —
writing is done via `PUT`, which is easy to miss since it's an unusual verb
choice for "add a comment" (more commonly modeled as POST-to-collection).
An empty/garbage `PUT` body was tried first as a safe probe and returned 200
without visibly changing anything (confirmed via a follow-up GET) — but
don't rely on that leniency for anything other than initial discovery; the
real payload is untyped raw text, so a wrong-shaped write is a real risk to
what appears on a live job's comment thread.

Note: the job-detail endpoint uses singular `/job/classic/` while the jobs-list and target-files
endpoints use plural `/jobs/classic/`. This asymmetry is intentional and matches the live API.

### xtrf_upload.py — file matching rules

The script searches the client project folder (matched by `project_id` substring in folder name
within `WORK_DIR`) for exactly:
- One `*_German*.docx` — translated claims/description docx
- One `*_German*.pdf` — bilingual PDF
- One `project_QA_Report_*.xlsx` — QA report

Errors loudly if any is missing or ambiguous. Upload is one file per POST request (not batched).

### Job lookup

`xtrf_upload.py` searches `IN_PROGRESS,IN_PROGRESS_AWAITING_CORRECTIONS,PENDING` jobs and matches
by `overview.projectName` containing the given `project_id`. The projectName may have a
`"Patents | "` prefix (e.g. `"Patents | <CLIENT_CODE>_<YYMM>_P<NNNN>"`) — the `in` check handles both forms.

## Step 3 — Typical tasks this skill is invoked for

- **Debugging upload failures**: check that the job status is IN_PROGRESS (not PENDING or done);
  check file naming matches `*_German*` pattern; check XTRF session cookie is fresh.
- **File not found errors**: verify `WORK_DIR` folder name contains the project_id; check that
  `xtm_final_download.py` has been run and files are in the client project folder (not the code folder).
- **Job not found**: the job may be in a different status — temporarily broaden the statuses list,
  or pass the numeric job ID directly if known.
- **Extending xtrf_job_setup.py**: reuse `_login` and `_make_session` patterns; always use
  singular `/job/classic/` for job detail fetches.
