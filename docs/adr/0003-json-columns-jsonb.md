# ADR-0003: JSON-typed schema columns use PostgreSQL JSONB

- Status: Accepted
- Date: 2026-08-26
- Deciders: pratik.pawar@apexon.com

## Context

BED-01 re-implements the reference Prisma schema's 18-table shape in SQLAlchemy 2.0 (PRD §8.4, `docs/requirements/data.md` `db-schema` contract). Two columns are Prisma `Json`-typed: `program_summary.monthly_token_sparkline` and `usage_events.models`. PRD §8.4's type-mapping rule states `Json` → `JSON`/`JSONB` without picking one, and `docs/test-cases/BED-01.json` `BED-01-TC-13` explicitly accepts either. This is a durable-schema encoding choice on a contract 13 downstream stories consume (`db-schema` `consumed_by`: BED-02/03/04, AUTH-02/04, OVW-01..04, PGD-01..06, SHP-02..07, ING-01/02/03/07/08) — getting it wrong is not a private fix, it's a new migration every consumer has to re-verify against.

## Decision

Both columns use `sqlalchemy.dialects.postgresql.JSONB`, not plain `sqlalchemy.JSON`. JSONB stores as parsed binary (supports future GIN indexing and containment operators `@>`/`?` without a schema change) and is materially faster to query than text-based `JSON`. These columns are only written by the rollup-rebuild path (BED-03), never on a request-serving hot path — this story's NFR section already scopes out request-path latency — so JSONB's marginally higher write-time parse cost is irrelevant here.

## Consequences

- Positive: dashboard read APIs (OVW/PGD stories) can add a GIN index or containment filter on either column later without an `ALTER COLUMN TYPE` migration; smaller on-disk footprint than text `JSON` for repeated key names (sparkline arrays, model lists).
- Negative: none material — no code in this story or its documented downstream consumers relies on JSON's exact-whitespace/key-order text preservation, which is the only capability JSONB drops.
- Reversible? Medium — changing back to `JSON` is a new Alembic revision (`ALTER COLUMN ... TYPE json USING ...::json`), not a data-loss operation since both types round-trip the same JSON documents. No data exists yet (first migration, greenfield database per this story's Rollout plan), so the practical cost today is zero; cost grows once downstream rollups have live data.
