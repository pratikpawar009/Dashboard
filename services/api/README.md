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

## Auth

`/auth/*` routes (Keycloak OIDC + dev-bypass) live in `app/auth/`; the bearer-JWT verification dependency is `app/core/auth.py::get_current_user`. Root [README.md](../../README.md) has the full `/auth/*` route table and the per-variable env defaults — this section covers only how to run the two auth paths locally.

### Booting with real Keycloak auth

`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_ISSUER` (see root README's Environment variables table for defaults) must ALL be set for `/auth/login`, `/auth/callback`, and `/auth/refresh` to work. While any one is unset or empty, those three routes return `501 {"error": {"code": "http_501", "message": "oidc_not_configured", ...}}` — the app still boots normally, it never crashes on incomplete OIDC config. `services/api/.env.example` ships `OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET` empty on purpose, so a plain `cp .env.example .env` reproduces this default-disabled state.

### Signing in locally via dev-bypass (no live IdP required)

`POST /auth/dev-bypass` issues a token through the same `{access_token, refresh_token, expires_in}` shape as `/auth/callback`, without contacting Keycloak at all. `role`, `email`, and `programs` are optional overrides:

```bash
curl -s -X POST http://localhost:8000/auth/dev-bypass \
  -H "Content-Type: application/json" \
  -d '{"role": "admin", "email": "dev@example.com", "programs": ["alpha", "beta"]}'
# -> {"access_token": "<jwt>", "refresh_token": "<jwt>", "expires_in": 3600}
```

No route in this story requires `get_current_user` yet (AUTH-01 delivers the dependency; AUTH-02/03/04 and later endpoints consume it), so there is no shipped protected route to demonstrate against today. Once one exists, use the returned `access_token` the same way against it:

```bash
curl -s http://localhost:8000/<protected-route> \
  -H "Authorization: Bearer <access_token>"
```

The token is only verifiable against the *same running process* that issued it — see "Why this works locally" below.

### The gate is fail-closed, not "disabled in production"

`/auth/dev-bypass` is registered at all only when `ENVIRONMENT` (normalized to lowercase) is one of `local`, `development`, `dev`, `test`, `ci` — this is an allow-list. Every other value, including `production`, `prod`, `staging`, and any typo, leaves the route unregistered, so it 404s via routing itself, before any handler code runs. This is deliberately not a `!= "production"` deny-check: a deny-check fails *open* on anything it wasn't written to anticipate (an abbreviation, a typo, an unnamed real environment); the allow-list fails *closed* on the same unanticipated input by design.

### Why the dev-bypass token actually works locally

The token is signed by an ephemeral RSA keypair generated once per process, at first use, and never persisted (`app/auth/jwks.py`). `get_current_user`'s JWKS cache resolves that key's `kid` only when `dev_bypass_enabled` is true — the same allow-list gating router registration — so verification stays on the one JWKS path with no branch added to `get_current_user` itself. Two consequences follow directly:

- **Tokens do not survive a process restart** — a fresh keypair is generated on every `uvicorn` start, so a token issued by a previous run will not verify against a new one.
- **The same token is rejected (401) in production** — the signing key is process-local and the `kid` never resolves outside an allow-listed environment, by design.
- **Each worker holds its own key** — under `uvicorn --workers N`, gunicorn, or several API instances, a token 401s on any worker that did not mint it. The `Dockerfile` runs a single uvicorn process, so this only bites if you add workers yourself.

## Persona resolution

`app.state.persona_resolver` (`app/core/persona_resolver.py`) maps a session's Keycloak `role` to one
of five personas — `cio`, `architect`, `developer`, `product-manager`, `engineering-manager` — through
three sources. Env var names and defaults are in the root `README.md` § Environment variables; this
section is the operational side only.

### Changing a mapping

Precedence is Tier-1 → Tier-2 → Tier-3; the first tier holding the role wins. Only Tier-3 is
editable on a running service.

| Tier | Source | To take effect |
|---|---|---|
| 1 | `PERSONA_ROLE_MAP` env var (JSON object) | **Restart** |
| 2 | `services/api/config/persona_role_map.yaml` | **Restart** — loaded once at boot, no hot-reload (D-02) |
| 3 | Postgres `persona_config` table | **No restart** — picked up within the 5-minute TTL |

That asymmetry is the thing to remember on call: to change a mapping without a deploy, write it to
`persona_config`. Editing the YAML on a live box does nothing until the process is restarted.

### The service will not start

**Symptom** — `uvicorn` exits non-zero and the boot traceback ends in `FileNotFoundError` or
`yaml.YAMLError` inside `PersonaResolver.__init__`.

**Cause** — `services/api/config/persona_role_map.yaml` is missing or malformed. `create_app()`
constructs the resolver synchronously with no try/except, so a bad Tier-2 file stops the process
(D-02/D-07). This is deliberate fail-closed behaviour, not a crash to work around.

**Fix** — restore the file. An empty mapping is valid and must be written as `{}`; a zero-byte file
parses to `None` and will not do.

### A user cannot reach any dashboard

**`PersonaNotFoundError`** — the role resolved to no persona in any of the three tiers. The resolver
never falls back to a default (AC-4), so such a user reaches nothing. Add the mapping to whichever
tier is appropriate: Tier-3 for a live fix, Tier-1/2 for a deployed one.

Note the empty-role case: AUTH-01 hands over `role == ""` when every role on the token is a Keycloak
system role (`default-roles-*`, `offline_access`, `uma_authorization`). That surfaces here as an
ordinary `PersonaNotFoundError` with an empty role, and the real fix is in Keycloak group
configuration, not in a persona mapping.

**`PersonaResolutionError`** — a different failure, and a different fix path: Tier-3 itself is in
trouble. The Postgres query timed out at 3.0s or the database is unreachable. Check database health;
do not add mappings.

### Reading the logs

Every `resolve()` call that returns a persona emits `persona_mapping_loaded` at INFO with
`{role, persona, tier, timestamp}` and no user context. `tier` is one of `tier-1-env`,
`tier-2-yaml`, `tier-3-postgres` and tells you which source the answer actually came from.

A **fresh** Tier-3 resolution carries one extra field, `tier3_latency_ms` — the measured query time.
That is the field to alert on; the documented threshold is p95 > 200ms. Because only fresh queries
carry it, its p95 is not diluted by cached reads.

Two things that mislead if you don't know them:

- A warm cache hit **also** emits the event, reusing the tier recorded when the value was first
  resolved. So the event is per-call, and a `tier-3-postgres` line is not proof that a query just
  ran — the presence of `tier3_latency_ms` is. A `tier-3-postgres` event without it is a cache hit.
- Nothing is logged when the resolver raises — an absent event is the signal for a rejected user, not
  an error line.

### A mapping change did not take effect

The cache is per-role, 5-minute TTL, and **per process**. Under multiple workers or multiple API
instances each holds its own cache, so different requests can legitimately return the old and new
mapping for up to the TTL window after a Tier-3 edit. Wait out the five minutes, or restart to flush
every cache at once.

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
