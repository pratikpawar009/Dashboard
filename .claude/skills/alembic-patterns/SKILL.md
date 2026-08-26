---
name: alembic-patterns
description: alembic patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing alembic code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# alembic Patterns

<!-- Harness scaffold: stack=alembic — STRUCTURE only; -->
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

- Single Alembic environment at `services/api/migrations/` (`script_location = %(here)s/migrations`, `alembic.ini:8`) — not the tool's default `alembic/` dir name.
- `env.py` uses a SQLAlchemy 2.0 **async** engine — `async_engine_from_config(..., poolclass=pool.NullPool)` driven via `asyncio.run(run_async_migrations())` (`migrations/env.py:64-79,82-85`), matching the async psycopg3 stack.
- `sqlalchemy.url` is not read from `alembic.ini`'s static value — `env.py` overrides it at runtime from `app.core.config.settings.database_url` (`migrations/env.py:20`), so the app's `.env`/`Settings` is the single source of truth for the DB URL, not `alembic.ini:89`.
- `target_metadata = None` today (`migrations/env.py:25`) — no ORM `Base`/models module exists yet, so `--autogenerate` has nothing to diff. Migrations must be hand-written until a models module is added and its `Base.metadata` is wired in.
- New revisions render from `migrations/script.py.mako`: revision id, `down_revision` chain, and both `upgrade()`/`downgrade()` functions are always present (mako only defaults a function body to `pass` when there are no ops to emit — don't leave a real schema change's `downgrade()` as `pass`).
- No `migrations/versions/` directory exists yet — no migration has been written; the first one creates that directory.

## Project structure

- `services/api/alembic.ini` — top-level config; `script_location` points at `migrations/`.
- `services/api/migrations/env.py` — runtime wiring: async engine, settings-sourced URL, offline/online migration functions.
- `services/api/migrations/script.py.mako` — template for new revision files.
- `services/api/migrations/versions/` — individual revision files (not yet created).

## Layering & dependency rules

- `migrations/env.py` imports `app.core.config.settings` only — it must not import `app.api.*` routers or `app.schemas.*` request/response models; migrations operate on raw `sqlalchemy`/`alembic.op` DDL, not Pydantic schemas.
- Once an ORM models module exists, only `migrations/env.py` should import its `Base.metadata` for autogenerate — application code (routers, services) must never import migration scripts.

## Error handling

- Migrations fail loudly: `do_run_migrations`/`run_migrations_offline` both wrap `context.run_migrations()` in `context.begin_transaction()` (`migrations/env.py:53-54,60-61`) — a failed migration rolls back rather than being caught and continued.
- No try/except-and-continue exists anywhere in `env.py` — an upgrade error must stop the run, matching `.claude/rules/performance-baseline.md`'s "no silent infinite waits" spirit (fail fast, don't mask).

## Anti-patterns

- Hand-editing `sqlalchemy.url` in `alembic.ini` expecting it to take effect — it's overridden by `env.py` from `Settings` every run (`alembic.ini:89-90`, `migrations/env.py:20`).
- Writing a migration with an empty/no-op `downgrade()` when the `upgrade()` performs real schema changes — only leave it `pass` when the change is genuinely irreversible, and say so in the migration docstring.
- Expecting `--autogenerate` to detect model changes today — it can't while `target_metadata = None` (`migrations/env.py:25`); until a models module lands, migrations are hand-written.

## Examples

BAD — assuming alembic.ini's URL is authoritative:
```ini
# alembic.ini — editing this does nothing; env.py overrides it at runtime
sqlalchemy.url = postgresql://prod-host/dashboard
```

GOOD — the real override point (migrations/env.py:20):
```python
config.set_main_option("sqlalchemy.url", settings.database_url)
```

## References

- `services/api/alembic.ini`
- `services/api/migrations/env.py`
- `services/api/migrations/script.py.mako`
- `docs/config/project-commands.yaml` — `Migrate: cd services/api && uv run alembic upgrade head`
- `docs/adr/0002-system-architecture.md` — State & data (Postgres + Alembic owns migrations)

## Data access & migrations

Commands (`docs/config/stack-smoke.md`): `cd services/api && uv run alembic upgrade head` to migrate; `uv run alembic revision --autogenerate -m "<msg>"` once a models module exists, otherwise hand-write the revision body against `migrations/script.py.mako`. File naming follows Alembic's default `%%(rev)s_%%(slug)s` (`alembic.ini:10` comment, not overridden). Transaction boundaries are per-migration via `context.begin_transaction()` (`migrations/env.py:53,60`); no multi-migration transaction grouping is configured.

## Dependency, build & CI

`alembic>=1.13` pinned in `pyproject.toml:13`, run through `uv run alembic ...` (never a bare `alembic` — `uv` manages the venv/lockfile, `uv.lock`). No CI pipeline invokes migrations yet (`CI: none` per `CLAUDE.md`) — `alembic upgrade head` is a manual/preflight step (`docs/config/project-commands.yaml` `preflight:` does not yet include it).
