# ADR-0001: Tech stack

- Status: Accepted
- Date: 2026-08-26
- Deciders: pratik.pawar@apexon.com

## Context

Dashboard is a greenfield AI SDLC monitoring dashboard: a full-stack web app (Next.js frontend + FastAPI backend + Postgres) tracking harness activity for engineering managers, developers, PMs, architects, QA, and leadership stakeholders. Stack was pre-declared in `harness.yaml` at generate time.

## Decision

The harness records the following stack (source: `harness.yaml stacks[]`):

- `fastapi` — fastapi (backend framework, paths: `**`)
- `typescript` — typescript (paths: `**`)
- `next` — next (paths: `**`)
- `postgres` — postgres (paths: `**`)
- `pytest` — pytest (paths: `**`)
- `alembic` — alembic (paths: `**`)
- `pydantic` — pydantic (paths: `**`)
- `nextjs` — nextjs v15 (package manager: pnpm, test runner: vitest, paths: `apps/web/**`)
- `fastapi-2` — fastapi v0.115 (package manager: uv, test runner: pytest, paths: `services/api/**`)

- Package manager / Build / Test / Lint / Format: not yet finalized — `docs/config/project-commands.yaml` does not exist yet; written by `bootstrap-agent` in Phase 4 of this `/arh-init` run.
- Integrations: issue_tracker=github, doc_tracker=local, design=html-mockup, vcs=github, ci=none.

## Consequences

- Positive: Next.js + FastAPI + Postgres is a well-trodden full-stack combination with strong typing on both ends (TypeScript, Pydantic) and a battle-tested migration story (Alembic).
- Negative: two runtimes (Node + Python) to keep in sync; no CI configured yet (`ci: none`) so there's no automated gate until one is added.
- Reversible? Stack change before real feature code exists is low-cost (greenfield, nothing built on top yet).
