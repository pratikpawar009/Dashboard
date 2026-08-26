---
name: project-memory
description: Populate the project memory file (CLAUDE.md) — canonical sections, @import + Where-to-look wiring, fill/add/overwrite rules, no-duplicate discipline. Used by bootstrap-agent.
user-invocable: false
---
# Project memory file

Goal: ensure the project memory file (`CLAUDE.md` for Claude Code) carries the canonical sections below. Fill them from the Phase-1 answer log, add any that are absent, and never clobber existing content.

Conventions and any overwrite approvals were collected in Phase 1 — fill mechanically and report what you changed.

## Execution order

The bootstrap-agent applies skill `project-commands` before this one, so `docs/config/project-commands.yaml` (the `@import` target below) already exists within the run. That fixed order is what makes the `@import` reachability check meaningful.

## Canonical sections

A complete memory file carries these. Verify each against the file on disk.

**Navigation wiring**

- Two import lines at the very top: `@README.md` and `@docs/config/project-commands.yaml`.
- `## Where to look` — a table mapping *what → where*: build/test/dev commands → `docs/config/project-commands.yaml`; stack idioms / anti-patterns / design tokens → `.claude/skills/<framework>-patterns/SKILL.md`; cross-cutting rules → `.claude/rules/*-baseline.md`; architectural decisions → `docs/adr/<NNNN>-<slug>.md`; per-feature artefacts → `docs/features/<id>/`; tracker config → `docs/config/`.

**Context (from the Phase-1 answers)**

- `## Conventions` — project-wide always-do-X bullets (≤8, each ≤120 chars).
- `## Personas` — one bullet per persona: role + one-line goal.
- `## Domain glossary` — one bullet per term + one-sentence definition.
- `## Target platforms` — concrete list, e.g. `iOS 17+, Android 12+, Web (Chrome 122+, Safari 17+)`.

**Conventions appends**

- `## Branch conventions` — `feature/<id>`, `bugfix/<id>`, `hotfix/<id>`, `chore/<id>`.
- `## Commit format` — Conventional Commits (`type(scope): summary`) unless Phase 1 said otherwise.
- `## PR conventions` — title format, body template, required sections (Summary, Test plan, Migration).
- `## Design system` — Figma file key + URL, when role frontend/mobile and design integration enabled.

## Verify and update

For each canonical section, compare against the file on disk:

- present with real content → **leave it** (report `kept: <section>`).
- present but still a TODO-comment placeholder → **fill** from the Phase-1 answers.
- **absent** → **add** it — navigation wiring at the appropriate position, context/append sections appended in order. Add a context section only when Phase 1 actually gathered a value; never add an empty heading.
- a section Phase 1 pre-approved for overwrite → **overwrite** it, and record `OVERWROTE: <section>`.

Same path for both modes: a freshly generated file lands mostly on "fill the placeholder"; a preserved (brownfield) file lands mostly on "add the absent piece".

## Don't duplicate

If the team already documents conventions / personas / domain under a **differently-named** heading, leave theirs, skip the canonical heading, and report `possible-duplicate: <their heading> ≈ <canonical section>`. Never create a second copy — let the human reconcile.

The harness-structure sections `## Tech stack`, `## Integrations`, `## SDLC` are data-rendered at generate time and are not owned here. If a preserved file lacks them, report `missing-structure: <section>` rather than rebuilding them.

## @import reachability

After writing, verify the two import targets resolve:

```bash
for f in README.md docs/config/project-commands.yaml; do
  if [ ! -f "$f" ]; then
    echo "WARNING: memory-file @import target missing: $f"
  fi
done
```

Greenfield: `README.md` is created later by `/arh-scaffold` — the warning is expected and benign on the first run; surface it, do not block. Brownfield: both should already exist; a warning is a real gap — list it under "Flagged".
