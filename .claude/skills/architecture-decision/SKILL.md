---
name: architecture-decision
description: Record a project's high-level architecture as ADRs — altitude guardrail, ADR numbering, greenfield-record vs brownfield-reverse-engineer branches. Used by bootstrap-agent.
user-invocable: false
---
# High-level architecture (ADRs)

Goal: capture the project's **high-level software architecture** as Architecture Decision Records under `docs/adr/`. ADRs are the only output. Use skill `adr-template` for ADR structure.

## Altitude guardrail (read first)

This records **system-level** decisions only. Stay at this altitude:

**DECIDE here** — the six high-level dimensions settled in the orchestrator's Step 4.0 architecture-decisions step, in the project's own vocabulary (not necessarily a backend shape):
- **Runtime & delivery** — where the code runs, how it ships.
- **State & data** — where state/data lives, or stateless.
- **Interfaces & contracts** — what it exposes or consumes; the boundary contract.
- **Execution model** — sync/async, batch/stream, scheduled/event/manual.
- **Trust & access** — identity, authz, secrets, compliance.
- **Operability** — health signals, error handling, retry/idempotency.

**DO NOT decide here** (out of scope — belongs to `/arh-plan-implementation` Phase 1 decision log, `DECISIONS.md`):
- Individual modules, classes, or function design.
- Table-level schema or endpoint lists.
- Source-file layout.

If a decision is about ONE component's internals, it is the wrong altitude — defer it to per-feature planning.

## ADR numbering

`docs/adr/0001-tech-stack.md` (tech stack) is written in Phase 3. Architecture ADRs start at the next free id:

1. List `docs/adr/` and find the highest existing `NNNN`. Never hardcode `0002` — a brownfield repo may already have ADRs.
2. **Default to ONE** consolidated `NNNN-system-architecture.md`. Splitting is the exception — justified only by a distinct, independently-revisable decision (e.g. a compliance data-handling rule), never by topic tidiness.
3. Update the `docs/adr/README.md` index if present.

## Greenfield branch — record the decisions

The architecture was settled with the user in Step 4.0. **Record it — do not re-derive or invent.**

- Inputs: the Step-4.0 `architecture:` block (the six dimensions — runtime, state, interfaces, execution, trust, operability) + the topology from the wired `<framework>-patterns` skills and `docs/adr/0001-tech-stack.md` (recorded frameworks imply tiers — `nextjs` ⇒ web tier, `fastapi` ⇒ API tier, a declared DB ⇒ datastore tier).
- Output: ONE consolidated ADR. `Status: Accepted` for decisions the user confirmed; `Status: Proposed` / `[NEEDS CLARIFICATION]` for any the user deferred — do not fill a gap by guessing. Include `Consequences` incl. reversibility.

## Brownfield branch — reverse-engineer

The code already exists — document what is real, do not propose a target:

1. Load skill `codebase-exploration`. Produce an Exploration Log focused on architecture questions: entry points, module/package boundaries, datastore clients, auth middleware, message/queue clients, deployment manifests / Dockerfiles / CI.
2. Write ADR(s) describing the architecture **as it actually is** — `Status: Accepted` (it exists).
3. Add a `## Flagged gaps` section listing undocumented layers or missing configs (e.g. "no migration tooling found", "auth split across two middlewares"). Pass these to the hand-off report.
4. Only when a gap is material, write one follow-up ADR `Status: Proposed` with a recommended fix.
