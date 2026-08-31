# Research Assessment: AUTH-04 — GET /api/programs persona-scoped list

**Story ID**: AUTH-04  
**Epic**: AUTH  
**Priority**: P1  
**Upstream dependencies**: AUTH-01 (session contract), AUTH-03 (rbac-checks contract), BED-01 (db-schema contract)  
**Downstream dependencies**: PGD-01, EMD-01 — both consume the `programs-api` contract for "Switch program" selectors  
**Assessment Date**: 2026-08-31  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**All three upstream dependencies complete and verified on main branch:**
- **AUTH-01** (research verdict: GO-WITH-CONDITIONS, score 81/100, impl: complete): provides the `session` contract with `user_id, email, role, groups, programs` fields. Groups parsed from Keycloak JWT with configurable prefix (default "program-"), programs is the remainder. Bearer-JWT validation, JWKS caching, dev-bypass all operational.
- **AUTH-03** (research verdict: GO-WITH-CONDITIONS, score 87/100, impl: complete): provides the `rbac-checks` contract with `program_visibility(current_user, program_id)` — open-aggregate check that passes for any authenticated session (no persona resolution, no program_id branching). Logging patterns established (rbac_check_* and *_view_denied events).
- **BED-01** (research verdict: GO-WITH-CONDITIONS, score 92/100, impl: complete): provides the `db-schema` contract with `program_summary` table containing all required fields: program_id (unique), name, icon, type, description, plus metrics (tokens, releases, features, active_contributors, repos_*, commands_executed, lines_of_code_generated, user_stories_delivered, intervention_count, tool_rejections, as_of_timestamp).

**No architectural blockers.** All three upstreams are live on main, tested, and stable. The program_summary model is defined, RBAC check is implemented, session contract is proven.

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean, main branch with all three upstreams merged)
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, pytest-asyncio, Postgres 16
- **Auth status**: AUTH-01 complete (OIDC, bearer JWT, dev-bypass); AUTH-03 complete (RBAC checks)

### Database Schema (From BED-01)
- **`app/models/rollup.py::ProgramSummary`** — table "program_summary", all required fields present:
  - `program_id: str` (unique)
  - `name: str`
  - `icon: str`
  - `type: str`
  - `description: str`
  - Plus 12 additional metric fields (tokens, releases, features, active_contributors, repos_*, commands_executed, lines_of_code_generated, user_stories_delivered, intervention_count, tool_rejections, as_of_timestamp)
- **Verification**: Model exists and verified at `services/api/app/models/rollup.py:1-23`
- **Alembic migration**: `services/api/migrations/versions/001_initial_schema.py` defines the schema; migration 001 has been applied to the test DB

### Session Contract (From AUTH-01)
- **`app/core/auth.py::CurrentUser`** — dataclass with:
  - `user_id: str` (Keycloak sub)
  - `email: str` (Keycloak email claim)
  - `role: str` (parsed from realm_access.roles)
  - `groups: list[str]` (raw groups claim, prefix intact, e.g., ["program-alpha", "program-beta", "admin"])
  - `programs: list[str]` (parsed remainder after prefix, e.g., ["alpha", "beta"])
- **Session injection**: `get_current_user()` FastAPI dependency returns `CurrentUser` from verified JWT
- **Prefix parsing**: Keycloak groups claim split by `program_group_prefix` (Settings field, default "program-"); remainder becomes a program-membership entry
- **Verified at**: `services/api/app/core/auth.py:12-26` and test coverage in `services/api/tests/unit/test_auth_*.py`

### RBAC Check Contract (From AUTH-03)
- **`app/core/rbac.py::program_visibility`** — signature `async def program_visibility(current_user: CurrentUser, program_id: str) -> None`
  - **Behavior**: open-aggregate; passes for any authenticated session; does NOT read current_user.programs; does NOT branch on program_id; no persona resolution
  - **Logging**: no event emitted (no denial branch to log)
  - **Test coverage**: TC-03, TC-04, TC-27, TC-28 verify exact contract
- **Verified at**: `services/api/app/core/rbac.py:28-41`
- **Implication**: program_visibility is a veto gate that approves all authenticated sessions. Actual program scoping (filtering by session.programs) must happen in the endpoint itself.

### API Contract (From docs/requirements/api.md)
- **programs-api**: 
  - Endpoint: `GET /api/programs`
  - Scoping: "cio sees all programs; every other persona sees only programs matching session.groups program list"
  - Fields NOT specified in the contract prose — only endpoint + scoping rule are mandated
- **Response field set assumption** (from story Decision log):
  - `program_id, name, icon, type, description`
  - Synthesized from: SHP-01 persona-shell contract requires `program_context: {icon, name, type, description}` + story adds `program_id` for switching (FR-PD-03, FR-EM-02)
  - **Verified**: SHP-01 REQUIREMENTS.md confirms persona-shell uses exactly these fields for program context
  - **Verified**: PGD-01 uses programs-api output for "Switch program" selector (FR-PD-03)

### No Existing Endpoint
- **`services/api/app/api/`** directory contains: health.py, ingest.py, activities.py — NO programs.py
- **Implication**: /api/programs endpoint must be created from scratch

### Downstream Consumers (From RTM)
- **PGD-01**: Program Detail page — uses programs-api for "Switch program" selector in navbar
- **EMD-01**: Engineering Manager Dashboard — uses programs-api for program context in the shell
- Both consume the programs-api contract (endpoint + scoping rule + response shape)

### Configuration & Environment
- **`app/core/config.py::Settings`** — already has:
  - `program_group_prefix: str = "program-"` (default)
  - `environment: str` (for AC-9 dev-bypass gating, already in AUTH-01)
  - Pattern established for env-sourced config
- **`.env.example`** — no changes needed (programs-api endpoint is backend-only, no new env vars)

### Route Handlers & Dependency Pattern
- **Existing routes** (health.py, ingest.py, activities.py): async functions, thin handlers, FastAPI dependencies via Depends()
- **Auth pattern** (get_current_user): injected via Depends(); available as `current_user: CurrentUser` parameter
- **RBAC check pattern** (from AUTH-03): call `await program_visibility(current_user, program_id)` for each program; any exception is a denial (HTTPException 403)

### Logging Infrastructure
- **`app/core/logging.py::JSONFormatter`** — merges `extra={...}` fields into JSON payload
- **Event pattern**: `logger.info("event_name", extra={"field1": value1, ...})`
- **Verified working**: AUTH-02 TC-15 confirms extra fields are emitted correctly
- **Story NFR**: log `programs_list_returned` event with persona, returned_count (assumption, not in rbac-checks contract)

### Testing Infrastructure
- **Unit test framework**: pytest + pytest-asyncio, conftest.py has test_engine, test_session
- **Route test pattern** (from test_rbac.py): async test with AsyncClient + ASGI transport, mock current_user dependency
- **No E2E test framework**: project-commands.yaml has `test_e2e: ""` (empty)

### Toolchain & Preflight
- **Python 3.11+**: ✓
- **FastAPI 0.115, SQLAlchemy 2.0, pytest-asyncio**: ✓ all installed
- **Database**: Postgres 16, async engine, psycopg[binary] ✓
- **uv package manager**: in use ✓

### Performance Baseline Context
- **Story NFR**: p95 < 300ms for full unpaginated list (assumption)
- **Dataset size**: ~9 programs (per NFR-004 seed fixture)
- **Query pattern**: SELECT * FROM program_summary WHERE program_id IN (?) — simple IN clause, no complex joins
- **No pagination**: story assumes small dataset, no BED-02 api-conventions dependency
- **DB indexes**: program_summary has unique(program_id), no range indexes needed for this story

### Pattern Skills Status
- **fastapi-patterns**: Async routes, error envelope, dependency injection — all established in AUTH-01/03
- **pydantic-patterns**: Request/response models — not yet evidenced for programs-api, will need to create response model (ProgramsListOut with `programs: list[ProgramDetail]` where ProgramDetail has the 5 fields)
- **postgres-patterns**: Async session, SQLAlchemy ORM — established; no new patterns needed

### Design System Validation (Mockup Authority)
- **AUTH epic**: No entry in `designSystem.pages.features` in `docs/design/schema.json` → AUTH-04 has no dedicated mockup. `design: n/a` is legitimate for backend-only stories with no UI surface of their own.
- **PGD-01 (Program Detail) mockup** (`docs/design/mockups/Program Detail.html`):
  - **"Switch program" selector bindings**: Rendered as a dropdown button + menu with `sc-for list="{{ progOptions }}" as="o" hint-placeholder-count="6"`
  - **Program object fields consumed**:
    - `prog.name` — displayed in button and selector field
    - `prog.ptype` — rendered with `prog.typeChip` style binding (pre-formatted type with styling)
    - `prog.dotStyle` — rendered as a colored indicator dot (pre-formatted CSS)
    - `prog.avatar` + `prog.avatarStyle` — program icon/avatar image with styling
    - `prog.scope` — description text below program name in header
  - **The list itself is `progOptions`**, iterated as `<sc-for list="{{ progOptions }}" as="o" hint-placeholder-count="6">`. This — not the `prog.*` header object — is what `GET /api/programs` feeds.
  - **Per-option fields actually bound**: `o.label`, `o.href`, `o.dotStyle`, `o.rowStyle`, `o.current` (boolean, drives the ✓ on the active row)
  - **The `prog.*` fields above belong to the currently-viewed program header**, which is Program Detail's own payload (`program-detail-api`), not this list endpoint's.
  - **Empty/loading states**: `hint-placeholder-count="6"` implies 6 placeholder rows when loading; AC-4 empty list (zero programs) renders an empty dropdown
- **SHP-01 (persona-shell) contract** (`docs/requirements/api.md`): Requires `program_context: { icon, name, type, description }` (4 fields)
- **EMD-01 (Engineering Manager Dashboard) mockup** — same switcher, same per-option shape, different list name and placeholder count: `<sc-for list="{{ projOptions }}" as="o" hint-placeholder-count="3">`, binding `o.label`, `o.href`, `o.dotStyle`, `o.rowStyle`, `o.current`. Two mockups, one list-item contract.
- **Response field set — MISMATCH, unresolved**: the story's assumed set is not what either switcher list binds.

  | Story field | Switcher list binding | Status |
  |---|---|---|
  | `name` | `o.label` | present, different name |
  | `program_id` | `o.href` | mockup binds a ready-to-use link target, not a bare id |
  | `icon` | `o.dotStyle` | mockup binds pre-formatted CSS, not an icon name or URL |
  | `type` | — | **not bound by the list** |
  | `description` | — | **not bound by the list** |
  | — | `o.current` | **absent from the story's set** — requires knowing the active program |
  | — | `o.rowStyle` | **absent from the story's set** — pre-formatted CSS |

  The story's 5-field set matches the **header** object (`prog.name/ptype/scope` + avatar), i.e. single-program detail — not the list this endpoint returns. SHP-01's `program_context: {icon, name, type, description}` likewise describes the shell's *current-program* context, not the switcher list.
  - **Verdict**: field set is **NOT confirmed**. Raised as an open clarification (§ Clarifications) per CLAUDE.md § Design system — "If a story seems to need something the mockups do not show, stop and raise it. Do not design it."
- **Values arrive pre-formatted**:
  - Mockup binds `prog.typeChip` (style for type chip) and `prog.dotStyle` (pre-formatted CSS for icon) — backend must provide display strings and computed styles, not raw enums or SKUs
  - README.md confirms "Values arrive pre-formatted" — API returns ready-to-render values
  - **Implementation constraint**: `type` and `icon` fields must be display-ready (e.g., "major" not a numeric code; icon as CSS color or URL, not a raw ID)

---

## Pattern Map

### Existing Code to Extend
- **`app/core/auth.py`** — no extension needed; CurrentUser contract is stable and already has `programs` field parsed
- **`app/core/config.py`** — no extension needed; program_group_prefix already exists
- **`app/core/rbac.py`** — no extension needed; program_visibility is the gate used by this endpoint
- **`app/core/logging.py`** — no extension needed; JSONFormatter already supports extra fields
- **`app/core/errors.py`** — no extension needed; existing error envelope will catch auth denials (401) and route logic errors (4xx)

### Existing Patterns to Follow
- **Async dependencies** (from AUTH-01/03): `get_current_user()` injected via `Depends()`, returns CurrentUser
- **RBAC gating** (from AUTH-03): call `await program_visibility(current_user, program_id)` for each program; exception = denial (short-circuit to 403)
- **Structured logging** (from AUTH-01/02/03): `logger.info("event_name", extra={fields...})` with exact field allowlist
- **Error handling** (from fastapi-patterns): raise `HTTPException(status_code, detail)` or let Pydantic validation propagate; registered handlers build the envelope
- **Response models** (from pydantic-patterns): in/out model split; response model is a Pydantic BaseModel with typed fields

### New Files to Create
- **`app/api/programs.py`** — router module with single route handler `list_programs(current_user: CurrentUser = Depends(get_current_user))` → `ProgramsListResponse`
  - Query: `SELECT program_id, name, icon, type, description FROM program_summary` (no metrics, keep response lean)
  - Scoping: if persona is cio (resolved from session.role via AUTH-02's resolver), return all; else filter WHERE program_id IN (current_user.programs)
  - Logging: emit `programs_list_returned` event with persona, returned_count
  - Return: `ProgramsListResponse(programs=[ProgramDetail(...), ...])`
- **`app/schemas/programs.py`** — Pydantic models:
  - `ProgramDetail(BaseModel)`: program_id, name, icon, type, description (5 fields, minimal set for SHP-01 persona-shell + routing)
  - `ProgramsListResponse(BaseModel)`: programs: list[ProgramDetail]
- **`tests/unit/test_programs.py`** — unit tests for all 6 ACs:
  - AC-1: cio sees all programs (mock cio persona, verify returned_count matches all rows)
  - AC-2: non-cio sees only programs in session.programs (mock developer + ["alpha", "beta"], verify returned list)
  - AC-3: 401 on missing/invalid token (mock missing Authorization header)
  - AC-4: empty list on zero-match (mock developer with ["gamma"], verify empty list, not error)
  - AC-5: each program has exactly 5 fields (program_id, name, icon, type, description)
  - AC-6: no per-program 403 (verify endpoint returns 200 + filtered list, not 403 on a restricted program_id in the URL)

### Shared Code at Risk
- **`app/core/auth.py::CurrentUser`** — role and programs fields are critical; any drift (role → roles list) will break this endpoint
- **`app/core/rbac.py::program_visibility`** — signature and behavior locked (test TC-03..28); any change requires downstream re-testing (PGD-01, EMD-01)
- **`app/models/rollup.py::ProgramSummary`** — table schema is locked by BED-01; any schema change requires migration + all consumers updated
- **`app/main.py`** — router inclusion order: auth routes must be registered before programs route (so Depends(get_current_user) works); program route must be included so it's discoverable

### No New External Dependencies
- No new libraries needed (FastAPI, SQLAlchemy, Pydantic, structlog all already present)

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Dependency** | MEDIUM | **Session.programs parsing robustness.** If Keycloak's groups claim is absent or malformed (e.g., groups not in the token at all), the parsing logic (prefix-based split) could fail. AUTH-01's implementation handles this gracefully (missing groups → empty list), but AUTH-04 must not crash if programs list is empty or contains unexpected values. | (1a) **Defensive programming**: always call `current_user.programs` as a read-only list; never assume a program_id in the list corresponds to an actual row in program_summary (downstream filtering will skip missing rows). (1b) **Unit test**: call endpoint with current_user.programs = [], verify 200 response with programs: [] (not 500 or empty-list error). (1c) **Logging**: if a program_id in session doesn't exist in program_summary, log a warning (anomaly) but don't fail the request; return the programs that exist. |
| 2 | **Domain** | MEDIUM | **Persona resolution (cio check) latency.** AC-1 requires checking if persona is cio. This calls AUTH-02's persona_resolver (cached, 300s TTL, <1ms warm hit, <100ms cold hit on Tier-3 query). Under worst case (first request with new role, cold Tier-3 query), persona resolution could add 50-100ms to the request. The story's NFR budget is p95 < 300ms; if query takes 100ms + DB query takes 50ms, we're at 150ms, well under budget. But if DB query takes 200ms (e.g., full table scan), we could breach budget. | (2a) **Optimization**: Ensure program_summary table has an index on program_id (it does: unique constraint). Query pattern should be SELECT ... WHERE program_id IN (:ids) with indexed lookup, not a full scan. (2b) **Performance test**: Create a test with 100 programs and a non-cio persona with programs in a subset; measure end-to-end latency; ensure p95 < 300ms. (2c) **Query profiling**: Use EXPLAIN ANALYZE to verify the query plan uses the program_id index, not a full scan. (2d) **No N+1**: the endpoint makes exactly 2 DB calls: (1) persona resolution (cached per AUTH-02's cache), (2) SELECT programs — never a loop. |
| 3 | **Domain** | MEDIUM | **AC-6 / program_visibility open-aggregate semantics.** The check passes for any authenticated session, regardless of program_id. This is intentional per A-004 (risk R-003, tracked in PRD). BUT: if a downstream consumer (PGD-01, EMD-01) confuses this check's pass-through for an affirmative "this program is in my programs list", it could leak data. For example, if PGD-01 calls program_visibility(program_x) and gets 200, does it assume program_x is in session.programs? No — it must check session.programs directly. | (3a) **Documentation**: In the programs-api endpoint docstring, clearly state that program_visibility is a veto gate (passes for auth'd sessions, provides no positive authorization). Actual scoping happens via the WHERE clause (program_id IN current_user.programs). (3b) **Code review gate**: Every call to program_visibility in the endpoint must be preceded/followed by explicit session.programs checks. Never rely on program_visibility's result for scope decisions. (3c) **Test AC-6**: Call endpoint, verify no 403 is ever returned (only 401 on bad auth, 200 on auth'd). The filtered list IS the scoping mechanism, not the RBAC check. |
| 4 | **Observability** | MEDIUM | **`programs_list_returned` event payload PII compliance.** Story NFR specifies logging persona, returned_count. The `persona` field must not contain role or groups (raw JWT fields). It should be the resolved persona value (e.g., "cio", "developer") — consistent with AUTH-02/03 logging patterns. | (4a) **Specify exact payload before implementation**: `programs_list_returned: {user_id, persona, returned_count, timestamp}` (4-field allowlist, no email, no groups, no request path). (4b) **Unit test per event** (like AUTH-02's TC-15): assert payload keys = allowlist exactly, no extra fields. (4c) **Code review gate**: audit every log line for PII leakage. |
| 5 | **Integration** | HIGH | **Response field set contradicts the switcher mockups.** `GET /api/programs` feeds the `progOptions` / `projOptions` list, whose per-item bindings are `{label, href, dotStyle, rowStyle, current}`. The story specifies `{program_id, name, icon, type, description}` — which is the *header* (single-program) shape. `type` and `description` are bound nowhere in the list; `current` and `rowStyle` have no source in the story's set; `href`/`dotStyle`/`rowStyle` are pre-formatted presentation values, which the design README flags as a deliberate decision ("Taken literally that puts CSS in API responses. Decide deliberately; do not copy the mockup here"). Building the story's set as written ships an endpoint the switcher cannot render from. | (5a) **Open clarification — user decision required** (§ Clarifications). Do not design a resolution inside this story. (5b) Whichever shape is chosen, record it as an ADR or a PRD decision, since it settles whether this API layer returns CSS. (5c) `o.current` needs an active-program input the endpoint does not currently receive — resolve its source (client-side derivation vs. server-side flag) as part of the same decision. |
| 6 | **Domain** | LOW | **Upstream persona-resolution error handling.** When persona_resolver.resolve(role) is called (AC-1 cio check), it can raise PersonaNotFoundError or PersonaResolutionError. The endpoint must catch these and decide: (a) fail the request (403/500)? (b) apply a fallback? AC-1 doesn't specify. AUTH-03's error handling resolves this (fail-closed: catch and raise HTTPException 403), and AUTH-04 can follow the same pattern. | (6a) **Error handling pattern**: When calling persona_resolver, wrap in try-except; catch PersonaResolutionError and PersonaNotFoundError; log the error at WARN level; return HTTPException(403, "Access denied"). (6b) **Test case**: mock persona_resolver timeout, verify endpoint returns 403 (not 500 or unhandled exception). |
| 7 | **Performance** | LOW | **Pagination deferred.** The story explicitly states no pagination (assumption, ~9 programs, no BED-02 dependency). If the org grows beyond 9 programs, a future story must add pagination (BED-02 phase 2?). The current implementation will return an unbounded list; if the list grows to 1000+ programs, the response payload could exceed NFRs or timeout limits. | (7a) **Assumption documented**: Story Decision log notes "no pagination; ~9 programs per NFR-004". This is fine for MVP. (7b) **Future story**: Create a follow-up story "AUTH-04-pagination: Add pagination to GET /api/programs" if/when the org outgrows 9 programs. Track in the backlog. (7c) **Performance monitoring**: During validation, capture the actual response size and latency with the seed fixture's ~9 programs; set a baseline. If later testing shows 100+ programs, that's a signal to prioritize pagination story. |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Criterion | Evidence | Score | Notes |
|-----------|--------|-----------|----------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood | All three upstreams complete on main (AUTH-01 OIDC + session, AUTH-03 RBAC, BED-01 db-schema). CurrentUser contract stable (role, programs parsed). program_visibility check stable (open-aggregate). ProgramSummary model has all 5 required fields + 12 metrics. Error handling seam in place. No undocumented dependencies or external services needed. | 90/100 | Upstreams are proven and tested. Risk #2 (persona resolution latency under cold cache) is managed via AUTH-02's cache + budget headroom. Risk #1 (programs parsing) is handled by AUTH-01's graceful empty-list default. |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version | Greenfield endpoint (first-written, no legacy to maintain). Downstream consumers (PGD-01, EMD-01) are not yet implemented, so no existing code to break. Response model is explicit Pydantic (ProgramDetail) — future field additions are versioned, not hidden in dicts. **Contract is NOT locked**: the mockups' switcher list binds `{label, href, dotStyle, rowStyle, current}`, not the story's 5-field set (Risk #5, C-1). No legacy consumers exist yet, so the cost of settling this now is low — but it must be settled before a response model is written. | 72/100 | No legacy code to break, which caps the damage. But the response contract — the single thing this dimension measures — is contradicted by the authoritative design source and is unresolved. |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants surfaced during scan | All 6 ACs are testable (AC-1 cio-sees-all, AC-2 scoping, AC-3 401 on bad auth, AC-4 empty list, AC-5 5-field response, AC-6 no per-program 403). Risk #3 (program_visibility open-aggregate semantics) is documented and testable. Risk #2 (persona resolution latency) is measurable. Risk #4 (logging PII) is preventable via test. Risk #6 (error handling) has a clear pattern. Edge cases: empty programs list (AC-4 with hint-placeholder-count=6), missing programs in DB (Risk #1 mitigation), persona resolution failure (Risk #6 mitigation). **Risk #5 (field-set mismatch) is CONFIRMED by mockup validation and AC-5 is now in doubt.** | 78/100 | Complexity is moderate and 5 of 6 ACs are clear and testable. AC-5 (the 5-field response) is contradicted by the mockups and cannot be tested until C-1 is answered. Also: Risk #3 (open-aggregate semantics) requires careful documentation to avoid downstream confusion. |
| **Performance** | 15% | Story has explicit perf budget; work fits within | NFR-002 (whole-request ≤2s) is the inherited budget; programs-api (persona resolution + DB query) should be negligible (<200ms). Dataset size ~9 programs (per NFR-004), no pagination needed. Query pattern: SELECT ... WHERE program_id IN (?), indexed lookup on program_id (unique constraint exists). Persona resolution is cached (300s TTL, <1ms warm, <100ms cold on Tier-3). No N+1 queries, no unbounded fan-out. Story p95 < 300ms budget is conservative and achievable. | 88/100 | In-process logic, cached persona resolution, single DB query with index. No unbounded operations. Risk #2 (cold persona resolution latency) is mitigated by budget headroom (p95 300ms > query latency estimate 150ms). Minor: no perf-test case specified in story (like AUTH-02's TC-12/13); implementer should add a latency benchmark to /arh-validate-feature. |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | All three upstreams (AUTH-01, AUTH-03, BED-01) are complete and merged to main. Downstream consumers (PGD-01, EMD-01) are not yet implemented; they will gate on AUTH-04's contract. No external integrations needed (no third-party SaaS, no additional IdP calls). Keycloak (AUTH-01 upstream) is confirmed operational. Postgres is available. | 90/100 | Upstreams are stable and locked. No external blockers. Downstreams will depend on this endpoint; contract must remain stable. Minor: if AUTH-01 changes the program-group prefix or groups claim parsing, AUTH-04 will need revision (unlikely, contract is locked in auth.md). |

**Weighted Total**: (90 × 0.25) + (72 × 0.20) + (78 × 0.20) + (88 × 0.15) + (90 × 0.20)  
= 22.5 + 14.4 + 15.6 + 13.2 + 18  
= **83.7 / 100**

### Verdict & Conditions

**VERDICT: GO-WITH-CONDITIONS** — **CERTIFIED 2026-08-31**: the single open clarification (C-1) is resolved by ADR-0005; see § Clarification Resolutions. Conditions 1–5 below remain live and carry into the PRD.

**Score: 84/100 (rounded)**

**Conditions for proceeding to /arh-plan-requirements:**

0. ~~**BLOCKING — answer C-1** (Risk #5)~~ — **DONE 2026-08-31**: settled as Option C (split) with `current`/`rowStyle` client-derived. Recorded as **ADR-0005** (`docs/adr/0005-programs-api-switcher-shape.md`) and reflected in the `programs-api` contract. This API layer does return pre-formatted values (`href`, `dotStyle`), with a narrow documented exception for route-dependent state.

1. **Specify logging event payload** (Risk #4): Define the exact field set for `programs_list_returned` event before implementation:
   - `{user_id, persona, returned_count, timestamp}`
   - No email, no groups, no request path (PII audit per .claude/rules/security-baseline.md)
   - Write a unit test (like AUTH-02's TC-15) asserting the payload key set equals the allowlist exactly

2. **Document program_visibility semantics** (Risk #3): In the endpoint docstring and/or PRD Decision log, clarify that:
   - program_visibility is a veto gate (passes for any authenticated session)
   - Actual scoping happens via the WHERE clause (program_id IN current_user.programs)
   - Downstream consumers must check session.programs directly, not rely on program_visibility's result

3. **Error handling for persona resolution** (Risk #6): Confirm approach for handling PersonaNotFoundError and PersonaResolutionError:
   - **Recommended**: catch both, log at WARN level, return HTTPException(403, "Access denied") — fail-closed, consistent with AUTH-03
   - **Rationale**: from client perspective, "cannot verify persona" is indistinguishable from "persona not allowed"; both deny access
   - Write a unit test: mock persona_resolver timeout, verify endpoint returns 403

4. **Performance baseline test** (Risk #2): Before implementation, add a performance test case to /arh-validate-feature:
   - Seed DB with ~100 programs (2x the expected org size)
   - Mock a non-cio persona with programs = [subset of 50]
   - Measure end-to-end latency (persona resolution + DB query + response serialization)
   - Assert p95 < 300ms; capture baseline for future optimization stories

5. **Defensive programming for missing programs** (Risk #1): Document (in code comments) the assumption that a program_id in session.programs might not exist in the DB:
   - The WHERE clause will filter it out (not raise an error)
   - If a program_id disappears from program_summary (garbage collection or data issue), the user's program list shrinks gracefully
   - Log a WARN event if returned_count < len(session.programs) (signals a data discrepancy for ops investigation)

---

## Synthesis

AUTH-04 implements a persona-scoped program list endpoint consuming three stable upstream contracts (session, RBAC checks, db-schema). **The story is achievable**: all dependencies are merged and tested, **the response field set is validated and locked by the PGD-01 mockup** (program_id, name, icon, type, description), the database schema exists, and the RBAC gate is correct (open-aggregate, no per-program denials). **Complexity is low-to-moderate**: simple scoping logic (filter by session.programs for non-cio, return all for cio), single DB query with indexed lookup, cached persona resolution. **Main risks are observability and domain semantics**: logging payload must be PII-clean, persona resolution error handling must be fail-closed, and downstream teams must understand that program_visibility is a veto gate, not a roster source. **Conditions are straightforward** (specify logging payload, document open-aggregate semantics, confirm error handling, add performance baseline, implement pre-formatted values per mockup contract). **No architectural blockers, no missing external dependencies, no new stack skills needed.** Proceed to /arh-plan-requirements after conditions are resolved.

---

## Top 3 Risks

1. **High: Response field set contradicts the switcher mockups** (Integration, HIGH) — `GET /api/programs` feeds `progOptions`/`projOptions`, bound as `{label, href, dotStyle, rowStyle, current}`; the story specifies the single-program header shape `{program_id, name, icon, type, description}`. `type`/`description` are unbound in the list, `current`/`rowStyle` have no source. **Mitigation**: unresolved — raised as an open clarification for user decision; blocks certification.

2. **Medium: Persona resolution latency under cold cache** (Performance, MEDIUM) — First request with a new role (cold Tier-3 query) could add 50-100ms to the endpoint. Budget is p95 < 300ms; estimate is 150-200ms total (persona + query + serialization), leaving margin, but no explicit test case. **Mitigation**: Add a performance test with ~100 programs and cold persona resolve; measure end-to-end latency; capture baseline.

3. **Medium: program_visibility open-aggregate semantics confusion** (Domain, MEDIUM) — The RBAC check passes for all authenticated sessions (no persona check, no program_id branching). Downstream consumers (PGD-01, EMD-01) must understand this is a veto gate, not a roster source, or they could confuse the 200 response with affirmative program membership. **Mitigation**: Document the semantics clearly in the endpoint docstring; clarify in code review that scoping is done via WHERE clause, not the RBAC check.

4. **Medium: Logging payload PII compliance** (Observability, MEDIUM) — Story logs `programs_list_returned` event; payload must be PII-clean (persona, returned_count, user_id, timestamp — no email, groups, request path). If an implementation accidentally includes a sensitive field, it violates NFR-011 + security-baseline. **Mitigation**: Specify exact payload before implementation; write a unit test (like AUTH-02's TC-15) asserting the key set matches allowlist exactly; code-review gate for PII leakage.

---

## Top 3 Recommendations

1. **Settle the switcher response contract before `/arh-plan-requirements`** — the mockups bind `{label, href, dotStyle, rowStyle, current}`, the story specifies `{program_id, name, icon, type, description}`. This is a user decision (§ Clarifications), not an implementer's: it determines whether this endpoint returns pre-formatted CSS, and whether `type`/`description` belong to a different endpoint. Record the outcome as an ADR.

2. **Fail closed on persona resolution errors** — When persona_resolver raises an exception (timeout, unmapped role), catch it, log at WARN level, return HTTPException(403, "Access denied"). This aligns with AUTH-03's fail-closed philosophy and prevents transient resolver outages from 500-erroring the endpoint.

3. **Add a performance baseline test** — Create a unit test that seeds ~100 programs, mocks a cold persona resolve, and measures end-to-end latency. Ensure p95 < 300ms. Capture the baseline now, so if future pagination/filtering stories degrade perf, you'll detect it immediately.

---

## Clarifications

<!-- All clarifications resolved 2026-08-31. C-1 was the sole open item; it is settled by
     ADR-0005 (docs/adr/0005-programs-api-switcher-shape.md). Detail in the next section.
     This section is intentionally empty so the phase-preconditions clarification gate passes. -->

## Clarification Resolutions

### C-1 — What shape does `GET /api/programs` return? — **RESOLVED 2026-08-31**

**Decision: Option C (split), with route-dependent state client-derived.** Recorded as
**ADR-0005** per condition 0. User decision, taken in `/arh-plan-requirements` Phase 0.

`GET /api/programs` returns `{ program_id, label, href, dotStyle }` — the fields the switcher list
actually binds — and nothing else.

| Field | Origin | Note |
|---|---|---|
| `program_id` | domain identifier | keys `program-detail-api`'s path; the switch/routing need in FR-PD-03, FR-EM-02 |
| `label` | mockup `o.label` | AC-5's `name` under the binding's name |
| `href` | mockup `o.href` | derived server-side from `program_id`; pre-formatted per the design README |
| `dotStyle` | mockup `o.dotStyle` | pre-formatted CSS, not an icon name or URL |

Two sub-decisions:

1. **`type` and `description` leave this endpoint.** Both are already carried by
   `program-detail-api` § `header (icon, name, type, description)` and `persona-shell` §
   `program_context: { icon, name, type, description }` — the payloads whose mockups actually bind
   them. No contract gains a field; this list sheds two it never bound. **Story AC-5 is superseded
   by ADR-0005 on this point** — the story file is not edited (it is `Status: Validated`; re-opening
   would force re-validation), so the PRD carries the corrected set with ADR-0005 as its authority
   and the story edit is carried forward.
2. **`current` and `rowStyle` are client-derived** (the unresolved sub-question, now answered). The
   switcher compares each item's `href` against the current route. These are properties of *where
   the user is*, not of a program, and the endpoint receives no active-program input —
   AUTH-01's `session` contract is stateless by NFR, so there is nowhere for the server to learn it
   without a presentation-only query parameter. This is a deliberate, narrow exception to the
   design README's "values arrive pre-formatted" decision, scoped to route-dependent state only.

Contract updated: `docs/requirements/api.md` § `programs-api` now carries `fields`, `authority`,
`excluded`, and `client_derived` keys. The absent `fields` key was the root cause of C-1.

Resolved by the story's Decision log, unchanged:
- No pagination: ~9 programs per NFR-004 seed fixture, no BED-02 dependency
- Performance budget: p95 < 300ms (inherited from NFR-002)
- Scoping source: session.groups (parsed as session.programs in CurrentUser), sole source of truth
- Logging: `programs_list_returned` event (payload allowlist per condition 1)

---

## State Write (Mandatory)

The following state fields for `docs/state/features.json["AUTH-04"]` are now updated:

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-08-31T00:00:00Z"
}
```

**Preserved fields** (not modified): `story`, `story_priority`, `story_independent_test`, `needs_clarification_count`, `rtm_source_sha`, `tracker_story`.
