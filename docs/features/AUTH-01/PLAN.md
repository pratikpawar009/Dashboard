# AUTH-01 — Implementation Plan

Keycloak OIDC sign-in, bearer-JWT session bridging, dev-bypass. Backend-only (FastAPI); no `DESIGN.md` (`design: n/a` — no auth screen in `docs/design/mockups/`, per `docs/features/AUTH-01/state.json`).

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log): D-01 (fail-closed dev-bypass allow-list), D-02 (`app/auth/oidc.py` + `app/auth/dev_bypass.py` split), D-03 (mock-based integration tests, no E2E framework), D-04 (custom JWKS fetch-once cache), D-05 (Authlib adopted — promoted to `docs/adr/0004-keycloak-oidc-authlib.md`), D-06 (`respx` as the dev-only outbound-HTTP mock library).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`.

## 3. Module Hierarchy

```
app/auth/                                       (new package, D-02)
├── __init__.py                                 (F-01)
├── jwks.py                                     (F-03)
│   - input:  kid (str), extracted from an inbound JWT's header
│   - output: JWK public-key material (dict); raises 401 if the kid remains
│              unrecognized after exactly one fresh fetch (D-04)
│   - public: async def get_signing_key(kid: str) -> dict
├── oidc.py                                     (F-05)
│   - input:  GET /auth/login; GET /auth/callback?code&state;
│              POST /auth/refresh {refresh_token}
│   - output: 302 redirect (login) | 200 TokenResponse (callback/refresh) |
│              501 (config incomplete, FR-2) | 401 (refresh failure, FR-6)
│   - public: router: APIRouter  (mounted unconditionally in app.main, D-02)
└── dev_bypass.py                                (F-06)
    - input:  POST /auth/dev-bypass {role?, email?, programs?}
    - output: 200 TokenResponse — identical shape to oidc.py, zero outbound
               Keycloak calls
    - public: router: APIRouter  (mounted in app.main only when
               settings.environment is allow-list member, D-01/D-02 — every
               other value leaves the router unregistered, i.e. 404)

app/schemas/auth.py                              (F-02, new)
- input:  n/a (pure Pydantic models)
- output: TokenResponse{access_token: str, refresh_token: str, expires_in: int},
           DevBypassRequest{role: str | None, email: str | None,
           programs: list[str] | None}
- public: TokenResponse, DevBypassRequest

app/core/auth.py                                 (F-04, modified — replaces the
                                                   501 stub)
- input:  Authorization: Bearer <jwt> header, injected via FastAPI Depends()
- output: CurrentUser{user_id: str, email: str, role: str, groups: list[str]}
           (program-membership already parsed per program_group_prefix, FR-5);
           401 on signature-verification failure
- public: async def get_current_user() -> CurrentUser   (signature unchanged
           from the stub — downstream AUTH-02/03/04 depend on this staying
           stable)

app/core/config.py                               (F-07, modified)
- adds: oidc_client_id/client_secret/issuer/realm: str | None,
         oidc_scope: str = "openid profile email groups",
         program_group_prefix: str = "program-", cors_origins: list[str] = [];
         environment is lowercased at load and resolved against the pinned
         allow-list {local, development, dev, test, ci} (D-01)

app/main.py                                      (F-08, modified — wiring)
- adds: CORSMiddleware(allow_origins=settings.cors_origins,
         allow_credentials=False, allow_methods=[GET,POST,OPTIONS],
         allow_headers=[Authorization,Content-Type]) (FR-9);
         app.include_router(oidc_router) unconditionally;
         app.include_router(dev_bypass_router) only when settings.environment
         is an allow-list member (D-01/D-02)
```

### Route table

```
routes/
├── GET  /auth/login       → app.auth.oidc.router       (redirect to Keycloak, or 501)
├── GET  /auth/callback    → app.auth.oidc.router        (code exchange -> TokenResponse, or 501)
├── POST /auth/refresh     → app.auth.oidc.router         (refresh grant -> TokenResponse, or 401)
└── POST /auth/dev-bypass  → app.auth.dev_bypass.router   (registered only when ENVIRONMENT is
                                                            allow-listed; 404 otherwise)
```

No UI screens — see `docs/design/README.md` override; `docs/features/AUTH-01/REQUIREMENTS.md` § Visual spec.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/AUTH-01.md` § Risk Register (rows numbered 1–9, mapped to `R-01`..`R-09` below in row order).

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 (Authlib not yet declared) | HIGH | T-01, T-22 |
| R-02 (no E2E framework, but story test mapping names E2E flows) | HIGH | T-02 (D-03: resolved as mock-based integration tests, not deferred or reframed as a framework gap) |
| R-03 (AC-2/AC-9 testable-design risk) | HIGH | T-06, T-08, T-09, T-11, T-16 |
| R-04 (program-group claim parsing complexity) | MEDIUM | T-06, T-13, T-14 |
| R-05 (token-refresh error-path variance) | MEDIUM | T-07, T-15 |
| R-06 (CORS credential-less-mode misconfiguration) | MEDIUM | T-09, T-17 |
| R-07 (dev-bypass gating-logic correctness) | MEDIUM | T-03, T-08, T-09, T-16 |
| R-08 (JWKS caching/perf overhead) | MEDIUM | T-05, T-20 |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-09 (no local Keycloak service in `docker-compose.yml`; E2E against a real IdP needs a test realm or a keycloak service) | LOW | accepted — dev-bypass (T-08) covers local dev; adding a `keycloak` service to `docker-compose.yml` is explicitly out of this story's scope (`REQUIREMENTS.md` § Scope · Out). `docs/how-to/dev-bypass-auth.md` (T-25) documents pointing at the real `Apexon` realm for pilot testing instead. Revisit if/when a dedicated E2E-against-real-IdP story is scheduled. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim, abbreviated) | Addressed by |
|------|------------------------------------|--------------|
| C-1  | Add authlib to pyproject.toml before implementation starts | T-01 |
| C-2  | Resolve E2E test strategy before implementation | T-02 |
| C-3  | Finalize OIDC config schema (Settings + .env.example) before implementation | T-03, T-23 |
| C-4  | Document the dev-bypass security assumption (fail-closed, sole gate) | T-03, T-08, T-09 |
| C-5  | Finalize auth route structure (split vs single file) | T-04, T-07, T-08 |
| C-6  | Write unit tests for all 11 ACs | T-10, T-11, T-12, T-13, T-14, T-15, T-16, T-17, T-19 |

### Cross-Feature Dependency Notes

None. AUTH-01 has no upstream dependency (`Depends-on: —`). Downstream stories (AUTH-02, AUTH-03, AUTH-04, SHP-01, SHP-02, SHP-03) consume the `session` contract (`docs/requirements/auth.md#session`, filled by this plan) but are not in flight concurrently with this story.

## 7. Test Strategy

Runner: `pytest` (already configured — `services/api/pyproject.toml [tool.pytest.ini_options] testpaths = ["tests"]`, invoked via `docs/config/project-commands.yaml` `test`/`test_unit`). No new runner is required: `performance`-type and `contract`-type test cases below follow this codebase's existing conventions — `services/api/tests/perf/*.py` (wall-clock timing via `time.perf_counter()`, no dedicated benchmark tool, e.g. `test_rollup_rebuild_perf.py`) and `services/api/tests/unit/test_rollup_rebuild_contract.py` (contract-shape assertions as plain pytest) respectively — both already discovered and run by the standing `test`/`test_unit` commands. No `e2e`-typed test case exists (D-03); `docs/config/project-commands.yaml` `test_e2e: ""` stays empty, unchanged by this story.

| Layer | Test path | TCs covered | Notes |
|-------|-----------|-------------|-------|
| Unit | `services/api/tests/unit/test_auth_config.py` | TC-12 | Settings field list/types/defaults; no network/DB |
| Integration | `services/api/tests/unit/test_auth_oidc_login.py` | TC-01, TC-02, TC-13, TC-14, TC-15 | mock-based (respx), in-process ASGI app (D-03); no live Keycloak |
| Integration + Security + Contract | `services/api/tests/unit/test_auth_callback.py` | TC-03, TC-16, TC-26, TC-36 | TC-16 no-Set-Cookie (security); TC-36 `expires_in` passthrough (contract) |
| Integration + Security | `services/api/tests/unit/test_auth_jwt_validation.py` | TC-04, TC-17, TC-33 | JWKS mocked; TC-33 asserts a forged `X-Role`/`X-Groups` header is ignored |
| Integration | `services/api/tests/unit/test_auth_groups.py` | TC-05, TC-18, TC-19, TC-20 | program-group prefix parsing + boundary cases (empty/missing claim) |
| Integration | `services/api/tests/unit/test_auth_refresh.py` | TC-06, TC-07, TC-21, TC-27, TC-31 | refresh grant success/failure mapping; 4xx never retries |
| Integration + Security | `services/api/tests/unit/test_auth_dev_bypass.py` | TC-08, TC-09, TC-10, TC-22, TC-23, TC-24, TC-37, TC-38, TC-39 | allow-list gating across every allow-listed value plus `PRODUCTION`/`Prod`/`staging`/`produciton`; audit-log exclusion (black-box TC-10, white-box TC-24) |
| Integration + Contract | `services/api/tests/unit/test_auth_cors.py` | TC-11, TC-25 | end-to-end preflight behavior + exact `CORSMiddleware` constructor kwargs |
| Security + Integration | `services/api/tests/unit/test_auth_logging_security.py` | TC-32, TC-35 | token values never in log output; every `/auth/*` log line is valid JSON |
| Contract | `services/api/tests/unit/test_auth_accessibility_scope.py` | TC-34 | confirms no `/auth/*` route serves `text/html` (NFR-accessibility scope boundary) |
| Performance | `services/api/tests/perf/test_auth_jwks_perf.py` | TC-28, TC-29 | latency budgets (<10ms warm, <100ms cold); JWKS fetch-once on unrecognized `kid` |
| Performance | `services/api/tests/perf/test_auth_retry_perf.py` | TC-30 | bounded retry (max 2) + exponential backoff/jitter on transient failures |

All 39 test cases in `docs/test-cases/AUTH-01.json` appear above (`coverage_audit.uncovered == []`); none are flagged `manual: true`.

### Coverage gates

Unit coverage threshold: 80% (no override in `harness.yaml`, falls back to the `plan-authoring` default). `test`/`test_unit` (per `docs/config/project-commands.yaml`) must be green pre-commit — enforced by `/arh-implement` Step 2.

## Plan validation

- Date: 2026-08-28
- Verdict: PASS
- Wiring: PASS (new routers `app/auth/oidc.py` (F-05) and `app/auth/dev_bypass.py` (F-06) both list their entry-registration site `app/main.py` (F-08, modify) via T-09; new helper `app/auth/jwks.py` (F-03) lists its consumer `app/core/auth.py` (F-04, modify) via T-06)
- Docs: PASS (T2 new-route + T3 new-env-var both fire — T-23 updates root `README.md` API section + environment-variables table and `services/api/.env.example` in the same task; T-24 adds the `services/api/README.md` Auth subsection. T1 does not fire — no new runnable surface, FastAPI already exists. T4 does not fire — no new service/port)
- Runner-setup: PASS (test-strategy declares `performance`- and `contract`-typed TCs, but no new runner is required — `pytest` is already fully configured (`testpaths = ["tests"]`) and this exact TC-type pattern already runs under it via `services/api/tests/perf/*.py` and `services/api/tests/unit/test_rollup_rebuild_contract.py`; documented in PLAN §7 opening paragraph)
- Cross-section: PASS (verified programmatically: `predecessors` acyclic with no dangling edges; every `file_plan` entry covered by ≥1 task; every task `files[]` id resolves in `file_plan`; no two DAG-independent tasks share a file; every test-strategy TC type has a backing task)
- Config drift: PASS (C1 fires — `authlib`/`respx` added to `services/api/pyproject.toml`; T-22 updates `docs/config/project-commands.yaml preflight:`. C2/C3 do not fire — no new service or port)
- Decision-promotion: PASS (only D-05 carries `blast:system`; it is promoted to `adr:ADR-0004`, `docs/adr/0004-keycloak-oidc-authlib.md`. D-01/D-02/D-03/D-04/D-06 are `blast:feature|service` + `rev:mechanical|medium` and correctly remain `adr:—`)
- Rounds: 1

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1 | PASS | — | Plan complete; hand off to `/arh-implement` |
