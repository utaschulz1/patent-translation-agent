# patent-translation-agent

Automation scripts for EN→DE patent translation. Covers XTRF job intake (step 3), job setup (step 4), XTM file download, pre-translation via Lara and IP.appify (step 5), and LLM-based consistency/glossary checks (step 6).

---

## Project structure

```
patent-translation-agent/
│
├── get_XTRF_job.py               # Step 3: fetch pending jobs from XTRF job list
├── xtrf_job_setup.py             # Step 4: XTRF login → create folders → download sources → glossary CSV
│
├── xtm_initial_download.py       # Step: XTM download → xlsx + xliff to project folder
│
├── lara_translate.py             # Step 5 (primary): Lara pre-translation
├── lara_glossary_upload.py       # Upload project glossary to Lara
├── lara_glossary_download.py     # Download glossary from Lara
├── lara_glossary_upload_standard.py  # Upload standard glossary to Lara
│
├── ipappify_translate.py         # Step 5 (alt): IP.appify pre-translation (Azure B2C auth)
├── ipappify_translate_apikey.py  # Step 5 (alt): IP.appify pre-translation (API key auth)
│
├── LLM_verb_comparison_xlsx.py   # Step 6: verb consistency check → verb_flags.csv + _checks.xlsx
├── LLM_noun_comparison_xlsx.py   # Step 6: noun consistency check → noun_inconsistency_table.csv
├── LLM_capability_comparison_xlsx.py  # Step 6: capability consistency check
├── merge_glossaries.py           # Step 6b: merge verb/noun/standard glossaries → project glossary
├── llm_glossary_cleanup.py       # Step 6b: LLM-based cleanup of merged glossary
├── glossary_compare.py           # Step 6c: rule-based glossary mismatch check
├── glossary_compare_revised_translation.py  # Step 6c: glossary check on revised translation
│
├── xtm_upload_translations.py    # Upload revised translation xlsx back to XTM
├── xtm_final_download.py         # Final XTM download (docx/PDF/xlsx deliverables)
├── xtrf_upload.py                # Upload deliverables to XTRF vendor portal
│
├── gdrive.py                     # Google Drive sync module (push + pull)
├── gdrive_push.py                # Push project files to Google Drive
├── gdrive_pull_revised.py        # Pull revised translation from Google Drive
├── pull_from_gdrive.py           # General-purpose Drive pull
│
├── workflow_lara.py              # Orchestrator: Lara pre-translation workflow
├── workflow_iptranslate.py       # Orchestrator: IP.appify workflow
├── workflow_review.py            # Orchestrator: post-translation review workflow
│
├── config.py                     # Shared configuration
├── linter.py                     # Terminology linter
├── archive_preprocessing.py      # Archive and preprocessing utilities
├── consolidate_scorecards.py     # Consolidate QA scorecards
├── project_log.py                # Shared: project context (project_dir()) + event log
├── standard_glossary.csv         # Shared terminology used by merge_glossaries.py
├── stop-eng.txt                  # Stop words (legacy spaCy reference)
│
├── Matecat/                      # Matecat integration scripts
│   ├── matecat_upload.py
│   ├── matecat_download.py
│   ├── matecat_xtm_upload.py     # XLF upload from Matecat to XTM
│   ├── matecat_xtm_verify.py
│   ├── matecat_glossary_upload.py
│   ├── matecat_info.py
│   ├── matecat_xlf_to_excel.py
│   ├── XLF2TMX.py
│   ├── CSV2TMX-XLSX.py
│   ├── Excel2TMX.py
│   └── extract_xlf_from_xbpkg.py
│
├── utilities/                    # One-off and alignment tools
│   ├── align_docx.py
│   ├── sort_csv_alphabet.py
│   └── extract_align_bilingual_pdf.py
│
├── projects/                     # Per-project working folders — gitignored
│   └── PCODE_YYMM_PNNNN/
│       ├── PCODE_YYMM_PNNNN_translated.xlsx
│       ├── PCODE_YYMM_PNNNN_checks.xlsx
│       ├── glossary_PCODE_YYMM_PNNNN.csv
│       └── *.csv  (verb/noun pairs, flag tables)
│
├── current_project.json          # Active project pointer — gitignored
├── project_log.json              # Cross-project event history — gitignored
└── .env                          # Credentials — gitignored
```

---

## Setup

### Dependencies

```
pip install requests python-dotenv openai openpyxl pandas python-docx spacy lara-sdk websocket-client
python -m spacy download en_core_web_sm
python -m spacy download de_core_news_sm
```

### .env

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

# OpenRouter (DeepSeek / LLM checks)
OPENROUTER_API_KEY=...

# XTM Workbench (preferred account first)
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

Each project gets an isolated working folder under `projects/`:

```
projects/PCODE_YYMM_PNNNN/
```

When `xtrf_job_setup.py` runs, it creates this folder and writes `current_project.json` at the repo root. Every downstream script calls `project_dir()` from `project_log.py` to find its input/output path — no hardcoded paths, no shared `input/` folder.

To switch projects, run step 3/4 again. `current_project.json` is overwritten; the previous project folder stays intact.

---

## Workflow

| Step | What | Script | Status |
|------|------|--------|--------|
| 3 | Fetch pending XTRF jobs | `get_XTRF_job.py` | automated |
| 4 | XTRF job setup, folder creation, glossary | `xtrf_job_setup.py` | automated |
| 4b | Download XTM bilingual files (xlsx + xliff) | `xtm_initial_download.py` | automated |
| 5 | Pre-translation via Lara | `lara_translate.py` | automated |
| 5 alt | Pre-translation via IP.appify | `ipappify_translate_apikey.py` | automated |
| 6 | Verb + noun + capability consistency checks | `LLM_verb/noun/capability_comparison_xlsx.py` | automated |
| 6b | Merge + clean glossaries | `merge_glossaries.py` + `llm_glossary_cleanup.py` | automated |
| 6c | Glossary mismatch check | `glossary_compare.py` | automated |
| 6d | Upload glossary to Lara | `lara_glossary_upload.py` | automated |
| 7–14 | Revision of `_checks.xlsx` | — | manual |
| 15 | Pull revised xlsx from Google Drive | `gdrive_pull_revised.py` | wired |
| 16 | Upload xliff to XTM (via Matecat) | `Matecat/matecat_xtm_upload.py` | working locally |
| 17 | Upload revised translation xlsx to XTM | `xtm_upload_translations.py` | wired |
| 18 | Final XTM download | `xtm_final_download.py` | wired |
| 19 | Upload deliverables to XTRF | `xtrf_upload.py` | working locally |

### Running the automated workflow

```bash
python workflow_lara.py            # steps 3 → 4 → 4b → 5 (Lara) → 6 → 6b → 6c → 6d
python workflow_iptranslate.py     # steps 3 → 4 → 5 (IP.appify) → 6 → 6b
python workflow_review.py          # post-translation review steps
```

To run steps individually:

```bash
python get_XTRF_job.py
python xtrf_job_setup.py <XTRF-job-URL-or-ID>
python xtm_initial_download.py
python lara_translate.py
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

Source files (downloaded in step 4) land in the local work folder:

```
PATH_TO_WORK_DIR\JOBNUM_LANGPAIR_PROJ_ID\
```

e.g. `12345678ENDE11_CC_YYMM_PNNNN\`

The relevant CAT file inside the zip is `*Clean_XTM.docx`. Do not modify it — it is the reference file.

---

## XTM Workbench

Login URL: `https://word.welocalize.com/project-manager-gui/login.jsp?client=CLIENT_CODE`  
Company field: `CLIENT_CODE`  
XTM accounts: `XTM_WORKBENCH_USERNAME1` / `XTM_WORKBENCH_PASSWORD1` (up to 6 accounts configured)

**Important:** A redirect to `login.jsp` after POST = failure, even if HTTP 200. Only a redirect to `configuration-pages.action` = success.

XTM file download is handled by `xtm_initial_download.py`.

---

## Known issues / notes

- `Dictionary` field in IP.appify API is non-functional (tested 2026-04-23). Glossary enforcement is client-side in the Word plugin only. Use `ipappify_translate_apikey.py` (API key auth) rather than the older token-based variant.
- LLM prompts must **not** say "Normalize" — causes global lowercase of both EN and DE output.
- `glossary_compare.py` is more reliable than the LLM-based glossary check for catching systematic mismatches. Both complement each other.
- For EN multi-word glossary entries where DE is adj.+noun (e.g. `selective co-product → selektives Co-Produkt`): either strip the EN adjective or add a bare-noun entry alongside. The LLM extracts the longest phrase present, so the full EN adjective+noun may not always be captured.
- `XTM_FINAL_DOWNLOAD` and `XTRF_UPLOAD` are local-only steps — they use the local work folder (OneDrive). Railway support is a future TODO.
- `MATECAT_COOKIE` is a session cookie and will expire periodically; update it from browser dev tools when `matecat_xtm_upload.py` returns 401.
