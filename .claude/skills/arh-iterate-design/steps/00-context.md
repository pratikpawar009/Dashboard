# Phase 0 — Context + preconditions

Goal: parse the invocation arguments, verify preconditions, and prepare the iteration context for ux-agent.

## Argument parsing

`$ARGUMENTS` is split positionally:

- `$ARGUMENTS[0]` → feature id (e.g. `BKM-04`). Required; abort with `Usage: /arh-iterate-design <feature-id> [--feedback "..."] [--reset]` when missing.
- Remaining args scanned for `--feedback "<text>"` and `--reset` flags. `--feedback` value is captured verbatim (may include spaces; preserve the user's prose).

Store the parsed args:

```
feature_id = $ARGUMENTS[0]
feedback   = <--feedback value | empty>
reset      = <true | false>
```

## Preconditions

Load skill `phase-preconditions`. Apply the `/arh-iterate-design <id>` row:

- `state[feature_id].prd == "complete"` — otherwise abort: `Run /arh-plan-requirements <id> first; no PRD to iterate from.`
- `state[feature_id].design != "n/a"` — otherwise abort: `Feature <id> has design = n/a (backend-only). Nothing to iterate. Run `harness add integration design <provider>` and re-run /arh-plan-requirements if UX is now in scope.`
- `integrations.design != "none"` — otherwise abort: `integrations.design == none. Run `harness add integration design <provider>` first.`

Do NOT require `gate == APPROVE`. Iteration runs at any phase — before product gate (refining draft design), after gate (refining post-approval), during /arh-implement (visual fidelity gap).

## Read in order

1. `docs/features/$ARGUMENTS[0]/state.json` — current `design`, `design_provider`, `design_iteration`, `design_artifact` (P-tier fields).
2. `docs/features/$ARGUMENTS[0]/REQUIREMENTS.md` — authoritative `## Screen inventory`. The ux-agent will NOT add screens not in this section.
3. `docs/features/$ARGUMENTS[0]/DESIGN.md` (when present) — the existing design output. Iteration mode reads this as the **baseline** and applies `--feedback` as a delta. Absent → ux-agent runs first-pass (equivalent to fresh `/arh-plan-requirements` design phase).
4. `docs/design/schema.json` — workspace design system + accumulated tokens.

## Reset handling

When `--reset` is passed:

- **figma**: delete only `docs/features/<id>/DESIGN.md` locally. The Figma file (shared, external) stays untouched — `--reset` does NOT call any Figma MCP delete. Surface a notice: `--reset: removed local DESIGN.md; Figma feature page remains (delete manually if needed).`
- **claude-design**: delete `docs/features/<id>/DESIGN.md` only. The user-exported bundle under `docs/design/<id>/` is user-owned — never touched.
- **html-mockup**: delete `docs/features/<id>/DESIGN.md` AND `docs/design/<id>/screens/*.html` AND `docs/design/<id>/tokens.css` (all Harness-generated, safe to wipe).
- **stitch**: delete only `docs/features/<id>/DESIGN.md`. Stitch project stays untouched.

Without `--reset`, the prior DESIGN.md is kept as iteration baseline (ux-agent reads it).

## Archive the prior DESIGN.md

Whether `--reset` was set or not, if `DESIGN.md` exists before this run, copy it to `docs/features/<id>/DESIGN.history/round-<N>-<ISO8601>.md` where `N = .design_iteration` from `docs/features/<id>/state.json`. Idempotent — never overwrite an existing archive file (timestamps make collisions vanishingly rare).

The archive is for audit / diff: future readers can see how the design evolved across iterations. Never used by code; humans only.

## State write

Bump the iteration counter and mark in-progress:

```json
{
  "design": "pending",
  "design_iteration": "<prior + 1; default 1 if absent>",
  "last_updated": "<iso8601>"
}
```

If `design = complete` was the prior state, archive AND bump. If `design = pending` (prior iteration didn't finish), still bump — every invocation is one round.

## Output

```
/arh-iterate-design <feature-id>  round <N+1>
  Provider:    <integrations.design>
  Feedback:    <verbatim | (none — full refresh)>
  Reset:       <yes | no>
  Baseline:    DESIGN.md (round <N>) archived to docs/features/<id>/DESIGN.history/round-<N>-<iso>.md
  Next:        invoke ux-agent
```

Then proceed to Step 1.
