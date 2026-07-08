# patent-translation-agent

Automation scripts for EN→DE patent translation. The scripts are orchestrated by
the FastAPI app in the parent repository (`patent-translation-app`). Individual
scripts can also be run standalone for debugging.

---

## Project structure

```
patent-translation-agent/
│
├── get_XTRF_job.py               Fetch pending jobs from XTRF job list
├── xtrf_job_setup.py             XTRF login → create folders → download sources → glossary CSV
│
├── xtm_initial_download.py       XTM download → xlsx + xliff to project folder
├── xtm_upload_translations.py    Upload revised translation xlsx back to XTM
├── xtm_final_download.py         Final XTM download (docx/PDF/xlsx deliverables)
├── xtm_probe_preview_types.py    Helper: probe available XTM preview types
│
├── ice_tm_creation.py            Extract ICE/100% XLF matches → create Lara TM (no-op if no matches)
├── add_client_tm.py              Resolve client TM by acronym → register client_memory_{pid}
├── import_segments.py            Parse source XLF → write segments to workflow.db for CAT UI
├── lara_translate.py             Lara pre-translation (ICE TM + client TM + glossary via adapt_to)
├── lara_segment.py               Per-segment Lara translation for CAT UI + update_project_tm()
├── lara_glossary_upload.py       Upload project glossary to Lara
├── lara_glossary_download.py     Download glossary from Lara
├── lara_glossary_upload_standard.py  Upload standard glossary to Lara
│
├── ipappify_translate.py         IP.appify pre-translation (Azure B2C auth — legacy)
├── ipappify_translate_apikey.py  IP.appify pre-translation (API key auth — current)
│
├── LLM_verb_comparison_xlsx.py   Verb consistency check → verb_flags.csv + _checks.xlsx
├── LLM_noun_comparison_xlsx.py   Noun consistency check → noun_inconsistency_table.csv
├── LLM_capability_comparison_xlsx.py  Capability consistency check
├── merge_glossaries.py           Merge verb/noun/standard glossaries → project glossary
├── llm_glossary_cleanup.py       LLM-based cleanup of merged glossary (DeepSeek V3 via OpenRouter)
├── glossary_compare.py           Rule-based glossary mismatch check on translated output
├── glossary_compare_revised_translation.py  Glossary check on revised translation
├── linter.py                     Terminology linter — detects forbidden patterns in DE text
│
├── xtrf_upload.py                Upload deliverables to XTRF vendor portal
├── delete_project.py             Remove project from workflow.db
├── delete_project_folder.py      Delete local project folder (confirm backup first)
│
├── project_log.py                Shared: project context, find_project_dir(), event log
├── config.py                     Shared configuration
├── consolidate_scorecards.py     Consolidate QA scorecards across segments
│
├── standard_glossary.csv         Shared EN→DE terminology used by merge_glossaries.py
│
├── lara_glossaries.json          Registry: project_id → Lara glossary ID (written at upload)
├── lara_memories.json            Registry: memory_{pid} (ICE TM), client_memory_{pid}, client_tms (by acronym)
├── DE_verb_lemma_lookup.json     DE verb lemma lookup table (spacy pre-computed)
├── EN_verb_lemma_lookup.json     EN verb lemma lookup table (spacy pre-computed)
├── linter_categories.json        Category definitions for the terminology linter
├── scorecard_log.json            Cross-project QA scorecard log
│
├── Matecat/                      Matecat integration scripts
│   ├── matecat_upload.py
│   ├── matecat_download.py
│   ├── matecat_xtm_upload.py     XLF upload from Matecat to XTM
│   ├── matecat_xtm_verify.py
│   ├── matecat_glossary_upload.py
│   ├── matecat_info.py
│   ├── matecat_xlf_to_excel.py
│   ├── XLF2TMX.py
│   ├── CSV2TMX-XLSX.py
│   ├── Excel2TMX.py
│   └── extract_xlf_from_xbpkg.py
│
├── utilities/                    One-off and alignment tools
│   ├── align_docx.py
│   ├── sort_csv_alphabet.py
│   ├── extract_align_bilingual_pdf.py
│   ├── project_spreadsheet.gs    Google Apps Script: project tracking spreadsheet
│   └── scheduler_xtrf.gs         Google Apps Script: XTRF job scheduling helper
│
├── projects/                     Per-project working folders — gitignored
│   └── JOBNUM_LANGPAIR_PID/
│       └── pre-processing/       XLF, TMX, glossary CSV, checks outputs
│
├── current_project.json          Active project pointer — gitignored
├── project_log.json              Cross-project event history — gitignored
└── .env                          Credentials — gitignored (only needed for standalone runs)
```

> **Note:** `workflow_lara.py`, `workflow_iptranslate.py`, and `workflow_review.py`
> are legacy standalone orchestrators. They are no longer the primary way to run
> the workflow. The FastAPI app in `patent-translation-app/` runs each script as
> an individual subprocess. The standalone scripts remain for ad-hoc debugging.

---

## Setup

### Dependencies

```bash
pip install requests python-dotenv openai openpyxl pandas python-docx spacy \
            lara-sdk websocket-client lxml
python -m spacy download en_core_web_sm
python -m spacy download de_core_news_sm
```

`lxml` is required by `import_segments.py` and `ice_tm_creation.py` (XLF parsing).

### .env (standalone runs only)

When running scripts through the FastAPI app, credentials come from the app's
`.env` — the subprocess inherits the app's environment. Only needed here for
direct standalone execution:

```env
# XTRF vendor portal
CLIENT1_JOBLIST_USERNAME=...
CLIENT1_JOBLIST_PASSWORD=...

# IP.appify
IPAPPIFY_ACCOUNT=...
IPAPPIFY_API_KEY=...

# Lara
LARA_ACCESS_KEY_ID=...
LARA_ACCESS_KEY_SECRET=...

# OpenRouter (DeepSeek V3 / LLM checks)
OPENROUTER_API_KEY=...

# XTM Workbench (preferred account first; up to 6)
XTM_WORKBENCH_USERNAME1=...
XTM_WORKBENCH_PASSWORD1=...

# Matecat
MATECAT_API_KEY=...
MATECAT_COOKIE=...

# Google Drive
GDRIVE_CLIENT_ID=...
GDRIVE_CLIENT_SECRET=...
GDRIVE_REFRESH_TOKEN=...
GDRIVE_BASE_PATH=patent-translation-agent/CLIENT1
```

---

## How projects work

### Folder layout

`xtrf_job_setup.py` creates a project folder under `projects/`:

```
projects/JOBNUM_LANGPAIR_PID/
    pre-processing/
        *.xlf          XTM bilingual source file
        ICE_PID.tmx    ICE TM file (if matches found)
        glossary_PID.csv
        ...
```

`find_project_dir(project_id)` in `project_log.py` returns the `pre-processing/`
subfolder (not the top-level project folder).

`current_project.json` in the repo root is overwritten by each new job setup.
Every script that doesn't take an explicit `--pid` argument calls `project_dir()`
from `project_log.py` to locate input/output paths.

### Segment database

`import_segments.py` writes segments to `workflow.db` (in the app's root directory,
not in `agent/`). The DB path is resolved by `workflow_db.py` in the app as
`Path(__file__).parent / "workflow.db"` — always absolute, always the same file
regardless of cwd. Never set `DB_PATH` to a relative path in `.env`.

### Lara TM and glossary registries

Two JSON files act as per-project registries, written at the time of upload and
read at translation time:

| File | Key pattern | Written by | Read by |
|---|---|---|---|
| `lara_glossaries.json` | `glossary_{project_id}` → glossary ID | `lara_glossary_upload.py` | `lara_translate.py`, `lara_segment.py` |
| `lara_memories.json` | `memory_{project_id}` → ICE TM ID | `ice_tm_creation.py` | `lara_translate.py`, `lara_segment.py` |
| `lara_memories.json` | `client_memory_{project_id}` → client TM ID | `add_client_tm.py` | `lara_translate.py`, `lara_segment.py`, `update_project_tm()` |
| `lara_memories.json` | `client_tms.{ACRONYM}` → client TM ID | `add_client_tm.py` (once per new client) | `add_client_tm.py` |

`lara_translate.py` and `lara_segment.py` pass both `memory_{pid}` (ICE TM, if it
exists) and `client_memory_{pid}` as `adapt_to`, in that order. "Update Memory" in
the CAT UI uploads confirmed segments to the client TM (`client_memory_{pid}`), not
the ICE TM.

---

## Workflow (FastAPI-managed)

The FastAPI app runs each step as a subprocess. Steps run in this order for a
standard post-editing job:

| Step | Script | Description |
|---|---|---|
| `JOB_SETUP` | `xtrf_job_setup.py` | Download job metadata and source files from XTRF |
| `XTM_FILES_DOWNLOADED` | `xtm_initial_download.py` | Download XLF/XLSX from XTM |
| `ICE_TM_CREATION` | `ice_tm_creation.py --pid {pid}` | Extract ICE/100% matches, create Lara TM — no-op if none |
| `ADD_CLIENT_TM` | `add_client_tm.py --pid {pid}` | Resolve client TM from acronym; create new Lara TM if unknown |
| `LARA_PRETRANSLATION` | `lara_translate.py` | Pre-translate with standard glossary + ICE TM + client TM |
| `GLOSSARY_ANALYZED` | LLM comparison scripts + merge | Verb/noun checks, merge, LLM cleanup |
| `GLOSSARY_REVIEWED` | *(CAT UI checkpoint)* | Manual review in app UI — edit CSV, confirm |
| `GLOSSARY_UPLOADED_TO_LARA` | `lara_glossary_upload.py` | Upload clean glossary to Lara |
| `IMPORT_SEGMENTS` | `import_segments.py --pid {pid}` | Parse XLF → DB for CAT UI |
| `TRANSLATION_LARA` | *(CAT UI)* | Segment-by-segment translation at `/projects/{id}/cat` |
| `MATECAT_XLF_TO_EXCEL` | `Matecat/matecat_xlf_to_excel.py` | Convert Matecat export to Excel |
| `TRANSLATION_CHECKS` | `linter.py` + `glossary_compare.py` | Linter and glossary compliance |
| `XLF_XTM_UPLOAD` | `Matecat/matecat_xtm_upload.py` | Upload corrected XLF to XTM |
| `XLSX_XTM_UPLOAD` | `xtm_upload_translations.py` | Upload revised XLSX to XTM |
| `MATECAT_XTM_VERIFY` | `Matecat/matecat_xtm_verify.py` | Verify XTM upload segment by segment |
| `XTM_FINAL_DOWNLOAD` | `xtm_final_download.py` | Download final deliverables from XTM |
| `XTRF_UPLOAD` | `xtrf_upload.py` | Upload deliverables to XTRF vendor portal |
| `DELETE_PROJECT_FILES` | `delete_project_folder.py` | Delete local job folder (confirm backup first) |

### CAT UI and TM update

The `TRANSLATION_LARA` step opens the CAT UI at `/projects/{id}/cat`. Each
segment is translated via `lara_segment.py`, which passes both the ICE TM
(`memory_{pid}`, if it exists) and the client TM (`client_memory_{pid}`) as
`adapt_to`. After translating a batch of segments:

1. Confirm segments in the CAT UI (status = CONFIRMED)
2. Click **Update Memory** → `POST /api/projects/{id}/update-tm`
3. Confirmed segments are uploaded to the **client TM** via `update_project_tm()`
4. Future translations for this client will incorporate the confirmed choices

### Legacy standalone workflow

```bash
python workflow_lara.py          # steps JOB_SETUP → XTM_FILES_DOWNLOADED → LARA_PRETRANSLATION → GLOSSARY_ANALYZED
python workflow_iptranslate.py   # same with IP.appify instead of Lara
```

For direct script invocation:

```bash
python xtrf_job_setup.py
python xtm_initial_download.py
python ice_tm_creation.py --pid PAS_2606_P0032
python add_client_tm.py --pid PAS_2606_P0032
python lara_translate.py
python import_segments.py --pid PAS_2606_P0032
python LLM_verb_comparison_xlsx.py
python LLM_noun_comparison_xlsx.py
python LLM_capability_comparison_xlsx.py
python merge_glossaries.py <project_id>
python llm_glossary_cleanup.py
python glossary_compare.py
python lara_glossary_upload.py
```

---

## XTRF job folder

Source files downloaded in `JOB_SETUP` land in the local work folder (path set by
`WORK_DIR` in app `.env`):

```
WORK_DIR/JOBNUM_LANGPAIR_PROJ_ID/
```

e.g. `12345678ENDE11_CC_YYMM_PNNNN/`

The relevant XTM bilingual file is downloaded by `XTM_FILES_DOWNLOADED`.

---

## XTM Workbench

Login URL: `https://word.welocalize.com/project-manager-gui/login.jsp?client=CLIENT_CODE`  
Company field: `CLIENT_CODE`  
XTM accounts: `XTM_WORKBENCH_USERNAME1` / `XTM_WORKBENCH_PASSWORD1` (up to 6 configured)

**Important:** A redirect back to `login.jsp` after POST = failure, even if HTTP 200.
Only a redirect to `configuration-pages.action` = success.

XTM sessions expire after ~15 WebSocket TU_UPDATED operations — `xtm_upload_translations.py`
handles reconnection automatically.

---

## Known issues / notes

- **`MATECAT_COOKIE` expires.** Update from browser dev tools when `XLF_XTM_UPLOAD`
  returns 401.
- **IP.appify `Dictionary` field is non-functional** (tested 2026-04-23). Glossary
  enforcement is client-side only. Use `ipappify_translate_apikey.py` (API key
  auth), not the older token-based variant.
- **LLM prompts must not say "Normalize"** — causes global lowercase of both EN
  and DE output.
- **`glossary_compare.py` is more reliable than the LLM check** for catching
  systematic mismatches. Both complement each other.
- **EN multi-word glossary entries**: for EN adj.+noun → DE adj.+noun entries,
  either strip the EN adjective or add a bare-noun entry alongside. The LLM
  extracts the longest matching phrase, so the full phrase may not always match.
- **`XTM_FINAL_DOWNLOAD` and `XTRF_UPLOAD` are local-only** — they use the local
  `WORK_DIR` (OneDrive path). Railway support is a future TODO.
