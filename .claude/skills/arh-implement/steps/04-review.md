# code-review-agent — Validate ∥ Review gate contract

The review side of the **Validate ∥ Review gate**. This is not a sequential step that runs after validation — `code-review-agent` runs *concurrently* with `validation-agent`, and the gate consumes both verdicts together.

## Invocation (gate mode)

The orchestrator dispatches `validation-agent` and `code-review-agent` in a **single message** (two Task calls), both **READ-ONLY** on the source tree and reviewing the **same snapshot** — anchored by a **source-scoped** `git status --porcelain` hash (excludes agent artefacts — see `steps/02-validate.md` § Snapshot).

Invoke `code-review-agent` with `$ARGUMENTS`. It reviews the branch diff and produces `docs/features/$ARGUMENTS/REVIEW.md` with severity-ranked findings citing rule files.

## Verdict contract

`code-review-agent` returns one of `PASS` / `PASS WITH WARNINGS` / `BLOCKED` (`R`). The gate consumes it as:

| Verdict | Gate consumption |
|---|---|
| **PASS** | GREEN on the review side. |
| **PASS WITH WARNINGS** | GREEN on the review side — a **proceed-with-carry-forward** state, NOT a fix-loop trigger. Warnings flow to the PR body. |
| **BLOCKED** | Fires a fix pass. |

The gate goes GREEN only when both `V ∈ {PASS, PARTIAL}` and `R ∈ {PASS, PASS WITH WARNINGS}`.

A fix pass fires ONLY on `V==FAIL` or `R==BLOCKED`. The fix directive folds validation bug-blocks (when `V==FAIL`) ⊕ review `CRITICAL` + `HIGH` findings ONLY (when `R==BLOCKED`); `MEDIUM/LOW` are PR-body warnings, never a fix trigger. The fix pass is governed by `root-cause-first`, `G4` (regression-test-per-failure), and `G14` (ADR-contradiction pause).

## Review sub-cap

Escalate after the 2nd BLOCKED round — `review_blocked_rounds >= 2` (2 BLOCKED rounds, NOT 3) → write `docs/features/$ARGUMENTS/REVIEW-ESCALATION.md` with the unresolved findings and stop. Options for the user: re-scope (drop the offending tasks), accept-with-ADR (justify the deviation, then re-review), or pause (keep the branch open for human review, no merge).

The combined hard cap across validation + review is 3 rounds → `ESCALATION.md`. **Never proceed to commit while CRITICAL findings remain.**

## State-write deferral

In **gate mode** the agent writes ONLY its report file (`REVIEW.md`) and RETURNS its verdict + `review_report` path + carry-forward entries. The orchestrator is the **single writer** that applies all `state.json` / `features.json` writes after the join.

Standalone invocation keeps self-writing — that path is covered by `review-assessment`.
