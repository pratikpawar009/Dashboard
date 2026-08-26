---
name: tracker-sync
description: Pull tracker + doc-tracker state into the harness — pull procedures per provider, three-way merge decision matrix, drift report format, state baseline write. Used by sync-agent.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep mcp__github__*
---
# Tracker sync

The method for pulling remote tracker / doc-tracker state back into the harness and merging it against local edits. Apply the phases in order. Never overwrite without explicit user approval.

Phase numbering used throughout: 1 = Pull issue tracker, 2 = Pull doc tracker, 3 = Three-way merge, 4 = Drift report.

## Pull issue tracker

Goal: fetch the current state of every tracker issue referenced in `state/features.json` and diff against the local story files.

Skipped when `provider: none` in `docs/config/issue-tracking.yaml` or when `--doc-tracker` flag was passed.

### Procedure

For every entry in `docs/state/features.json` (index) with a non-null `tracker_story` key — iterate the index for cross-feature scan; for each id, read the canonical record via reader rule (`docs/features/<id>/state.json` if present, else the index entry):

1. Call the matching MCP tool to fetch current issue:
   - Jira: `mcp__atlassian__get_issue(issueIdOrKey=$tracker_story)`
   - Linear: `mcp__linear__getIssue(id=$tracker_story)`
   - GitHub Issues: `mcp__github__getIssue(owner=…, repo=…, issue_number=…)`
   - GitLab: `mcp__gitlab__get_issue(project_id=…, issue_iid=…)`
   - Azure DevOps: `mcp__ado__getWorkItem(id=…)`
2. Extract canonical fields from the response:
   - `summary` / `title`
   - `description` (markdown body)
   - `status` (mapped through `docs/config/issue-tracking.yaml status_workflow`)
   - `priority` (mapped through `priorities` in config)
   - `assignee` (when populated)
   - `labels`
   - `epic_link` / `parent` field
3. Stash the remote snapshot as `tmp/arh-sync/<id>.remote.json` for Phase 3.

### Acceptance criterion fields

For each issue, also fetch:

- Acceptance criteria text (Jira: custom field; Linear: description body block).
- NFR fields if the team encodes them as labels (`nfr-perf-p95`, `nfr-a11y-aa`).

The agent infers location from `docs/config/issue-tracking.yaml field_mapping`. When mapping is missing, the agent flags it and skips that field with a log line.

### Rate limiting

- Batch up to 50 issues per MCP call when the provider supports it (Jira `searchByJQL`, Linear
  bulk, GitLab `mcp__gitlab__list_issues`).
- Backoff on 429 with exponential delay (1s, 2s, 4s; max 3 retries).
- After 3 retries, abort the per-feature pull and continue with the rest. Surface affected ids in the report.

### Output (per feature)

```json
{
  "<EPIC>-<SEQ>": {
    "remote_summary": "...",
    "remote_description": "...",
    "remote_status": "Ready for Refinement",
    "remote_priority": "Should",
    "remote_labels": ["promo", "checkout"],
    "remote_acs": ["...", "..."],
    "remote_nfrs": {"perf_p95_ms": 250},
    "fetched_at": "<iso8601>"
  }
}
```

Stored under `tmp/arh-sync/issue-snapshots.json` for Phase 3 to consume.

### Edge cases

- **404 on tracker key (story-deleted-on-remote, Y2)** — issue moved, deleted, or permanently archived on remote. Emit a `tracker-deleted` finding in Phase 4 with the local file path. Do NOT delete the local story file or remove the tracker key from state. The user resolves manually:
  1. If the remote deletion is legitimate (issue closed, replaced) → run `/arh-sync --apply` after deciding to keep, archive, or rename the local story. The agent never auto-deletes local content.
  2. If the remote deletion was accidental → user restores in tracker, re-runs `/arh-sync`.
- **MCP auth failure** — abort Phase 1 entirely with the env var name to set (GitLab:
  `GITLAB_TOKEN`); do not partially apply.
- **Throttling beyond 3 retries** — partial pull; flag affected ids in the report; user re-runs `/arh-sync` after rate window resets.
- **Issue with no tracker key in state file (orphaned-local, Y3)** — when issue-tracker provider is configured but `tracker_story` is absent in the index entry for a non-imported story (`story != "imported:*"`), surface in Phase 4 under `## Orphaned local items`. Suggest `/arh-intake` Step 5 (issue-tracker-sync) to register the story upstream. Do not block the sync.


## Pull doc tracker

Goal: fetch RTM page + per-feature PRD pages from Confluence/Notion and diff against `docs/requirements/RTM.md` and `docs/features/<id>/REQUIREMENTS.md`.

Skipped when `provider: local` in `docs/config/doc-tracker.yaml` or when `--issue-tracker` flag was passed.

### Procedure

### 2a. RTM page

1. Read `docs/config/doc-tracker.yaml` for `provider`, `space_key` / `database_id`, and `parent_page_title`.
2. Fetch the RTM page:
   - Confluence: `mcp__atlassian__get_page` by title under `space_key`.
   - Notion: `mcp__notion__get_page` for the database root or page id stored in config.
3. Convert page body to markdown (Confluence storage format → markdown; Notion blocks → markdown).
4. Stash as `tmp/arh-sync/rtm.remote.md` for Phase 3.

### 2b. Per-feature PRD pages

For every entry in `docs/state/features.json` (index) with a non-null `tracker_prd` key OR a doc-tracker page id stored — iterate the index for cross-feature scan; for each id, read canonical record via reader rule:

1. Fetch the page body via the matching MCP server.
2. Convert to markdown.
3. Stash as `tmp/arh-sync/<id>.prd.remote.md`.

When the feature has no doc-tracker page id but has a `tracker_story` key in Jira/Linear, the agent attempts to resolve the doc page by title pattern (`<EPIC>-<SEQ>: <title>`). If no match, flag for Phase 4 reporting; do not invent a page id.

### Caching

Cache pulled pages for 5 min by feature id to avoid re-fetching when `/arh-sync --all` is re-run rapidly. Cache path: `tmp/arh-sync/cache/`. Bypass with `--no-cache`.

### Page-attachment scope

For now, sync pulls the page body only. Attachments (PDFs, embedded images, Notion file uploads) are out of scope for v1; the report flags features whose tracker page has new attachments since `last_synced_at`.

### Output (per feature)

```json
{
  "<EPIC>-<SEQ>": {
    "remote_prd_body": "...",
    "remote_prd_url": "https://...",
    "remote_attachments_count": 3,
    "remote_attachments_changed_since_last_sync": true,
    "fetched_at": "<iso8601>"
  }
}
```

Stored under `tmp/arh-sync/doc-snapshots.json`.

### Edge cases

- **Page deleted** — flag in Phase 4. Do not delete local PRD.
- **Page renamed** — title pattern resolution fails; flag for human review.
- **Notion database schema mismatch** — body extraction works but field mapping fails for a column. Skip that field; log and continue.
- **Confluence storage-format conversion errors** — when the page contains custom macros not supported by markdown, escape the unsupported block as `<!-- unsupported macro: <name> -->` and continue.


## Three-way merge

Goal: reconcile remote (tracker) values, local (harness) values, and the last-synced snapshot. Auto-apply when only one side changed; surface conflicts when both changed since last sync.

### Three-way inputs per field

```
base    = value at last_synced_at (read from `docs/features/<id>/state.json` at `.sync_baseline.<field>`; pre-plan features have no sync_baseline yet)
local   = current value in docs/stories/<id>.md or docs/features/<id>/REQUIREMENTS.md
remote  = value pulled in Phase 1 / Phase 2 (tmp/arh-sync/<id>.{remote,prd.remote})
```

### Decision matrix

| base | local | remote | resolution |
|---|---|---|---|
| `X` | `X` | `X` | no change — skip |
| `X` | `X` | `Y` | remote-only change — auto-apply when `--apply`, but for AC/PRD-body fields, **classify first** (see below) |
| `X` | `Y` | `X` | local-only change — keep local; tracker should be re-pushed by next `/arh-intake` Step 5 |
| `X` | `Y` | `Y` | converged independently — log; pick `Y` (no-op) |
| `X` | `Y` | `Z` | **CONFLICT** — surface in report; do not auto-resolve; user picks |

### Classify before auto-applying AC / PRD-body content

Status, priority, and labels are process metadata, not claims about the code — an `X|X|Y` row on those fields always auto-applies as-is, no classification needed.

**Acceptance criteria and PRD body text are different: they can describe what the code does.** A ticket's AC text drifts from reality constantly — someone changes the behavior and never updates the ticket. Auto-applying an `X|X|Y` row on these fields without checking is exactly what let a stale ticket silently overwrite a locally-correct acceptance criterion. Before auto-applying a remote change to an AC or PRD-body field, classify what the remote text is actually claiming:

1. **Does it name a specific, checkable thing** — an endpoint, a function, a field, a status code, a behavior? If not (it's a vague or purely aspirational statement), treat it as **prescriptive** and auto-apply normally; there's nothing to check it against.
2. **If it does name something checkable, look at the actual code** (grep/read the relevant file — the story's linked implementation, or the module the AC describes).
   - **Descriptive and it matches the code** — the ticket is just confirming current behavior. Apply it; it's a no-op in substance.
   - **Descriptive and it contradicts the code** — the ticket is describing something that already exists but got the details wrong, or the code changed since. **Code wins.** Do NOT auto-apply. Write it to `docs/sync/conflicts-<DATE>.md` under a `code-wins, doc-stale` verdict instead, same file the CONFLICT row already uses — this is not a new report or a new state field, just one more entry in the existing one.
   - **Prescriptive** ("must support partial refunds", "should return 404 not 403") — a real instruction to change something. Auto-apply normally; this is exactly what `/arh-sync` exists for.
3. When genuinely unsure whether a claim is descriptive or prescriptive, default to treating it as a conflict (do not auto-apply) — a missed real update costs a re-run; a wrongly-applied stale description costs a silently broken requirement.

### Field-by-field application

Apply the matrix per field, not per file. Story-level fields go to `docs/stories/<id>.md`; PRD-level fields go to `docs/features/<id>/REQUIREMENTS.md`.

### Story file fields

- Title (`# Story: <id> — <title>`)
- ACs (`## Acceptance criteria` numbered list)
- NFRs
- Status (mapped from `remote_status` via `status_workflow`)
- Priority (`P1|P2|P3` from MoSCoW mapping)
- Labels (replace whole list when changed)

### PRD file fields

- Body (full document) — handled as a unified diff. Agent presents the diff per section, not the whole body, when `--apply` is used interactively.

### Auto-apply rules

When `--apply` is set:

- Auto-resolvable changes (`X|X|Y` rows) write to local files.
- Conflicts (`X|Y|Z` rows) are written to `docs/sync/conflicts-<DATE>.md` and reported. Local files are NOT modified for conflicts.
- After apply, update `docs/features/<id>/state.json` at `.sync_baseline` to remote values; set `.last_synced_at` to now (P-tier; no index mirror). For pre-plan features that lack a per-feature file, skip the baseline write — `/arh-sync` only persists baselines for features past plan-requirements migration.

When `--dry-run` is set (default):

- No file mutations.
- Phase 4 prints the planned changes per feature.

### Marker discipline carry-over

If the remote PRD body still contains `[NEEDS CLARIFICATION: ...]` markers from a prior session, the merge keeps them; the agent does not silently resolve. The agent surfaces marker-count diff (remote vs local) in Phase 4 so the user knows whether stakeholders ANSWERED any markers in the tracker.

### Output

`tmp/arh-sync/merge-plan.json` — per-feature, per-field plan that Phase 4 renders into a human-readable report.

```json
{
  "<EPIC>-<SEQ>": {
    "auto_apply": [
      {"field": "status", "from": "Draft", "to": "Ready"},
      {"field": "labels", "from": ["promo"], "to": ["promo", "tier-1"]}
    ],
    "conflicts": [
      {"field": "ac.2", "base": "...", "local": "...", "remote": "..."}
    ],
    "skipped": [
      {"field": "summary", "reason": "no change"}
    ]
  }
}
```

### Anti-patterns

- Silent auto-merge of conflicts. Always surface; user picks.
- Field-by-field apply when local has uncommitted manual edits. The pre-flight check rejects an unclean working tree.
- Re-pushing local changes to the tracker in this phase. `/arh-sync` is pull-only; `/arh-intake` Step 5 owns push.
- Auto-applying a descriptive AC/PRD-body change without checking it against the actual code first — the exact bug the classify step above exists to close.


## Drift report

Goal: render the merge plan into a human-readable drift report. Always print, regardless of `--dry-run` vs `--apply`.

### Report path

- Always print to stdout.
- Also write to `docs/sync/sync-<YYYYMMDD-HHMM>.md` so the user can review later.

### Report structure

```
# Sync Report — <iso8601>

- Mode: <dry-run | apply>
- Sources: <issue-tracker | doc-tracker | both>
- Features pulled: <count>
- Drift detected: <count>

### Auto-resolvable (<count>)

| Feature | Field | From | To |
|---|---|---|---|
| CHK-014 | status | Draft | Ready |
| CHK-018 | labels | [promo] | [promo, tier-1] |
| CHK-022 | priority | Should | Must |

<!-- when --apply, these are written. When --dry-run, action prompt at end. -->

### Conflicts (<count>) — manual review needed

### CHK-018 — AC #2 differs three ways

```
base (last sync):
  Given a logged-out user, when they apply a code, then they see "sign in to apply".

local (current story file):
  Given a logged-out user, when they apply a code, then the code is held in session and applied at login.

remote (tracker):
  Given a logged-out user, when they apply a code, then they are redirected to login with the code in URL.
```

User must pick one (or merge). Resolution recorded in `docs/sync/conflicts-<DATE>.md`.

### CHK-022 — NFR perf budget

```
base: p95 < 500ms
local: p95 < 250ms (tightened during /arh-research)
remote: p95 < 1000ms (relaxed by ops in tracker)
```

### Skipped (<count>)

| Feature | Field | Reason |
|---|---|---|
| CHK-001 | summary | no change |
| CHK-005 | (all) | no tracker_story key in state |

### Tracker errors (<count>)

| Feature | Tracker key | Error |
|---|---|---|
| CHK-027 | ACME-91 | 404 — issue moved or deleted |
| CHK-031 | (rate-limited) | retry exhausted; re-run /arh-sync |

### Doc-tracker drift (<count>)

| Feature | Page | Change since last_synced_at |
|---|---|---|
| CHK-014 | https://acme.atlassian.net/wiki/spaces/ENG/pages/14 | body changed; 1 new attachment |

### Next steps

- `<count>` auto-resolvable changes available. Run `/arh-sync --apply` to write them.
- `<count>` conflicts require manual review. See `docs/sync/conflicts-<DATE>.md`.
- `<count>` tracker errors. Investigate auth/connectivity, then re-run.
- `<count>` features have new doc-tracker attachments — open the URL to review.
```

### Apply mode tail

When `--apply` was used, append to the report:

```
APPLIED CHANGES
─────────────────
Files modified:    <list of paths>
docs/features/<id>/state.json updated for <count> post-plan features (last_synced_at set to <iso8601>)
sync_baseline refreshed for <count> features (per-feature only — pre-plan features have no baseline yet)

Conflicts NOT applied. Resolve manually then re-run /arh-sync --apply.
```

### Dry-run mode tail

```
DRY RUN — no files modified.

Run /arh-sync --apply to write the auto-resolvable changes.
Conflicts will not be auto-applied; review them in the report above first.
```

### Exit code

- 0 — clean (no drift, no conflicts).
- 1 — drift detected (auto-resolvable or conflicts present). CI uses this as a regression signal.

### Anti-patterns

- Silently writing changes without printing them.
- Bundling conflicts into the auto-resolvable list to inflate the "fixed" count.
- Skipping the report when `--apply` succeeds — humans need to see what changed.

