# Phase 3 — Consolidate state

Runs after the Phase 2 barrier. Phase 2's agents produced their artifacts and returned their
hand-offs; this phase writes the state / doc updates that depend on those results. It is
single-threaded — the only writer here — so there is no race with Phase 2.

## Tracker record (when a tracker is configured)

Using the subtask key returned by `issue-tracking-agent` in Phase 2:

1. Patch `docs/stories/$ARGUMENTS.md` traceability header: `**Tracker Plan Requirements:** {KEY-XX}`.
2. Write `tracker_prd` per `docs/state/SCHEMA.md § Writer rule` — a **B-tier** field (mirrored):
   - PRIMARY — `docs/features/$ARGUMENTS/state.json`:
     ```json
     { "tracker_prd": "<KEY-XX>", "last_updated": "<iso8601>" }
     ```
   - MIRROR — `docs/state/features.json[$ARGUMENTS]`:
     ```json
     { "tracker_prd": "<KEY-XX>", "last_updated": "<iso8601>" }
     ```

   Status fields (`prd`, `phase`) were written in Phase 1 and MUST NOT be overwritten here. The
   subtask key is a separate concern from PRD completion.
3. Reflect the Phase-2 results on the subtask so they are visible in the configured tracker (when
   `provider != none`) — invoke `issue-tracking-agent` with operation `comment` on the subtask key:

   `Plan Requirements ready — Test cases: <N> (<M> automatable), coverage <PASS | GAP: ids> · Design: <complete | n/a>`

   Values come from the Phase-2 hand-offs (test-case-agent coverage result; ux-agent design status).
   Best-effort and non-blocking: on any tracker failure (MCP unavailable, permission) log it and
   continue — never fail the phase.

## Design mirror (when `design_mode != none`)

`ux-agent` set `design = complete` in the per-feature `state.json` during Phase 2. Confirm the index
mirror carries the same value; if `ux-agent` did not mirror it, mirror `design = complete` to
`docs/state/features.json[$ARGUMENTS]` now. When `design_mode == none`, the `design = "n/a"` written
in Phase 1 stands — nothing to do.

## Coverage confirmation (before the gate)

Read `docs/test-cases/$ARGUMENTS.json` and confirm `coverage_audit.uncovered == []`. If
`test-case-agent` reported an uncovered gap in its Phase 2 hand-off, surface it now:
`Coverage gap: <ids>. Resolve before Product Gate.` Do not regenerate the manifest.

## Skip conditions (must be logged)

- `provider: none` → skip the tracker record silently.
- Parent story has no tracker key → log and skip the tracker record.
- MCP was unavailable in Phase 2 (no subtask key returned) → log:
  `Tracker subtask FAILED — MCP unavailable. Re-run later.` and continue (best-effort).
