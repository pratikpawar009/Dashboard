# Phase 5 — Brownfield branch (suggest /arh-import)

Goal: when Phase 0 classified the repo brownfield, surface concrete `/arh-import` commands the user can run to backfill harness state.

## When to run

Only when Phase 0 reported `Mode: brownfield`. For greenfield, this phase is a no-op and the final summary points to `/arh-scaffold` or `/arh-intake` directly.

## Detection-driven suggestions

Build the suggestion list from what was detected:

| Signal                                                               | Suggestion                                                          |
|----------------------------------------------------------------------|---------------------------------------------------------------------|
| Manifest exists with non-trivial deps + active commits               | `/arh-import --from-files docs/specs/` (import existing PRDs)           |
| Issue tracker config has a project key                               | `/arh-import --jira-jql "project=<KEY> AND status!=Done"` (or linear)   |
| Issue tracker config is GitLab (project path set)                    | `/arh-import --gitlab-project <group/project>`                          |
| Doc tracker config points to a Confluence space                      | `/arh-import --confluence-space <space>`                                |
| Doc tracker config points to a Notion database                       | `/arh-import --notion-database <db-id>`                                 |
| `docs/legacy-prds/` or similar local dir                             | `/arh-import --from-files docs/legacy-prds/`                            |

## Output

```
Brownfield detected. Suggested next:

  /arh-import --jira-jql "project=ACME AND status!=Done"
  /arh-import --confluence-space ENG --filter "label=prd"

Run these to backfill harness state. Skip if the project is small enough to start from scratch.
```

## Behaviour

- Do not auto-run `/arh-import`. Always ask the user.
- If the user declines, the harness still works — they can use `/arh-intake --from-jira <key>` per-feature later.
