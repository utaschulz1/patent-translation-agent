# IPappify IP Translator skill

You are helping with the IPappify IP Translator integration: `ipappify_translate.py`, `ipappify_translate_apikey.py`, and `not-in-use/ipappify_translate_dict.py`.

## Step 1 — Load context

Before answering, read:
1. `ipappify_translate_apikey.py`
2. `ipappify_translate.py`
3. The memory file at `C:\Users\utasc\.claude\projects\c--Users-utasc-OneDrive-Dokumente-Code-Python-patent-translation-agent\memory\ipappify_translate.md`

## Step 2 — Domain knowledge (authoritative)

### Auth

Two methods are supported:

**Static ApiKey** (preferred — no expiry):
```
Authorization: ApiKey <key>
```
Set `IPAPPIFY_API_KEY` in `.env`. Used by `ipappify_translate_apikey.py`.

**JWT Bearer** (OAuth2 via Azure B2C, expires ~1h):
```
Authorization: Bearer <jwt>
```
Set `IPAPPIFY_TOKEN` + `IPAPPIFY_REFRESH_TOKEN` in `.env`. `ipappify_translate.py` auto-refreshes. Capture initial refresh token from mitmproxy (POST to `ipappifyusers.b2clogin.com`).

---

### Dictionary field — correct format

```python
{"SourceText": "method", "TargetText": "Verfahren", "IsLiteral": False}
```

- Lives at `Translate.Options.Dictionary` (list)
- `DictionaryReward` must be non-zero (e.g. `1.0`) for terms to have effect — set to `0.0` only when list is empty
- **Known bug in `not-in-use/ipappify_translate_dict.py`:** used `{"Source": ..., "Target": ...}` — wrong field names. The API silently ignores them, so the dictionary had no effect. Fix is to rename to `SourceText`/`TargetText` and add `IsLiteral: False`.

---

### Per-segment dictionary filtering

Only include glossary entries where any word of the EN term appears in the source segment:

```python
def build_dictionary(source_text, glossary):
    src_lower = source_text.lower()
    return [
        {"SourceText": en, "TargetText": de, "IsLiteral": False}
        for en, de in glossary
        if any(w in src_lower for w in en.lower().split())
    ]
```

Glossary is a list of `(en_term, de_term)` tuples loaded from a CSV with EN and DE columns.

---

### Response parsing

```python
data = resp.json()
translated = data["Translate"]["Translations"][0]["TargetText"].strip()
```

---

## Step 3 — Typical tasks

- **Add dictionary support to `ipappify_translate_apikey.py`:** load glossary CSV, add `build_dictionary()` helper, pass result to `Options.Dictionary` and set `DictionaryReward=1.0` when non-empty. Use `SourceText`/`TargetText`/`IsLiteral` field names (not `Source`/`Target`).
- **Dictionary terms not applied:** check field names are `SourceText`/`TargetText` (not `Source`/`Target`); check `DictionaryReward` is non-zero; check per-segment filter is not too strict.
- **401 error with ApiKey:** key in `.env` as `IPAPPIFY_API_KEY`; header must be `ApiKey <key>` not `Bearer <key>`.
- **401 error with Bearer:** token expired — script will auto-refresh from `IPAPPIFY_REFRESH_TOKEN`; if refresh also fails, re-capture from mitmproxy.
- **Resume / skip already-translated segments:** `ipappify_translate_apikey.py` supports resume via `_translated.xlsx`; `not-in-use/ipappify_translate_dict.py` does not (it always writes all at the end).
