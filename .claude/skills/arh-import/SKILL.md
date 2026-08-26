---
name: arh-import
description: Bulk backfill — pulls existing artifacts (Jira/Linear stories, Confluence/Notion pages, local files, code) into harness state. Idempotent. Run once at adoption or to refresh.
argument-hint: "[--jira-jql Q | --linear-team T | --gitlab-project G/P | --confluence-space S | --notion-database ID | --from-files PATH] [--force] [--priority-map PATH]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep
---
# /arh-import

Backfill harness state from existing project artifacts.

Delegate to `import-agent` with `$ARGUMENTS`. The agent:

1. Detects the requested source type from flags.
2. Pulls items via the configured MCP server (atlassian, linear, gitlab, notion, confluence).
3. **Checks idempotency** (I4) before writing each item — see below.
4. **Resolves conflicts** (I2) when a local artefact already exists — see below.
5. Writes one entry per item to the right place:
   - tickets → `docs/stories/<EPIC-SEQ>.md` (with source backlink header per I3)
   - PRD pages → `docs/features/<id>/REQUIREMENTS.md` (with source backlink)
   - local files → wraps and links to source
6. Appends rows to `docs/requirements/RTM.md` (with Source column per I3).
7. Updates `docs/state/features.json` with `phase: imported`, `story: "imported:<source>"`, defaults per I1, and source backlink.

Print the resulting backlog table grouped by phase.

## Defaults for imported stories (I1)

External sources rarely carry every field the harness needs. The agent applies these defaults at import time. The user adjusts via `/arh-validate-story` or direct edit later.

| Field | Default when source has no value |
|---|---|
| `story_priority` | `"P2"` — mid-rank. Sources with a priority field override via the priority-map (I5). |
| `story_independent_test` | `false` — conservative. P2/P3 don't require it; P1 will fail rubric until fixed. |
| `needs_clarification_count` | `0` — placeholder. Validation will recount on `/arh-validate-story` if user inserts `[NEEDS CLARIFICATION]` markers. |
| `rtm_source_sha` | `git rev-parse HEAD` at import time |

The story file body uses the canonical `story-template` shape. Missing fields (acceptance criteria, NFRs) are populated with `[NEEDS CLARIFICATION: ...]` markers up to the hard cap of 3 — the user resolves them via `/arh-validate-story`.

## Source-priority mapping (I5)

The agent maps source priority/severity values to Harness's `P1 | P2 | P3`. Override via `--priority-map <path>` to a JSON file.

| Source field value | → Harness priority |
|---|---|
| Jira: Highest, Critical | P1 |
| Jira: High | P1 (when AC indicates ship-blocker) or P2 |
| Jira: Medium | P2 |
| Jira: Low, Lowest | P3 |
| Linear: Urgent | P1 |
| Linear: High | P1 |
| Linear: Medium | P2 |
| Linear: Low, No priority | P3 |
| GitHub Issues: `priority:critical` label | P1 |
| GitHub Issues: `priority:high` | P1 |
| GitHub Issues: `priority:medium` | P2 |
| GitHub Issues: `priority:low` or none | P3 |
| Azure DevOps: 1 | P1 |
| Azure DevOps: 2 | P2 |
| Azure DevOps: 3, 4 | P3 |
| GitLab: `priority::P1` label | P1 |
| GitLab: `priority::P2` label | P2 |
| GitLab: `priority::P3` label | P3 |
| GitLab: no `priority::` label | P2 (default) |
| Confluence / Notion / local files | `P2` (default) |

When the source carries a non-standard value, the agent maps to P2 and surfaces a warning. Custom override via `--priority-map`:

```json
{
  "jira": {"Showstopper": "P1", "Nice to have": "P3"},
  "linear": {"P0": "P1", "P4": "P3"}
}
```

## GitLab source scope

`--gitlab-project <group/project>` pulls issues via the GitLab MCP server (`mcp__gitlab__list_issues`). GitLab encodes everything Harness needs as labels, so the import reads them back:

- **Import only story issues.** Filter on the story marker label (`type::story` by default — read the project's actual label set from `docs/config/issue-tracking.yaml`). Issues labeled `TestCase` are test-case vehicles pushed by `push-test-cases`, never stories — skip them.
- **Epic comes from the `epic::<ID>` label.** GitLab has no epic object in this integration (issues-only model); the label is the RTM epic id for the imported row. An issue with no `epic::` label imports with an empty epic — surface a warning.
- **`workflow::*` stage labels are NOT imported as status.** Every imported story enters as `imported:gitlab` regardless of board stage — same rule as every other source; the user graduates it via `/arh-validate-story`.
- **Priority labels follow the I5 table** (`priority::P1|P2|P3` by default; team-renamed labels override via `--priority-map`'s `"gitlab"` key).
- **Id and backlink are qualified.** Story id records as `<group>/<project>#<iid>` (iids are per-project, a bare number is ambiguous); the Source line carries the issue's `web_url`.

## Source backlink (I3)

Every imported story file carries a `**Source:**` line in its traceability header:

```markdown
# Story: <EPIC-SEQ> — <title>

**Source:** https://example.atlassian.net/browse/ACME-123
**Source-imported-at:** 2026-05-11T14:32:00Z
**Status:** imported:jira
**Owner:** <as-imported-or-blank>
**Updated:** <iso8601>
```

`docs/requirements/RTM.md` gains a Source column for every imported row:

| ID | Title | Status | Source |
|----|-------|--------|--------|
| ACME-123 | Add CSV export | imported:jira | https://example.atlassian.net/browse/ACME-123 |

For `--from-files PATH`, the source path (relative to repo root) is preserved instead of a URL.

## Conflict policy (I2)

Before writing each `docs/stories/<EPIC-SEQ>.md` or `docs/features/<id>/REQUIREMENTS.md`, the agent checks for an existing local file.

| Local file state | Default action |
|---|---|
| Absent | Write the imported file. Proceed. |
| Exists, content identical | Skip silently (idempotent path). |
| Exists, content differs, no `--force` | **Stop.** Surface diff to user; prompt resolution. Do NOT overwrite. |
| Exists, content differs, `--force` | Overwrite. Annotate `**Imported-overwrote:**` in the file header. |

Diff surfacing format:

```
[CONFLICT] docs/stories/ACME-123.md
  Local:   <last-modified> <commit-sha>
  Remote:  <source-modified-at>
  Diff:    <abbreviated diff>
  Action:  re-run with --force to overwrite, OR resolve manually then re-run.
```

This mirrors `/arh-intake` Step 2's anti-pattern rule (existing story with manual edits → do not overwrite silently).

## Re-run idempotency (I4)

Re-running `/arh-import` on the same source MUST NOT create duplicates. Before importing each item, the agent reads `state/features.json[<id>]` and applies:

| State for id | Source (in flag) | Action |
|---|---|---|
| Absent | any | Import normally. |
| `story: "imported:<same-source>"` | same source | Skip silently — already imported from this source. With `--force`, re-import (overwrites local). |
| `story: "imported:<other-source>"` | different source | **Stop** with conflict message. Same id was imported from a different source previously. User decides. |
| `story: "draft"` or `"validated"` | any | Skip with warning — local story exists in active state. With `--force`, importing overwrites and resets to `imported:<source>` (likely undesirable; warn loudly). |

Output a re-run summary:

```
Imported:  <N> new
Skipped:   <K> already-imported from same source
Conflicts: <C> (see report)
Force:     <F> overwritten
```

## Validation skip

Imported stories bypass the `/arh-validate-story` rubric — they are marked `phase: imported` (not `story-validated`). Downstream commands (`/arh-research`, etc.) require `story: "validated"` per `phase-preconditions`. The user runs `/arh-validate-story <id>` per imported story to graduate.

## Anti-pattern

- Auto-running `/arh-validate-story` after import — imported content may carry assumptions the rubric would flag; let the user review and validate explicitly.
- Bulk overwrite without `--force` — even when source seems authoritative, local edits may be in-flight. Conflict policy stops the destructive path by default.
- Storing source priority verbatim (e.g. `"Highest"`) in `story_priority` — must map to `P1|P2|P3` per I5; non-standard values are warnings, not state.
