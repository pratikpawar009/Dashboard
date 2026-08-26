---
name: arh-plan-requirements
description: Story + research → REQUIREMENTS.md + structured test cases. Detects design mode (figma vs ascii); Product Gate before plan-implementation.
argument-hint: "[story-id ...]"
disable-model-invocation: true
allowed-tools: Read Write Edit AskUserQuestion Task
---
**Batch:** Split `$ARGUMENTS` on whitespace, commas, or semicolons. `--` tokens are flags; all others are story IDs.
- **0 story IDs** → abort: print `Usage: /plan-requirements <story-id> [story-id ...]`.
- **1 story ID** → skip this, continue to the phase below (single-story mode, unchanged).



**2+ story IDs — batch:**

1. **Do NOT loop in this session.** For each story ID in order, fire one isolated `Task` invocation: `/plan-requirements <story-id>`. Each `Task` gets a fully isolated context window — no state, findings, or decisions from one story can affect another.
2. **Wait** for each `Task` to finish completely before starting the next.
3. **Display each story's complete output to the user immediately** after it finishes — do not collect silently and show only at the end.
4. After all complete, print: `BATCH COMPLETE — /plan-requirements (<N> stories)` with columns `Story | Gate | Test cases | Output`.
5. If `Task` is unavailable: do not loop — ask the user to run each story individually.



# /arh-plan-requirements — Main Orchestrator

Expand a certified story into REQUIREMENTS.md (PRD), generate structured test cases, conditionally produce hi-fi UX, and route through the Product Gate before plan-implementation.

**Input:** `$ARGUMENTS` — one story id, or multiple space-separated ids for batch (see Batch mode above)

## Pipeline

```
0. Context + design-mode detection (design_mode = none → skip § Visual spec + § Screen inventory)
1. product-spec-agent → REQUIREMENTS.md (PRD) + create per-feature state.json
2. Parallel fan-out (all read the finished PRD; disjoint outputs):
   ├── test-case-agent            →  docs/test-cases/<id>.json  (+ coverage audit)
   ├── ux-agent (design != none)  →  DESIGN.md + design = complete
   └── issue-tracking-agent       →  tracker subtask + parent transition (returns key)
3. Consolidate state — write tracker_prd, mirror B-tier fields to the index
4. Product Gate (coverage audit + open questions + approvals)
   └── 4b. On APPROVE only → push test cases (one linked Test issue per TC, conditional)
```

All visual content lives in `docs/features/<id>/DESIGN.md` (produced by `ux-agent`). The PRD's `## Visual spec` section is always a one-line pointer to DESIGN.md — never inline screens / tokens / wireframes.

## Phase 0 — Context + design-mode detection

_Single-story mode — batch detection (above) has already run; if there were multiple story IDs, this point is never reached._

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-design-mode.md`

## Phase 1 — Draft REQUIREMENTS.md

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-draft-prd.md`

Invoke `product-spec-agent` with `$ARGUMENTS`. Outputs `docs/features/$ARGUMENTS/REQUIREMENTS.md`
and creates the per-feature `state.json` (two-tier migration). It does NOT generate test cases or
design — those run in Phase 2.

## Phase 2 — Parallel: test cases, design, tracker

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-parallel.md`

Dispatch concurrently in a single turn — all read the finished PRD, write disjoint outputs:
`test-case-agent` (→ test-cases JSON), `ux-agent` (when `design_mode != none` → DESIGN.md), and
`issue-tracking-agent` (when a tracker is configured → subtask + parent transition). Barrier before
Phase 3. Only `ux-agent` writes `state.json` in this phase; `tracker_prd` is written in Phase 3.

## Phase 3 — Consolidate state

Read and follow: `${CLAUDE_SKILL_DIR}/steps/03-consolidate.md`

After the Phase 2 barrier, write `tracker_prd` from the returned subtask key, patch the story
traceability header, reflect test-case + design status on the tracker subtask (best-effort), and
confirm the test-case coverage audit before the gate.

## Phase 4 — Product Gate

Read and follow: `${CLAUDE_SKILL_DIR}/steps/04-product-gate.md`

Surface the gate checklist to the user. Plan-implementation is blocked until the gate passes.

## Phase 4b — Push test cases

Run this phase only when **both** conditions hold. Check them in this order and skip on the first
failure — a tracker read is pointless once the gate has already ruled the push out:

1. `gate == "APPROVE"` in `docs/features/$ARGUMENTS/state.json` — Phase 4 wrote it there. On
   `CHANGES` or `PENDING`, skip entirely and go to the final summary with
   `Test cases pushed: n/a (gate not approved)`.
2. `provider != none` in `docs/config/issue-tracking.yaml`. On `none`, skip silently and summarise
   as `Test cases pushed: skipped (no tracker configured)`.

Gate on the state field, not on the verdict as you remember it from the conversation — `gate` is
B-tier and Phase 4 § On entry guarantees it always holds an explicit value.

Read and follow: `${CLAUDE_SKILL_DIR}/steps/04b-push-test-cases.md`

`issue-tracking-agent` creates one linked Test issue per test case under the parent story,
capped per run. This is the phase's only call site — placed after the gate so a `CHANGES` /
`PENDING` verdict never leaves orphan issues in the tracker. Best-effort — a tracker failure
never downgrades an approved gate.

## Final summary

```
PLAN-REQUIREMENTS COMPLETE
──────────────────────────────────────
Story:                 $ARGUMENTS
Design mode:           figma | ascii
REQUIREMENTS.md:       docs/features/$ARGUMENTS/REQUIREMENTS.md
UI designs:            <figma-url>            | inline ASCII
Test cases:            <N> total, <M> automatable
Tracker subtask:       {KEY-XX}                | skipped (<reason>)
Test cases pushed:     <N>/<total>             | skipped (<reason>) | n/a (gate not approved)
Open questions:        <count>

Gate status: PENDING APPROVAL  (run /arh-plan-implementation $ARGUMENTS once approved)
```
