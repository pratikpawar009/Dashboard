# Step 0 — Auto-configure integrations

Goal: ensure `docs/config/issue-tracking.yaml` and `docs/config/doc-tracker.yaml` are populated so downstream steps can sync. On first run, discover the live environment via the configured MCP servers; on subsequent runs, just verify and proceed.

## 0a. Issue tracker discovery

If `docs/config/issue-tracking.yaml` exists, read it.

**Completeness check (mandatory).** A file may exist as a stub written by `/arh-init`. Validate:

- `provider` is set and != `none` → required fields below must be populated.
- For `provider: jira` — `site`, `project_key`, `issue_types.epic`, `issue_types.story` must be set, NOT one of: empty string, `null`, `TODO`, `FILL`, `<…>` placeholder.
- For `provider: linear` — `team_id`, `workflow_states` must be set with the same rules.
- For `provider: github` — `org`, `repo` must be set.
- For `provider: gitlab` — `project` and `stage_labels` (all four stages) must be set.
- For `provider: azure-devops` — `organization`, `project` must be set.

If any required field is missing or a placeholder, treat the file as **not configured** — fall through to the discovery flow below, prompt the user, and overwrite the placeholders.

If the file is fully populated, log the summary and proceed to Step 1.

If it does not exist OR is incomplete:

- **Provider = none**: write a stub with `provider: none` and continue. Steps 4–5 will skip.
- **Provider = jira**: 
  - Call `mcp__atlassian__getAccessibleAtlassianResources` → `cloudId`, `site`.
  - Call `mcp__atlassian__getVisibleJiraProjects` → list of projects.
  - Ask the user: *"Which Jira project should stories be created in?"* — show project keys and names.
  - After selection, call `mcp__atlassian__getJiraProjectIssueTypesMetadata`:
    - Epic issue type id
    - Story issue type id
    - Subtask issue type id (match `hierarchyLevel: -1` or name containing `subtask` / `sub-task`, case-insensitive). If not present, set `null` and warn — phase subtasks will be skipped.
  - Extract priority ids from the Story type's `priority.allowedValues`.
  - Determine the Epic→Story link field (`parent` if present on Story type).
- **Provider = linear**:
  - Call `mcp__linear__getTeams` → list of teams.
  - Ask the user which team. Resolve team id.
  - Call `mcp__linear__getWorkflowStates` for that team to map intake states.
- **Provider = github**:
  - Call `mcp__github__listRepos` for the org configured in `harness.yaml`.
  - Ask the user which repo's Issues will hold stories.
- **Provider = gitlab**:
  - Call `mcp__gitlab__list_issues` against the candidate project to confirm the token reaches it. A `401`/`403` means `GITLAB_TOKEN` is missing or lacks `api` scope — report that distinction, since the remedy differs from an unreachable server.
  - Ask the user which `<group>/<project>` holds Stories.
  - Call `mcp__gitlab__list_labels` → create any missing stage label with `mcp__gitlab__create_label`.
  - No epic discovery — this integration creates issues only. See `issue-tracking-gitlab` § Epics.
- **Provider = azure-devops**: equivalent calls via `mcp__ado__*`.

## 0b. Doc tracker discovery

If `docs/config/doc-tracker.yaml` exists, read it.

**Completeness check (mandatory).** Validate:

- `provider` set and != empty.
- For `provider: confluence` — `space_key` and `parent_page_title` must be set, NOT placeholders (`TODO`, `FILL`, empty, `null`).
- For `provider: notion` — `database_id` must be set, NOT a placeholder.
- For `provider: local` — `doc_root` defaults to `docs/`; no other required fields.

If any required field is missing or a placeholder, treat as **not configured** — fall through to the discovery flow, prompt the user, and overwrite.

If fully populated, proceed.

Otherwise (missing or incomplete):

- **Provider = local**: write a stub recording the local doc root (default `docs/`).
- **Provider = confluence**: call `mcp__atlassian__getConfluenceSpaces`, ask the user which space holds the RTM, write `spaceKey` and `parentPageTitle`.
- **Provider = notion**: call `mcp__notion__listDatabases`, ask which database holds PRDs.

## 0c. Write configs

Create `docs/config/` if missing.

**Write semantics (mandatory):**

- If the YAML file does NOT exist → create it with all discovered values.
- If the YAML file DOES exist but failed the 0a/0b completeness check → read existing YAML, overwrite ONLY placeholder fields (`TODO`, `FILL`, empty, `null`, `<…>`) with discovered/selected values; preserve any non-placeholder fields the user may have hand-edited.
- If the YAML file passed the completeness check → do not touch.

Use round-trip YAML (preserve comments + ordering) when overwriting.

Verification: after writing, re-run the 0a/0b completeness check against the file you just wrote. It MUST pass — otherwise abort intake with a clear error.

Write `docs/config/issue-tracking.yaml` using the shape for the configured provider — the
shapes differ, and each MUST contain every field the 0a completeness check requires for that
provider. Write only the matching block.

**Priority model:** keys are `P1 | P2 | P3` (the story scale), never MoSCoW. Map each to the
tracker's priority id/level. If the project has **no priority field** (team-managed Jira often
doesn't), set them `null` and add `P1`/`P2`/`P3` as **labels** instead.

```yaml
# provider: jira
provider: jira
site: <discovered>
cloud_id: <discovered>
project_key: <user-selected>
project_id: "<discovered>"
issue_types:
  epic: "<id>"
  story: "<id>"
  subtask: "<id | null>"     # null → phase subtasks skipped
priorities:                  # P-scale → priority id, or all null + use labels
  P1: <id | null>
  P2: <id | null>
  P3: <id | null>
epic_story_link_field: parent
labels:
  - <project-slug>
```

```yaml
# provider: linear
provider: linear
team_id: <discovered>
project_id: <discovered | null>
workflow_states:             # Harness stage → Linear state id
  validated: <id>
  in_progress: <id>
  in_review: <id>
  done: <id>
priorities:                  # → Linear native priority 0-4
  P1: <n>
  P2: <n>
  P3: <n>
labels:
  - <project-slug>
```

```yaml
# provider: github  (no type/priority fields — encode via labels)
provider: github
org: <discovered>
repo: <user-selected>
project:                     # optional GitHub Project (v2) board
  number: <id | null>
  status_field: <name | null>
labels:
  - <project-slug>
  - type:story
  - P1               # priority carried as a label
```

```yaml
# provider: gitlab  (no type/priority fields — encode via labels)
provider: gitlab
api_url: https://gitlab.com/api/v4   # self-managed: the instance API root
project: <group>/<project>   # user-selected — holds the Stories
                             # no group/epic keys: this integration creates issues only
stage_labels:                # Harness stage → GitLab label (issues are only opened/closed)
  validated: "workflow::validated"
  in-progress: "workflow::in progress"
  in-review: "workflow::in review"
  done: "workflow::done"
labels:
  - <project-slug>
  - type::story
  - priority::P1             # priority carried as a scoped label — import's I5 table matches `priority::P1|P2|P3`
  - epic::<EPIC-ID>          # RTM epic id as a filter handle, NOT a GitLab epic
```

```yaml
# provider: azure-devops
provider: azure-devops
organization: <discovered>
project: <user-selected>
process: <Agile | Scrum | CMMI | Basic>
work_item_types:             # depends on process
  epic: <type>
  story: <type>              # "User Story" (Agile) | "Product Backlog Item" (Scrum)
  subtask: <type>            # e.g. "Task"
priorities:                  # → ADO priority field 1-4
  P1: 1
  P2: 2
  P3: 3
area_path: <default | null>
iteration_path: <default | null>
labels:
  - <project-slug>
```

```yaml
# provider: none
provider: none
```

```yaml
# docs/config/doc-tracker.yaml
provider: confluence | notion | local
space_key: <discovered>          # confluence
database_id: <discovered>        # notion
parent_page_title: <project> — Requirements Traceability
```

## 0d. Log

```
CONFIG AUTO-CREATED
───────────────────
Files:        docs/config/issue-tracking.yaml, docs/config/doc-tracker.yaml
Issue:        <provider> @ <site>          | not configured
Doc:          <provider> @ <space|db|local>
Epic type:    <id>
Story type:   <id>
Subtask:      <id | "not available">
```

Never store credentials in these files. Tokens stay in env vars referenced by `.mcp.json`.
