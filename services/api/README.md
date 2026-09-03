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

## Ingest token auth

`app/core/ingest_auth.py` is service-internal only, like Rollup rebuild above — no HTTP route consumes it yet (ING-02 wires the first `/ingest/*` route). `scripts/mint_ingest_token.py` is the only way to issue a credential today.

```bash
cd services/api
uv run python scripts/mint_ingest_token.py --label "ci-pipeline" --user-email ops@example.com --program-ids alpha,beta
# -> prints the raw token to stdout exactly once, and only after the DB commit succeeds
```

- **`--label` and `--user-email` are required; `--program-ids` is optional.** **Omitting** it produces `allowed_program_ids=[]`, which is **allow-all** — the token is valid for every program, not none. This is the deliberate, accepted default (ADR-0006 §3 / § Consequences), not a bug: pass an explicit comma-separated id list, or the literal `"*"`, to scope it.
- **`--program-ids` values are trimmed** — `"alpha, beta"` stores `["alpha", "beta"]`, and empty elements between commas are dropped. A value that is supplied but collapses to nothing after trimming (`" "`, `","`) is a **usage error**: non-zero exit, no row written, no token printed. Only omitting the flag reaches the allow-all default, so a typo cannot silently mint an unscoped token (DECISIONS.md D-05a, amending D-05).
- **Printed once, stored hashed.** The raw `hrn_pat_...` token reaches stdout exactly once and is never logged or stored; only `hashlib.sha256(raw).hexdigest()` is persisted, in `ingest_tokens.token_hash`. Lose it and mint a new one — there is no way to recover or redisplay it.
- **`expires_at` defaults to null — the token never expires.** Revocation via `revoked_at` is the only containment mechanism (ADR-0006 §4). No revoke command ships in this story; that is ING-03's scope.
- **Set `DATABASE_URL` deliberately before minting.** A live local Postgres answers on `Settings.database_url`'s default (`localhost:5432/dashboard`) — running the script with `DATABASE_URL` unset writes a real row into the dev database instead of failing.

### Bearer contract

Callers present the token the same way as a session JWT — `Authorization: Bearer <raw-token>` — but against a separate dependency, `app.core.ingest_auth.get_ingest_token(program_id, ...)`, which never imports or shares state with `app/core/auth.py::get_current_user` (structural isolation, FR-6). `program_id` is an ordinary route parameter FastAPI resolves independently — never read off the token itself.

| Outcome | Status | `detail` | Cause |
|---|---|---|---|
| Authorized | — | — | header present, hash matches an active row, program in scope |
| Missing/malformed header | 401 | `missing` | no `Authorization` header, or not a Bearer scheme |
| Unknown token | 401 | `unknown` | hash matches no row |
| Revoked | 401 | `revoked` | `revoked_at` is set |
| Expired | 401 | `expired` | `expires_at` is set and in the past |
| Out of scope | 403 | `scope` | `allowed_program_ids` is non-empty, has no `"*"`, and excludes the requested `program_id` |

No route declares `Depends(get_ingest_token)` yet — this story ships the dependency only.

## RBAC checks

`app/core/rbac.py` is a pure in-process authorization library — five async check functions, no route surface of its own. Each of 16 downstream stories (AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06) imports directly, e.g. `from app.core.rbac import org_access`; full contract at `docs/requirements/auth.md#rbac-checks`.

```python
async def org_access(current_user: CurrentUser) -> None
async def program_visibility(current_user: CurrentUser, program_id: str) -> None
async def individual_usage_visibility(current_user: CurrentUser, target_user_id: str) -> None
async def member_in_program_visibility(current_user: CurrentUser, program_id: str, target_member_id: str) -> None
async def governance_visibility(current_user: CurrentUser, program_id: str | None = None) -> None
```

Every check either returns `None` (authorized) or raises `HTTPException(status_code=403)` (denied) — never a bool, never a 5xx for a denial.

### The five checks

| Check | Passes when | Denies when |
|---|---|---|
| `org_access` | persona == `cio` | any other persona |
| `program_visibility` | always — any authenticated session, any `program_id` | never (see veto-gate caveat below) |
| `individual_usage_visibility` | `target_user_id == current_user.user_id` (self, no persona resolution), or persona == `cio` | neither self nor `cio` |
| `member_in_program_visibility` | `program_visibility` passes AND (`target_member_id == current_user.user_id` or persona == `cio`) | `program_visibility` denies, or neither self nor `cio` |
| `governance_visibility` | persona in `{architect, product-manager, developer}` AND (`program_id` omitted or `program_visibility` passes) | persona not in that set, or the `program_visibility` cascade denies |

### Cascade order — deliberately opposite nestings

`member_in_program_visibility` calls `program_visibility` **first**, before self-or-cio is evaluated — a `program_visibility` denial propagates immediately even when `target_member_id == current_user.user_id`.

`governance_visibility` evaluates its persona gate **first**; only when that passes and a `program_id` was supplied does it call `program_visibility` — a persona denial never reaches the cascade. Both orders are AUTH-03-FR-4's explicit, tested requirement, not an inconsistency to reconcile.

### The four log events

| Event | Fields | Logged on |
|---|---|---|
| `rbac_check_org_access` | `{user_id, persona, outcome, timestamp}` | authorized + denied |
| `rbac_check_governance_visibility` | `{user_id, persona, outcome, timestamp}` | authorized + denied |
| `individual_view_denied` | `{user_id, target_user_id, outcome, timestamp}` | denied only |
| `member_view_denied` | `{user_id, program_id, target_member_id, outcome, timestamp}` | denied only |

`outcome` is always the literal string `"authorized"` or `"denied"` — never a boolean. No event ever carries `email`, `groups`, a JWT claim, session id, or request path. `program_visibility` emits no event of its own — the open-aggregate check has no denial branch to log.

`persona` is the one optional field, present whenever persona resolution itself succeeded (an authorized outcome, or a denial reached by comparing a resolved persona) and omitted only on the rarer denial where resolution itself failed.

### Fail-closed on resolver failure

Both of the persona resolver's failure modes deny with `HTTPException(403)` — zero default-permit, ever — but at different log levels:

| Exception | Meaning | Log level |
|---|---|---|
| `PersonaNotFoundError` | routine — role unmapped in all three tiers | `logging.INFO` |
| `PersonaResolutionError` | operational failure — Tier-3 Postgres timeout/connectivity | `logging.ERROR` |

This is the single most useful fact for debugging a 403 storm: **a transient Postgres failure presents to the client as an ordinary permissions error and does not invite a retry.** The two exceptions are caught in separate `except` clauses at every call site that resolves persona (`org_access`, `individual_usage_visibility`'s non-self branch, `member_in_program_visibility`'s non-self branch, `governance_visibility`) — never a bare `except Exception`, and never a 500 for either failure mode.

### `program_visibility` is a veto gate, not a roster source

Any authenticated session passes `program_visibility` for any `program_id` — it never reads `current_user.programs` and never branches on `program_id`. A passing call is **not** an affirmative "this program is in my list"; a consumer needing a roster answer must read `CurrentUser.programs` directly. This open-aggregate model (R-003) remains **OPEN**, flagged for `/arh-security-review` — not accepted or closed by AUTH-03.

### Wiring the persona resolver

`create_app()` calls `rbac.configure(app.state.persona_resolver)` immediately after constructing the resolver. Without that call, every persona-resolving check raises `RuntimeError("rbac.configure() was never called")` at first use — deliberately loud, not a silent default-permit.

### Consumers

The checks have no route surface of their own. Each consuming story imports directly (`from app.core.rbac import org_access`); route wiring is out of AUTH-03's scope by design.

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

## Freshness accessor

`app/services/freshness.py` is service-layer only — no HTTP route, like Rollup rebuild and Ingest token auth above.

```python
class FreshnessAccessor:
    def __init__(
        self, *, session_factory: async_sessionmaker[AsyncSession] | None = None
    ) -> None: ...  # defaults to app.core.db.SessionLocal
    async def get_last_successful_run(self) -> datetime: ...
```

- **Returns a raw, timezone-aware `datetime`** — not a pre-formatted display string. No consumer should assume pre-formatted output; whichever story adds a display element owns its own formatting.
- **Construction** — each downstream dashboard-composition story (OVW-01, ARC-01, DEV-01, PMD-01, EMD-01) owns constructing/sharing its own instance; BED-04 wires no `app.state` singleton, since no route consumes it yet.
- **300s TTL, expiry is the only invalidating event** — the writer is out-of-process (CLI ingester / MCP push) and cannot invalidate an in-process cache, so the TTL length is the worst-case apparent staleness. Same cache shape as Persona resolution above; see that section for the TTL-matching rationale.
- **Row absent** — raises `HTTPException(status_code=500, detail="ingestion job may not have run yet")` and emits a `logger.warning()` on every such call. Never negative-cached: the outcome is not stored, so every call re-queries while the row stays absent.
- **3.0s read timeout** — the read is bounded by an explicit `asyncio.wait_for(..., timeout=3.0)`, matching Persona resolution's Tier-3 bound above. On timeout, raises `HTTPException(status_code=500, detail="ingestion freshness query timed out")` and emits a `logger.warning()` — never negative-cached, same as the row-absent case.
- **No writer exists yet** — nothing writes `system_metadata.last_successful_run_at` (ING-01 added ingest-token minting and bearer auth only), so the accessor currently raises against any database that hasn't been seeded by hand.

Full contract: `docs/requirements/api.md#freshness-api`.

Not wired into any route yet — wiring is each consumer story's own scope.
