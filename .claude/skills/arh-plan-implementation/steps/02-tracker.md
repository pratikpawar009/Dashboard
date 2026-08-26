# Phase 2 — Tracker subtask (Plan Implementation)

Goal: mirror PLAN.md to the configured issue tracker as a subtask under the parent story.

Mandatory when `provider != none`.

## Procedure

Invoke `issue-tracking-agent`:

- Operation: `upsert-subtask`
- Parent story key: from the story header
- Subtask name: `Plan Implementation: <story title>`
- Subtask body: full markdown content of `docs/features/$ARGUMENTS/PLAN.md`
- Labels: `plan-implementation`, plus project labels
- Time estimate (when available): sum of S=2h / M=4h / L=8h

## After success

- Patch `docs/stories/$ARGUMENTS.md` traceability header: `**Tracker Plan Implementation:** {KEY-XX}`.
- Update state per `docs/state/SCHEMA.md § Writer rule`. `plan`, `tracker_plan`,
  `phase`, `last_updated` are all B-tier (mirrored).
  - PRIMARY (`docs/features/$ARGUMENTS/state.json`) AND MIRROR (`docs/state/features.json[$ARGUMENTS]`):
    ```json
    {
      "plan": "complete",
      "tracker_plan": "<KEY-XX>",
      "phase": "plan-implementation",
      "last_updated": "<iso8601>"
    }
    ```
  The `plan` field is a STATUS (`complete` | `pending`), not a tracker key. `/arh-implement`
  Step 0 reads it via the phase-preconditions matrix (`plan == "complete"`).
  Storing the tracker key in `plan` would break the precondition gate. The subtask key
  goes in the separate `tracker_plan` field (mirrors `tracker_story`, `tracker_research`,
  `tracker_prd`). When `provider == none`, set `plan: "complete"` and omit `tracker_plan`.

## Advance parent story status (best-effort, non-blocking)

After the state write above completes, dispatch a **second** `issue-tracking-agent` call to
advance the **parent story's** tracker status. The harness state written above is the source
of truth; this transition is best-effort and **MUST NOT block or fail the phase**. On any
failure (no matching status, permission, MCP unavailable) log it and continue — never roll
back or re-run the phase.

- Operation: `transition`
- Issue key: the parent story key (not the subtask)
- Target stage: `in-progress`  (agnostic literal — the provider skill maps it to the
  tracker's real status; never name a provider status here)

Skip silently when `provider: none` or the parent story has no tracker key.

## Skip conditions (must be logged)

- `provider: none` → skip silently.
- Parent story has no tracker key → log: `Plan subtask skipped — parent not synced.`
- MCP unavailable → log: `Plan subtask FAILED — MCP unavailable. Re-run later.`
- Project has no subtask issue type → log: `Subtask type unavailable; PLAN recorded locally only.`
