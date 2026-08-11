# Docx Comment Reply Skill

Answer reviewer comments left in a translated .docx (an Issue Resolution / QA
round) by checking each one against the original source, then writing the
answers back in as threaded Word reply comments — without touching the
translated text itself.

This is one building block of the (not yet fully designed) Issue Resolution
workflow/skillset — it only covers "read the comments, answer the comments".
It does not decide what to do with the answers afterwards (e.g. feeding
"change needed" items back into a revision pass) — that's a separate step.
The other building block is [[resolve-tracked-changes]] (accepting/rejecting
Word tracked changes in the same kind of docx) — check for both comments and
tracked changes regardless of which one the user asked about first, a docx
can have either or both.

## Key files

| File | Purpose |
|---|---|
| `utilities/extract_docx_comments.py` | Pulls every comment out of the docx — text, anchored text, and any images (screenshots pasted into the comment, or pictures embedded at the anchor point) — into a JSON report + PNGs. |
| `utilities/reply_docx_comments.py` | Injects answers back in as proper threaded Word reply comments, keyed by comment id. Validates the result before writing. |

Both scripts are generic (not specific to any one patent) and run from the
`agent/` directory.

## Workflow

### Step 0 — Locate the files
You need two files, usually in the same "Work Files" / "Issue Resolution"
folder: the editable .docx with the reviewer's comments, and the original
source PDF the translation was made from. Confirm both exist before
starting.

### Step 1 — Extract the comments
```
python utilities/extract_docx_comments.py "<editable>.docx"
```
Produces `<stem>_comments/comments.json` and `.../images/*.png`. Read
`comments.json` with the Read tool — do not try to eyeball the raw docx XML
by hand, and do not print the whole JSON into chat if it's long.

Each entry has: `id`, `author`, `date`, `comment_text`, `anchor_text`,
`anchor_paragraph_text`, `comment_images` (screenshots pasted into the
comment — usually a crop of the *source*), `anchor_images` (pictures
embedded in the *translation* at the comment's location, populated when the
comment targets a drawing rather than text, in which case `anchor_text` is
empty).

### Step 2 — View every image
View every file in `images/` with the Read tool. `comment_images` show what
the reviewer is pointing at; `anchor_images` show what's currently in the
translation at that spot. Don't skip this — a comment anchored on a drawing
has no useful `anchor_text`, the image is the only content.

### Step 3 — Cross-check against the source PDF
Comments often cite a page/line in the source, e.g. "pdf6" or "pdf15, line
57". Render the relevant page(s) — don't rely on `pdftotext`, EPO grant PDFs
are frequently flattened and it silently returns nothing:
```
pdftoppm -png -f <N> -l <N> -r 150 "<source>.pdf" page
```
Read the rendered PNG. When a comment flags a chemical structure or figure as
"inconsistent with source", crop and zoom (e.g. via PIL) rather than judging
from a thumbnail — structures that differ only in a caption or label position
can look identical at a glance.

Two answer patterns cover most comments:
- **"Please check if translation is required"** (IUPAC chemical names,
  literature citations, proper nouns) → usually **no change** — convention
  is to leave these in the source language. Verify, don't assume (Step 4).
- **"Missing translation"** for text baked into an embedded image (reaction
  schemes, figure captions) → **change needed**, but flag it for DTP/graphics
  — you cannot fix baked-in image text by editing the .docx body.

### Step 4 — Verify "check the whole file" claims
When a comment asks you to check the whole file for a pattern, don't answer
from the one instance shown. Grep the extracted paragraph text (or reread
`comments.json`'s `anchor_paragraph_text` plus a full-text grep of the docx)
for other occurrences and confirm they follow the same convention before
writing "consistent throughout, no change needed".

### Step 5 — Draft answers
One answer per comment id. State clearly: whether a change is needed, and
exactly what the change is. Do not edit the translated text — only answer.
Save as JSON:
```json
{"0": "No change needed. ...", "1": "Change needed. ...", ...}
```

### Step 6 — Inject replies
```
python utilities/reply_docx_comments.py "<editable>.docx" replies.json \
    --author "<translator name>" --initials "<initials>"
```
Writes `<stem>_replied.docx` next to the input by default — the original is
untouched. The script validates the output (zip integrity + reopens with
python-docx) before writing, and fails loudly listing any comment id in
`replies.json` that doesn't exist in the source docx.

### Step 7 — Confirm before overwriting
This is a real production deliverable. Always ask the user whether to
overwrite the original file in place or keep the separate `_replied` file —
never overwrite silently. If they want it in place, use `--in-place` (the
script keeps a `.bak` copy automatically) rather than manually copying over
the original.

## Notes / gotchas

- **Author name**: use the translator's own name for the reply comments
  (check memory, or ask), not a generic "Reviewer"/"AI" label — these are the
  translator's answers to the QA reviewer's comments.
- **Broken threading metadata in some source files**: docx files exported
  from certain CAT-tool workflows (seen from XTM-adjacent exports) have
  already-malformed reply-threading metadata (every comment sharing one
  placeholder paraId in `commentsExtended.xml`). `reply_docx_comments.py`
  works around this by keying off `comments.xml`'s own per-comment paraId
  rather than trusting `commentsExtended.xml` — no need to "fix" the
  pre-existing metadata yourself.
- **Docx with no threading parts at all**: the script falls back to adding
  plain top-level comments prefixed `[Reply to comment N]` and prints a
  WARNING. Mention this to the user if it happens — the reply won't visually
  nest under the original comment in Word.
