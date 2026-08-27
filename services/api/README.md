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
