---
name: arh-plan-implementation
description: REQUIREMENTS.md → PLAN.md with ADRs, file plan, module hierarchy, task breakdown, test strategy. Mirrors plan to issue tracker.
argument-hint: "[story-id ...]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob Task AskUserQuestion
---
**Batch:** Split `$ARGUMENTS` on whitespace, commas, or semicolons. `--` tokens are flags; all others are story IDs.
- **0 story IDs** → abort: print `Usage: /plan-implementation <story-id> [story-id ...]`.
- **1 story ID** → skip this, continue to the phase below (single-story mode, unchanged).



**2+ story IDs — batch:**

1. **Do NOT loop in this session.** For each story ID in order, fire one isolated `Task` invocation: `/plan-implementation <story-id>`. Each `Task` gets a fully isolated context window — no state, findings, or decisions from one story can affect another.
2. **Wait** for each `Task` to finish completely before starting the next.
3. **Display each story's complete output to the user immediately** after it finishes — do not collect silently and show only at the end.
4. After all complete, print: `BATCH COMPLETE — /plan-implementation (<N> stories)` with columns `Story | Plan-validation | Tasks | Output`.
5. If `Task` is unavailable: do not loop — ask the user to run each story individually.



# /arh-plan-implementation — Main Orchestrator

Convert REQUIREMENTS.md into PLAN.md with concrete tasks anchored to the project's stack rules.

Hybrid flow: the gate (Phase 0) and the tracker sync (Phase 2) run inline here in the main session; the plan authoring (Phase 1) is delegated to the `impl-planning-agent` subagent, which applies the `plan-authoring` skill (pinned 7-section PLAN.md order, DECISIONS.md decision log, `F-NN` file plan, `T-NN` task breakdown, plan-validation rubric with self-correct ≤2 rounds, test strategy). Lint rule **F-051** (warn) fires on any PLAN.md whose `## ` section set deviates from the pinned list in `plan-authoring`.

**Input:** `$ARGUMENTS` — one story id, or multiple space-separated ids for batch (see Batch mode above)

**Precondition:** `/arh-plan-requirements $ARGUMENTS` must have completed AND the Product Gate must show APPROVED in `REQUIREMENTS.md`.

## Pipeline

```
0. Gate                          (main, read-only)
   → INVOKE impl-planning-agent   (ADRs → file plan → tasks → 3b plan validation → test strategy → write PLAN.md)
2. Tracker subtask               (main, MCP: mandatory when issue_tracker enabled)
```

## Phase 0 — Gate

_Single-story mode — batch detection (above) has already run; if there were multiple story IDs, this point is never reached._

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

If any precondition fails (Product Gate not APPROVE, state missing), abort here with the helpful message and do NOT invoke the agent.

## Phase 1 — Plan authoring (invoke impl-planning-agent)

Invoke the `impl-planning-agent` subagent with `$ARGUMENTS`. It applies skill `plan-authoring`: decision-log entries (via `decide`, to `DECISIONS.md`), file + module plan with `F-NN` ids (every new module's entry-registration site listed as edited), `T-NN` task breakdown with carry-forward link-through to the research risk register, **self-validation via the `plan-validation` rubric** (6 dimensions: wiring / docs / runner-setup / cross-section / config-drift / decision-promotion; ≤2 self-correct rounds, then escalation), the test strategy, and writes `docs/features/$ARGUMENTS/PLAN.md` plus the `plan_validation` state fields.

Consume the agent's hand-off (task count, plan-validation result, escalation if any). On escalation, surface it and **stop — skip Phase 2**.

## Phase 2 — Tracker subtask

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-tracker.md`

## Final summary

```
PLAN-IMPLEMENTATION COMPLETE
──────────────────────────────────────
Story:           $ARGUMENTS
PLAN.md:         docs/features/$ARGUMENTS/PLAN.md
Architecture:    <N> ADRs
Files:           <created> new, <modified> modified
Modules:         <count>
Tasks:           <count>  (S=<n>, M=<m>, L=<l>)
Test strategy:   <unit>+<integration>+<e2e>+<perf>
Tracker subtask: {KEY-XX}      | skipped (<reason>)
Top risks (carried from research):
  1. <severity>  <one-line>

Next: /arh-implement $ARGUMENTS
```
