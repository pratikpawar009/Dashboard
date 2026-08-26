---
name: arh-validate-feature
description: Generate or rerun E2E flows from test-case JSON, run all flows against real APIs, update JSON status, emit consolidated bug-style report.
argument-hint: "[story-id ...] [--rerun | --rerun-failed]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Task
---
**Batch:** Split `$ARGUMENTS` on whitespace, commas, or semicolons. `--` tokens are flags (this skill uses: `--rerun`, `--rerun-failed`); all others are story IDs.
- **0 story IDs** → abort: print `Usage: /validate-feature <story-id> [story-id ...]`.
- **1 story ID** → skip this, continue to the phase below (single-story mode, unchanged).



**2+ story IDs — batch:**

1. **Do NOT loop in this session.** For each story ID in order, fire one isolated `Task` invocation: `/validate-feature <story-id> [flags]`. Each `Task` gets a fully isolated context window — no state, findings, or decisions from one story can affect another.
2. **Wait** for each `Task` to finish completely before starting the next.
3. **Display each story's complete output to the user immediately** after it finishes — do not collect silently and show only at the end.
4. After all complete, print: `BATCH COMPLETE — /validate-feature (<N> stories)` with columns `Story | Verdict | Pass/Fail/Skip | Report`.
5. If `Task` is unavailable: do not loop — ask the user to run each story individually.



# /arh-validate-feature — Main Orchestrator

Generate flows (default) or rerun existing flows (`--rerun`). Always run every flow — never stop on first failure.

Hybrid flow: the gate (Phase 0) runs inline here in the main session; the validation run (Phase 1) is delegated to the `validation-agent` subagent, which applies the `validation-execution` skill (environment → flows → stack smoke → run → JSON update → report).

**Input:** `$ARGUMENTS` — one story id (plus optional `--rerun`), or multiple space-separated ids for batch (see Batch mode above)

## Pipeline

```
0. Gate                       (main, read-only)
   → INVOKE validation-agent   (environment → flows → Phase 2b stack smoke → run → JSON → report)
2. Summary                    (main: consume the agent's hand-off)
```

## Run modes

| Flag | Flows | Run |
|---|---|---|
| (none, default) | Generate flows for every automatable TC | Run every TC |
| `--rerun` | Reuse existing flow files; skip generation | Run every TC |
| `--rerun-failed` (V2) | Reuse existing flow files; skip generation | Run **only** TCs whose previous `last_run.verdict != "PASS"` (or `last_run` absent) |

Use `--rerun-failed` after a fix-loop pass to validate only the touched flows; saves CI time and keeps the rest of the report stable. Pass the flag through to the agent.

## Phase 0 — Gate

_Single-story mode — batch detection (above) has already run; if there were multiple story IDs, this point is never reached._

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

If any precondition fails, abort here with the helpful message and do NOT invoke the agent.

## Phase 1 — Validation run (invoke validation-agent)

Invoke the `validation-agent` subagent with `$ARGUMENTS` plus any run-mode flag. It applies skill `validation-execution`: environment preflight, flow generation/load, **Phase 2b stack smoke** (starts the real application server(s), runs migrations, hits health endpoints — disabled when `harness.yaml outputs.validation.stack_smoke: false`; catches the class of failure where the test runner passes but the real system never booted), runs all flows without stopping on failure, updates `docs/test-cases/$ARGUMENTS.json`, verifies PLAN task completion, and writes the consolidated report with the proof-of-run footer.

Consume the agent's hand-off (pass/fail/skip counts, stack-smoke results, task-completion tally, report path) for the summary below.

## Final summary

```
VALIDATE-FEATURE COMPLETE
──────────────────────────────────────
Story:       $ARGUMENTS
Flows ran:   <P>/<TOTAL> passed
Verdict:     PASS | PARTIAL | FAIL
Failures:    <count>  (see report)
Manual TCs:  <count>  (require human follow-up)
Report:      docs/features/$ARGUMENTS/VALIDATION-<DATE>.md

Next:
  PASS    → /arh-review $ARGUMENTS
  PARTIAL → fix and /arh-validate-feature $ARGUMENTS --rerun
  FAIL    → escalate or fix; do not advance
```
