---
name: postgres-patterns
description: postgres patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing postgres code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# postgres Patterns

<!-- Harness scaffold: stack=postgres — STRUCTURE only; -->
<!-- Fill every CORE section below. Under OPTIONAL, keep only the sections that apply to -->
<!-- this stack and DELETE the heading+slot of the rest BEFORE filling. Keep ≤ 200 lines. -->
<!-- Deletion is safe: OPTIONAL slots use the word OPTIONAL (not TODO) so the lint does not -->
<!-- nag for them; CORE TODO slots are nagged until filled — that is intentional. -->
<!-- Loaded by implementation-, impl-planning-, validation-, code-review-, security-review-, -->
<!-- scaffold-, and cicd-agents when this stack is active. -->

## Verified facts

<!-- BEGIN VERIFIED FACTS -->
<!-- Owned by skill `deep-scan-verification` (/arh-init Phase 6) — `harness fill` never -->
<!-- edits between these markers. Empty until a brownfield deep scan approves facts here. -->
<!-- Each bullet ends in (see file:line); the file it cites is this fact's proof. -->
<!-- END VERIFIED FACTS -->

## Idioms

- No ORM models or session module exists yet in `app/` (no `app/db.py`, no `app/models/`) — routers still return stub data with explicit markers: `app/api/ingest.py:19` (`# TODO(implementation): write-through to Postgres via SQLAlchemy session`) and `app/api/activities.py:20` (`# TODO(implementation): query Postgres via SQLAlchemy, apply LIMIT/OFFSET or keyset pagination`).
- The only DB-connection code written so far is the Alembic migration runner's async engine (`migrations/env.py:70-74`), using `poolclass=pool.NullPool` — appropriate for a one-shot migration connection, not necessarily the pooling policy the running API should use.
- Driver: `psycopg[binary]>=3.2` (`pyproject.toml:14`) via SQLAlchemy's `postgresql+psycopg` dialect (`app/core/config.py:11`, `.env.example:3`).
- The connection string is centralized in `app.core.config.Settings.database_url`, sourced from the `DATABASE_URL` env var / `.env` (`app/core/config.py:11`, `.env.example:3`) — no other module builds a DSN.

## Project structure

- `app/core/config.py` — holds the single `database_url` setting used by both the (future) app runtime and the Alembic migration runner.
- No `app/models/` package exists yet — schema is currently defined only through Alembic migration files (none written yet, see alembic-patterns).

## Layering & dependency rules

- All DB access must go through `app.core.config.settings.database_url` as the single source of the connection string — no module should read `DATABASE_URL` directly via `os.environ` (only `config.py` and `migrations/env.py` touch it today).
- When a data-access layer is added, routers (`app/api/*`) should call into it rather than issuing SQL/ORM queries inline — keeps `app.api.*` free of SQL per the layering rule in fastapi-patterns.

## Error handling

Not yet evidenced — no query code exists in the scaffold to show how DB errors are caught or wrapped. State this plainly rather than inventing a convention: the first module that adds real queries should establish this pattern (e.g. wrap driver exceptions, don't let raw `psycopg` errors reach the client — route them through `app/core/errors.py`'s catch-all 500 handler at minimum).

## Anti-patterns

- Reading `DATABASE_URL` via `os.environ` directly in application code instead of importing `settings` from `app.core.config` (`config.py` already centralizes this).
- Adding a DB-backed list read without pagination bounds — `app/api/activities.py:11-18` already reserves `page`/`page_size` `Query` bounds (default 20, max 100) for when the query lands; `.claude/rules/performance-baseline.md` requires this on every list endpoint.
- Using `NullPool` outside the migration runner — it's correct for a one-off Alembic run (`migrations/env.py:73`) but would defeat connection pooling if copied into the API's runtime engine setup, which doesn't exist yet.

## Examples

BAD — bypassing the centralized settings for the connection string:
```python
import os
engine = create_engine(os.environ["DATABASE_URL"])  # duplicates config.py's job
```

GOOD — use the single settings source (matches app/core/config.py:11 / migrations/env.py:20):
```python
from app.core.config import settings
engine = create_async_engine(settings.database_url)
```

## References

- `services/api/app/core/config.py` — `database_url` setting
- `services/api/migrations/env.py:70-79` — only existing engine-construction code
- `services/api/app/api/activities.py:11-18` — pagination bounds reserved for the future query
- `.claude/rules/performance-baseline.md` — pagination / no N+1 requirement
- `docs/adr/0002-system-architecture.md` — State & data (Postgres primary datastore, no cache layer yet)

## Data access & migrations

Schema is defined solely through Alembic migrations (none written yet — see alembic-patterns). No SQLAlchemy ORM models module exists. When one is added: follow SQLAlchemy 2.0 declarative style (`sqlalchemy>=2.0` pinned, `pyproject.toml:12`) and wire its `Base.metadata` into `migrations/env.py:25` (currently `target_metadata = None`) so `--autogenerate` becomes usable.

## Security (stack-specific)

DB credentials flow only through the `DATABASE_URL` env var, never hardcoded in source (`app/core/config.py:11` default is the local-dev placeholder `postgres:postgres`, matching `.env.example:3`). `.env` is gitignored at the repo root (`.gitignore:40-42`); only `.env.example` (placeholder values) is committed. Real deploys must override `DATABASE_URL` via env/secret store, per `.claude/rules/security-baseline.md` ("Secrets live in env vars or the project's secret store; never committed to git").
