# Phase 3 — Verify + display

Goal: confirm the file is syntactically valid and let the user see what was written before they commit.

## Verification

| Provider          | Lint command (when available)         |
|-------------------|---------------------------------------|
| github-actions    | `actionlint .github/workflows/`       |
| gitlab-ci         | `gitlab-ci-lint .gitlab-ci.yml`       |
| circleci          | `circleci config validate`            |
| jenkins           | `jenkins-cli linter` (if configured)  |
| azure-pipelines   | `az pipelines validate`               |

If the linter is not installed, skip and warn — do not block on the missing tool.

## Display

Print the workflow file's structure to the user — not the full body, just the section headings:

```
Generated workflow: .github/workflows/ci.yml

  on:
    pull_request: [main]
    push: [main]
    workflow_dispatch: {}

  jobs:
    typecheck:   (uses: <stack-typecheck>)
    lint:        (uses: <stack-lint>)
    test_unit:   (uses: <stack-test_unit>)
    test_integration: (uses: <stack-test_integration>)
    build:       (uses: <stack-build>)
    e2e:         (uses: <stack-e2e>)
```

## Anti-pattern

- Don't dump 200 lines of YAML to the user. They have an IDE for that.
- Don't auto-commit. The user must inspect and commit themselves.
