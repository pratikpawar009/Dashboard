# Phase 0 — Preconditions

Goal: confirm the configs and MCP servers are reachable before pulling.

## Preconditions (mandatory)

Load skill `phase-preconditions` and apply the `/arh-sync` row of its matrix — the row's conditions (tracker configs present, MCP server + auth env reachable) and abort message are canonical there; do not re-derive them.

## Mode resolution

Determine mode from `$ARGUMENTS`:

| Flag | Effect |
|---|---|
| `--issue-tracker` | Phase 1 only |
| `--doc-tracker` | Phase 2 only |
| `--all` (default when no flag) | Phase 1 and Phase 2 |
| `--dry-run` (default) | Read-only; emit drift report |
| `--apply` | Write merged values; update `last_synced_at` |

`--apply --all` runs both pulls AND writes results. Without `--apply`, no file mutations happen except the drift report.

## Pre-flight

- Working tree is clean enough to apply patches without merge conflicts (no half-merged conflicts in `docs/stories/` or `docs/features/`).
-- `docs/features/<id>/state.json (per-feature, post-plan) and docs/state/features.json (index)` exists; otherwise abort: `State file missing; run /arh-init first.`
- Network reachability to the configured MCP endpoints. If `mcp__atlassian__*` or equivalent fails on a smoke call, abort with the underlying error and the env var name to check.

## Orphaned-local scan (Y3)

Before Phase 1, scan `state/features.json` for orphaned-local entries — local stories that should be in the tracker but are not:

- Entry has `story` set (not `null`)
- Entry's `story` is NOT `"imported:*"` (imported stories may never sync upstream)
- Issue-tracker provider is configured (`provider != none`)
- Entry has NO `tracker_story` key

Each match becomes an orphaned-local finding in the Phase 4 report under `## Orphaned local items`. The agent does NOT auto-create remote issues — `/arh-intake` Step 5 (issue-tracker-sync) is the right tool for that. The drift report surfaces the gap.

Orphaned-local items do NOT block `/arh-sync` from proceeding with the rest of the work.

## Output

```
SYNC PRE-FLIGHT
─────────────────
Configs:        issue-tracking.yaml=<jira|linear|github|gitlab|azure-devops|none>  doc-tracker.yaml=<confluence|notion|local>
MCP reachable:  atlassian=<ok|fail>  linear=<ok|fail>  gitlab=<ok|fail>  notion=<ok|fail>
Mode:           <issue|doc|all>  <dry-run|apply>
Features:       <count>          (from state/features.json)

Proceeding to Phase 1.
```

If any config is `none`/`local` for a requested mode, log and skip the corresponding pull phase silently.
