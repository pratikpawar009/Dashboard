# Phase 0 — Gate (main session)

Goal: confirm preconditions before spending the impl-planning-agent. If a check fails, abort with the helpful message and do NOT invoke the agent.

> **Ownership split.** The `/arh-plan-implementation` orchestrator (main session) runs § Preconditions, § Pre-flight, and § Patterns-skill freshness below. The `impl-planning-agent` performs the § Read in order list itself after it is invoked (its frontmatter already carries `codebase-exploration`, `adr-template`, `plan-authoring`).

## Preconditions (mandatory)

Load skill `phase-preconditions` and apply the `/arh-plan-implementation <id>` row of its matrix — the row's conditions (Product Gate, tech-stack ADR, state file) and abort messages are canonical there; do not re-derive them. The Product Gate decision is read from `docs/features/$ARGUMENTS/state.json` `.gate` — the file is the source of truth, not the checklist.

Do NOT skip this check. Aborting here protects downstream tasks from operating on an unapproved PRD.

## Read in order

1. `docs/features/$ARGUMENTS/REQUIREMENTS.md` — must contain the Approvals section (Product Gate passed). Read `## Screen inventory` (when present) to drive UI file plan.
2. `docs/features/$ARGUMENTS/DESIGN.md` — **load when present**. Carries the per-screen component list, tokens used, form factors, and implementation notes that drive the file plan + task table for UI work. Absent when `integrations.design == none` or design hasn't run yet (in which case `design ∈ {pending, n/a}` per `docs/features/$ARGUMENTS/state.json`). If `design == pending` AND `integrations.design != none`: surface a warning (`⚠ DESIGN.md not yet produced — UI tasks may be under-specified. Consider invoking ux-agent before /arh-plan-implementation.`) but proceed.
3. `docs/research/$ARGUMENTS.md` — risk register and pattern map carry into PLAN.md.
4. `docs/stories/$ARGUMENTS.md` — for traceability headers.
5. `CLAUDE.md` — stack, module conventions, branch/commit format.
6. Load skills `codebase-exploration`, `adr-template`.
7. All `.claude/rules/*.md` matching the file globs identified in research.

## Pre-flight

- REQUIREMENTS.md "Approvals" section has at least one APPROVE entry. Otherwise abort: `Product Gate not passed. Run /arh-plan-requirements $ARGUMENTS first.`
- Research verdict is `GO` or `GO-WITH-CONDITIONS`. SPIKE / BLOCK abort: re-run research after the conditions retire.

## Patterns-skill freshness check (G15)

Run the patterns-freshness check per skill `phase-preconditions` § G15 — warn per unfilled skill (do NOT abort), consequence: "PLAN.md may be generic".

## Output

```
Context loaded for $ARGUMENTS.
  Approvals: <count>   Last: <name> on <date>
  Research:  <verdict> (<score>/100)
  Design:    <complete | pending | n/a>   <DESIGN.md path if complete>
  Rules:     <count> path-scoped active
  Patterns:  <W> unfilled warnings
```
