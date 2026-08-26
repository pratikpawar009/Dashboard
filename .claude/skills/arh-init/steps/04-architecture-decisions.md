# Phase 4.0 — Architecture decisions (main session, interactive)

Goal: settle the high-level architecture decisions **with the user**, before invoking `bootstrap-agent`. The agent (Phase 4c) only *records* what you settle here — it must not invent these. Run this in the main session so you can ask; the subagent cannot.

## The frame — six dimensions, instantiated per project

Every software project — frontend, backend, data pipeline, automation, cloud/IaC, library — answers the same six high-level questions. **Only the vocabulary changes with the declared stacks/roles.** Do NOT assume a backend shape.

- **D1 · Runtime & delivery** — where the code runs, and how it ships.
- **D2 · State & data** — where state/data lives, or stateless.
- **D3 · Interfaces & contracts** — inputs/outputs; what it exposes or consumes.
- **D4 · Execution model** — how work is triggered: sync/async, batch/stream, scheduled/event/manual.
- **D5 · Trust & access** — identity, authz, secrets, compliance (PII/HIPAA).
- **D6 · Operability** — health signals, error handling, retry/idempotency.

## Instantiate from the declared roles — do not hardcode

For each dimension, derive its concrete form from the project itself, not a fixed list:

- the declared stacks + roles in `docs/adr/0001-tech-stack.md`;
- each stack's `<framework>-patterns` skill — its `Data access` / `API contracts` / `State management` / `Observability` sections already name what a dimension means for that stack;
- `docs/prd/*` + `docs/config/domains.json` for stated intent + compliance.

A dimension with no surface in this project is **N/A — skip it.** (A stateless CLI has no D2; a pure frontend has no D3 API to *expose* — it *consumes* one; an automation job's D1 is a runner/cron, not a server.) For multi-role projects, **union** the live dimensions across roles and merge their vocabulary. Never force a backend term onto a non-backend role.

## Sources first — ask only the gaps

Before asking, check the sources above. If a dimension is already settled (stack implies it, PRD/domains state it), record that and move on. Ask only the live, unsettled dimensions — **one at a time**.

## How to ask (recommendation-first)

For each gap, lead with a recommended default + a one-line reason, then let the user confirm or override:

```
D<n> <dimension>: recommended <choice> — because <reason from the role's stack / PRD / domains>.
Use this, or name another?
```

Keep it at dimension altitude (the shape of the choice) — NOT component or schema design (that emerges per feature in `/arh-plan-implementation`). One question at a time; do not batch.

## Worked example — a backend stack (illustrative only)

This is how the six dimensions read for **one** role. Other roles read the *same* six through their own vocabulary — derive theirs from the declared stacks; do not copy this list.

- **D1** Runtime & delivery → container vs serverless; CI/CD target.
- **D2** State & data → primary DB engine + cache; migration approach.
- **D3** Interfaces & contracts → API style (REST / GraphQL / gRPC) + schema & versioning.
- **D4** Execution model → synchronous API + async jobs/queue; event-driven boundaries.
- **D5** Trust & access → authn (session / JWT / OIDC) + authz; secrets handling.
- **D6** Operability → metrics / logs / traces; error handling + retry/idempotency.

## Record

Append each settled dimension to the Phase-1 answer log under an `architecture:` block, keyed by dimension; mark skipped ones `N/A (<reason>)`:

```
architecture:
  runtime:     <choice>   (source)
  state:       <choice>   (source)
  interfaces:  <choice>   (source)
  execution:   <choice>   (source)
  trust:       <choice>   (source)
  operability: <choice>   (source)
```

Phase 4c reads this block and records it as the architecture ADR. Anything the user defers stays out — 4c marks it `Status: Proposed` / `[NEEDS CLARIFICATION]` rather than guessing.
