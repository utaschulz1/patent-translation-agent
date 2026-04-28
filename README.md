# patent-translation-agent

Automation scripts for EN→DE patent translation at Comunica DK. Covers email intake (step 3), XTRF job setup (step 4), pre-translation via IP.appify (step 5), and LLM-based consistency/glossary checks (step 6).

---

## Project structure

```
patent-translation-agent/
│
├── workflow.py                   # Orchestrator: runs steps 4 → 5 → 6 → 6b in sequence
│
│── get_XTRF_link.py              # Step 3: Gmail intake → extract XTRF link → trigger step 4
├── xtrf_job_setup.py             # Step 4: XTRF login → create folders → download sources → glossary CSV
│
├── ipappify_translate.py         # Step 5: IP.appify API translation → *_translated.xlsx
├── excel_to_word_table.py        # Alt step 5a: export xlsx to Word table for manual IP.appify plugin
├── word_to_excel_target.py       # Alt step 5b: import DE column back from Word into xlsx
├── deepseek_translate.py         # Alt step 5: DeepSeek translation (for comparison)
│
├── LLM_verb_comparison_xlsx.py   # Step 6:  verb consistency check → verb_flags.csv + _checks.xlsx
├── LLM_noun_comparison_xlsx.py   # Step 6:  noun consistency check → noun_inconsistency_table.csv
├── merge_glossaries.py           # Step 6b: merge verb/noun/standard glossaries into project glossary
├── LLM_glossary_check_xlsx.py    # Step 6c: glossary compliance check → glossary_flags.csv
├── glossary_compare.py           # Step 6c: rule-based glossary mismatch check (more reliable)
├── spacy_verb_comparison_xlsx.py # Legacy: spaCy-based verb check (reference only)
│
├── xtm_workbench.py              # Step 6 (pre): XTM login → download bilingual Excel
├── xtm_workbench_playwright.py   # Step 6 (pre): Playwright variant of above
├── XTM_download_playwright_warmstart.py
│
├── project_log.py                # Shared: project context (project_dir()) + event log
├── standard_glossary.csv         # Shared terminology used by merge_glossaries.py
├── stop-eng.txt                  # Stop words for spaCy script
│
├── projects/                     # Per-project working folders — gitignored
│   └── SYICTL_2604_P0069/
│       ├── SYICTL_2604_P0069_EP1234567.xlsx
│       ├── SYICTL_2604_P0069_translated.xlsx
│       ├── SYICTL_2604_P0069_checks.xlsx
│       ├── glossary_SYICTL_2604_P0069.csv
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
pip install requests python-dotenv openai openpyxl pandas python-docx spacy
python -m spacy download en_core_web_sm
python -m spacy download de_core_news_sm
```

For Gmail (step 3):
```
pip install google-auth google-auth-oauthlib google-api-python-client
```

### .env

```env
# XTRF
COMUNICA_JOBLIST_USERNAME=...
COMUNICA_JOBLIST_PASSWORD=...

# IP.appify
IPAPPIFY_TOKEN=...
IPAPPIFY_REFRESH_TOKEN=...

# OpenRouter (DeepSeek / LLM checks)
OPENROUTER_API_KEY=...

# XTM Workbench (preferred account first)
XTM_WORKBENCH_USERNAME5=...
XTM_WORKBENCH_PASSWORD5=...
```

---

## How projects work

Each project gets an isolated working folder under `projects/`:

```
projects/SYICTL_2604_P0069/
```

When `xtrf_job_setup.py` runs, it creates this folder and writes `current_project.json` at the repo root. Every downstream script calls `project_dir()` from `project_log.py` to find its input/output path — no hardcoded paths, no shared `input/` folder.

To switch projects, run step 3/4 again. `current_project.json` is overwritten; the previous project folder stays intact.

---

## Workflow

| Step | What | Script | Status |
|------|------|--------|--------|
| 3 | Gmail intake → extract XTRF link | `get_XTRF_link.py` | planned |
| 4 | XTRF job setup, folder creation, glossary | `xtrf_job_setup.py` | automated |
| 5 | Pre-translation via IP.appify API | `ipappify_translate.py` | automated |
| 6 | Verb + noun consistency checks | `LLM_verb_comparison_xlsx.py` + `LLM_noun_comparison_xlsx.py` | automated |
| 6b | Merge verb/noun/standard glossaries | `merge_glossaries.py` | automated |
| 6c | Glossary compliance + mismatch check | `LLM_glossary_check_xlsx.py` + `glossary_compare.py` | automated |
| 6 pre | Download bilingual Excel from XTM | `xtm_workbench.py` | login issue |
| 7–14 | Revision of `_checks.xlsx` | — | manual |
| 15 | Paste segments back to XTM Workbench | — | manual |
| 16–22 | Xbench, upload, finish | — | manual |

### Gmail OAuth2 setup (step 3, one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project, enable the **Gmail API**.
2. Create **OAuth 2.0 credentials** (type: Desktop app). Download the JSON and save it as `gmail_credentials.json` in the project root.
3. Add `gmail_credentials.json` and `gmail_token.json` to `.gitignore` (already done).
4. Install the Gmail client library:
   ```bash
   pip install google-auth google-auth-oauthlib google-api-python-client
   ```
5. Run `python get_XTRF_link.py` once — a browser window opens for consent. After approval, `gmail_token.json` is saved and all subsequent runs are headless.

The script reads the label **ComunicaDK/TODO**, processes the oldest unhandled email, and uses `project_log.json` to skip already-processed message IDs. Emails are never moved or marked read.

### Running the automated workflow

```bash
python workflow.py             # step 3 (email intake) → 4 → 5 → 6 → 6b
python workflow.py --manual    # skip email; paste XTRF URL manually
```

Step 5 pauses to let you place the XTM bilingual Excel in the project folder (or it's already there if the Downloads copy succeeded in step 3).

To run steps individually:
```bash
python get_XTRF_link.py                       # step 3 standalone
python xtrf_job_setup.py <XTRF-job-URL-or-ID> # step 4 standalone
python ipappify_translate.py
python LLM_verb_comparison_xlsx.py
python LLM_noun_comparison_xlsx.py
python merge_glossaries.py <project_id>
python LLM_glossary_check_xlsx.py
python glossary_compare.py
```

---

## XTRF job folder

Source files (downloaded in step 4) land in OneDrive:

```
C:\Users\utasc\OneDrive\ArbeitNEU\Comunica DK\{idNumber}_{project_id}\
```

e.g. `20264311ENDE11_RTC_2604_P0732\`

The relevant CAT file inside the zip is `*Clean_XTM.docx`. Do not modify it — it is the reference file.

---

## XTM Workbench

Login: `https://word.welocalize.com/project-manager-gui/login.jsp?client=IP#!/login`  
Company field: `IP` (all minor clients; Ford and similar use a different name)  
Preferred credentials: `XTM_WORKBENCH_USERNAME5` / `XTM_WORKBENCH_PASSWORD5`  
If login fails, notify the project manager before trying other accounts.

**Important:** A redirect to `login.jsp` after POST = failure, even if HTTP 200. Only a redirect to `configuration-pages.action` = success.

---

## Known issues / notes

- `Dictionary` field in IP.appify API is non-functional (tested 2026-04-23). Glossary enforcement is client-side in the Word plugin only. Do not pursue API-side glossary injection further without a captured real Word plugin request.
- `xtm_workbench.py` login is unresolved (all accounts redirect back to `login.jsp`).
- LLM prompts must **not** say "Normalize" — causes global lowercase of both EN and DE output.
- `glossary_compare.py` is more reliable than `LLM_glossary_check_xlsx.py` for catching systematic glossary mismatches. Both complement each other.
- For EN multi-word glossary entries where DE is adj.+noun (e.g. `selective co-product → selektives Co-Produkt`): either strip the EN adjective or add a bare-noun entry alongside. The LLM extracts the longest phrase present, so the full EN adjective+noun may not always be captured.
