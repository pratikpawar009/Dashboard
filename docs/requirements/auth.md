### session

```yaml
produced_by: AUTH-01
consumed_by: [AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03]
shape:
  mechanism: "FastAPI-owned Keycloak OIDC code exchange (Authlib's starlette_client.OAuth) with bearer-JWT bridging — no shared-origin session cookie. Routes: GET /auth/login (redirect to Keycloak's authorization endpoint), GET /auth/callback?code=&state= (code exchange), POST /auth/refresh {refresh_token} (refresh grant), POST /auth/dev-bypass {role?, email?, programs?} (registered only for an allow-listed ENVIRONMENT, see dev_bypass below). Login/callback/refresh return Keycloak's token-endpoint response verbatim as a JSON body `{access_token, refresh_token, expires_in}` — never a Set-Cookie header."
  token_origin: "the JWT is Keycloak's own signed access_token from its token endpoint (role/groups claims as issued by the IdP); FastAPI does not mint its own session token. Realm: Apexon (https://lab.apexonlab.com/apexonlogin/realms/Apexon)."
  frontend_storage: "frontend holds access_token + refresh_token server-side, in a Next.js Route Handler/server-action-owned store (httpOnly cookie scoped to the frontend's own origin, or in-memory on the Node server) — never localStorage, never a client-JS-readable cookie or storage API"
  transport: "frontend attaches `Authorization: Bearer <access_token>` on every request to the FastAPI API origin; a shared FastAPI dependency (`app.core.auth.get_current_user`) validates the JWT signature per request against Keycloak's JWKS (fetched/cached by `app.auth.jwks`, 3600s TTL, fetch-once-per-unrecognized-kid on a verification failure — no server-side session store) and derives `user_id=sub, email=email, role=<realm/client role claim>, groups=groups` from its claims. CORS (`app.main`) allow-lists `settings.cors_origins` explicitly with `allow_credentials=False`, `allow_methods=[GET,POST,OPTIONS]`, `allow_headers=[Authorization,Content-Type]` — no credentials/cookie mode, since auth rides the Authorization header."
  refresh: "access_token lifetime is realm-driven — implementation reads `expires_in` from Keycloak's response and never hardcodes it (Apexon realm's documented default is 300s, a test-fixture value only). The frontend's server-side store calls POST /auth/refresh with the refresh_token proactively at a 60s-remaining skew or reactively on a 401 from any API call; FastAPI exchanges it via Keycloak's refresh_token grant and returns a new access/refresh pair (200). Any non-2xx Keycloak response (expired/revoked/generic error) maps to 401, not a passthrough of Keycloak's raw status, so the frontend uniformly redirects through the Keycloak login flow (see 'Session expiry' UX case, PRD §Persona Flows)."
  fields: { user_id: str, email: str, role: str, groups: ["program-<slug>", ...] }
  program_group_parsing: "each string in the groups claim starting with `program_group_prefix` (Settings field, default \"program-\") contributes its remainder as a program-membership entry (e.g. \"program-alpha\" -> \"alpha\"); non-matching groups are dropped; an absent or empty groups claim yields an empty list, never an error"
  config_completeness_gate: "if any of oidc_client_id/oidc_client_secret/oidc_issuer is unset, /auth/login and /auth/callback return 501 via the standard error envelope at request time — app startup never crashes on incomplete OIDC config (the unset-triple is also the feature flag: set them to go live, unset to back out without a redeploy)"
  dev_bypass: "POST /auth/dev-bypass issues a token through the same {access_token, refresh_token, expires_in} Bearer shape without contacting Keycloak. Gated fail-closed by allow-list membership, not a `!= \"production\"` deny-check: the router is registered in `app.main` only when `settings.environment` (lowercased at Settings load) is a member of the pinned non-production set {local, development, dev, test, ci} — every other value, including \"production\", \"prod\", \"staging\", and any typo, leaves the route unregistered (404), not merely unauthorized. Dev-bypass never emits the dashboard_login (or any audit-log) event — the logging call is skipped on that code path entirely, not filtered downstream."
  observability: "a successful /auth/callback or /auth/refresh (never dev-bypass) emits one structlog JSON `dashboard_login` event carrying `user_id` only — no email, name, or token values, ever."
```

### persona-resolver

```yaml
produced_by: AUTH-02
consumed_by: [AUTH-03, SHP-01]
shape:
  mechanism: "PersonaResolver instance on app.state.persona_resolver, constructed synchronously in create_app() (mirrors JwksCache, AUTH-01 D-07). Per resolve() call: Tier-1 env-JSON dict (Settings.persona_role_map, parsed once at Settings load from PERSONA_ROLE_MAP; unparseable -> logged warning + treated as empty, falls through) -> Tier-2 YAML (services/api/config/persona_role_map.yaml, loaded once at PersonaResolver.__init__; missing/malformed file is a startup error that propagates uncaught through create_app(), aborting Uvicorn boot -- fail-fast, no lifespan wrapper) -> Tier-3 Postgres persona_config table (role PK point lookup via an injectable session_factory defaulting to app.core.db.SessionLocal, 3.0s asyncio.wait_for timeout). All 3 tiers empty raises PersonaNotFoundError(role) -- fail-closed, never a default persona."
  interface: "async def resolve(self, role: str) -> str  (raises PersonaNotFoundError | PersonaResolutionError)"
  input: "role: str -- the session contract's role field (docs/requirements/auth.md#session, CurrentUser.role)"
  output: "persona: str -- typically one of cio | architect | developer | product-manager | engineering-manager, but the resolver is fully data-driven: any string an ops-configured tier maps a role to is returned verbatim, no hardcoded persona enum or exec-role branch"
  cache: "per-role in-process dict {role: (persona, expiry_ts)}, 300s TTL, asyncio.Lock-guarded read+miss+write critical section (no threading.Lock -- no synchronous call path exists in this story's or its consumers' scope). Per-worker/per-process, no cross-worker coherence; Postgres is the source of truth; an app restart is the ops-level hard-refresh lever."
  errors: "PersonaResolutionError(role, reason) is the base class (Tier-3 timeout or connectivity failure); PersonaNotFoundError(role) is the fail-closed subclass raised when all 3 tiers miss. Callers (AUTH-03) must catch and decide fail-request vs. deny-and-log."
  observability: "every resolve() call (cache hit or miss) emits logger.info('persona_mapping_loaded', extra={role, persona, tier, timestamp}) with tier in {tier-1-env, tier-2-yaml, tier-3-postgres}; a FRESH tier-3 query additionally carries tier3_latency_ms (the measured query time, rounded to 3dp) -- a warm cache hit whose stored tier is tier-3-postgres deliberately omits it, since no query ran and re-emitting the original measurement would dilute the p95 the 200ms alert is built on; presence of the field is therefore the reliable signal that a query actually executed (AUTH-02 D-11). No user_id/email/groups/session context is ever included (PII invariant, unit-tested)."
  note: "config-driven additional executive roles (FR-SH-20) resolve to `cio` via any of the 3 sources, no code change -- the resolver contains zero `if role in {...}` branches, verified by a dedicated test case (AUTH-02-TC-07) using a custom slug, not a hardcoded exec-role example."
```

### rbac-checks

```yaml
produced_by: AUTH-03
consumed_by: [AUTH-04, OVW-01, OVW-02, OVW-03, OVW-04, PGD-01, PGD-02, PGD-03, PGD-04, PGD-05, PGD-06, SHP-02, SHP-03, SHP-04, SHP-05, SHP-06]
shape:
  module: "app.core.rbac (services/api/app/core/rbac.py) — pure in-process functions, no route surface of its own; each of the 16 consumers imports directly, e.g. `from app.core.rbac import org_access`"
  checks:
    - org_access: "cio only; org-wide /api/overview/* endpoints"
    - program_visibility: "open-aggregate — any authenticated session; program id not used for gating (A-004)"
    - individual_usage_visibility: "self always; else cio only"
    - member_in_program_visibility: "program_visibility AND (self OR cio)"
    - governance_visibility: "architect | product-manager | developer only (cio, engineering-manager excluded); includes developer from day one per FR-DV-05, no later scope-reversal story needed"
  signatures: |
    async def org_access(current_user: CurrentUser) -> None
    async def program_visibility(current_user: CurrentUser, program_id: str) -> None
    async def individual_usage_visibility(current_user: CurrentUser, target_user_id: str) -> None
    async def member_in_program_visibility(current_user: CurrentUser, program_id: str, target_member_id: str) -> None
    async def governance_visibility(current_user: CurrentUser, program_id: str | None = None) -> None
    # all five: async, current_user is always the first positional argument (AUTH-03-FR-5,
    # AUTH-03-TC-25 asserts this via inspect.iscoroutinefunction + inspect.signature).
    # Names, parameter order, and count are locked from AUTH-03's Product Gate forward — a
    # post-hoc rename requires a coordinated migration across all 16 consumers, not a silent
    # signature change.
  behavior: "each check either returns None (authorized) or raises fastapi.HTTPException(status_code=403) (denied) — never a bool return, never a 5xx for a denial. PersonaResolutionError and PersonaNotFoundError (both from app.core.persona_resolver, AUTH-02) are caught at every call site that resolves persona and converted to HTTPException(403); neither ever propagates to the caller (AUTH-03-FR-1, fail-closed, zero default-permit)."
  cascades: "member_in_program_visibility calls program_visibility(current_user, program_id) first — a denial there short-circuits immediately, without evaluating self-or-cio (AUTH-03-FR-4). governance_visibility, when given a program_id, evaluates the persona gate (AC6) first, then calls program_visibility(current_user, program_id) only if that passed — both must pass (AUTH-03-FR-4)."
  logging: "every check outcome logged (rbac_check_org_access, rbac_check_governance_visibility, individual_view_denied, member_view_denied); the two rbac_check_* events record both authorized and denied outcomes, the two *_view_denied events record denials only. rbac_check_governance_visibility extends NFR-011's set per AUTH-03 Decision log 2026-08-31. Exact field allowlist per event and outcome semantics: AUTH-03-FR-2 (docs/features/AUTH-03/REQUIREMENTS.md). program_visibility emits no event of its own (no denial branch to log)."
```

### ingest-token-auth

```yaml
produced_by: ING-01
consumed_by: [ING-02, ING-03, ING-07]
shape:
  token_format: "hrn_pat_ + 32 CSPRNG bytes hex (64 hex chars, secrets.token_hex(32)), printed once, never stored raw"
  storage: "ingest_tokens.token_hash = hashlib.sha256(raw).hexdigest(); label, user_email, allowed_program_ids (array; wildcard is the single element \"*\"; empty array = allow-all); expires_at/revoked_at null at mint"
  auth_check_function: "app.core.ingest_auth.get_ingest_token(program_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)), session: AsyncSession = Depends(get_db)) -> IngestToken"
  auth_check_behavior: >
    SHA-256-hashes the bearer token, looks up ingest_tokens.token_hash (unique index).
    401 reason=missing (no header or non-Bearer scheme) | reason=unknown (no matching hash) |
    reason=revoked (revoked_at is not null) | reason=expired (expires_at is not null and <= now()).
    403 reason=scope when the row is active but ING-01-FR-3's check fails. On pass, returns the
    resolved IngestToken row. program_id is a caller-supplied parameter of the dependency itself
    (resolved by FastAPI the same way any route parameter of that name is) -- never read off the
    token row (ING-01-FR-6 / DECISIONS.md D-01).
  scope_semantics: "empty allowed_program_ids == allow-all (unscoped, ADR-0006 accepted default); [\"*\"] == explicit wildcard; otherwise exact-string membership test (no UUID-specific parsing)"
  lifetime: "expires_at defaults to null (no expiry); revocation via revoked_at is the containment mechanism"
  mint_surface: "uv run python scripts/mint_ingest_token.py --label <str> --user-email <str> [--program-ids <comma-separated ids or \"*\">] (stdlib argparse, no new dependency); --label/--user-email required, --program-ids optional. Each comma-separated element is whitespace-trimmed and empty elements dropped (\"a, b\" -> [\"a\", \"b\"]; \"*\" -> [\"*\"]); allowed_program_ids=[] (allow-all) is reachable ONLY by omitting --program-ids entirely (DECISIONS.md D-04, D-05a) -- a supplied value that collapses to zero usable elements after trimming (e.g. \"\", \" \", \",\") is a usage error, never allow-all. Exits 0 with one raw-token stdout line and one committed row on success; exits non-zero with no DB write and no token printed on any argparse failure, the input-validation usage-error case above, or a DB failure"
  log_event: "ingest_token_auth_failed, emitted from app.core.ingest_auth, INFO level, once per denial (never on success); required fields exactly {token_id, reason, program_id, timestamp}, optional {} -- token_id is null when no row was resolved (reason missing|unknown), else ingest_tokens.id; reason in {missing, unknown, revoked, expired, scope}; never user_email, raw token, or token_hash"
  authority: "ADR-0006 - supersedes story AC-1's 24-byte figure per security-baseline CSPRNG >= 32 bytes; DECISIONS.md D-01..D-05a (docs/features/ING-01/DECISIONS.md) settle the implementation-surface choices ADR-0006 leaves open"
```
