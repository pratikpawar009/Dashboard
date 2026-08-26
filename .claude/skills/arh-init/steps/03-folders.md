# Phase 3 — Folders + RTM stub + ADR-0001

Goal: ensure the docs tree exists and write the two seed documents downstream commands assume.

## Folders

Create when missing:

```
docs/
├── stories/
├── research/
├── features/
├── requirements/
├── adr/
├── sessions/
├── test-cases/
└── design/
    └── schema.json     (only when role frontend or mobile and design integration enabled)
```

Do not delete existing files. Do not delete folders with content.

## RTM stub

`docs/requirements/RTM.md`:

```
# Requirements Traceability Matrix

> Source of truth for requirement IDs. Updated by `/arh-intake`, `/arh-plan-requirements`, `/arh-plan-implementation`, `/arh-implement`.

## Numbering

- Epics: `<EPIC>` (3-letter uppercase code, e.g. `CHK`).
- Stories: `<EPIC>-<NN>`.
- Tasks: `<EPIC>-<NN>.<MM>`.
- Test cases: `<EPIC>-<NN>-TC-<MM>`.

## Matrix

| ID | Title | Source | Type | Parent | Status | Tracker | Story file | Tests |
|----|-------|--------|------|--------|--------|---------|------------|-------|
```

## ADR-0001

ADR-0001 is **tech-stack only**. The high-level system-architecture ADRs (`0002`+) are written later by `bootstrap-agent` in Phase 4c — do not author architecture here. Ensure `docs/adr/` exists (folder list above) — otherwise the ADR-0001 write below fails against a missing directory.

Source the stack list from `harness.yaml stacks[]` (id, framework, version, package_manager, test_runner); for brownfield, reconcile against the manifests detected in Phase 0. This is a main-session step, so reading the generator config here is fine. Record every stack's `<id>` — Phase 4 (commands, architecture) reads stacks from this ADR, not from `harness.yaml`.

**Stack guard — when `harness.yaml stacks[]` is empty.** No stack was declared at generate
time. `harness.yaml stacks[]` is the source of truth the composer reads, so an empty list
means no `<framework>-patterns` are wired and the § Decision stack list would be blank —
`/arh-plan-implementation` would later abort ("No tech stack declared"). Settle it **into
`harness.yaml`** here, before writing the ADR.

If `harness.yaml stacks[]` is already non-empty at this point — because the user declared it
interactively during `harness init`, or Phase 0's `harness detect --write` already found and
recorded it — **this guard does not fire**. Say so plainly instead of silently skipping past
it: `Stack already declared in harness.yaml — skipping the stack guard.` There is nothing left
to settle; go straight to sourcing § Decision from what's already there.

Otherwise, load skill `stack-selection` and follow its branch for the Phase-0 verdict:

- **Brownfield** → run its detect→map table over the manifests Phase 0 found (reuse
  `codebase-exploration` for the scan), autofill `{framework, version, package_manager,
  test_runner}` per detected stack, and confirm anything ambiguous with the user.
- **Greenfield** → run its recommendation rubric using the Phase-1 answers (product type Q1,
  primary language Q2, personas, compliance), recommendation-first; the user confirms or picks.

Then, per the skill's Output section, record each settled stack by **editing `harness.yaml`
directly** — append an entry under `stacks:` (`id`, `framework`, `version?`, `package_manager?`,
`test_runner` or `none`, `paths`). Do **not** write the stack only into ADR-0001; that drifts
from the source of truth. Once the stack is in `harness.yaml`, source the § Decision stack list
from it below as normal — `harness.yaml` and ADR-0001 then agree, and `/arh-plan-implementation`
has a stack to gate on.

**Wire `<framework>-patterns` skills — brownfield, always, regardless of how the stack got there.**
This step is NOT scoped to the stack guard above — it applies whenever this is a brownfield
project, whether `harness.yaml stacks[]` arrived via Phase 0's `harness detect --write`
(`steps/00-detect.md`, the common case — the guard above never even fires because the list is
already non-empty) or via the guard's own fallback just above. Either way, `harness generate`
has not run since the stack was recorded, so the patterns files still don't exist:

- **Brownfield** → before running anything, check whether the target `<framework>-patterns`
  skill(s) already exist with zero remaining TODO markers — e.g. the user already ran
  `harness generate` + `harness fill` themselves before this `/arh-init` run. If so, say so
  plainly instead of re-running silently: `<framework>-patterns already wired and filled (0
  TODOs) — harness generate is a no-op here.` Either way, still run `harness generate --config
  harness.yaml` right here, in the main session, before Phase 4 begins — it stays safe to
  re-run even when there's nothing left to do (`preserve_on_regen`; see below), so the check
  only changes what gets said about it, not whether it runs. `harness.yaml` already has every
  stack recorded by this point (from Phase 0 and/or the guard above), so this runs
  non-interactively — no `--target` flag; leave it unset so the CLI resolves the project's
  already-chosen emitter target itself. This synthesises every declared stack's
  `<framework>-patterns` (and `<runner>-patterns`) skill immediately, so Phase 4a
  (`project-commands` consulting those bodies) and Phase 6 (deep scan writing into them) both
  have real files, not a scaffold that doesn't exist yet. It is safe to re-run — existing
  patterns skills the team has filled are preserved, never reset to TODO placeholders. If the
  command exits non-zero, stop and surface the error to the user before continuing — do not
  proceed into Phase 4 with patterns skills still missing.
- **Greenfield** → unchanged: tell the user (surface it in the Final summary) to run
  `harness generate` once after `/arh-init` themselves. Until then, stack-specific agents fall
  back to package-manager defaults (degraded, not blocked).

`docs/adr/0001-tech-stack.md`:

```
# ADR-0001: Tech stack

- Status: Accepted
- Date: <YYYY-MM-DD>
- Deciders: <project lead>

## Context

<1 paragraph: why we are starting this project / continuing this work and what constraints shape the stack>

## Decision

The harness records the following stack:

- Stacks: one line per stack — `<id> — <framework> v<version>` (the `<id>` is the canonical stack identifier downstream phases key on; record it for every stack).
- Package manager / Build / Test / Lint / Format: <from project-commands.yaml>
- Integrations: <issue_tracker, doc_tracker, design, vcs, ci>

## Consequences

- Positive: <list>
- Negative: <list>
- Reversible? <cost to undo if a stack change becomes necessary>
```

## design/schema.json (only when applicable)

```json
{
  "designSystem": {
    "fileKey": "<figma-file-key | TODO>",
    "url": "<figma-url | TODO>",
    "pages": {
      "tokens": "",
      "atoms": "",
      "molecules": "",
      "organisms": "",
      "icons": "",
      "features": {}
    }
  },
  "tokens": {
    "color": [],
    "spacing": [],
    "typography": []
  }
}
```
