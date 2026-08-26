---
name: arh-review
description: Architectural and standards code review — accepts story-id, PR url, PR number, branch, or current diff. Six-dimension framework with severity-ranked findings.
argument-hint: "[story-id | PR-url | PR-number | branch-name]"
disable-model-invocation: true
allowed-tools: Read Grep Glob Bash
---
# /arh-review — Main Orchestrator

Review the diff for architecture, design pattern adherence, and standards conformance. Output `docs/features/<id>/REVIEW.md` with severity-ranked findings citing rule files.

Hybrid flow: input-mode detection (Phase 0) runs inline here in the main session; the assessment (Phase 1) is delegated to the `code-review-agent` subagent, which applies the `review-assessment` skill (context load → categorise → six-dimension assess → report + state write).

**Input:** `$ARGUMENTS` (any of: story id, PR url, PR number, branch name, or empty for the current branch's diff vs main).

## Pipeline

```
0. Detect input mode        (main)
   → INVOKE code-review-agent (context load → categorise → 6-dim assess → report + state)
2. Exit code                (main)
```

## Phase 0 — Detect input mode

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-input-mode.md`

Resolve the target ref and (when known) the story id. Hand both to the agent.

## Phase 1 — Assessment (invoke code-review-agent)

Invoke the `code-review-agent` subagent with the resolved target ref + story id. It applies skill `review-assessment`: loads context (CLAUDE.md, matching rules, PLAN/REQUIREMENTS/arh-research, PR body), categorises the changed files, assesses the six dimensions + `scope-creep` + `adr-violation` + `contract-drift`, writes `docs/features/<id>/REVIEW.md` (or `docs/reviews/REVIEW-<DATE>.md` when no story id), and performs the state write (standalone invocation → the agent self-writes; there is no gate directive here).

Consume the agent's hand-off (verdict + finding counts) for the exit code and summary below.

## Phase 2 — Exit code

| Verdict                | Exit |
|------------------------|------|
| PASS                   | 0    |
| PASS WITH WARNINGS     | 0    |
| BLOCKED                | 1    |

These literals match the state schema `review` field, the `/arh-implement` Validate ∥ Review gate verdict handling, and the code-review-agent hand-off. The exit code lets CI gate merges automatically.

## Final summary

```
REVIEW COMPLETE
──────────────────────────────────────
Mode:           story | pr-url | pr-number | branch | current
Target:         <ref>
Files reviewed: <N>
Findings:       C=<crit>  H=<high>  M=<med>  L=<low>
Categories:     scope-creep=<n>  adr-violation=<n>  contract-drift=<n>
Verdict:        PASS | PASS WITH WARNINGS | BLOCKED
Report:         docs/features/<id>/REVIEW.md  (or docs/reviews/REVIEW-<DATE>.md)

Next:
  PASS / PASS WITH WARNINGS → continue to commit / merge
  BLOCKED                   → address findings; re-run /arh-review
```

## Scope note

The agent focuses on architecture, design patterns, and standards adherence — not style nitpicks (linter handles those) and not business logic (humans). Treat agent review as complementary to human review, not a replacement.
