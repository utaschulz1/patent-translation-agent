# MateCat skill

You are helping with the MateCat integration in `Matecat/`.

## Step 1 — Load context

Before answering, read:
1. `Matecat/matecat_upload.py`
2. `Matecat/matecat_download.py`
3. `Matecat/matecat_xtm_upload.py`
4. `Matecat/matecat_projects.json`
5. The memory file at `C:\Users\utasc\.claude\projects\c--Users-utasc-OneDrive-Dokumente-Code-Python-patent-translation-agent\memory\matecat_api.md`

## Step 2 — Workflow overview

```
XTM XLF export
  → matecat_upload.py       # pre-process XLF + upload glossary + create MateCat project
  → (translate in MateCat / Lara)
  → matecat_download.py     # download *_GERMAN.xlf
  → matecat_xtm_upload.py   # push translations back to XTM via WebSocket
  → XLF2TMX.py              # convert *_GERMAN.xlf to TMX for TM seeding
```

## Step 3 — Auth

`x-matecat-key` header does NOT work programmatically — the account has not been activated for API access.

**Working solution:** browser session cookie in `.env`:
```
MATECAT_COOKIE="AWSALB=...; AWSALBCORS=...; matecat_login_v6=eyJ...; PHPSESSID=...; upload_token=..."
```
Cookie expires approximately 7 days after login. Refresh by logging in to matecat.com, opening DevTools → Application → Cookies → https://www.matecat.com, and rebuilding the string.

Script checks `MATECAT_COOKIE` first, falls back to `MATECAT_API_KEY`.

## Step 4 — Key parameters for POST /api/v1/new

```python
form_data = {
    "project_name":            project_id,
    "source_lang":             "en-US",
    "target_lang":             "de-DE",
    "mt_engine":               "12687",   # Lara engine ID
    "pretranslate_100":        "1",
    "pretranslate_101":        "1",
    "get_public_matches":      "0",
    "qa_model_template_id":    "0",
    "payable_rate_template_id":"0",
    "filters_template_id":     "0",
    "xliff_config_template_id":"0",
}
# TM keys passed as repeated field via list-of-tuples (NOT in form_data dict)
extra = [("private_tm_key", tm_key)]
requests.post(url, data=list(form_data.items()) + extra, files={"files[]": ...})
```

**Critical:** `private_tm_key` must be in the `_extra_fields` list-of-tuples appended after `form_data.items()`, NOT embedded in the dict. Embedding in dict caused TM not activating.

`project_template_id` is NOT a valid parameter — all settings must be inline.

`lara_glossaries` takes a JSON array string: `json.dumps(["gls_xxx"])`.

`private_tm_key_json` format fails with "Required property missing: tm_prioritization" — use plain `private_tm_key` string instead.

## Step 5 — Client auto-discovery

If a client (pid prefix) is not in `matecat_projects.json`, the script:
1. Queries `GET /api/v3/project-template` and finds a template matching the client name
2. Extracts `template_id` and TM keys (sorted by penalty: lowest = primary)
3. Saves to `matecat_projects.json` automatically
4. If no template found: asks user `Continue without TM? [y/N]`

`template_id` is stored for reference only — it is NOT passed to the API.

## Step 6 — Glossary upload

```
POST /api/v3/glossaries/import/
  file: XLSX (row 1 = language codes en-US, de-DE, "")
  tm_key: client TM key
```

202 response = accepted. The status endpoint `GET /api/v3/glossaries/import/status/{tm_key}` returns 500 unreliably — ignore it, trust the 202.

Glossary is stored inside the TM key (same resource, `glos: true` flag). Terms appear underlined in source and highlighted when missing in target.

## Step 7 — Common issues

- **Lara shows "inactive" in project settings:** cosmetic UI bug — Lara works correctly in the translation editor regardless.
- **Pre-translation threshold is 86%, not 93%:** MateCat uses `mt_quality_value_in_editor: 85` from the template as its editor threshold. This is separate from the script's 93% XLF pre-processing, which already cleared low-quality targets before upload. Both thresholds coexist and are not in conflict.
- **TM not active / Lara not active:** check that `private_tm_key` is in `_extra_fields` tuples, not in `form_data` dict. Also verify Lara API credentials in MateCat account engine settings match the ones in `.env`.
- **401 on all endpoints:** `x-matecat-key` not activated — refresh `MATECAT_COOKIE` from browser.
- **400 "JSON Validation Error":** do not use `private_tm_key_json` — use plain `private_tm_key`.
- **400 "lara_glossaries is not valid JSON":** must be `json.dumps(["gls_xxx"])` not the raw ID string.
- **Glossary poll 500:** expected — MateCat status endpoint is unreliable. Upload succeeded if initial response was 202.
- **XLF pre-processing:** segments with `state-qualifier="leveraged-tm"` or fuzzy ≥93% keep their targets; MT and <93% fuzzy targets are cleared so Lara translates them fresh.
