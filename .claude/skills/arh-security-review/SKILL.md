---
name: arh-security-review
description: Multi-phase security gate — SAST grep, dependency scan, OWASP checklist, stack-pattern check, compliance overlay. Blocks on Critical/High. Writes report + state.
argument-hint: "[story-id ...]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob Task
---
**Batch:** Split `$ARGUMENTS` on whitespace, commas, or semicolons. `--` tokens are flags; all others are story IDs.
- **0 story IDs** → abort: print `Usage: /security-review <story-id> [story-id ...]`.
- **1 story ID** → skip this, continue to the phase below (single-story mode, unchanged).



**2+ story IDs — batch:**

1. **Do NOT loop in this session.** For each story ID in order, fire one isolated `Task` invocation: `/security-review <story-id>`. Each `Task` gets a fully isolated context window — no state, findings, or decisions from one story can affect another.
2. **Wait** for each `Task` to finish completely before starting the next.
3. **Display each story's complete output to the user immediately** after it finishes — do not collect silently and show only at the end.
4. After all complete, print: `BATCH COMPLETE — /security-review (<N> stories)` with columns `Story | Verdict | C/H/M/L | Report`.
5. If `Task` is unavailable: do not loop — ask the user to run each story individually.



# /arh-security-review — Main Orchestrator

Multi-phase gate before merge. Combines SAST grep, dependency vuln scan, manual OWASP checklist, stack-specific idioms, and (when active) compliance overlay rules.

**Input:** `$ARGUMENTS` — one story id, or multiple space-separated ids for batch (see Batch mode above)

Hybrid flow: the gate (Step 0) runs inline here in the main session; the autonomous assessment (Step 1) is delegated to the `security-review-agent` subagent (model `sonnet`) — it does the read-heavy scan, and the gate aborts early before spending it.

## Pipeline

```
0. Context + gate           (main, read-only)
   → INVOKE security-review-agent  (subagent: deps scan → SAST → checklist → report + state)
```

## Step 0 — Context + gate (main, read-only)

_Single-story mode — batch detection (above) has already run; if there were multiple story IDs, this point is never reached._

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md` — run the **gate**: preconditions (`review` set, `impl == complete`, state present) plus the patterns-freshness (G15) warning.

If a precondition fails, **abort here with the helpful message and do NOT invoke the agent.** Reading the diff inputs, loading the checklist, and governance detection are the agent's job (skill `security-assessment`).

## Step 1 — Assessment (invoke security-review-agent)

Invoke the `security-review-agent` subagent with `$ARGUMENTS`. It runs dependency scan → SAST grep → OWASP checklist + compliance overlay + stack-pattern pass (method + verdict rule from skill `security-assessment`), writes `docs/features/$ARGUMENTS/SECURITY-<DATE>.md`, and writes the `security` / `security_findings` / `phase` state fields. It blocks on any Critical/High finding or compliance-tagged carry-forward. State write is unconditional regardless of issue-tracker `provider`.

Consume the agent's hand-off (verdict + finding counts) for the summary below.

## Final summary

```
SECURITY REVIEW COMPLETE
──────────────────────────────────────
Story:               $ARGUMENTS
Governance profile:  <profile>
Findings:            <C> critical, <H> high, <M> medium, <L> low
Tool-missing:        <list or "none">
Verdict:             PASS | BLOCKED
Report:              docs/features/$ARGUMENTS/SECURITY-<DATE>.md

Next:
  PASS    → merge after CI passes
  BLOCKED → fix Critical/High findings; re-run /arh-security-review
```
