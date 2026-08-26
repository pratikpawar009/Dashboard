---
name: arh-fix
description: Hotfix lane — fixes a standalone defect without full SDLC (no story/research/PRD/plan). Root-cause-first, surgical, regression-tested, evidence-gated. Bounces architectural changes to /arh-intake.
argument-hint: "[\"<bug description>\" | --from-test <path> | <TRACKER-KEY>] [--for <feature-id>] [--debug]"
disable-model-invocation: true
allowed-tools: Read Write Edit Bash Grep Glob
---
# /arh-fix — Hotfix lane

Fix one defect fast, without routing through `intake → research → plan-requirements → plan-implementation → implement`. For a one-line bug, a regression, a production hotfix, or a failing test that needs no new feature work.

**This is NOT a governance backdoor.** It keeps the floor that protects the codebase — root-cause discipline, surgical scope, a regression test, an evidence pass, and a human commit gate — and **bounces anything architectural back to the full flow** (Step 1). A fix that needs an ADR is not a hotfix.

## When to use `/arh-fix` vs `/arh-intake`

| Use `/arh-fix` | Use `/arh-intake` (full flow) |
|---|---|
| One root cause, bounded blast radius | New behaviour / feature |
| No new ADR, no contract change, no data-model change | Needs an architecture decision |
| Touches a handful of files | Touches many modules / services |
| Regression test + existing tests prove it | Needs new acceptance criteria |

If unsure, Step 1's architectural-bounce check decides for you.

## Inputs

- `"<bug description>"` — free-text defect report, OR
- `--from-test <path>` — a known failing test to make green, OR
- `<TRACKER-KEY>` — a tracker bug ticket (issue-tracker provider must be configured)
- `--for <feature-id>` — optional; attaches the fix record to that feature's state `fixes[]`
- `--debug` — optional; **investigate-only**. Run Step 0 + Step 1 (root cause), write an RCA report, then STOP. No fix, no test, no commit. Read-only — safe to run on `main`. Use when you want the diagnosis first and will decide the fix yourself.

## Modes

| Mode | Runs | Output |
|---|---|---|
| **fix** (default) | Steps 0 → 4 | committed fix + regression test + PR + `docs/fixes/fix-<NN>.md` |
| **`--debug`** | Steps 0 → 1, then STOP | `docs/fixes/RCA-<NN>.md` — root cause + evidence + classification + recommended next step. No code change. |

`--debug` is the diagnosis half on its own. Its report ends with the recommended next command: `/arh-fix` (re-run without `--debug`) for a hotfix-able cause, or `/arh-intake` for an architectural one.

## Sequence (strict)

No phase preconditions — `/arh-fix` is the bypass lane. But every step below is mandatory.

### Step 0 — Context

Read and follow: `${CLAUDE_SKILL_DIR}/steps/00-context.md`

Parse the defect input, load project memory + commands + matching rules, confirm a working branch (never `main`), assign a `FIX-<NN>` id.

### Step 1 — Root cause + architectural bounce

Read and follow: `${CLAUDE_SKILL_DIR}/steps/01-root-cause.md`

Apply the `root-cause-first` skill: state `<cause> produces <symptom> because <mechanism>` before any code. **If the root cause is architectural — needs an ADR, changes a public contract, touches the data model, or spans many modules — STOP and route to `/arh-intake`.** `/arh-fix` does not proceed on architectural defects.

**`--debug` mode ends here:** write `docs/fixes/RCA-<NN>.md` (root cause + evidence + classification + recommended next command) and STOP. Do NOT run Steps 2–4.

### Step 2 — Fix

Read and follow: `${CLAUDE_SKILL_DIR}/steps/02-fix.md`

Invoke `implementation-agent` with the defect + stated root cause. Surgical scope only (`surgical-changes` rule) — patch the cause, nothing adjacent.

### Step 3 — Regression test + evidence

Read and follow: `${CLAUDE_SKILL_DIR}/steps/03-verify.md`

Mandatory regression test that would have caught this defect (G4), then the six-dimension evidence pass via the `evidence-pass` skill. BLOCKED evidence stops the lane.

### Step 4 — Commit + PR

Read and follow: `${CLAUDE_SKILL_DIR}/steps/04-commit-pr.md`

Human-gated commit (conventional `fix(<scope>): …`), write the `docs/fixes/fix-<NN>.md` record, attach to a feature's `fixes[]` when `--for` was given. Never auto-push.

## Hand-off

- **fix mode**: `Fix complete: FIX-<NN>. Root cause: <one-line>. Files: <N>. Regression test: <id>. Evidence: <READY | BLOCKED>. Next: human merge after CI.`
- **`--debug` mode**: `Diagnosis complete: RCA-<NN>. Root cause: <one-line>. Classification: <hotfix-able | architectural>. Next: <`/arh-fix …` | `/arh-intake …`>. No code changed.`
