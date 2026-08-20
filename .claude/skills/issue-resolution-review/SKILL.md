# Issue Resolution Review Skill

Orchestrates [[docx-comment-reply]] and [[resolve-tracked-changes]] across every
part of an Issue Resolution job in one invocation, using the manifest and
status files those steps already produce as the source of truth — so this is
one command instead of manually figuring out which of N parts need which
skill. This is the piece of the Issue Resolution workflow/skillset meant to
be run from a phone via Claude Code Remote Control when a job is urgent and
you're away from your desk — the local session it connects to has the same
filesystem/skill access as running it directly, so nothing here is
mobile-specific.

## Key files

| File | Purpose |
|---|---|
| `pre-processing/issue_resolution_manifest.json` | Written by `ISSUE_RESOLUTION_LOCATE` (the app step) — per-part docx paths + `source_file` for cross-reference |
| `pre-processing/issue_resolution_status.json` | Written by `check_docx_resolved.py` — per-part `clean`/`had_comments`/`had_tracked_changes`/`problems` |
| `pre-processing/issue_resolution_xtm_corrections.json` | What you draft at the end of this skill (see Step 4) — read by `XTM_SEGMENT_MATCH` |

## Workflow

### Step 0 — Locate the project and get current status
```
python3 -c "import project_log; print(project_log.find_project_dir('<project_id>'))"
```
Read `issue_resolution_manifest.json` from that folder. If `issue_resolution_status.json`
doesn't exist yet, or you suspect it's stale (e.g. the app hasn't been touched since
`ISSUE_RESOLUTION_LOCATE`), run `python3 check_docx_resolved.py --pid <project_id>`
yourself first (from the `agent/` directory) to get a current read — this skill can
call app scripts directly via Bash, no need to go back to the app UI for this part.

If `status["any_needed_work"]` is `False` for every part: nothing to do here at all —
tell the user and stop. (In practice they'd rarely reach this skill in that case, since
the app's own `ISSUE_RESOLUTION_REVIEW_CHECK` step already tells them so directly —
but check anyway rather than assume.)

### Step 1 — Process each unresolved part
For every entry in `status["parts"]` where `"clean": false`:

1. Look up that part's `renamed_docx` and `source_file` from the manifest.
2. Read its `problems` list from status.json to see what's actually wrong —
   don't re-derive this, it's already there (tracked-change locations, which
   comment ids lack a reply from you specifically).
3. If any problems mention comments → invoke the `docx-comment-reply` skill on
   this docx (with the source file for cross-reference), per its own workflow.
4. If any problems mention tracked changes → invoke the `resolve-tracked-changes`
   skill on this docx, per its own certainty protocol (≥4 act, ≤3 escalate to
   the user — this still happens here, mobile or not; nothing about running
   from Remote Control changes the bar for autonomous judgment on legally
   binding patent text).
5. Move to the next unresolved part. Work through all of them before re-checking —
   don't ping-pong between the check script and individual parts.

### Step 2 — Re-verify
```
python3 check_docx_resolved.py --pid <project_id>
```
If it now reports `all_clean: true`, proceed to Step 3. If not — some items were
likely escalated back to the user per the skills' own certainty protocol rather
than resolved automatically; report exactly what's still outstanding (the same
per-part `problems` the script prints) and stop. Don't loop on this indefinitely
or guess your way past an escalation you were specifically told to raise.

### Step 3 — Report
Summarize what was accepted/rejected/answered, per part, the same way
[[resolve-tracked-changes]] and [[docx-comment-reply]] already report their own
work. This is the point to tell the user the job is ready for
`ISSUE_RESOLUTION_XTRF_UPLOAD` in the app.

### Step 4 — Draft the XTM corrections file (if any_needed_work was true)
You just did the resolution work in this same session, so you already know which
fixes were pure DTP/image/linebreak issues (never XTM-relevant) versus genuine
text-content fixes (typos, wording, spacing) that need propagating to the live
XTM translation — this is exactly the judgment call `XTM_SEGMENT_MATCH` deliberately
leaves to a human/skill session rather than trying to infer itself. Draft
`pre-processing/issue_resolution_xtm_corrections.json` — a `[{"old_text": "...",
"new_text": "..."}]` list — from the accepted tracked-change old/new text and any
comment-driven wording fixes, but **show the draft to the user for confirmation
before writing it** (or before treating an already-written one as final) — don't
silently write and let `XTM_SEGMENT_MATCH` run on unconfirmed judgment. If nothing
qualifies, say so explicitly and don't write an empty file speculatively — its
absence has a specific meaning downstream (see [[project-patent-resolve-tracked-changes]]-adjacent
scripts) that you don't want to create by accident.

## Gotchas

- **Don't reinvent what status.json already computed.** The `problems` list is
  the ground truth for what's wrong with a part — read it, don't re-run
  `extract_docx_comments`/`resolve_tracked_changes` from scratch to figure out
  the same thing a second time.
- **Per-part, not per-job.** A job can have multiple parts (Figures +
  Specification, etc.) with completely independent resolution states — process
  each on its own, exactly like [[resolve-tracked-changes]] and
  [[docx-comment-reply]] already operate one docx at a time.
- **This skill does not touch XTRF or XTM itself.** It stops at "docx resolved,
  corrections drafted" — uploading and pushing corrections stays the app's job
  (`ISSUE_RESOLUTION_XTRF_UPLOAD`, `XTM_SEGMENT_MATCH`, `XTM_CORRECTION_UPLOAD`),
  run separately once you're back at the app (or via Bash against the same
  scripts, if that's more convenient mid-session — they're just as callable
  from here as the check script is).
