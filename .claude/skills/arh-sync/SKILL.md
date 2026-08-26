---
name: arh-sync
description: Pull-on-demand bidirectional sync — pulls tracker / doc-tracker changes back into harness state and stories. Three-way merge with manual edits.
argument-hint: "[--issue-tracker | --doc-tracker | --all] [--dry-run | --apply]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep
---
# /arh-sync — Pull-on-demand drift sync

The harness is the source of truth, but trackers (Jira/Linear/Confluence/Notion) drift when humans edit issues directly. `/arh-sync` pulls remote state back into the harness with a three-way merge against manual local edits. Never auto-overwrites — `--dry-run` reports drift; `--apply` writes after explicit user approval.

Hybrid flow: the gate (Phase 0) runs inline here in the main session; the pull + merge + report (Phase 1) is delegated to the `sync-agent` subagent (model `haiku`), which applies the `tracker-sync` skill plus the provider integration skills its frontmatter declares (via Jinja, per the project's `harness.yaml integrations`): `requirement-tracing`, one of `issue-tracking-jira` / `issue-tracking-linear` / `issue-tracking-github` / `issue-tracking-gitlab` / `issue-tracking-azure`, and one of `doc-tracker-confluence` / `doc-tracker-notion` when configured.

**Input flags:**

- `--issue-tracker` — pull from Jira/Linear/GitHub-Issues/Azure-DevOps only.
- `--doc-tracker` — pull from Confluence/Notion only.
- `--all` (default when no flag) — both.
- `--dry-run` (default) — print drift; do not write.
- `--apply` — write changes after presenting per-feature diff.

## Pipeline

```
0. Gate                  (main, read-only)
   → INVOKE sync-agent    (pull issue tracker → pull doc tracker → three-way merge → drift report)
2. Summary               (main: consume the agent's hand-off)
```

## Phase 0 — Gate

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-precondition.md`

If any precondition fails (configs missing, MCP unreachable), abort here with the helpful message and do NOT invoke the agent.

## Phase 1 — Pull + merge + report (invoke sync-agent)

Invoke the `sync-agent` subagent, passing the input flags. It applies skill `tracker-sync`: pulls the configured issue tracker and/or doc tracker, runs the three-way merge decision matrix against local edits, renders the drift report, and on `--apply` writes auto-resolvable changes plus the per-feature `.last_synced_at` / `.sync_baseline` state fields. Conflicts are never auto-resolved — they surface for manual resolution.

Consume the agent's hand-off (auto-applied / conflicts / tracker-error counts + report path) for the summary below.

## Final summary

```
SYNC COMPLETE
──────────────────────────────────────
Mode:                <dry-run | apply>
Sources:             <issue-tracker | doc-tracker | both>
Features pulled:     <count>
Drift detected:      <count>
  ├─ Story field:    <count>     (e.g. AC text changed in tracker)
  ├─ NFR budget:     <count>
  ├─ Status:         <count>
  └─ Tracker key:    <count>     (issue moved or deleted)

Auto-resolvable:     <count>     (no local edit conflict)
Conflicts:           <count>     (local edit + remote change; user picks)

Last synced:         <iso8601>   (written per-feature to docs/features/<id>/state.json `.last_synced_at`)

Next:
  /arh-sync --apply     to write the auto-resolvable changes
  manual review     for conflicts (see drift report)
```

## When to run

- After a sprint where stakeholders edited Jira issues directly.
- Before `/arh-plan-implementation` if you suspect the source story drifted from RTM.
- Nightly in CI to surface drift early.
- After importing a brownfield repo and stakeholders amended fields you did not capture in `/arh-import`.

## When NOT to run

- Mid `/arh-intake` or `/arh-research` — the harness is mid-write; sync would race.
- During an active session with uncommitted manual story edits — commit or stash first.
- When tracker MCP is throttled or auth is failing — investigate auth before sync.

## Anti-patterns

- Auto-applying without user diff approval. Always present the diff; wait for confirmation.
- Bidirectional auto-merge without conflict resolution — silently picks a winner; data loss.
- Treating tracker as source of truth permanently. The harness owns the canonical artefact; sync is corrective, not directional.
