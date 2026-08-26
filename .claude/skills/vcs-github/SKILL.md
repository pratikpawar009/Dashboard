---
name: vcs-github
description: GitHub VCS operations — PR creation, status checks, releases. Uses gh CLI plus the GitHub MCP server.
when_to_use: Opening PRs, fetching PR diffs / metadata, or triggering releases.
user-invocable: false
allowed-tools: Bash mcp__github__*
---
# VCS — GitHub

Required env: `GITHUB_TOKEN` (or run via `gh auth login` for the local user).

## Operations

<!-- Harness scaffold: integration=github (vcs) -->

- Open PR → `gh pr create --title "..." --body-file body.md`
- Fetch PR → `gh pr view <num> --json title,body,headRefName,files`
- Diff → `gh pr diff <num>`
- Checks → `gh pr checks <num>`
- Release → `gh release create v<X> --notes-file CHANGELOG.md`

## PR body convention
<!-- TODO: project-specific PR template path; mandatory sections -->

## Branch protection
<!-- TODO: which branches are protected; required checks; merge strategy (squash / merge / rebase) -->
