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
  checks:
    - org_access: "cio only; org-wide /api/overview/* endpoints"
    - program_visibility: "open-aggregate — any authenticated session; program id not used for gating (A-004)"
    - individual_usage_visibility: "self always; else cio only"
    - member_in_program_visibility: "program_visibility AND (self OR cio)"
    - governance_visibility: "architect | product-manager | developer only (cio, engineering-manager excluded); includes developer from day one per FR-DV-05, no later scope-reversal story needed"
  logging: "every check outcome logged (rbac_check_org_access, individual_view_denied, member_view_denied)"
```

### ingest-token-auth

```yaml
produced_by: ING-01
consumed_by: [ING-02, ING-03, ING-07]
shape:
  token_format: "hrn_pat_ + 24 random bytes hex, printed once, never stored raw"
  storage: "ingest_tokens.token_hash (SHA-256 hex), label, user_email, allowed_program_ids (array or literal wildcard \"*\")"
  authz: "bearer hash lookup -> 401 if missing/revoked/expired; program-scope check -> 403 if target program not in allowed set and no wildcard"
```
