---
name: fastapi-patterns
description: fastapi patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing fastapi code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# fastapi Patterns

<!-- Harness scaffold: stack=fastapi — STRUCTURE only; -->
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

- One `APIRouter` per resource under `app/api/<resource>.py`, exporting `router`; assembled in fixed order (health, ingest, activities) via `app.include_router(...)` in `app/main.py:16-18`.
- Route handlers are thin async functions named `<verb>_<noun>` (`ingest_event`, `list_activities` — `app/api/ingest.py:30`, `app/api/activities.py:16`); business logic is not yet layered out into services (see Anti-patterns).
- Query params get inline `fastapi.Query(...)` bounds, not hand validation (`app/api/activities.py:17-18`).
- App-wide config is one `settings` singleton imported from `app.core.config`, never re-instantiated per request (`app/core/config.py:15`).
- `configure_logging()` runs once at import time in `app/main.py:10`, before the `FastAPI()` app is constructed.

## Project structure

- `app/main.py` — assembles the app: logging config, `FastAPI()`, exception handlers, router includes. No route logic here.
- `app/api/` — one module per resource: `health.py`, `ingest.py`, `activities.py`, each exporting a single `router`.
- `app/core/` — cross-cutting concerns: `config.py` (Settings), `errors.py` (exception handlers), `logging.py`, `retry.py`, `auth.py` (seam only).
- `app/schemas/` — Pydantic request/response models (`schemas/activity.py`).
- No `app/models/`, `app/db/`, or `app/services/` yet — persistence and business-logic layers are unbuilt (`app/api/ingest.py:19`, `app/api/activities.py:20` both `TODO(implementation)`).

## Layering & dependency rules

- `app.main` imports only from `app.api.*` and `app.core.*`.
- `app.api.*` (routers) may import `app.core.*` and `app.schemas.*`; router modules must not import each other.
- `app.core.*` must not import `app.api.*` or `app.schemas.*` (exception: `logging.py` imports `core.config`).
- `app.schemas.*` has no internal project dependencies — pure Pydantic leaf modules.
- No ORM/DB layer exists yet; when added, routers must go through a data-access seam, not raw SQL (see postgres-patterns).

## Error handling

- Single envelope for every error response: `{"error": {"code", "message", "details"}}`, built by `error_body()` in `app/core/errors.py:9-10`.
- `register_exception_handlers(app)` wires exactly three handlers (`app/core/errors.py:14-33`): `StarletteHTTPException` → `http_{status_code}`; `RequestValidationError` → 422 `validation_error` with `exc.errors()` as `details`; catch-all `Exception` → 500 `internal_error` with no internal detail leaked.
- Routers raise `HTTPException` or rely on Pydantic validation and let it propagate — no route catches and reshapes its own error body.
- No stack traces or internal identifiers reach the client, per `.claude/rules/security-baseline.md` ("Errors shown to end users contain no stack traces or internal identifiers").

## Anti-patterns

- Returning an ad hoc error dict from a route instead of raising and letting the registered handlers build the envelope — breaks the single error shape (`app/core/errors.py`).
- An unbounded or manually-looped retry — only `retry_with_backoff` (bounded, jittered) is allowed on I/O paths, per `.claude/rules/performance-baseline.md` (`app/core/retry.py`).
- A list endpoint without `page`/`page_size` `Query` bounds — every list endpoint needs a default and max page size (`app/api/activities.py:11-18` is the reference; performance-baseline.md).
- Treating `get_current_user()`'s current HTTP 501 as working auth, or building authorization logic on top of it before an OIDC provider is chosen (`app/core/auth.py:20-24`).

## Examples

BAD — swallowing and reshaping an error instead of letting the handler build the envelope:
```python
try:
    ...
except Exception as e:
    return {"error": str(e)}  # bypasses register_exception_handlers
```

GOOD — raise and let the registered handler produce the envelope (app/core/errors.py:28-33):
```python
if not found:
    raise HTTPException(status_code=404, detail="not_found")
# -> {"error": {"code": "http_404", "message": "not_found", "details": null}}
```

## References

- `services/api/app/main.py` — app assembly / router include order
- `services/api/app/core/errors.py` — error envelope + handler registration
- `services/api/app/core/retry.py` — bounded retry pattern
- `services/api/app/core/auth.py` — OIDC seam (stub, HTTP 501)
- `docs/adr/0002-system-architecture.md` — Interfaces & contracts, Operability decisions
- `.claude/rules/performance-baseline.md`, `.claude/rules/security-baseline.md`

## API / interface contracts

REST over HTTP; FastAPI's auto-generated OpenAPI schema is the contract source of truth (ADR-0002: Interfaces & contracts). Resource-prefixed routers (`/health`, `/ingest/events`, `/activities`). Paginated list responses use the envelope `{"items", "page", "page_size", "total"}` (`app/api/activities.py:21`). No API versioning prefix (e.g. `/v1`) exists yet — undecided, not yet a convention to follow.

## Security (stack-specific)

`app/core/auth.py`'s `get_current_user()` is a placeholder dependency seam that always raises HTTP 501 (`auth.py:20-24`) — no route currently declares `Depends(get_current_user)` (confirmed: no such usage in `app/api/*.py`). The OIDC/SSO provider is unspecified (ADR-0002 flagged gap, `[NEEDS CLARIFICATION]`). Do not build RBAC/authorization logic against this stub — wait for a provider decision, then wire real claims into `CurrentUser` (`auth.py:12-17`) without changing the dependency's call signature.

## Logging, config & observability

Structured JSON logs: `JSONFormatter` emits `{timestamp, level, logger, message, exc_info?}` to stdout (`app/core/logging.py:11-21`), configured once via `configure_logging()` before app construction (`app/main.py:10`). Log level is env-driven through `settings.log_level` (`LOG_LEVEL` in `.env`, default `INFO` — `app/core/config.py:12`, `.env.example:4`). No APM/tracing vendor chosen (ADR-0002 flagged gap) — logs are the only observability signal today.

## Dependency, build & CI

Package manager: `uv`, lockfile `services/api/uv.lock` committed. Lint/format: `ruff` (`line-length=100`, `target-version=py311`, `select=["E","F","I","UP"]` — `pyproject.toml:26-31`). Types: `mypy` with `disallow_untyped_defs = false` (lenient — `pyproject.toml:33-36`). Commands are recorded in `docs/config/project-commands.yaml` (`uv run ruff check .`, `uv run mypy .`, `uv run pytest`). CI provider is `none` (`CLAUDE.md` Integrations) — these checks run locally/preflight only, not in a pipeline yet.
