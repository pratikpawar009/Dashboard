---
name: arh-setup-ci
description: Generate CI pipeline config from stack-overlay recipes for the configured CI provider. Detects existing workflow conflicts.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash
---
# /arh-setup-ci — Main Orchestrator

Emit a CI pipeline file for the configured CI provider, composed from the per-stack recipes.

## Pipeline

```
0. Context           → 1. Conflict check  → 2. Compose pipeline
3. Verify + display  → 4. Final summary
```

## Phase 0 — Context

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

## Phase 1 — Conflict check

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-conflict-check.md`

## Phase 2 — Compose pipeline

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-compose.md`

Invoke `cicd-agent`. The agent loads stack-overlay recipes and writes the provider's pipeline file.

## Phase 3 — Verify + display

Read and follow: `${CLAUDE_SKILL_DIR}/steps/03-verify.md`

Read the generated file back. Display its key sections to the user. Run a syntax check (`actionlint` for GitHub Actions, `gitlab-ci-lint` for GitLab CI, etc.) when available.

## Final summary

```
SETUP-CI COMPLETE
──────────────────────────────────────
Provider:    github-actions | gitlab-ci | circleci | jenkins | azure-pipelines
Workflow:    .github/workflows/ci.yml         (or provider-specific path)
Triggers:    pull_request, push
Jobs:        <list, e.g. typecheck, lint, test, build>
Stacks:      <list>
Secrets:     <0 leaked>  (always 0; references only)

Next: commit and push to enable.
```
