# services/api

FastAPI backend. See root [README.md](../../README.md) for getting-started commands.

## Database setup

Run migrations before the first API boot:

```bash
cd services/api && uv run alembic upgrade head
```

Connection string is read from `DATABASE_URL` (`.env`, see `.env.example`), sourced via `app.core.config.Settings.database_url`. Default local value:

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/dashboard
```

Only start `uvicorn app.main:app` after migrations are applied.

## Session factory

`app/core/db.py` builds the engine + session factory once, at import time:

```python
engine = create_async_engine(settings.database_url)          # module-level, process-wide singleton
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
async def get_db() -> AsyncIterator[AsyncSession]: ...       # FastAPI Depends() provider
```

`app/main.py` imports `engine` at module level and disposes it in an `@app.on_event("shutdown")` handler. Every DB-touching module must inject a session via `get_db()`; never construct a second engine.

## Rollup rebuild

`app/services/rollup_rebuild.py` is service-layer only — no HTTP route. Callers (ING-02/ING-06) invoke it directly.

```python
async def rebuild_program_rollups(session: AsyncSession, program_id: str) -> RebuildResult   # 7 program-scoped tables
async def rebuild_org_rollups(session: AsyncSession) -> RebuildResult                        # 3 org-scoped tables
```

- **Full replace** — each call DELETEs the scope's rows and re-INSERTs from `usage_events`. Program scope is bounded to `program_id`; other programs are untouched.
- **Transaction scope** — each call wraps its own tables in one transaction. The two scopes are never combined into a single cross-scope transaction.
- **Idempotent**, precisely — re-running over an unchanged `usage_events` set reproduces identical business-value columns. Excludes `id` (fresh `uuid4()` on every INSERT) and `as_of_timestamp`/`created_at`/`updated_at` (set to "now" on every rebuild): idempotency does not mean byte-identical rows.

## Shared modules

`app/dependencies/`, `app/services/`, `app/utils/` are the shared layer for router-facing derived values. Reach for these instead of re-implementing range/pagination/rollup/format logic per router — 13 downstream stories (OVW-01..04, PGD-01..06, SHP-02..06) depend on them behaving identically.

- `dependencies/` — FastAPI `Depends()` providers: `range.validate_range` / `range.range_to_start`, `pagination.get_offset_limit` / `pagination.get_page_params`.
- `services/` — pure, DB-session-free derived-value computation over pre-fetched ORM rows: `rollup_compute.*`, `guardrail_compute.compute_guardrail_summary`.
- `utils/` — `format.format_number` / `format.format_duration`. Backend is the single formatting layer; there is deliberately no frontend equivalent.

Two rules are easy to violate, and a router that re-implements either one breaks cross-story consistency silently:

- **400, not 422** — an invalid `range` must fail through `validate_range`'s `HTTPException(400, ...)`, routed through `app/core/errors.py`'s existing envelope, not FastAPI's default Pydantic 422.
- **Clamp, never reject** — both pagination helpers clamp (`limit`→50, `page_size`→100) instead of raising.

Full signatures and the authoritative contract: `docs/requirements/api.md#api-conventions`.

None of these are wired into any route yet — wiring is each consumer story's own scope. Not wired ≠ dead code.
