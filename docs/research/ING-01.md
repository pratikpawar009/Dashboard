# Research Assessment: ING-01 — Ingest token minting + bearer auth

**Story ID**: ING-01  
**Epic**: ING  
**Priority**: P1  
**Size**: M  
**Upstream dependencies**: BED-01 via `db-schema` contract (ingest_tokens table exists)  
**Downstream dependencies**: ING-02, ING-03, ING-07 consume the `ingest-token-auth` contract; ING-04/05/06/09 depend transitively (7 stories on this contract)  
**Assessment Date**: 2026-08-31  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**BED-01 (complete, PR #110 merged)** provides the `ingest_tokens` table via `docs/requirements/data.md`:
- **Table shape** (verified in `services/api/app/models/ingestion.py:62-80`): id (String PK, uuid4), token_hash (String, unique, SHA-256 hex 64 chars), label (String), user_email (String, indexed), allowed_program_ids (ARRAY(String) or wildcard "*"), expires_at (DateTime nullable), revoked_at (DateTime nullable), last_used_at (DateTime nullable).
- **Constraint**: unique index on token_hash; index on user_email.
- **Security invariant**: no raw token column ever added (SECURITY CRITICAL comment in model).
- **Status**: Model exists and is integrated into `app/models/ingestion.py`; Alembic migration (`001_initial_schema.py`) created the table.

**No blockers from BED-01.** The schema is present, typed correctly, and production-ready.

**Design contract**: `docs/design/schema.json` § features maps dashboard epics to mockups (OVW, PGD, EMD, ARC, DEV, PMD). **ING epic is NOT listed** — this is a backend auth/ingestion story with no UI surface. Setting `design: n/a` is correct per CLAUDE.md § Design system rule (backend-only stories exempt).

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (feature/ING-01 branch, clean)
- **Upstream**: BED-01 (complete), AUTH-01 (complete), AUTH-02 (complete), AUTH-03 (security-review), AUTH-04 (review) are all merged to origin/main
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, Alembic 1.13, psycopg3, pytest + pytest-asyncio

### Auth Landscape (Existing Patterns)

**Existing Auth Paths:**
- **User Session (AUTH-01)**: Keycloak OIDC → bearer JWT (no server session store, stateless per-request JWKS validation via `app.auth.jwks.JwksCache`). Dependency seam: `Depends(get_current_user)` returns `CurrentUser(user_id, email, role, groups, programs)` (`app/core/auth.py:57-72`).
- **RBAC Checks (AUTH-03)**: Five async checks (`org_access`, `program_visibility`, `individual_usage_visibility`, `member_in_program_visibility`, `governance_visibility`) gated on `CurrentUser`, resolving persona via `PersonaResolver` (AUTH-02). Fail-closed: denials raise `HTTPException(403)` or `401`; no default-permit paths (`app/core/rbac.py`).
- **Dev-bypass (AUTH-01-AC-8)**: Ephemeral in-process JWKS key, allowed only in non-production environments (environment allowlist: {local, development, dev, test, ci}). Registered conditionally at `app.main.create_app()` via `if cfg.dev_bypass_enabled`.

**Security Baseline (`.claude/rules/security-baseline.md`):**
- No raw tokens/credentials in logs (log user_id/resource_id, not email/token).
- Trust-boundary validation on all inbound HTTP (Pydantic schemas enforce this).
- Errors show no stack traces or internal identifiers.
- Secrets in env vars only; never committed.

**Logging Pattern (AUTH-03 precedent):**
- Structured JSON logs via `JSONFormatter` (`app/core/logging.py:11-21`).
- Auth-relevant events (deny/authorize outcomes) logged with per-event field allowlists (e.g., `rbac_check_org_access: {user_id, persona, outcome, timestamp}`; no email or token values ever).

### Ingest Token Landscape

**Model exists (verified):**
```python
class IngestToken(Base):
    __tablename__ = "ingest_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True, ...)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # SHA-256 hex
    label: Mapped[str] = mapped_column(String, nullable=False)
    user_email: Mapped[str] = mapped_column(String, nullable=False)
    allowed_program_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)  # or "*"
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```
(See `services/api/app/models/ingestion.py:62-80`)

**Contract (docs/requirements/auth.md § ingest-token-auth):**
- **Token format**: `hrn_pat_` + 24 random bytes (hex), e.g., `hrn_pat_a1b2c3d4...` (48 hex chars total after prefix)
- **Minting**: prints raw token exactly once, never stored; only SHA-256 hash persists
- **Storage**: token_hash (unique index), label, user_email, allowed_program_ids
- **Auth check**: bearer header → hash lookup → 401 if missing/revoked/expired; program-scope check → 403 if out of scope
- **Scope model**: wildcard "*" means all programs; otherwise array of allowed program IDs

**Acceptance Criteria (story § AC1-5):**
1. CLI mint: label + email + program-id scope (list or "*") → raw token (hrn_pat_ + 48 hex) once, exits 0
2. Row stored: token_hash (SHA-256), label, user_email, allowed_program_ids (no raw token ever)
3. Valid token: hash matches, not revoked (revoked_at null), not expired (expires_at null or future), program_id in allowed set or wildcard → resolve and authorize
4. Invalid token: missing, unknown hash, revoked, or expired → 401
5. Out-of-scope token: valid/active but program_id not in allowed_program_ids and not wildcard → 403

### CLI Tool Investigation

**Current state**: No CLI framework declared in `services/api/pyproject.toml` (searched: no click, argparse in-use, typer, fabric).
- **Candidates**: click (Flask ecosystem standard), typer (modern, Pydantic-native), standard argparse (stdlib)
- **Story does not specify**: AC1 says "CLI mint command runs" but does not name a tool or entry point
- **Entry point**: Where does the mint command live? Options:
  - Standalone script (`services/api/scripts/mint_ingest_token.py` run via `uv run python services/api/scripts/mint_ingest_token.py`)
  - FastAPI CLI command via a plugin (less common, adds framework coupling)
  - Within the existing FastAPI app as a management command (e.g., a FastAPI Typer integration)
  - Admin HTTP endpoint (deferred to ING-02 likely, since story says "CLI")

**RESOLVED 2026-08-31 (ADR-0006 §2)** — a **standalone script using stdlib `argparse`** at
`services/api/scripts/mint_ingest_token.py`, run as `uv run python scripts/mint_ingest_token.py`.
No new dependency; identical behaviour inside and outside the container image (the Dockerfile builds
with `uv sync --no-dev`). Not a Typer plugin, not a management command, not an HTTP endpoint.

### Token Hashing Scheme

**Story specifies**: "token_hash (SHA-256 hex of the raw token)"
- **Algorithm**: SHA-256 (not SHA-1, not bcrypt, not Argon2; story explicitly names SHA-256)
- **Format**: hex digest (64 ASCII characters, not base64)
- **Verification flow**: (1) accept raw token in Authorization header, (2) SHA-256 hash it, (3) query ingest_tokens.token_hash with the hash (unique index → O(1)), (4) if found and not revoked/expired, resolve record

**Implementation concern**: Python's hashlib.sha256 is standard library. Example:
```python
import hashlib
raw_token = "hrn_pat_a1b2c3d4..."
token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
# token_hash is str, 64 hex chars
```
No external hashing library needed (unlike AUTH-02's bcrypt for password hashing).

**No risks**. SHA-256 is cryptographically sound for this use case (token is already 24 random bytes; no need for iterative/salted hashing).

### Auth Path Coexistence

**Two independent bearer-token paths must coexist on the same FastAPI app:**

1. **User JWT auth** (AUTH-01): Authorization: Bearer \<Keycloak-JWT\> → validates signature against Keycloak JWKS cache → returns CurrentUser
2. **Ingest token auth** (ING-01): Authorization: Bearer \<ingest-token-raw\> → hashes token, queries ingest_tokens table → returns token record with program scope

**Critical**: These paths must not interfere. Dependency patterns in FastAPI:
- `Depends(get_current_user)` for user-only routes (e.g., dashboard views)
- `Depends(get_ingest_token)` for ingest-only routes (e.g., POST /ingest/events, ING-02)
- Never both on the same route (they have different principal types: CurrentUser vs IngestTokenRecord)

**Separation model** (verified in app/api/ingest.py:15, app/main.py:79):
- Ingest routes live under `/ingest/` prefix (already established)
- Ingest auth dependency injected independently of user auth
- No route should call both `Depends(get_current_user)` and `Depends(get_ingest_token)` — one auth path per route

**Pattern precedent**: app/core/rbac.py configures its own module-level seam (`rbac.configure()` called once in create_app()) to avoid threading PersonaResolver through every route. ING-01's ingest token dependency can follow a similar pattern: inject a database session or connection pool into the ingest-token checker, configure once at startup.

### Observability / Logging

**Story § NFR-008**: "structured JSON log event `ingest_token_auth_failed` (token id/hash prefix, reason: missing|revoked|expired|scope, program_id, timestamp) on every 401/403 outcome"

**Decision log note**: "ingest_token_auth_failed event name is assumed (source's NFR-011 event list does not name an ingest-token-specific event); added by analogy to existing structured-logging pattern"

**Alignment with AUTH-03 logging** (app/core/rbac.py:329-365):
- Four named events with fixed per-event field allowlists: `rbac_check_org_access`, `rbac_check_governance_visibility`, `individual_view_denied`, `member_view_denied`
- Each emits at `logging.INFO` (authorized/routine-deny) or `logging.ERROR` (operational failure)
- Required fields: `{user_id, outcome, timestamp}`; optional: `{persona}`
- Never logs: email, token, session id

**Ingest token event fields** (inferred from AC4/AC5 outcomes):
- Required: `{token_id_or_hash_prefix, reason, program_id, timestamp}` (reason: "missing" | "revoked" | "expired" | "scope")
- Token id/hash prefix: Store ingest_tokens.id (UUID) or first 8 chars of token_hash (opaque identifier, not the full hash) to avoid accidental raw-token leakage
- User email: NOT included (per .claude/rules/security-baseline.md: no PII in logs)
- Outcome: implicit (all events are denials/failures; no "authorized" variant since ingest token validation succeeding doesn't warrant a logged event per NFR-011 precedent)

**RESOLVED 2026-08-31 — answered by an existing binding rule, no decision required.**
`.claude/rules/security-baseline.md` § Core: *"Never log tokens, passwords, API keys, session ids,
or PII (email, name, ...) at any log level. Log opaque identifiers (`user_id`, `resource_id`)
only."* The rule binds on `**/*.py`, so `user_email` is **forbidden** in the event payload.
Log the `ingest_tokens.id` UUID as the opaque owner identifier instead; an auditor joins to
`user_email` through the table. The raw token and its full hash are likewise excluded — a hash
prefix is a token derivative and adds nothing the row id does not already give.

### Database Access Pattern

**Ingest token lookup** (AC3): bearer hash → query ingest_tokens table → resolve record
- **Index**: unique(token_hash) enables O(1) index lookup
- **Session management**: FastAPI dependency injection; app.core.db.SessionLocal (SQLAlchemy session factory) or async equivalent
- **Pattern precedent**: No service layer exists yet in the codebase (app/api/ingest.py:19 comment says "TODO(implementation): write-through to Postgres via SQLAlchemy session"). Will need to create one (app/services/ingest.py or similar) to keep auth logic separate from route handlers.

**Verification logic** (pseudocode):
```python
async def verify_ingest_token(token: str, session: AsyncSession) -> IngestToken | None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC)
    row = await session.execute(
        select(IngestToken).where(
            IngestToken.token_hash == token_hash,
            IngestToken.revoked_at == None,
            (IngestToken.expires_at == None) | (IngestToken.expires_at > now),
        )
    )
    return row.scalar_one_or_none()
```
This query:
1. Hashes the bearer token
2. Queries the unique index on token_hash
3. Filters out revoked (revoked_at not null)
4. Filters out expired (expires_at <= now)
5. Returns the record if all conditions pass, None otherwise

**Performance**: Index-backed single-row lookup, plus two datetime comparisons (all in SQL) → sub-millisecond latency expected.

### Minting Surface Ambiguity

**Story says** "CLI mint command runs" and AC1 specifies the output format/exit code, but does NOT specify:
- **Entry point**: Is it a standalone Python script? A FastAPI-integrated CLI? A management command?
- **Database write**: Does the CLI use the same database_url env var as the running app? Does it handle migrations?
- **Authentication/authorization for minting**: Who can run the mint command? Is it only accessible to certain roles via an HTTP admin endpoint, or is it a local CLI for ops/developers only? (Story doesn't mention a "mint token" HTTP route, so presumed CLI-only.)
- **Default expiry**: Story AC1 doesn't specify expires_at or revoked_at values for a newly minted token. Assumptions: newly minted tokens are never expired (expires_at null or set to a far-future default like +90 days) and never revoked (revoked_at null). 

**RESOLVED 2026-08-31 (ADR-0006)** —
**(1)** Standalone CLI script, stdlib `argparse` (§2). No HTTP mint route exists in ING-01.
**(2)** Authority to mint is possession of **local shell access plus database credentials** — the
script connects directly via `DATABASE_URL`. Because no network-reachable mint surface exists, there
is no route to gate and no additional authn layer in this story. Anyone who can already reach the
database could insert a row by hand regardless; the script does not widen that boundary.
**(3)** `expires_at` defaults to **null — tokens do not expire** (§4). `revoked_at` is null at mint;
revocation is the containment mechanism. See ADR-0006 § Consequences for the accepted risk this
carries in combination with empty-scope allow-all.

### Test Mapping (Story § Test mapping)

- **E2E**: N/A — no UI surface
- **Unit**: `backend/app/cli/mint_ingest_token.py` (mint command), `backend/app/auth/ingest_token.py` (hash lookup + program-scope check)
  - **Path note**: story says `backend/app/...` but real root is `services/api/app/...` (implementation will use correct path)
  - **Implied modules to create**: mint command implementation + ingest token auth dependency
- **Manual**: N/A

### Preflight & Toolchain

- **Python 3.11+**: available ✓
- **FastAPI, SQLAlchemy, Pydantic, Alembic, psycopg3**: installed ✓
- **Postgres** with ingest_tokens table: available via docker-compose + BED-01 migration ✓
- **CLI framework** (click/typer/argparse): UNDECIDED (not declared in pyproject.toml; story doesn't specify)
- **hashlib.sha256**: Python stdlib, available ✓

---

## Pattern Map

### Existing Code to Extend

- **`app/models/ingestion.py`** — IngestToken model already defined (AC5, NFR-006 security invariant: no raw token column). No extension needed; model is complete.
- **`app/core/config.py`** — extend Settings to add any ingest-token config vars (e.g., token_prefix="hrn_pat_", token_random_bytes=24, default_expiry_days=90). [NEEDS CLARIFICATION on defaults before finalizing.]
- **`app/core/auth.py`** — currently holds `CurrentUser` class and `get_current_user()` for JWT auth. No change needed; ingest token auth lives in a parallel dependency (see "New files" below).
- **`app/core/errors.py`** — no change needed; existing error envelope will catch ingest-token auth failures correctly (401/403 raised by the auth dependency, caught and enveloped by registered handlers).
- **`app/main.py`** — no change needed; ingest routes already registered via `app.include_router(ingest_router)`.
- **`services/api/pyproject.toml`** — add CLI framework if minting is a standalone script (e.g., `typer>=0.12` or `click>=8.1`); undecided pending clarification on mint entry point.

### Existing Patterns to Follow

- **Settings pattern** (`app/core/config.py`): env-sourced via BaseSettings, single module-level `settings` singleton, no re-instantiation per request.
- **Bearer token dependency** (`app/core/auth.py`): HTTPBearer to extract token from Authorization header, then verify and return a principal object (CurrentUser in AUTH-01; will be IngestTokenRecord or similar in ING-01).
- **Auth failure pattern**: raise `HTTPException(status_code=401, detail=_INVALID_TOKEN_DETAIL)` (generic detail per .claude/rules/security-baseline.md: no internal detail leaked); let registered exception handler build the envelope.
- **Logging pattern** (`app/core/rbac.py`): structured JSON events with per-event fixed field allowlists; no PII ever; timestamp, outcome, and opaque identifiers (id/hash prefix, not email/token).
- **Async routes & dependencies** (`fastapi-patterns`): `async def` route handlers; dependencies injected via `Depends()`; no blocking I/O.
- **Separation of concerns** (`fastapi-patterns`): route handlers are thin; business logic (hashing, expiry check, program-scope validation) lives in a service layer or helpers.

### New Files to Create

- **`app/auth/ingest.py`** — ingest token bearer extraction and verification dependency:
  - `async def get_ingest_token(credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer), session: AsyncSession = Depends(...)) -> IngestTokenRecord`
  - Mirrors AUTH-01's `get_current_user()` pattern but returns a different principal type (IngestTokenRecord with id, label, user_email, allowed_program_ids, expires_at, revoked_at, last_used_at)
  - Raises `HTTPException(401)` on missing/invalid/revoked/expired; raises `HTTPException(403)` on program-scope mismatch (if checking at dependency time; alternatively, scope check is deferred to the route handler)

- **`app/schemas/ingest_token.py`** — Pydantic model for ingest token responses (if routes expose it):
  - `IngestTokenRecord(id: str, token_hash: str, label: str, user_email: str, allowed_program_ids: list[str] | str, expires_at: datetime | None, revoked_at: datetime | None, last_used_at: datetime | None)`
  - Or simpler: just return the SQLAlchemy row (if app/schemas/ is reserved for request/response models only, not internal data transfer)

- **`app/services/ingest_token.py`** (or functionality in a helper module) — token verification logic:
  - `async def verify_ingest_token(raw_token: str, session: AsyncSession) -> IngestToken | None` — hash lookup with revocation/expiry checks
  - `async def check_program_scope(token_record: IngestToken, program_id: str) -> None` — raise `HTTPException(403)` if out of scope
  - May also include: `def mint_token() -> tuple[str, str]` returning (raw_token_hrn_pat, token_hash) [used by CLI]

- **`app/cli/mint_ingest_token.py`** (pending clarification on entry point) — CLI command for minting:
  - Signature per AC1: takes label, user_email, program_ids (list or "*"), outputs raw token once, exits 0
  - Uses same `DatabaseURL` / session as the app to persist the IngestToken row
  - [NEEDS CLARIFICATION on CLI framework and authorization model before implementing]

- **`tests/test_ingest_token.py`** (or split into `tests/unit/test_mint.py` + `tests/unit/test_ingest_auth.py`) — unit tests:
  - AC1: mint command output format (hrn_pat_ + 48 hex, exit 0)
  - AC2: token_hash stored (not raw token) with SHA-256 digest
  - AC3/AC4: valid/invalid token verification (missing, unknown hash, revoked, expired)
  - AC5: program-scope enforcement (allowed_program_ids check, wildcard handling)
  - Edge cases: program_ids=["*"] as list vs "*" as string; expires_at in past; revoked_at in past; empty program_ids array

### Shared Code at Risk

- **`services/api/app/models/ingestion.py`** (IngestToken model) — consumed by ING-01 (minting), ING-02 (validation during ingest), ING-03 (token listing/mgmt), ING-07 (token validation). Changes here (e.g., adding a column) ripple to all consumers. Mitigation: keep the model stable after this story; defer new fields to a separate story if needed.
  
- **`services/api/app/core/config.py`** (Settings singleton) — if token config (default TTL, prefix, random bytes) is added here, all consumers read it via the same singleton. Safe if this is the only source of truth; risk if later stories hardcode different assumptions. Mitigation: document the settings in README.md or CLAUDE.md.

- **Database session management** (app/core/db.py + SessionLocal) — ingest token auth dependency will need async session access. If this story or a consumer introduces a new session pooling policy, it may affect other routes. Mitigation: isolate session acquisition to a dependency factory; do not change pooling policy without coordinating with other stories.

- **Error envelope** (app/core/errors.py) — ingest token auth (401/403) is caught by the same exception handler that catches JWT auth errors. If the handler's logic changes (e.g., to emit a different error code for a specific reason), both auth paths may be affected. Mitigation: no change anticipated; the generic HTTP status codes (401/403) are stable.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Domain** | CRITICAL | **Minting surface ambiguous.** Story AC1 specifies CLI mint command output/exit format but does NOT name the CLI framework (click/typer/argparse), entry point (standalone script vs. management command), authorization model (who can mint?), or default token TTL. Without clarity, implementation will guess, risking a wrong surface entirely. | (1a) **Decision required**: Answer — (i) CLI framework (click, typer, or argparse)? (ii) Entry point (standalone `uv run python services/api/scripts/mint.py`, FastAPI-integrated management command, or HTTP admin endpoint)? (iii) Authorization (local-only ops CLI, or role-gated admin endpoint)? (iv) Default expiry (null = never expires, or +90 days / configurable)? (1b) Record in story DECISIONS.md or PRD with explicit answers. (1c) No implementation begins until these are settled. |
| 2 | **Integration** | HIGH | **Two auth paths must coexist without interference.** JWT auth (Keycloak OIDC, AUTH-01) and ingest token auth (ING-01) both use Authorization: Bearer header. If a route incorrectly uses both dependencies (Depends(get_current_user) AND Depends(get_ingest_token)), or if dependency resolution is ambiguous (which one runs first?), auth failures will be hard to debug. | (2a) **Dependency isolation**: Define `get_ingest_token()` as a separate, parallel dependency to `get_current_user()`. Routes under `/ingest/*` use only ingest auth; routes requiring user context use only JWT auth. No route uses both. (2b) **Unit test**: Create a mock route with both dependencies and verify it raises a clear error (or explicitly document it's forbidden). (2c) **Documentation**: Add a comment in app/main.py or auth module explaining the two auth paths and which routes use which. |
| 3 | **Security** | HIGH | **Token representation in logs.** Story says `ingest_token_auth_failed` logs token_id/hash_prefix, but doesn't clarify: (i) include user_email (for audit)? (ii) how much of the hash prefix (8 chars? first 16 chars?)? (iii) is the raw token ever logged anywhere (e.g., during minting or on a debug/dev-bypass path)? Per .claude/rules/security-baseline.md, PII and credentials must never be logged. | (3a) **Field spec**: Define exact event fields: `{token_id (UUID), hash_prefix (first 8 hex chars), reason (enum: missing|revoked|expired|scope), program_id, timestamp}`. Omit user_email, raw token, full hash. (3b) **Audit trail alternative**: If user_email is needed for audit, store it separately (e.g., in a system_metadata event or a separate audit_log table, deferred to a later story). For ING-01, keep `ingest_token_auth_failed` fields minimal and safe. (3c) **Test**: Verify no raw token or email ever appears in logs, even on debug paths. |
| 4 | **Domain** | HIGH | **Scope validation timing (dependency vs. route handler).** AC5 (program-scope check) can happen at two points: (i) in `get_ingest_token()` dependency (requires program_id parameter → dependency signature changes per route's context), or (ii) in the route handler after resolving the token. If done at dependency time, the dependency must be parameterized; if at handler time, the token record is passed and checked inline. Story doesn't specify which. | (4a) **Decision**: Recommend deferring scope check to route handler. `get_ingest_token()` returns the token record (auth check: hash valid, not revoked, not expired). Each route then calls `check_program_scope(token_record, program_id)` to enforce scope. Keeps the dependency signature stable (mirrors AUTH-01's `get_current_user()` which doesn't take program_id). (4b) **ING-02 contract** (docs/requirements/auth.md § ingest-token-auth): "authz: bearer hash lookup -> 401 if missing/revoked/expired; program-scope check -> 403 if target program not in allowed set and no wildcard" — phrasing suggests two checks, not one. (4c) **Test**: Route handler correctly raises 403 on scope mismatch after receiving a valid token. |
| 5 | **Domain** | HIGH | **Wildcard program scope representation.** AC1 says program-id scope is "a list of program ids, or the literal wildcard `\"*\"`". Model has `allowed_program_ids: ARRAY(String)`. How is wildcard stored? (i) Single-element array `["*"]`? (ii) Empty array `[]`? (iii) Special sentinel string in config? Ambiguity will break scope validation logic. | (5a) **Decision required**: Story should clarify wildcard storage. Recommend: allowed_program_ids array can contain "*" as a single element, OR be an array of specific program IDs, OR contain "*" anywhere (any rule; pick one). (5b) **Scope check logic**: `if "*" in token.allowed_program_ids or target_program_id in token.allowed_program_ids: return authorized`, else 403. (5c) **Test**: mint with scope ["*"], verify it matches any program_id; mint with scope ["prog-a", "prog-b"], verify it only matches those two. |
| 6 | **Performance** | MEDIUM | **Token hash lookup latency.** AC3 specifies O(1) index lookup via token_hash unique index, but actual latency depends on (i) database connection pooling (is NullPool from alembic-patterns correct, or does the app need a real pool?), (ii) network round-trip time to Postgres, (iii) query parsing overhead. No explicit latency budget given (story § NFR performance says "assumption"). | (6a) **Baseline measurement**: Implement token verification, measure single-row lookups via the unique index, confirm <10ms latency (and include in validation evidence). (6b) **Connection pooling**: Verify app.core.db uses a real connection pool (not NullPool; NullPool is Alembic-only per alembic-patterns). Default SQLAlchemy async pooling (QueuePool) is suitable for an HTTP API. (6c) **Observability**: Log token validation latency on a sample basis (e.g., every 100th request) so ops can see if degradation occurs. |
| 7 | **Dependency** | MEDIUM | **CLI framework choice and dependency footprint.** If minting is a standalone script using a new CLI framework (click, typer, fabric), the framework adds a new transitive dependency. Risk: (i) CLI framework has its own dependencies (typer depends on Pydantic, click is heavier than stdlib argparse), (ii) version conflicts with existing pins (unlikely but possible), (iii) added complexity for a small CLI. | (7a) **Evaluation**: If CLI is lightweight (label + email + scope input → output token), stdlib argparse is sufficient (no new dependency). If CLI needs structured help/validation, typer (Pydantic-native, clean API) is better than click. (7b) **Decision record**: Document chosen framework in story DECISIONS.md. (7c) **Test**: CLI runs standalone; test both success (valid input) and failure (missing required arg) paths. |
| 8 | **Integration** | MEDIUM | **Logging event field allowlist inconsistency.** Story names `ingest_token_auth_failed` event and gives example fields (token_id, reason, program_id), but AUTH-03-precedent events have fixed required+optional field sets validated at runtime (app/core/rbac.py:315-359). If ING-01's logging doesn't enforce the same contract, a future story may add unexpected fields or omit required ones. | (8a) **Pattern alignment**: Define `_EVENT_REQUIRED_FIELDS["ingest_token_auth_failed"] = frozenset({"token_id", "reason", "program_id"})` and `_EVENT_OPTIONAL_FIELDS["ingest_token_auth_failed"] = frozenset({...})` (if any). Validate at every `_log_event()` call via an assertion, same as RBAC does. (8b) **Test**: Log an ingest_token_auth_failed event; assert field set matches spec; test with missing/extra fields and verify AssertionError is raised. (8c) **Documentation**: Document the event in docs/requirements/auth.md or a new docs/requirements/ingest.md file, alongside the other auth events. |
| 9 | **Domain** | MEDIUM | **Token revision and rotation strategy.** AC1 defines minting a new token but doesn't cover: (i) can a user/ops mint multiple tokens? (ii) can a token be revoked on-demand? (iii) what happens if a token is compromised and leaked? ING-02/03 likely handle listing/revocation, but ING-01 should clarify the min-safe token lifecycle. | (9a) **Assumption**: Multiple tokens per user_email are allowed (e.g., one for CI, one for local dev). No automatic rotation; revocation is manual (via ING-03 likely). ING-01 focus: mint + validate only. (9b) **Carry-forward**: If token rotation or automatic expiry renewal is needed, track as a separate story (e.g., ING-08 "token lifecycle management"). (9c) **Documentation**: Record in story DECISIONS.md or PRD § Assumptions. |
| 10 | **Domain** | LOW | **Prefix collision risk.** Token format is `hrn_pat_` (hardcoded prefix) + 24 random bytes (hex). Risk: if another token system (e.g., GitHub PAT `ghp_` prefix) is later added and a consumer confuses the formats, auth failures will be silent. | (10a) **Mitigation**: Document the prefix in a constants module (`app/core/constants.py` or similar) and reference it everywhere. (10b) **Test**: Verify prefix is never hardcoded inline in multiple places; central constant ensures consistency. (10c) **Future-proofing**: If multiple token systems coexist, add a token_type field to ingest_tokens or prefix-based routing in the auth dependency to clarify which system handles which token. For ING-01, single-system assumption is safe. |

---

## Scoring Rubric (5 Dimensions, 100 points)

| Dimension | Weight | Criterion | Score | Reasoning |
|-----------|--------|-----------|-------|-----------|
| **Integration** | 25% | All upstream dependencies available; failure modes well understood | 75 | BED-01 (db-schema) is complete and integrated. AUTH-01/02/03 auth patterns are mature and well-tested. **Gap**: Minting surface (CLI framework, entry point) is ambiguous; no existing pattern for admin CLI commands in codebase. Dependency injection for ingest token auth is clear but untested. Dependency isolation (JWT vs. ingest token) requires careful routing and testing. Mitigation covers this, but until clarified, 25% uncertainty remains. |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version | 80 | Ingest token auth is a NEW auth path; no existing clients to break compat with. Contract shape (bearer header + 401/403 codes) is stable across HTTP clients (curl, CI systems, webhook tools). **Gap**: No versioning strategy if token format ever changes (e.g., if "hrn_pat_" prefix is ever swapped). Mitigation: treat token_format as immutable for ING-01; future token systems are separate stories. **Upside**: Backend-only service; no frontend version-pinning needed. |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants surfaced | 65 | **Strong**: AC1-5 are concrete and cover common paths (valid token, revoked, expired, scope mismatch). Hashing scheme (SHA-256) is clear. **Gaps**: (i) Wildcard program scope representation (array vs. string) — risk of subtle bugs in scope logic. (ii) Minting surface ambiguous (who mints? where? via what interface?). (iii) Token TTL default unclear (expires_at null forever, or +90 days default?). (iv) Logging event field allowlist not formally spec'd (aligned with AUTH-03 pattern but not enforced). (v) Multi-token-per-user and revocation lifecycle deferred to ING-02/03, but ING-01 should clarify assumptions. Mitigations address these; without them, integration bugs likely. |
| **Performance** | 15% | Story has explicit perf budget; estimated work fits within budget | 75 | **Budget**: AC3 implicitly requires O(1) token lookup (unique index on token_hash) — no explicit ms target, but index-backed queries are sub-millisecond (standard for bearer token validation per HTTP auth patterns). **Gap**: No explicit latency SLA (e.g., p95 < 5ms). Assumption: token validation overhead is negligible compared to downstream business logic (ingest processing). Mitigation: measure baseline during validation phase; if deviation, flag for optimization. **Scope**: Minting (CLI) has no perf constraint; should complete in seconds. No risk here. |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | 85 | **Complete**: BED-01 (schema ✓), AUTH-01/02/03 (auth patterns ✓), Postgres driver (✓), Python stdlib (hashlib ✓). **Gaps**: (i) CLI framework undecided (click/typer/argparse) — no blocker, but deferred clarity costs implementation time. (ii) No existing pattern for admin/management CLI commands in codebase — will require new code path, but not blocked by external work. (iii) Admin auth/RBAC for minting not specified (ING-01 assumes local CLI; if HTTP endpoint, needs RBAC gating — deferred to ING-02 likely). Mitigation: decisions on minting surface resolve this. |

**Total Score: (75×0.25) + (80×0.20) + (65×0.20) + (75×0.15) + (85×0.20) = 18.75 + 16 + 13 + 11.25 + 17 = 76**

**Total: 76/100 → GO-WITH-CONDITIONS**

---

## Conditions for GO

This story meets the `GO-WITH-CONDITIONS` threshold. Conditions that PLAN.md must explicitly address:

1. **Minting surface decision** (CRITICAL): PRD/plan must specify:
   - CLI framework (click, typer, or argparse)
   - Entry point (standalone script path, or FastAPI CLI integration)
   - Authorization model (local ops CLI, or RBAC-gated HTTP admin endpoint; if HTTP, who authorizes mint requests?)
   - Default token TTL (expires_at null for no expiry, or +90 days / configurable)
   - **Rationale**: Implementation cannot proceed without these decisions. Affect file structure, dependencies, test scope.

2. **Wildcard program scope representation** (HIGH): Plan must specify exactly:
   - Is wildcard stored as `["*"]` (array with single "*"), or as a special string value?
   - Scope validation logic (exact pseudocode: if "*" in allowed_program_ids OR target_id in allowed_program_ids: pass, else 403)
   - Test cases for both array-of-specific-ids and wildcard-array
   - **Rationale**: Logic error here breaks AC5; scope validation is security-critical.

3. **Logging event field allowlist** (MEDIUM): Plan must detail:
   - Exact fields in ingest_token_auth_failed event: required = {token_id, reason, program_id, timestamp}, optional = {}
   - Omission of user_email, raw token, and full hash (per security-baseline.md)
   - Validation at log time (assert fields match spec, per AUTH-03 pattern)
   - **Rationale**: Prevents future inconsistency; matches RBAC logging contract.

4. **Dependency isolation** (MEDIUM): Plan must describe:
   - Route decorator/organization ensuring ingest routes use only get_ingest_token(), user routes use only get_current_user()
   - How the dependency will be injected (AsyncSession, connection pool, configuration)
   - Unit test demonstrating a route with both dependencies raises a clear error (or is forbidden by design)
   - **Rationale**: Two auth paths must not interfere; coexistence requires careful design.

5. **Test surface** (MEDIUM): Plan must identify:
   - Unit tests for token minting (output format AC1, storage AC2)
   - Unit tests for token verification (AC3, AC4, AC5 — valid, revoked, expired, scope)
   - Edge cases: wildcard matching, expired tokens, array handling, program_id types (string vs. UUID)
   - No E2E required (backend-only service)
   - **Rationale**: High-security code needs comprehensive unit coverage; E2E deferred per story test mapping.

---

## Synthesis

**ING-01 introduces a second machine-facing authentication path** (ingest tokens) alongside AUTH-01's Keycloak user JWTs. The ingest contract is well-scoped (AC1-5 are concrete, model exists, hashing scheme is clear), but **three design ambiguities block immediate planning**: (1) where does the mint command live (CLI tool choice, entry point, authorization), (2) how is wildcard program scope represented and validated, and (3) what is the token lifetime default. These are not architecture-level problems — they're implementation-surface decisions that affect file structure and test scope, not correctness.

**Upstream dependencies are satisfied.** BED-01's ingest_tokens table is complete and integrated; AUTH-01/02/03's patterns (dependency injection, error handling, structured logging, RBAC models) are stable and reusable. No blocking external work.

**Key risk is security surface.** Ingest tokens are raw credentials (unlike JWTs which carry claims inline); they must NEVER appear in logs or be stored unhashed. Story correctly specifies SHA-256 hashing and token_hash unique index. Plan must enforce this via code review and test coverage.

**Coexistence of two auth paths** (JWT and ingest) is well-established in other systems (e.g., GitHub's user JWT + PAT bearer tokens). Mitigation (dependency isolation, route organization, clear error handling) is straightforward and tested above.

**Verdict: GO-WITH-CONDITIONS.** The three conditions (minting surface, wildcard spec, logging event schema) must be resolved in PLAN.md before implementation. No architectural blockers; implementation can proceed immediately upon clarification.

---

## Clarifications

<!-- All clarifications resolved 2026-08-31. Settled by ADR-0006, plus a fourth conflict -->
<!-- (token entropy) found during resolution. Detail in the next section.                 -->
<!-- Section intentionally empty so the phase-preconditions clarification gate passes.    -->

## Clarification Resolutions

All resolved **2026-08-31** by user decision, recorded as **ADR-0006** and reflected in
`docs/requirements/auth.md` § `ingest-token-auth`.

### C-4 — Token entropy conflict (found during resolution, not in the original scan)

`.claude/rules/security-baseline.md` § Auth tokens requires **CSPRNG >= 32 bytes** and binds on
`**/*.py`; the contract and story AC-1 both specified 24. **Resolved: 32 bytes / 64 hex chars**,
via `secrets.token_hex(32)`. The rule wins over a standing exception. Free to change now — no code
exists, no token minted; after ING-02/03/07 ship it would invalidate every issued credential.
**Story AC-1 is superseded on the byte count**; the story file is deliberately not edited
(`Status: Validated`), matching the disposition ADR-0005 applied to AUTH-04's AC-5.

### C-1 — Minting surface

**Resolved: stdlib `argparse` in a standalone script**, `services/api/scripts/mint_ingest_token.py`,
run as `uv run python scripts/mint_ingest_token.py`. AC-1 had already fixed the surface as a CLI;
this settles the framework. No new dependency, and identical behaviour inside and outside the
container — the Dockerfile builds with `uv sync --no-dev`, the mechanism that broke `httpx` at boot
(AF-03) when a required package sat in the dev group. ING-06 may still choose a richer framework for
the manual ingester.

### C-2 — Wildcard scope representation

**Resolved: the wildcard is `["*"]` inside the array** — the schema leaves no alternative, since
`allowed_program_ids` is `ARRAY(String) NOT NULL` with no sibling column. **An empty array means
allow-all (unscoped)**, chosen over the fail-closed alternative. Check order: empty -> pass;
`"*"` present -> pass; membership test -> pass; otherwise 403.

### C-3 — Default token lifetime

**Resolved: `expires_at` defaults to null — tokens do not expire.** AC-3 already contemplates the
null state. Revocation via `revoked_at`, not expiry, is the containment mechanism.

### Security posture note

C-2 and C-3 compound, and ADR-0006 § Consequences records this explicitly: the most permissive
credential the system can issue — every program, forever — is also the one produced by omitting a
flag at mint time. This inverts the fail-closed default used by AUTH-01 (dev-bypass allow-list),
AUTH-03 (fail-closed persona gating) and AUTH-04 (403 on resolver failure), and no compensating
detection control exists today (nothing lists, ages, or flags unscoped tokens). These are **accepted
decisions, not oversights** — `/arh-security-review` should read ADR-0006 before raising them.

---

## Open questions

<!-- None. Count: 0. The three original clarifications plus the token-entropy conflict found -->
<!-- during resolution are all settled -- see § Clarification Resolutions and ADR-0006.      -->
<!-- Kept as a comment deliberately, matching AUTH-02/AUTH-04: the phase-preconditions       -->
<!-- clarification gate treats ANY non-blank, non-comment line in this section as an open    -->
<!-- question, so even a bare "0" trips it.                                                  -->
