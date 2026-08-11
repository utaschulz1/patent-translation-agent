# Resolve Tracked Changes Skill

Review Word tracked changes (insertions/deletions) in a translated .docx —
an Issue Resolution / QA round where the reviewer edited directly instead of
(or in addition to) leaving comments — rate your confidence per change, and
accept/reject accordingly, escalating only what you're genuinely unsure
about.

This is the other building block of the (not yet fully designed) Issue
Resolution workflow/skillset, alongside [[docx-comment-reply]]. The two are
independent: a docx can have comments only, tracked changes only, or both —
check for both regardless of which one the user asked about first.

## Key files

| File | Purpose |
|---|---|
| `utilities/resolve_tracked_changes.py` | `list` extracts every tracked change (including inside tables — see Gotchas) into JSON with before/after context. `resolve` accepts/rejects by id, validates the result, and writes it out. |

## The certainty protocol

Unless the user gives different numbers, use this scale when asked to review
tracked changes:

- **5 — certain.** Verified against an authoritative source (the original
  patent text, an officially published translation, an unambiguous
  formatting rule). Accept or reject immediately, no need to ask.
- **4 — confident.** Strong textual/contextual evidence, no authoritative
  source needed to be sure. Accept or reject immediately.
- **3 or below — not sure.** Don't act. Collect it into a list with its
  location (paragraph/page/line) and a one-line reason for the uncertainty,
  and ask the user before doing anything.

Report back: what got accepted, what got rejected (rare — most Issue
Resolution edits are reviewer-verified corrections and should turn out
correct), and the escalation list for anything ≤3. Don't report a flat count
of "N changes reviewed" — group by what they actually were, the same way you
would for the comments in [[docx-comment-reply]].

## Workflow

### Step 1 — List every tracked change
```
python utilities/resolve_tracked_changes.py list "<file>.docx"
```
Produces `<stem>_tracked_changes/tracked_changes.json`. Read it with the Read
tool. Each entry has `ids`, `location` (e.g. `"paragraph 154"` or
`"table 0 row 0 cell 1 paragraph 0"`), `type` (`insertion` / `deletion` /
`replacement` / `paragraph_mark_insertion` / `paragraph_mark_deletion` /
`row_deletion` / `property_change:*`), `old_text`/`new_text`, `author`,
`date`, and the reconstructed paragraph both before (`paragraph_original`)
and after (`paragraph_revised`) the edit.

### Step 2 — Don't review edits one at a time — group first
Before judging anything, look at the shape of the whole list. Tracked
changes in a real Issue Resolution round are rarely 100 independent
one-word edits — they cluster. In the first real case this skill was built
from, "154 tracked changes" was actually one coherent block (an entire
missing claims section restored wholesale) plus two unrelated one-line
fixes. Group by `location` proximity and `type` before deciding anything;
review each *group* as a unit, not each XML fragment.

A large block where `paragraph_original` is empty/near-empty across many
consecutive paragraphs and `paragraph_revised` has real content usually
means: this content didn't exist before, the "edit" is a restoration, not a
correction. That's a very different (and usually higher-certainty, once
verified) review than "reviewer tweaked existing wording."

### Step 3 — Find the authoritative source, don't just judge quality
For patent claims specifically: **check whether the source PDF itself
contains an officially granted translation before judging the docx
translation on your own linguistic judgment.** EPO B2 (granted) publications
include the claims in all three official languages (EN/DE/FR) after grant —
usually a several-page block right after the English claims end. If it's
there, diff the tracked-change text against it directly; an exact match is
certainty 5 regardless of how the translation "sounds" to you. Don't
translate-review claims from scratch if an authoritative version already
exists in the same source file — find it first (`pdftoppm` + read the
pages; these PDFs are usually flattened images, `pdftotext` returns
nothing).

For everything else (spacing/formatting fixes, structure image swaps,
artifact cleanup): cross-check against the source PDF page the comment or
edit's context implies, the same way as in [[docx-comment-reply]].

### Step 4 — Resolve
```
python utilities/resolve_tracked_changes.py resolve "<file>.docx" \
    --reject <id,id,...>   # omit --reject to accept everything
```
Everything not listed in `--reject` gets accepted. Writes
`<stem>_resolved.docx` by default (non-destructive); validates the result
(zip integrity + reopens with python-docx) before writing.

### Step 5 — Confirm before overwriting
Same as [[docx-comment-reply]]: this is a production deliverable. Ask
whether to overwrite in place (`--in-place`, keeps a `.bak`) or keep the
separate `_resolved` file. Never overwrite silently.

## Gotchas

- **Tables are invisible to a naive scan.** `word/document.xml`'s table
  paragraphs live at `body > tbl > tr > tc > p` — several levels below
  `body`'s direct `<w:p>` children. An early version of the underlying
  script only scanned direct children and completely missed an artifact
  table (a stray front-page "(54)" INID-code fragment) that had its own
  row-deletion and formatting-change tracked changes. `list` now walks
  tables explicitly. If you ever hand-roll XML inspection instead of using
  the script, remember tables need a separate pass.
- **A whole table row can be marked deleted** via `<w:del>` sitting directly
  inside `<w:trPr>` — it doesn't wrap a run the way normal deletions do.
  Accepting removes the entire `<w:tr>` (and the script drops the whole
  `<w:tbl>` too if that empties it).
- **A paragraph mark itself can be tracked** (inside `<w:pPr>/<w:rPr>`) —
  this means a paragraph break was inserted or proposed for deletion, as
  opposed to any visible content changing. `resolve` supports accepting
  paragraph-mark *insertions* and rejecting paragraph-mark *deletions* (both
  = "keep this break"); it deliberately does not support the opposite
  direction of either (merging two paragraphs into one), since that's more
  structural surgery than a QA round should need — if you hit that error,
  stop and handle that one manually rather than trying to force it.
- **Table property-change bookkeeping** (`tblPrChange`, `tcPrChange`,
  `trPrChange`, `tblGridChange`) stores the *old* formatting as a child of
  the element that already holds the *new*/active formatting — accepting is
  just deleting the bookkeeping child, nothing to actually apply.
- **Re-saving through Word can re-fragment runs** without changing content —
  don't be alarmed if the raw tracked-change count changes between sessions
  on the same file (e.g. 176 → 198 after the user round-tripped it through
  Word). Diff the reconstructed `paragraph_original`/`paragraph_revised`
  text, not the raw XML element count, to confirm nothing substantive
  changed before re-running your review.
- **lxml tree mutation during `tree.iter()` skips elements.** If you're
  extending the resolve logic, collect target elements into a list first,
  then mutate — mutating while the same `iter()` call is still walking the
  tree causes it to silently skip siblings/children.
