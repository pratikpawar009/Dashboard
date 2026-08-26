# Phase 2 — Tracker subtask (mandatory when configured)

Goal: mirror the Feasibility Assessment to the configured issue tracker as a subtask under the parent story so non-Claude readers see the same source of truth.

**Mandatory** when `docs/config/issue-tracking.yaml` has `provider != none`. This phase runs in the main session (the `research-agent` cannot reach MCP tools or spawn `issue-tracking-agent`). The orchestrator must not end its run without completing this OR explicitly logging why it was skipped.

## Procedure

Invoke `issue-tracking-agent` with:

- Operation: `upsert-subtask`
- Parent story key: from `docs/stories/$ARGUMENTS.md` traceability header
- Subtask name: `Research: <story title>`  (stable across re-runs so upsert updates in place — do NOT vary by status)
- Subtask body: a one-line status header followed by the full markdown of `docs/research/$ARGUMENTS.md`:
  - Header: `Verdict: <verdict> · Score: <T>/100 · Open clarifications: <N>`
  - When verdict ∈ {SPIKE, BLOCK} **or** open-clarifs > 0, prepend a banner:
    `> ⚠ NOT YET CERTIFIED — <N> open clarification(s) / verdict <verdict>. Do not start /arh-plan-requirements until clarifications are resolved.`
- Labels: `research`, plus `pending-clarifications` when not certified, plus the project labels from `docs/config/issue-tracking.yaml`

## Skip conditions (must be logged)

| Condition | Log message |
|---|---|
| `provider: none` | `Tracker subtask skipped — provider=none.` |
| Parent story has no tracker key | `Tracker subtask skipped — parent story not synced; run /arh-intake first.` |
| Tracker MCP unavailable | `Tracker subtask FAILED — MCP unavailable. Re-run after restoring connection.` |
| Project lacks subtask issue type | `Tracker subtask skipped — project has no subtask type.` |

## After success

- Patch `docs/stories/$ARGUMENTS.md` traceability header with `**Tracker Research:** {KEY-XX}`.
- Update `docs/state/features.json` for `$ARGUMENTS` with the tracker key only:
  ```json
  {
    "tracker_research": "<KEY-XX>",
    "last_updated": "<iso8601>"
  }
  ```
  Status fields (`research`, `research_verdict`, `phase`) are written in Phase 4
  (artefact-creation time) and MUST NOT be overwritten here. The subtask key is a
  separate concern from research completion.

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

## Anti-pattern

Do not silently skip. Do not "best-effort" without logging the reason. Either succeed and report the key, or surface a specific reason. The user must always know whether the tracker reflects reality.
