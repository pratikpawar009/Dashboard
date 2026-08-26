---
name: arh-implement
description: PLAN.md → branch → code → mandatory E2E validation → review → commit → PR → tracker comment. Strict sequence; never skip validation.
argument-hint: "[story-id ...]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob Task
---
**Batch:** Split `$ARGUMENTS` on whitespace, commas, or semicolons. `--` tokens are flags; all others are story IDs.
- **0 story IDs** → abort: print `Usage: /implement <story-id> [story-id ...]`.
- **1 story ID** → skip this, continue to the phase below (single-story mode, unchanged).



**2+ story IDs — batch:**

1. **Do NOT loop in this session.** For each story ID in order, fire one isolated `Task` invocation: `/implement <story-id>`. Each `Task` gets a fully isolated context window — no state, findings, or decisions from one story can affect another.
2. **Wait** for each `Task` to finish completely before starting the next.
3. **Display each story's complete output to the user immediately** after it finishes — do not collect silently and show only at the end.
4. After all complete, print: `BATCH COMPLETE — /implement (<N> stories)` with columns `Story | PR | Validation | Review`.
5. If `Task` is unavailable: do not loop — ask the user to run each story individually.



# /arh-implement — Main Orchestrator

End-to-end implementation from a PLAN.md. Strict sequence. **Never skip validation.** Never commit code that has not passed E2E validation.

**Input:** `$ARGUMENTS` — one story id, or multiple space-separated ids for batch (see Batch mode above)

## Sequence

```
0. Context load  →  1. Implement  →  2. Validate ∥ Review gate (bounded fix loop)  →  5. Commit + PR  →  6. Tracker
```

Step 1 runs the task DAG in parallel (file-disjoint batches of single-task workers), then a single end-of-session evidence pass (six-dimension packet via the `evidence-pass` skill, invoked as one `--evidence` agent call) with its own bounded fix loop. Evidence returns READY (all six PASS or accepted-N/A) or BLOCKED (round-3 escalation); only READY proceeds to Step 2. See `evidence-pass` skill.

If at any step you are blocked — environment failure, agent escalation, 3 failed fix rounds, or BLOCKED review verdict — stop and report to the user. **Do not commit or push code that has not passed E2E validation.**

## Step 0 — Context load

_Single-story mode — batch detection (above) has already run; if there were multiple story IDs, this point is never reached._

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

## Step 1 — Implement tasks

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-implement.md`

Step 1 is a **DAG scheduler**: read `tasks.json`, and each round dispatch a file-disjoint batch of ready (`pending`, predecessors-done) tasks as concurrent single-task `implementation-agent` workers (one `Task` each, single message, cap 4). The orchestrator is the single writer — it records each result into `tasks.json`, appends returned questions/flags to `QUESTIONS.md`/`FLAGS.md`, and folds worker diffs into the working tree in `T-NN` order. **No commit here — Step 5 owns the single gated commit.** When the DAG is drained, run the clarification check, then invoke `implementation-agent` **once in evidence mode** (`--evidence`) for the six-dimension packet. It returns READY (all dimensions PASS or accepted-N/A) or BLOCKED (round-3 escalation, `EVIDENCE-ESCALATION.md` written). On BLOCKED, stop and surface to the user — do NOT attempt Step 2.

## Step 2 — Validate ∥ Review gate (concurrent, mandatory)

Read and follow, in this order: `${CLAUDE_SKILL_DIR}/steps/02-validate.md` (the gate), `${CLAUDE_SKILL_DIR}/steps/03-fix-loop.md` (shared fix pass), `${CLAUDE_SKILL_DIR}/steps/04-review.md` (review-agent verdict contract).

The **Validate ∥ Review gate** collapses the old serial validate → fix → review steps into one round-based gate. Each round, anchor the tree with a **source-scoped** `git status --porcelain` hash (excludes the agents' own report / test-case-JSON writes — see `steps/02-validate.md` § Snapshot for the exact exclusions), then dispatch `validation-agent` and `code-review-agent` in a **single message** (two `Task` calls) — both READ-ONLY on the source tree against that **same snapshot**. Even if the implementation-agent reports all local checks pass, you MUST run this; do not skip due to time pressure or clean unit tests.

**Single writer.** In GATE MODE both agents write only their report artefacts (never `state.json` / `features.json`) and RETURN their verdict + carry-forward entries; the orchestrator is the **single writer** that applies all `state.json` / `features.json` writes AFTER the join. (Standalone invocation of either agent keeps self-writing.)

**GREEN condition.** `V ∈ {PASS, PARTIAL}` and `R ∈ {PASS, PASS WITH WARNINGS}`. `PARTIAL` and `PASS WITH WARNINGS` are proceed-with-carry-forward states, NOT fix-loop triggers.

**Fix pass** (`steps/03-fix-loop.md`) fires ONLY on `V==FAIL` or `R==BLOCKED`. The fix directive folds validation bug-blocks (when `V==FAIL`) ⊕ review `CRITICAL` + `HIGH` findings ONLY (when `R==BLOCKED`); `MEDIUM/LOW` are PR-body warnings, never a fix trigger. Hand the folded directive to `implementation-agent` under `root-cause-first` (with `G4` regression-test-per-failure and the `G14` ADR-contradiction pause), then re-run the gate against a fresh snapshot.

**Caps.** Review sub-cap: escalate after the 2nd BLOCKED round (`review_blocked_rounds >= 2` → `REVIEW-ESCALATION.md`). Combined hard cap = 3 rounds → `ESCALATION.md`. Do not attempt a 4th round.

## Step 5 — Commit + PR

Read and follow: `${CLAUDE_SKILL_DIR}/steps/05-commit-pr.md`

Stage only files within PLAN.md scope. Never `git add -A` or `git add .`. Never push to `main`. Never force-push. Open PR with the structured template.

## Step 6 — Tracker completion

Read and follow: `${CLAUDE_SKILL_DIR}/steps/06-tracker-completion.md`

Invoke `issue-tracking-agent` to post PR link, branch, validation outcome, and review verdict on the parent Story.

## Final summary

```
IMPLEMENTATION COMPLETE
──────────────────────────────────────
Story:           $ARGUMENTS
Branch:          feature/$ARGUMENTS
PR:              <url>
Validation:      <P>/<P> passed in <N> rounds
Code review:     PASS | PASS WITH WARNINGS
Tracker:         {KEY-XX} updated
Files changed:   <count>
Lines:           +<add> / -<del>

Next: human merge after CI passes
```

## Sequence enforcement (read once)

| Rule | Reason |
|---|---|
| Implementation → Validate ∥ Review gate → Commit. Never reorder. | validation and review gate the same tree snapshot each round; commit requires both green on one snapshot — a fix re-runs both. |
| Never accept BLOCKED hand-off from Step 1. | The agent's internal evidence pass returns BLOCKED only after 3 rounds of fix attempts. The orchestrator must surface `EVIDENCE-ESCALATION.md` to the user; bypassing into Step 2 with red evidence is what the gates exist to prevent. |
| Never skip Step 2. | Unit tests do not catch integration regressions; mocked tests do not match production. |
| Stop after 3 failed validation rounds. | A 4th round usually means the design is wrong. Escalate. |
| Stop after 2 BLOCKED review rounds with unresolved CRITICAL findings. | Re-implementation is not a workaround for an architectural flaw. |
| Never commit unsigned, unscoped, or pre-validation code. | Everything visible to humans must have passed every gate. |
| Never commit code changed after its last passing gate round. | The commit must be the exact snapshot both gates passed; any edit after the passing round invalidates both verdicts — re-run the gate. |
