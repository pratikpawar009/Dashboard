# Phase 2 — Tracker + design configs (MCP discovery)

Goal: write `docs/config/issue-tracking.yaml`, `docs/config/doc-tracker.yaml`, and (when design integration is non-trivial) update `docs/design/schema.json` with **real values discovered via MCP** when the corresponding provider in the project config is non-default.

This phase is where MCP discovery happens. `/arh-intake` Step 0 still has the fallback for placeholder stubs (defense-in-depth), but `/arh-init` is the canonical write site.

## Discovery matrix

For each integration declared in the project config, run the matching procedure and write the result. Fall back to a placeholder-TODO config ONLY if the corresponding MCP server is unavailable in the session.

| Provider | MCP server | Discovery procedure |
|---|---|---|
| `issue_tracker: jira` | `mcp__atlassian__*` | (1) `getAccessibleAtlassianResources` → cloudId + site. (2) `getVisibleJiraProjects` → ask user to pick project. (3) `getJiraProjectIssueTypesMetadata` → resolve Epic / Story / Subtask issue-type ids and priority ids. (4) Determine `epic_story_link_field` (`parent` if present). |
| `issue_tracker: linear` | `mcp__linear__*` | (1) `getTeams` → ask user to pick team. (2) `getWorkflowStates` for that team to map intake/done states. |
| `issue_tracker: github` | `mcp__github__*` | `listRepos` for the org configured → ask user to pick the Issues-bearing repo. |
| `issue_tracker: gitlab` | `mcp__gitlab__*` | (1) `list_issues` against the candidate project to confirm the token reaches it → ask the user which project holds Stories. (2) `list_labels` → create any missing `workflow::` stage label with `create_label`. No epic discovery — this integration creates issues only. |
| `issue_tracker: azure-devops` | `mcp__ado__*` | Equivalent calls — organization + project + work-item type ids. |
| `issue_tracker: none` | — | Write `provider: none`. No discovery. |
| `doc_tracker: confluence` | `mcp__atlassian__*` | `getConfluenceSpaces` → ask user to pick space. Record `space_key` + `parent_page_title`. |
| `doc_tracker: notion` | `mcp__notion__*` | `listDatabases` → ask user to pick the PRDs database. Record `database_id`. |
| `doc_tracker: local` | — | Write `provider: local` + `doc_root: docs/`. No discovery. |
| `design: figma` | `mcp__figma__*` | If a Figma file URL has been shared in `/arh-init` Phase 1 user answers, call `get_design_context` with that nodeId for sanity check. Update `docs/design/schema.json` `designSystem.fileKey` + `designSystem.url`. Otherwise leave both as `TODO` and prompt at next `/arh-plan-requirements`. |
| `design: stitch` | `mcp__stitch__*` | List projects; ask user to pick. Update `docs/design/schema.json` `designSystem.fileKey` (= project_id) + `designSystem.url`. |
| `design: claude-design` | — | No MCP. Update `docs/design/schema.json` `designSystem.url` from the user-supplied `claude.ai/design/...` link (or leave `TODO` until first `/arh-plan-requirements`). |
| `design: html-mockup` | — | No MCP. Leave `docs/design/schema.json` `designSystem.{fileKey,url}` as `TODO`; the `ux-agent` for html-mockup generates standalone HTML files per feature at `/arh-plan-requirements` time without needing a workspace pointer. |
| `design: none` | — | Skip — `docs/design/` may still exist; do not touch. |

## issue-tracking.yaml shape

```yaml
provider: jira | linear | github | gitlab | azure-devops | none
site: <discovered from MCP — only when applicable>
project_key: <discovered from MCP — user-selected>
issue_types:
  epic:    <id-or-name from MCP>
  story:   <id-or-name from MCP>
  subtask: <id-or-name from MCP | null when project has no subtask type>
priorities:
  Must:   <id from MCP>
  Should: <id from MCP>
  Could:  <id from MCP>
  Wont:   <id from MCP>
epic_story_link_field: parent
labels:
  - <project-slug>
```

GitLab has no issue-type and no priority field, so it uses a different shape — labels carry both,
and the stage map is explicit because GitLab issues are only `opened` / `closed`:

```yaml
provider: gitlab
api_url: https://gitlab.com/api/v4  # self-managed: the instance API root
project: <group>/<project>        # discovered — holds the Stories
stage_labels:
  validated:   "workflow::validated"
  in-progress: "workflow::in progress"
  in-review:   "workflow::in review"
  done:        "workflow::done"
labels:
  - <project-slug>
```

## doc-tracker.yaml shape

```yaml
provider: confluence | notion | local
# confluence-only
space_key: <discovered>
# notion-only
database_id: <discovered>
# applies to all non-local
parent_page_title: <project name> — Requirements Traceability
```

## docs/design/schema.json (canonical design store)

Design provider state lives in `docs/design/schema.json` (NOT a yaml under `docs/config/`). The shape is:

```json
{
  "designSystem": {
    "fileKey": "TODO",
    "url": "TODO",
    "pages": {
      "tokens": "",
      "atoms": "",
      "molecules": "",
      "organisms": "",
      "icons": "",
      "features": {}
    }
  },
  "tokens": {
    "color": [],
    "spacing": [],
    "typography": []
  }
}
```

`/arh-init` Phase 2 updates `designSystem.fileKey` and `designSystem.url` when MCP discovery yields a value. `/arh-plan-requirements` (via `claude-design` skill or `ux-agent` for figma) populates the `tokens.*` arrays from exported HTML or Figma variable defs.

When design = `none`, leave the file untouched (it may already exist from a prior provider).

## Procedure

1. Read the project config to determine the declared provider for each integration. (The project's harness config carries `integrations.issue_tracker`, `integrations.doc_tracker`, `integrations.design`. The composer placed those literals there at generate time.)
2. For each integration whose provider is **not** in {`none`, `local`, `claude-design`, `html-mockup`}:
   - Verify the matching MCP server is reachable. If not, print `mcp <name> unreachable — writing placeholder stub. Run /arh-intake after configuring the MCP server.` and emit a TODO-filled stub. Continue.
   - `issue_tracker: gitlab` needs `GITLAB_TOKEN` (an `api`-scoped PAT) in the environment, plus `GITLAB_API_URL` on self-managed instances. A `401`/`403` on the smoke call means the token is missing or under-scoped — print that distinction rather than a generic unreachable message, because the remedy differs.
   - Run the discovery procedure from the matrix above.
   - Write the resulting YAML to `docs/config/<file>.yaml`.
3. For providers `none` / `local` / `claude-design` / `html-mockup`, write the corresponding minimal YAML directly (no discovery).

## Fallback contract

`/arh-intake` Step 0 treats any `TODO` / `FILL` / empty / `null` / `<…>` value as **not configured** and re-runs the MCP-driven discovery flow at intake time. This bootstrap phase is the canonical write site; `/arh-intake` is the safety net for projects that bootstrap with an unreachable MCP server.

## Anti-pattern

Never store credentials in these files. The matching MCP server in `.mcp.json` references env vars instead.
