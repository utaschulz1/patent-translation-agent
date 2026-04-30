# Lara Translate skill

You are helping with the Lara Translate integration: `lara_glossary_upload.py` and `lara_translate.py`.

## Step 1 — Load context

Before answering, read:
1. `lara_translate.py`
2. `lara_glossary_upload.py`
3. The memory file at `C:\Users\utasc\.claude\projects\c--Users-utasc-OneDrive-Dokumente-Code-Python-patent-translation-agent\memory\lara_api.md`

## Step 2 — Domain knowledge (authoritative)

### SDK and auth

```python
from lara_sdk import AccessKey, TextBlock, Translator
lara = Translator(AccessKey(id=access_key_id, secret=access_key_secret))
```

`AccessKey` takes `id` and `secret` — NOT `access_key_id`/`access_key_secret` (those were deprecated `Credentials` kwargs).

---

### TextBlock context window

`TextBlock` has exactly two fields: `text` (str) and `translatable` (bool).

The window is a plain Python list passed to `lara.translate()`. Position is implicit from list order. Max total window size: 128 elements.

```python
window = (
    [TextBlock(text=s["Source"], translatable=False) for s in before]
    + [TextBlock(text=seg["Source"], translatable=True)]
    + [TextBlock(text=s["Source"], translatable=False) for s in after]
)
result = lara.translate(window, ...)
translated = result.translation[len(before)].text.strip()
```

**Why asymmetric window (5 before, 1 after):** Patent claims are subordinate clauses in German. The opening paragraph ("The method wherein...") establishes the main clause; all subsequent claim elements must use verb-final word order and accusative case. Preceding context is critical; following context is minor.

---

### Glossary

- Format: monodirectional CSV, `en,de` header
- `import_csv(id, path)` requires a file path — pass a temp file, NOT BytesIO
- Pro plan: max **1 glossary** — delete existing before creating new
- IDs stored in `lara_glossaries.json`, not in `.env`

---

### Tier restrictions (verify after May 2026 restructure)

| Feature | Pro | Team |
|---|---|---|
| Glossaries | ✓ | ✓ |
| `adapt_to` (TM adaptation) | — | ✓ |
| Reasoning (Lara Think) | ✓ (€2000/1M) | ✓ (€1500/1M) |

User is on Pro. Tier restructure expected May 2026 — feature boundaries may shift.

---

## Step 3 — Typical tasks

- **Glossary not applied:** check `lara_glossaries.json` exists and has an entry; check the glossary ID is still valid on Lara (list with `lara.glossaries.list()`)
- **Wrong clause structure in German:** verify `CONTEXT_BEFORE` is large enough (5 is current setting); check that `TextBlock` window is being built from the full `segments` list (not just the selected range)
- **Resume not working / retranslating already done segments:** check `FORCE_RETRANSLATE` flag
- **Tier-gated feature errors:** check which plan features are available; `adapt_to` requires Team plan
- **Import CSV fails:** `import_csv` requires a file path, not a stream — must write to disk first
