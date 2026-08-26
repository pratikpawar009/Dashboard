# Phase 2 — Compose pipeline

Goal: invoke `cicd-agent` to merge stack-overlay recipes into a provider-specific pipeline file.

## Procedure

The agent:

1. Reads the project's declared tech stack from `docs/adr/0001-tech-stack.md` § Decision (Frameworks list) and the matching recipes.
2. Adds a top-line stamp `# harness-managed: do not edit by hand; re-run /arh-setup-ci`.
3. Composes a workflow with at minimum these jobs:
   - `typecheck`
   - `lint`
   - `test` (split into `unit` + `integration` when both are configured)
   - `build` (when applicable)
   - `e2e` (only when a `test-automation` stack is enabled and the project supplies the runner)
4. References secrets via the provider's secret store (`secrets.X` for GitHub Actions, `$CI_SECRET` for GitLab, etc.). Never literal values.
5. Writes the file at the provider's canonical path.

## Provider-specific output paths

| Provider          | Output                                  |
|-------------------|-----------------------------------------|
| github-actions    | `.github/workflows/ci.yml`              |
| gitlab-ci         | `.gitlab-ci.yml`                        |
| circleci          | `.circleci/config.yml`                  |
| jenkins           | `Jenkinsfile`                           |
| azure-pipelines   | `azure-pipelines.yml`                   |

## Triggers

- `pull_request` on the default branch.
- `push` on protected branches matching `harness.yaml` `vcs.protected_branches` (default: `main`, `master`).
- `workflow_dispatch` for manual reruns.

## Caching

- Per-stack package-manager cache (npm/pnpm/yarn/uv/pip/go-mod/cargo).
- Avoid global caches that cross stacks.
