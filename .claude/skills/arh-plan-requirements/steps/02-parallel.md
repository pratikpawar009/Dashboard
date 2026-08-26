# Phase 2 — Parallel: test cases, design, tracker

The PRD (`docs/features/$ARGUMENTS/REQUIREMENTS.md`) is complete from Phase 1. Three units of work
depend only on it and are independent of each other — dispatch them **concurrently in a single
turn** (multiple `Task` calls in one assistant message), then barrier before Phase 3.

All three READ the finished PRD and write disjoint targets, so there is no write conflict:

| Agent | When | Reads | Writes |
|---|---|---|---|
| `test-case-agent` | always | PRD `## Functional` / `## Non-functional requirements` | `docs/test-cases/$ARGUMENTS.json` |
| `ux-agent` (provider from `integrations.design`) | `design_mode != none` | PRD `## Screen inventory` | `DESIGN.md` + `design = complete` in `state.json` |
| `issue-tracking-agent` | tracker configured (`provider != none`) | PRD | tracker subtask + parent transition (remote); returns the subtask key |

## State-write safety (why this is race-free)

Only `ux-agent` writes `state.json` during this phase (`design = complete`). `test-case-agent`
writes no state. `issue-tracking-agent` performs remote operations only and RETURNS the subtask
key — the `tracker_prd` state write is deferred to Phase 3 (Consolidate). So exactly one writer
touches `state.json` in the parallel wave; there is no read-modify-write race.

## Dispatch

1. In one turn, invoke concurrently:
   - `test-case-agent` with `$ARGUMENTS`.
   - `ux-agent` with `$ARGUMENTS` — only when `design_mode != none` (the provider-specific skill is
     wired by the composer). It reads `## Screen inventory`, writes `DESIGN.md`, replaces the
     `## Visual spec` stub with a one-line pointer, and sets `design = complete` (B-tier; mirror to
     index).
   - `issue-tracking-agent` — only when a tracker is configured (see the call spec below).
2. **Barrier** — wait for every dispatched agent to finish before Phase 3.
3. Collect their hand-offs — the test-case coverage result, the DESIGN.md pointer, and the tracker
   subtask key — and carry them into Phase 3.

## issue-tracking-agent call (when tracker configured)

- Operation: `upsert-subtask`
- Parent story key: from `docs/stories/$ARGUMENTS.md` traceability header
- Subtask name: `Plan Requirements: <story title>`
- Subtask body: full markdown of `docs/features/$ARGUMENTS/REQUIREMENTS.md`
- Labels: `plan-requirements`, plus project labels
- Then advance the **parent story** to agnostic stage `in-progress` — best-effort, non-blocking:
  on any failure (no matching status, permission, MCP unavailable) log it and continue, never fail
  the phase, never roll back.

The agent does NOT write `state.json`; it returns the subtask key for Phase 3. Skip the tracker
branch silently when `provider: none`.
