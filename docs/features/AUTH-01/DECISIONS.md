# AUTH-01 — Decisions

Story-level decision log. One `### D-NN` entry per non-trivial technical choice made while planning AUTH-01. `blast:`/`rev:` are greppable slugs (see skill `decide`); `adr:` names the full ADR when promoted.

### D-01: Dev-bypass gating is fail-closed on an allow-list, not a `!= "production"` deny-check · blast:service · rev:mechanical · adr:—

**Context**: AUTH-01-FR-7/AC-9 require dev-bypass to be unreachable in production. A naive `environment.lower() != "production"` deny-check silently admits every unanticipated value — an abbreviation (`"prod"`), a typo (`"produciton"`), or a real deployed environment name that is not literally `"production"` (e.g. `"staging"`) — all read as non-production and would serve a usable dev-bypass token in a real deployment. Because this check is the *sole* mechanism preventing production dev-bypass access (research condition C-4), a deny-check's failure mode is silent and severe: exposure survives until someone notices, not until the check runs.

**Decision**: `Settings.environment` is normalized (lowercased) at load, then resolved by *allow-list membership* against a pinned non-production set `{"local", "development", "dev", "test", "ci"}` (AUTH-01-FR-1). `app/auth/dev_bypass.py`'s router is registered in `app/main.py` only when the normalized value is a member of that set; every other value — including `"production"`, `"prod"`, `"staging"`, and any typo — leaves the router unregistered, so the route 404s via FastAPI's own routing rather than a reachable-but-rejecting handler. Fail-closed: an unrecognized value denies by default, the inverse of the deny-check's fail-open default. Product Gate decision, 2026-08-27.

### D-02: Auth routes split across `app/auth/oidc.py` + `app/auth/dev_bypass.py`, not a single `app/api/auth.py` · blast:feature · rev:mechanical · adr:—

**Context**: the story's `## Test mapping` (`docs/stories/AUTH-01.md`) names the split paths, and research condition C-5 flagged the ambiguity against this codebase's existing single-file-per-resource convention (`app/api/health.py`, `app/api/ingest.py`, `app/api/activities.py`).

**Decision**: keep the split under a new `app/auth/` package, distinct from `app/api/`: `oidc.py` (login/callback/refresh, always registered) and `dev_bypass.py` (conditionally registered per D-01). `app/main.py` then registers or omits the dev-bypass router as one clean `include_router` call gated by the allow-list check, with no conditional threaded through a shared file.

### D-03: E2E test strategy resolved as mock-based integration tests, not a configured E2E framework · blast:feature · rev:medium · adr:—

**Context**: research flagged (Risk #2, HIGH) that `docs/config/project-commands.yaml` `test_e2e: ""` is empty and no E2E framework is declared in ADR-0001, while the story's `## Test mapping` names E2E flows (sign-in redirect, dev-bypass, session-expiry re-auth). A live `Apexon` realm is an external test dependency this story explicitly defers (Risk #9, LOW, accepted — see PLAN.md §6).

**Decision**: every one of the 39 test cases in `docs/test-cases/AUTH-01.json` is typed `unit | integration | security | performance | contract` — none `e2e`. Outbound Keycloak HTTP calls (code exchange, refresh, JWKS fetch) are mocked at the `httpx` transport layer via `respx` (new dev dependency — chosen over `responses` because this codebase's outbound client is `httpx`, matching the existing `httpx.ASGITransport`-based in-process testing convention in `tests/unit/test_range_validation.py`). Configuring Playwright/Cypress against a real or containerized Keycloak is deferred, not ruled out.

### D-04: JWKS cache is a custom fetch-once-on-unrecognized-kid cache, not Authlib's default caching alone · blast:feature · rev:mechanical · adr:—

**Context**: AUTH-01-NFR-performance pins a specific invalidation policy — an unrecognized `kid` triggers exactly one fresh JWKS fetch before the request fails, not a fixed-interval background refresh — narrower than a generic TTL-only cache.

**Decision**: `app/auth/jwks.py` owns a small in-memory cache keyed by `kid`, TTL 3600s, with an `asyncio.Lock`-guarded fetch-once path: a verification failure against the cached key set triggers exactly one fresh fetch (stampede-protected under concurrent requests), and if the `kid` remains unrecognized after that fetch the request fails — no retry loop, no fixed-interval background task.

### D-05: Authlib adopted as the Keycloak OIDC client + JWT validation library · blast:system · rev:medium · adr:ADR-0004

**Context**: research condition C-1 (HIGH risk) flagged that no OIDC/JWT library is declared in `services/api/pyproject.toml`. This is a new production runtime dependency entering the system's trust boundary — 13 downstream stories (AUTH-02/03/04, SHP-01/02/03, and everything they in turn gate) consume the `session` this library's output feeds, and ADR-0002's own flagged gap ("OIDC/SSO identity provider not chosen") names exactly this class of decision as architecture-level.

**Decision**: `authlib>=0.15,<1.0` (pinned to the stable 0.x series). Used two ways: `authlib.integrations.starlette_client.OAuth` for the login/callback code-exchange flow, and `authlib.jose.jwt` for stateless per-request bearer-token signature verification against the JWKS `app/auth/jwks.py` maintains — never a server-side session store. Promoted to a full ADR (`docs/adr/0004-keycloak-oidc-authlib.md`) per the `blast:system` rule for new external dependencies.

### D-06: `respx` adopted as the outbound-HTTP mock library for tests, dev-only · blast:feature · rev:mechanical · adr:—

**Context**: D-03's mock-based test strategy needs to intercept outbound `httpx` calls (Keycloak token/refresh/JWKS endpoints) without a real IdP. `respx` is technically a new dependency, but it never ships to production, has zero consumers outside this story's test suite, and swapping it for `responses`/`pytest-vcr` later is a one-file `conftest.py` change — none of the system-wide exposure `blast:system` exists to flag.

**Decision**: `respx>=0.20` added to `services/api/pyproject.toml` `[dependency-groups] dev`. `services/api/tests/conftest.py` gains fixtures building a `respx.MockRouter` against Keycloak's token/refresh/JWKS endpoints, an RSA test keypair + JWT-builder helper (`authlib.jose.jwt.encode`), and a Keycloak-outbound-call spy.

### D-07: `create_app()` factory in `app/main.py`, with per-app settings on `app.state` · blast:service · rev:mechanical · adr:—

**Context**: surfaced during `/arh-implement` T-09/T-02 scheduling, not anticipated at plan time. D-01 registers the dev-bypass router conditionally on `settings.environment`, and AUTH-01-FR-2 gates OIDC routes on config completeness — both decided at app-assembly time. But `app/main.py` currently builds a module-level `app = FastAPI(...)` and `app/core/config.py` exposes a module-level `settings = Settings()` singleton, so registration is frozen at first import. Sixteen test cases require booting the app under a *different* configuration each (TC-09/22/23/37/38/39 each need a distinct `ENVIRONMENT`; TC-01/02/13/14/15 each need a distinct OIDC-config completeness state; TC-11/25 need `CORS_ORIGINS` set). `importlib.reload(app.main)` would technically work but is order-dependent, leaks module state across tests, and TC-01's own preconditions already name "the real FastAPI app factory".

**Decision**: `app/main.py` exposes `create_app(settings_override: Settings | None = None) -> FastAPI`, which assembles exception handlers, `CORSMiddleware`, the existing health/ingest/activities routers, the oidc router (always), and the dev-bypass router (only when the effective settings' environment is allow-listed, D-01). The effective `Settings` is stored on `app.state.settings`, and route handlers read it via a `get_settings(request)` FastAPI dependency exported from `app/core/config.py` — never by importing the module singleton directly, which would ignore the override. The module-level `app = create_app()` is retained unchanged, so `uvicorn app.main:app`, the `Dockerfile`, and `docker-compose.yml` keep working with no edit.

Consumer-facing signatures are unaffected: downstream stories still write `Depends(get_current_user)` exactly as against the 501 stub (PLAN.md §3) — the added parameters are FastAPI-injected, not caller-supplied.

### D-08: dev-bypass signs with an ephemeral process-local RSA key that the JWKS cache serves only in allow-listed environments · blast:service · rev:medium · adr:—

**Context**: AF-05 — verified end-to-end by T-08 — `POST /auth/dev-bypass` returned a well-formed `TokenResponse`, but that token 401'd against every `Depends(get_current_user)` route, because `get_current_user` verifies signatures exclusively against Keycloak's real JWKS and dev-bypass has no access to Keycloak's private signing key. All 39 test cases passed regardless, since none exercised a dev-bypass token against a protected route. That breaks the story's stated outcome ("developers without a live IdP can still sign in locally", "exercise persona-scoped routes locally") and invalidates PLAN.md §6's rationale for accepting risk R-09. Product decision requested and given 2026-08-28.

**Decision**: `app/auth/jwks.py` owns a lazily-generated, **process-local, ephemeral** RS256 keypair with a reserved `kid`. `JwksCache.get_signing_key` resolves that `kid` **only when `settings.dev_bypass_enabled`** is true — the same fail-closed allow-list that governs router registration (D-01). `app/auth/dev_bypass.py` signs its tokens with the matching private key.

Rejected alternatives: skipping signature verification inside `get_current_user` when dev-bypass is enabled (adds a second trust path to the security-critical function, weakening exactly what AUTH-01-NFR-security guarantees); and shipping a committed static dev key (a real private key in source, and a credential that outlives the process).

Properties this preserves: exactly ONE verification mechanism (JWKS) with no branch in `get_current_user`; D-01's fail-closed gate still the sole control, so in production the dev `kid` is never served and the token is rejected by the normal path; the key is generated per process and never persisted, so it cannot leak via git or survive a restart.

### D-09: `session.role` filters Keycloak system roles before selecting · blast:feature · rev:mechanical · adr:—

**Context**: Q-01. `realm_access.roles` is a list, and a real Keycloak token carries `["default-roles-<realm>", "offline_access", "uma_authorization", "<actual role>"]`. T-06's "first entry" satisfies every pinned test case (each supplies exactly one role) but would hand AUTH-02's persona resolver `"default-roles-apexon"` in production. Product decision 2026-08-28.

**Decision**: `_parse_role` drops Keycloak's system roles — `default-roles-*` (prefix match), `offline_access`, `uma_authorization` — then returns the first survivor, or `""` if none remain. Keeps AUTH-01 decoupled from AUTH-02's persona vocabulary (the rejected alternative of matching the five persona names) and avoids widening the `session` contract that six downstream stories consume.

### D-10: a zero-length program remainder is dropped, not admitted as an empty program id · blast:feature · rev:mechanical · adr:—

**Context**: AF-06. A group named exactly `program-` (the bare prefix) parsed to `[""]`, since it trivially `startswith` itself. AUTH-01-FR-5 does not forbid it, but an empty-string program id is meaningless to AUTH-03's program-scoping checks and more plausibly signals a malformed IdP group name. Product decision 2026-08-28.

**Decision**: `_parse_programs` drops zero-length remainders — `["program-"]` → `[]`. `groups` still retains the raw entry verbatim; only `programs` filters it.

### D-11: an explicit `oidc_redirect_uri` setting overrides the request-derived callback URL · blast:service · rev:mechanical · adr:—

**Context**: AF-08. AUTH-01-FR-1's pinned `Settings` field list omits a redirect-URI field, so T-07 derived the callback URL per request via `request.url_for("oidc_callback")` — verified by T-11 to resolve to the request host (`http://test/auth/callback`). Keycloak clients register an exact redirect URI, and a derived value will not match once the API sits behind a reverse proxy or load balancer unless `X-Forwarded-Proto`/`Host` are forwarded AND Starlette is configured to trust them. Correct locally and in tests; a near-certain failure at first pilot deployment. Product decision 2026-08-28.

**Decision**: add `oidc_redirect_uri: str | None = None` to `Settings`. `app/auth/oidc.py` uses it verbatim when set and falls back to the existing `request.url_for("oidc_callback")` derivation when unset, so local development and every existing test keep working with no configuration change. This deliberately extends FR-1's pinned field list by one optional field; the alternative considered and rejected was pushing the requirement into deployment config (trusted-proxy headers), which moves a correctness property into infra where it fails silently.

Rejected the "defer" option because the failure mode is a deployment-time redirect_uri mismatch that reads as an opaque Keycloak error, and the fix is one optional field.

### D-12: OAuth `state` verification (PKCE) deferred to a follow-up story · blast:feature · rev:medium · adr:—

**Context**: AF-07. `/auth/login` mints a random `state` that `/auth/callback` cannot verify, because the bearer-only, cookie-less topology (`docs/requirements/auth.md` § session) provides no server-side store. No AC, NFR, or test case in AUTH-01 mentions `state` or CSRF. Product decision 2026-08-28.

**Decision**: accept for AUTH-01 and carry forward. PKCE (`code_challenge`/`code_verifier`) is the intended fix — Keycloak supports it and it needs no server-side session — but it is a design change across login and callback with its own test cases, beyond this story's approved ACs. Recorded as pending carry-forward so it is visible at merge and cannot be lost; it must be resolved before the pilot rollout described in REQUIREMENTS.md § Rollout plan, not before merge.
