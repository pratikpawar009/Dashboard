### session

```yaml
produced_by: AUTH-01
consumed_by: [AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03]
shape:
  mechanism: "FastAPI-owned Keycloak OIDC code exchange (Authlib) with bearer-JWT bridging (Q-006/A-006 resolved: frontend and backend are on separate origins, no shared reverse-proxy — NOT a shared-origin session cookie). On successful OIDC callback, FastAPI returns Keycloak's token-endpoint response (access_token JWT, refresh_token, expires_in) to the Next.js frontend as a JSON body, not a Set-Cookie header."
  token_origin: "the JWT is Keycloak's own signed access_token from its token endpoint (role/groups claims as issued by the IdP); FastAPI does not mint its own session token"
  frontend_storage: "frontend holds access_token + refresh_token server-side, in a Next.js Route Handler/server-action-owned store (httpOnly cookie scoped to the frontend's own origin, or in-memory on the Node server) — never localStorage, never a client-JS-readable cookie or storage API"
  transport: "frontend attaches `Authorization: Bearer <access_token>` on every request to the FastAPI API origin; FastAPI validates the JWT signature against Keycloak's JWKS per request (stateless — no server-side session store) and derives role/groups from its claims; CORS on FastAPI allow-lists the frontend origin explicitly (no credentials/cookie mode needed since auth rides the Authorization header, not a cookie)"
  refresh: "access_token is short-lived (Keycloak-configured, e.g. 5 min); the frontend's server-side store calls FastAPI's token-refresh route with the refresh_token proactively before expiry or reactively on a 401 from any API call; FastAPI exchanges it via Keycloak's refresh_token grant and returns a new access/refresh pair. A refresh failure (refresh_token expired/revoked) sends the browser back through the Keycloak login flow (see 'Session expiry' UX case, PRD §Persona Flows)."
  fields: { user_id, email, role, groups: ["program-<slug>", ...] }
  dev_bypass: "FastAPI dependency override active only when ENVIRONMENT != production; issues a dev bypass token through the same Bearer path (not a cookie); never emits audit-log events (FR-AUTH-11)"
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
