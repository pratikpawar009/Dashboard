---
name: arh-research
description: Codebase feasibility for a certified story — exploration log, pattern map, risk register, scoring, and (when tracker enabled) mandatory tracker subtask sync.
argument-hint: "[story-id ...]"
disable-model-invocation: true
allowed-tools: Read Grep Glob Bash Write Edit Task AskUserQuestion
---
**Batch:** Split `$ARGUMENTS` on whitespace, commas, or semicolons. `--` tokens are flags; all others are story IDs.
- **0 story IDs** → abort: print `Usage: /research <story-id> [story-id ...]`.
- **1 story ID** → skip this, continue to the phase below (single-story mode, unchanged).



**2+ story IDs — batch:**

1. **Do NOT loop in this session.** For each story ID in order, fire one isolated `Task` invocation: `/research <story-id>`. Each `Task` gets a fully isolated context window — no state, findings, or decisions from one story can affect another.
2. **Wait** for each `Task` to finish completely before starting the next.
3. **Display each story's complete output to the user immediately** after it finishes — do not collect silently and show only at the end.
4. After all complete, print: `BATCH COMPLETE — /research (<N> stories)` with columns `Story | Verdict | Score | Report`.
5. If `Task` is unavailable: do not loop — ask the user to run each story individually.



# /arh-research — Main Orchestrator

Run a feasibility assessment after a story is certified. Output a Feasibility Assessment with verdict, ranked risks, and (when an issue tracker is configured) a tracker subtask mirroring the result.

Hybrid flow: the gate (Phase 0) and the tracker sync (Phase 2) run inline here in the main session; the autonomous assessment (Phase 1) is delegated to the `research-agent` subagent (model `haiku`) — it does the read-heavy scan at the cheaper model, and a subagent cannot prompt the user or spawn the tracker subagent, so those stay in the main session.

**Input:** `$ARGUMENTS` — one story id, or multiple space-separated ids for batch (see Batch mode above)

## Pipeline

```
0. Gate                     (main, read-only)
   → INVOKE research-agent   (subagent: scan → patterns → risks → score → write report + state)
2. Tracker subtask          (main, MCP: mandatory when issue_tracker enabled)
```

## Phase 0 — Gate (main, read-only)

_Single-story mode — batch detection (above) has already run; if there were multiple story IDs, this point is never reached._

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md` — run the **gate sections only**: Preconditions, the Upstream dependency resolver, and the patterns-freshness (G15) warning.

If any precondition or upstream check fails, **abort here with the helpful message and do NOT invoke the agent.** The autonomous parts of `00-context` (Read story, load `codebase-exploration`, pre-flight) are the agent's job, not yours.

## Phase 1 — Assessment (invoke research-agent)

Invoke the `research-agent` subagent with `$ARGUMENTS`. It runs scan → pattern map → risk register → score → verdict (formats from skill `research-assessment`), writes `docs/research/$ARGUMENTS.md`, and writes the `research` / `research_verdict` / `phase` status fields to the state index.

Consume the agent's hand-off (score, verdict, open-clarifs, report path), surface it, and **proceed to Phase 2 for every verdict**. Pass verdict + open-clarif count through; when verdict ∈ {SPIKE, BLOCK} **or** open-clarifs > 0 the result is **not yet certified** — Phase 2 flags the subtask pending.

## Phase 2 — Tracker subtask (main, mandatory when configured)

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-tracker.md`

This phase is **not optional** when `provider != none` in `docs/config/issue-tracking.yaml`. The orchestrator must not end its run without completing it OR explicitly logging why it was skipped.

## Final summary

```
RESEARCH COMPLETE
──────────────────────────────────────
Story:              $ARGUMENTS
Upstream deps:      <N> checked, all OK | aborted (see report)
Feasibility score:  <T>/100
Verdict:            GO | GO-WITH-CONDITIONS | SPIKE | BLOCK
Open clarifications: <N>            (must be 0 to advance)
Top risks:
  1. <severity>  <one-line>
  2. <severity>  <one-line>
  3. <severity>  <one-line>
Synthesis:          <1-line summary; full paragraph in research.md>
Top recommendations:
  1. <one-line>
  2. <one-line>
  3. <one-line>
Tracker subtask:    {KEY-XX}  | skipped (<reason>)
Report:             docs/research/$ARGUMENTS.md

Next: /arh-plan-requirements $ARGUMENTS  (if GO or GO-WITH-CONDITIONS)
      Address blockers              (if SPIKE or BLOCK)
```
