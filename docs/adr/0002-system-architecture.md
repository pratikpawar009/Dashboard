# ADR-0002: System architecture

- Status: Accepted
- Date: 2026-08-26
- Deciders: pratik.pawar@apexon.com

## Context

Dashboard is a greenfield AI-SDLC monitoring app (ADR-0001: Next.js frontend, FastAPI backend, Postgres, Alembic, Pydantic, pytest/vitest). Six high-level architecture dimensions were settled with the user in `/arh-init` Step 4.0, ahead of any scaffolding. CI is currently `none` and no serverless platform is declared.

## Decision

- **Runtime & delivery**: Containerized (Docker), self-hosted / any cloud. Chosen for portability across the two-runtime (Node + Python) stack given no CI/serverless platform is committed yet.
- **State & data**: Postgres as the primary datastore; Alembic owns migrations. No cache layer yet — add one only when a measured need appears (see `.claude/rules/performance-baseline.md`).
- **Interfaces & contracts**: REST API with Pydantic-validated request/response schemas; FastAPI auto-generated OpenAPI docs are the contract source of truth.
- **Execution model**: Event-driven ingestion — `.github/hooks/` (`harness-mcp-push.mjs`, `copilot-activity.mjs`) and the `agentrise` MCP push AI-activity/artifact events to a FastAPI ingest endpoint. Dashboard reads are synchronous REST against Postgres. No batch or scheduled jobs.
- **Trust & access**: OIDC/SSO authentication; role-based authorization mapped to the six personas (Engineering Manager, IC/Developer, Executive/Leadership, Project Manager, Architect, QA).
- **Operability**: Structured JSON logs; FastAPI exception handlers return a consistent error-response shape; bounded retry with exponential backoff + jitter on the ingest path. No APM/tracing vendor selected yet.

## Consequences

- Positive: event-driven ingest decouples the hooks/MCP producers from dashboard read latency; REST + OpenAPI gives both frontend and any future consumer a typed, self-documenting contract; containerization keeps deployment portable while `ci: none`.
- Negative: no cache layer means read-heavy dashboard queries hit Postgres directly — revisit if pagination (per performance-baseline) isn't enough; no APM/tracing means operability is log-only until a vendor is chosen; OIDC/SSO provider itself is unspecified — implementation planning must pick one before auth work starts.
- Reversible? All six are cheap to change now (no code built yet). Costliest to reverse later: the REST/OpenAPI contract shape, once frontend and hook producers depend on it; and the ingest endpoint's event schema, once `.github/hooks/` and `agentrise` are wired to it.

## Flagged gaps

- OIDC/SSO identity provider not chosen — `[NEEDS CLARIFICATION]` before auth implementation.
- No APM/tracing vendor selected for operability beyond structured logs.
- Cache layer intentionally deferred — no decision needed until a measured need exists.
