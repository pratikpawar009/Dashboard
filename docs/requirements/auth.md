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
  mechanism: "3-tier cached resolver (env JSON -> config file -> Postgres persona_config), 5-minute cache; raises if all 3 sources empty for a role"
  input: "session.role"
  output: "persona: cio | architect | developer | product-manager | engineering-manager"
  note: "config-driven additional executive roles (FR-SH-20) resolve to `cio` via any of the 3 sources, no code change"
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
