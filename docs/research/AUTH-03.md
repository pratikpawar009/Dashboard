# Research Assessment: AUTH-03 — RBAC check library (org-access, program-visibility, individual-usage, member-in-program, governance)

**Story ID**: AUTH-03  
**Epic**: AUTH  
**Priority**: P1  
**Upstream dependencies**: AUTH-01 (session contract), AUTH-02 (persona-resolver contract)  
**Downstream dependencies**: AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06 — 16 stories consuming the `rbac-checks` contract  
**Assessment Date**: 2026-08-31  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**Both upstream dependencies complete and researched:**
- **AUTH-01** (research verdict: GO-WITH-CONDITIONS, score 81/100, impl: complete): provides the `session` contract at `docs/requirements/auth.md` § session with `user_id, email, role, groups, programs` fields. Implementation live: bearer-JWT validation, role parsing, program-group parsing (prefix "program-" by default).
- **AUTH-02** (research verdict: GO-WITH-CONDITIONS, score 89/100, impl: complete): provides the `persona-resolver` contract at `docs/requirements/auth.md` § persona-resolver. Implementation live: 3-tier resolver (env → YAML → Postgres) with 300s per-role cache, asyncio.Lock-guarded, fully tested (16 test cases including concurrency, timeout, PII audit).

**No architectural blockers.** AUTH-01's session and AUTH-02's persona resolver are production-ready, integrated into the codebase, and tested. The five RBAC checks defined in AUTH-03's ACs branch on `persona` (from AUTH-02's resolver) and `role`/`groups` (from AUTH-01's session), both available as injectable dependencies.

**Clarification resolved:** The 2026-08-31 user decision log entry resolves the governance-visibility logging scope: the check emits `rbac_check_governance_visibility` recording BOTH authorized and denied outcomes (not denial-only), propagated to the `rbac-checks` contract in `docs/requirements/auth.md`. This is now locked and mirrors the pattern of `rbac_check_org_access`.

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean, main branch, feature/AUTH-01 merged)
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, pytest-asyncio, Postgres 16
- **Auth status**: AUTH-01 complete (OIDC, bearer JWT, dev-bypass all in place); AUTH-02 complete (persona resolver, caching, logging)

### Backend Session Contract (From AUTH-01 Implementation)
- **`app/core/auth.py`** — `CurrentUser` dataclass: `user_id: str, email: str, role: str, groups: list[str], programs: list[str]`
- **Session injection**: `get_current_user()` FastAPI dependency returns `CurrentUser` from verified JWT claims
- **All five RBAC checks will consume this contract** in their route handlers

### Persona Resolver (From AUTH-02 Implementation)
- **`app/core/persona_resolver.py`** — `PersonaResolver` singleton on `app.state.persona_resolver`
- **Interface**: `async def resolve(self, role: str) -> str` (raises `PersonaNotFoundError` or `PersonaResolutionError`)
- **Cache**: per-role 300s TTL, asyncio.Lock-guarded, per-worker
- **Logging**: `persona_mapping_loaded` event with `{role, persona, tier, tier3_latency_ms?}`
- **All five RBAC checks call this resolver** before gating decisions (except AC3, which doesn't use persona)

### Logging Infrastructure (Verified Working)
- **`app/core/logging.py`** — `JSONFormatter` merges `extra={...}` into the JSON payload
- **Verification**: Direct test confirms extra fields are included (custom_field, another, etc. appear in JSON output)
- **Test coverage**: `tests/unit/test_persona_resolver.py::test_persona_mapping_loaded_event_contains_no_pii_tc15` explicitly validates payload structure
- **Note**: Initial task concern about BED-02's logging silently dropping `extra` is **INCORRECT** — logging works as designed

### RBAC Check Shapes (From Story AC1-AC7)

| Check | Input | Decision Logic | Logging |
|-------|-------|-----------------|---------|
| **org_access** (AC1-AC2) | `persona` | `persona == "cio"` | `rbac_check_org_access` (both outcomes) |
| **program_visibility** (AC3) | none — always pass | Open-aggregate: any authenticated session | No logging event (AC3 silent) |
| **individual_usage_visibility** (AC4) | `user_id`, `email`, `target_user_id` | `target_user_id == user_id OR persona == "cio"` | `individual_view_denied` (denial only) |
| **member_in_program_visibility** (AC5) | `user_id`, `program_id`, `target_member_id` | `program_visibility(program_id) AND (target_member_id == user_id OR persona == "cio")` | `member_view_denied` (denial only) |
| **governance_visibility** (AC6-AC7) | `persona`, `program_id?` | `persona in {architect, product-manager, developer}`; if program_id: also `program_visibility(program_id)` | `rbac_check_governance_visibility` (both outcomes) |

### Test Pattern (From AUTH-02)
- **`tests/unit/test_persona_resolver.py`** — 16 test cases covering: tier precedence, cache hits/expiry, concurrency (10 coroutines collapse to 1 query), timeouts, PII audit, Tier-2 YAML errors
- **Fixtures**: `FakeSessionFactory`, `migrated_db`, `test_engine`, `test_session`, log capture via `_RecordCapturingHandler` and `_capture_logger`
- **AUTH-03 should follow the same pattern** for its five checks

### Toolchain & Preflight
- **Python 3.11+**: ✓
- **FastAPI 0.115, SQLAlchemy 2.0, pytest-asyncio**: ✓ all installed
- **No new dependencies required for AUTH-03**: all checks are in-process, CPU-bound, no external calls

### Design Patterns in the Codebase
- **Per-app state**: `app.state.persona_resolver` (AUTH-02), `app.state.jwks_cache` (AUTH-01) — AUTH-03's checks are stateless, no state needed
- **Async/await**: All auth paths are async; RBAC checks should be `async` functions too for consistency
- **Dependency injection**: FastAPI `Depends()` for `get_current_user`; AUTH-03 checks can be thin async functions called from route handlers (or bundled into a `depends`-injectable RBAC service)
- **Error handling**: HTTPException(status_code=403, detail=<reason>) for denied access; existing error envelope in `app/core/errors.py` handles routing
- **Logging**: `logger.info("event_name", extra={...})` for structured events; JSONFormatter merges into payload

### Routes Consuming RBAC Checks (Downstream, Not Yet Written)
- **org_access**: `/api/overview/*` routes (AUTH-04, future)
- **program_visibility**: All program-scoped routes (PGD-01..06, future)
- **individual_usage_visibility**: User-self data endpoints (OVW-01..04, future)
- **member_in_program_visibility**: Program member detail endpoints (future)
- **governance_visibility**: Governance/audit routes (SHP-02..06, future)
- **Note**: No route using these checks exists yet; checks are pure-function validation

---

## Pattern Map

### Existing Code to Extend
- **`app/core/auth.py`** — `CurrentUser` dataclass is the source of `user_id`, `email`, `role`, `groups` for RBAC checks; no change needed (contract is stable)
- **`app/core/logging.py`** — existing `JSONFormatter` supports `extra={...}` fields (verified working); no change needed
- **`app/core/config.py`** — no RBAC-specific config needed (in-process, no timeouts or thresholds to tweak)
- **`app/core/errors.py`** — existing error envelope will catch RBAC denials (HTTP 403); no change needed

### Existing Patterns to Follow
- **Async dependency injection** (AUTH-01): `get_current_user()` style — RBAC checks can be callable async functions injected via `Depends()`
- **Persona resolution** (AUTH-02): call `app.state.persona_resolver.resolve(role)` within a check, handle `PersonaNotFoundError` (fail-closed: raise HTTPException 403 or 500, decision TBD)
- **Structured logging** (APP-wide): `logger.info("event_name", extra={fields...})` with exact field allowlist per event (FR-based or decision log)
- **Concurrency safety** (AUTH-02): asyncio.Lock for shared state (RBAC checks have no shared mutable state, so this doesn't apply here)

### New Files to Create
- **`app/core/rbac.py`** — the library: five check functions (`org_access`, `program_visibility`, `individual_usage_visibility`, `member_in_program_visibility`, `governance_visibility`), each signature `async def check_*(current_user: CurrentUser, ...) -> bool | raises HTTPException` or a unified `RBACService` class
- **`app/schemas/rbac.py`** (optional) — Pydantic models if checks accept structured request bodies (currently all checks are pure-function, no request body, so this may be unnecessary)
- **`tests/unit/test_rbac.py`** — unit tests: one per check, covering pass/deny branches, logging event emission, persona resolution errors, edge cases (empty groups, missing persona, etc.)

### Shared Code at Risk
- **`app/core/auth.py::CurrentUser`** — role and groups fields are critical for org_access and governance_visibility checks; any drift (e.g., role becomes roles list) would ripple downstream to AUTH-03
- **`app/core/persona_resolver.py`** — resolver must not raise an unexpected exception type; AUTH-03 must handle `PersonaNotFoundError` and `PersonaResolutionError` correctly (fail-closed per AC4)
- **`app/core/config.py`** — if new config (e.g., a deny-list of roles for governance check) is needed, it must be settable via env, not hardcoded
- **Logging in multiple modules** — if RBAC checks call persona_resolver, two events will be emitted per check: `persona_mapping_loaded` (from AUTH-02) and `rbac_check_*` or `*_view_denied` (from AUTH-03). No collision, but observability dashboard must ingest both

### ASCII Diagram: Five RBAC Checks Flow

```
FastAPI route handler (future: OVW-01, PGD-01, etc.)
  ├─→ current_user = Depends(get_current_user)  [AUTH-01: verified JWT, role/groups parsed]
  │
  ├─→ Check 1: org_access(current_user)
  │   │ persona = await resolver.resolve(current_user.role)  [AUTH-02]
  │   │ if persona != "cio": raise HTTPException(403, "denied")
  │   │ log: rbac_check_org_access with {user_id, persona, outcome}
  │   │
  ├─→ Check 2: program_visibility(current_user, program_id)
  │   │ if not current_user.programs: raise PersonaNotFoundError? No — auth'd = pass
  │   │ (no persona resolution; open-aggregate per A-004)
  │   │ if current_user.programs: pass (no logging event)
  │   │
  ├─→ Check 3: individual_usage_visibility(current_user, target_user_id)
  │   │ if current_user.user_id == target_user_id: pass
  │   │ else:
  │   │   persona = await resolver.resolve(current_user.role)
  │   │   if persona != "cio": raise HTTPException(403, "denied")
  │   │   log: individual_view_denied with {user_id, target_user_id}
  │   │
  ├─→ Check 4: member_in_program_visibility(current_user, program_id, member_id)
  │   │ if not program_visibility(program_id): raise HTTPException(403)  [AC5 prereq]
  │   │ if current_user.user_id == member_id: pass
  │   │ else:
  │   │   persona = await resolver.resolve(current_user.role)
  │   │   if persona != "cio": raise HTTPException(403, "denied")
  │   │   log: member_view_denied with {user_id, program_id, member_id}
  │   │
  └─→ Check 5: governance_visibility(current_user, program_id=None)
       │ persona = await resolver.resolve(current_user.role)
       │ if persona not in {architect, product-manager, developer}:
       │   raise HTTPException(403, "denied")
       │   log: rbac_check_governance_visibility outcome=denied with {user_id, persona}
       │ else:
       │   if program_id:
       │     if not program_visibility(program_id): raise HTTPException(403)  [AC7 prereq]
       │   log: rbac_check_governance_visibility outcome=authorized with {user_id, persona}
```

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Domain** | HIGH | **AC3 (program_visibility) open-aggregate model intentional per A-004, but tracked as risk R-003 in PRD.** Any authenticated session passes; program_id is never consulted for gating. This is a deliberate architectural decision, but creates operational risk: a user in one program can see program-scoped data from any program (within roles/UI filtering). The check itself is trivial (always pass for auth'd), but the risk exists at the feature level. | (1a) **Verify with PO** that R-003 (open-aggregate architectural risk) is an accepted risk, not a blocker for AUTH-03. (1b) **No code change needed** — the check is correct per A-004/AC-3. (1c) **Document the risk in the PLAN** as inherited from ADR/PRD; AUTH-03 implements the check as specified, not "more secure" than A-004 allows. |
| 2 | **Integration** | HIGH | **PersonaResolutionError vs. PersonaNotFoundError handling.** When a check calls `resolver.resolve(role)`, two exceptions can be raised: (i) `PersonaNotFoundError` (all tiers missed — role unmapped), (ii) `PersonaResolutionError` (Tier-3 timeout or connectivity). Auth-03 must decide: (a) fail the request (403/500)? (b) log the error and retry? (c) apply a fallback persona? The spec does not prescribe this. If wrong, a transient DB hiccup could lock out users (if 500) or a bad role mapping could crash the route (if unhandled). | (2a) **Decision required before implementation**: How should AUTH-03 checks handle a PersonaResolutionError? Options: (i) fail the request with 500 (fail-open, bad for security), (ii) fail the request with 403 (fail-closed, safe), (iii) log the error and apply a default-deny decision (safest). Suggest (ii): catch PersonaResolutionError and raise HTTPException(403) — fail-closed, consistent with AC4 (all unmapped → fail). (2b) **Document the decision in PLAN** and add a test case: mock resolver timeout, verify route returns 403 (not 500). (2c) **Distinct from PersonaNotFoundError**: an unmapped role should return 403 + log `rbac_check_*` event (error recorded). A timeout should also return 403 but with a different log event or log level (warning vs. error). |
| 3 | **Observability** | HIGH | **Logging payload compliance with security baseline.** Each check emits 0-2 events: `rbac_check_org_access` (both outcomes), `rbac_check_governance_visibility` (both outcomes), `individual_view_denied` (denial only), `member_view_denied` (denial only). Payload must never include PII: email, groups claim, JWT claims, session ID, request path. Only non-PII fields: `user_id, persona, outcome, program_id?` — exactly per the `rbac-checks` contract logging section or the story's test mapping. If an implementation accidentally logs a sensitive field (e.g., request.user email), it violates NFR-011 (audit logging) and security-baseline (no PII). | (3a) **Specify exact payload per event** before implementation (unit test allowlist, like TC-15 for persona_resolver). Suggest: `rbac_check_org_access: {user_id, persona, outcome, timestamp}`; `rbac_check_governance_visibility: {user_id, persona, outcome, timestamp}`; `individual_view_denied: {user_id, target_user_id, outcome, timestamp}`; `member_view_denied: {user_id, program_id?, target_member_id, outcome, timestamp}`. (3b) **Unit test per event** (like TC-15): assert payload keys = allowlist exactly, no extra fields. (3c) **Code review gate**: audit every log line in rbac.py for PII leakage. |
| 4 | **Performance** | HIGH | **Persona resolution per-check N+1 risk.** If a route applies multiple RBAC checks (e.g., program_visibility AND member_in_program_visibility), each will call `resolver.resolve(role)`. Under ideal conditions (warm cache), each call is O(1) <1ms. Under cold-cache (first request, new role), each call is O(1) dict lookup + one Tier-3 query + one cache miss. Multiple cold calls for the same role in a single request could hit Tier-3 multiple times if not coordinated. AUTH-02's resolver's asyncio.Lock prevents concurrent resolve calls from duplicating queries within a single role, but does NOT deduplicate across routes in a single request. | (4a) **Worst case**: a route applies org_access + governance_visibility to the same request; both resolve(role), both hit cold Tier-3 (unlikely, role is same). The cache is per-role, so the second call hits warm cache (<1ms). No N+1 here. (4b) **If routes apply checks to different resources** (e.g., check A for resource X, check B for resource Y, both from the same session role), they'll both resolve the same role and hit cache. (4c) **Implementation recommendation**: Consider a request-scoped memo (e.g., a dict on the request context) to deduplicate resolve calls within a single request. Defer this optimization to a post-launch observability story if persona resolution latency becomes a bottleneck. Test and document cache hit rate / p95 during validation. |
| 5 | **Domain** | MEDIUM | **Empty groups claim vs. program_visibility.** AC3 states program_visibility passes for any auth'd session, "program id is not used for gating". But what if the session's `groups` claim is absent or empty (i.e., `current_user.programs = []`)? The check should still pass (auth'd = pass, per AC3), and the route handler should rely on other downstream filters to hide program-scoped data. But if the route handler confuses the RBAC check's silence (no veto) with an affirmative "this program is in my programs list", it could leak data. | (4a) **Document in rbac.py** that program_visibility is a veto gate (returns False only on certain conditions, True for auth'd), not a roster query. (4b) **Add a test case**: call program_visibility with `current_user.programs = []`, verify it returns True (or raises no exception). (4c) **Route-handler documentation** (to be written by downstream teams): RBAC checks are veto gates, not data sources; use `current_user.programs` directly if you need the list. |
| 6 | **Dependency** | MEDIUM | **Downstream 16 stories depend on this contract being stable.** AUTH-04, OVW-01..04, PGD-01..06, SHP-02..06 will call RBAC check functions. Any signature or behavior change after they're implemented will ripple. The `rbac-checks` contract is locked in the requirements file, but implementation must match exactly: function names, parameter order, exception types, logging event names. If a developer renames `org_access()` to `check_org_access()`, downstream code breaks. | (6a) **Lock the contract in PLAN**: exact function names, signatures, exception types, log event names. (6b) **No breaking changes in implementation**: the PLAN will define this; the implementation must not deviate. (6c) **Automated contract test** (optional, deferred): a downstream story (OVW-01) can unit-test it imports and calls the RBAC functions with the right signature; CI would catch breakage. For now, rely on code review to enforce the contract. |
| 7 | **Domain** | MEDIUM | **AC5 chaining: member_in_program_visibility depends on program_visibility.** AC5 reads "program_visibility AND (self OR cio)". This means: (1) call program_visibility first, (2) if it denies, member_in_program_visibility denies too. Implementation must call program_visibility(program_id) inside member_in_program_visibility; if it returns False (or raises), member_in_program_visibility should raise HTTPException 403 the same. This is straightforward in code but easy to miss in testing: a test that skips step 1 would hide a bug in step 2. | (7a) **Implementation**: member_in_program_visibility must explicitly call program_visibility(program_id) and handle its result (exception or return value). (7b) **Test case**: AC5 test should verify: (i) when program_visibility would deny, member_in_program_visibility denies too (even if "self" matches); (ii) when program_visibility passes and "self" matches, member_in_program_visibility passes; (iii) when program_visibility passes and "self" doesn't match but persona is "cio", passes. |
| 8 | **Domain** | MEDIUM | **AC6 persona list: architect, product-manager, developer (not cio, engineering-manager).** AC6 explicitly excludes cio and engineering-manager from governance access. This is a hardcoded list in the code (unlike persona resolver's data-driven approach). If a new persona is added to the system (e.g., "qa-lead"), someone must remember to update the hardcoded list in the governance_visibility check, or the check will silently deny valid users. | (8a) **Implement as a hardcoded tuple in rbac.py** (comment explaining why it's hardcoded: hardcoded list per FR-AUTH-09, contrast with persona resolver's data-driven approach). (8b) **Test case AC6**: iterate the hardcoded list, verify each persona passes governance_visibility; iterate personas NOT in the list (cio, engineering-manager), verify they're denied. (8c) **Future enhancement** (deferred): if governance access becomes config-driven (e.g., ops can add/remove personas), promote the list to Settings + env var. For now, hardcoded is acceptable. |
| 9 | **Observability** | LOW | **Log event outcome field semantics.** The contract specifies `rbac_check_*` events record "both authorized and denied outcome", but does not specify the `outcome` field's exact value (e.g., "authorized" vs. "denied", or "true" vs. "false", or a reason like "role_not_cio"). Unclear semantics could confuse downstream parsing (dashboards, audit tools). | (9a) **Standardize outcome values** in the PLAN: suggest `outcome: "authorized" | "denied"` or `outcome: true | false`. The JSON log event can include additional fields like `reason: "role is cio"` or `reason: "role is not in {architect, product-manager, developer}"` to enrich audit trails. (9b) **Test case per event**: assert outcome field is one of the expected values, and reason field (if present) is non-empty/meaningful. (9c) **Document in rbac.py module docstring** the semantic of each event's outcome. |
| 10 | **Performance** | LOW | **HTTP 403 status code decision for all denials.** AC1-AC7 all use 403 for denied access. This is correct per HTTP semantics (403 = "Forbidden", authentication succeeded but authorization failed). However, the story does not specify what status code persona resolution errors should use. If a Tier-3 timeout returns 500 (internal error), that differs from 403 (access denied). The client's retry logic differs: 500 → eventual retry, 403 → immediate fail. | (10a) **Decision**: PersonaResolutionError (timeout/connectivity) should return 403 (fail-closed), not 500. Mitigation #2 above resolves this. (10b) **Rationale**: from the user's perspective, "I cannot verify your permissions" is functionally equivalent to "your permissions don't allow this" — both deny access. Returning 500 encourages retry, which could mask a persistent misconfiguration (bad persona mapping). Returning 403 is fail-closed. (10c) **Test case**: mock a Tier-3 timeout, verify route returns 403 (and logs an error event, not a success event). |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Criterion | Evidence | Score | Notes |
|-----------|--------|-----------|----------|-------|-------|
| **Integration** | 25% | All upstream dependencies available; failure modes understood | AUTH-01 (session: user_id, email, role, groups verified) and AUTH-02 (persona resolver, caching, logging) both complete and live on main branch; error handling seam in place (HTTPException(403)); all five checks are call-graph traceable to CurrentUser fields and resolver.resolve(); no undocumented dependencies. Risk #2 (PersonaResolutionError handling) requires a decision, but mitigation is straightforward (fail-closed: return 403). | 85/100 | Auth-01/02 contracts are stable and proven (80 test cases across them). Missing: explicit handling spec for PersonaResolutionError (caught before implementation). |
| **Compatibility** | 20% | Backward compat plan exists for each affected client/version | Greenfield RBAC library (first-written, no legacy); downstream stories (16 total) are not yet implemented, so no existing code to break. Contract is locked in requirements file and story; signature drift will be caught at review time. | 95/100 | No legacy code to maintain. Contract is clear. Downstream stories will gate on this contract. |
| **Domain** | 20% | Edge cases enumerated; no hidden invariants surfaced during scan | All 7 ACs are testable (AC1-2: org_access persona check, AC3: program_visibility open-aggregate, AC4-5: individual/member visibility self-or-cio, AC6-7: governance persona list + program-visibility chaining). Risk #1 (open-aggregate per A-004) is an accepted architectural decision, not a bug. Risk #3 (PII in logs) is preventable via test (like TC-15 for persona_resolver). Risk #5 (empty groups) is a doc-and-test case. Risk #7 (AC5 chaining) is straightforward logic. Risk #8 (AC6 hardcoded list) is expected (contrast with persona resolver's data-driven). Risks are all mitigatable or documented. | 82/100 | Complexity: five checks with persona resolution on each, cascading dependencies (AC5, AC7), exact logging payloads, edge cases. All ACs traceable; no hidden logic. Minor: outcome field semantics (Risk #9) need standardization. |
| **Performance** | 15% | Story has explicit perf budget; work fits within | NFR-002 (whole-request ≤2s) applies; RBAC checks inherit this budget. In-process, no I/O, no network calls. Persona resolution cached (300s per-role, <1ms warm cache). Each check is O(1) complexity: persona resolve (cached), string comparison, HTTP exception raise. Risk #4 (N+1 persona resolves) is mitigated by AUTH-02's cache + asyncio.Lock (one query per role per TTL). No query bottleneck. | 88/100 | In-process, cached persona resolver, O(1) per check. NFR-002 budget applies; auth component should be negligible. No perf-test case specified in story (like AUTH-02's TC-12/13), but caching strategy is proven. |
| **Dependency** | 20% | All upstream stories complete; no blocking external work | AUTH-01 (complete, stable), AUTH-02 (complete, stable). Downstream 16 stories are not yet in research; they will depend on AUTH-03's contract. No external integrations needed (in-process checks). Keycloak (AUTH-01 upstream) is confirmed operational. | 88/100 | Upstreams stable. Downstreams gate on AUTH-03; contract must be locked and stable. No external risks (no third-party SaaS). Minor: if downstream stories reveal a contract mismatch during implementation, AUTH-03 may need a revision — unlikely given test coverage to come. |

**Weighted Total**: (85 × 0.25) + (95 × 0.20) + (82 × 0.20) + (88 × 0.15) + (88 × 0.20)  
= 21.25 + 19 + 16.4 + 13.2 + 17.6  
= **87.45 / 100**

### Verdict & Conditions

**VERDICT: GO-WITH-CONDITIONS**

**Score: 87/100 (rounded)**

**Conditions for proceeding to /arh-plan-requirements:**

1. **Clarify PersonaResolutionError handling** (Risk #2): Confirm whether RBAC checks should catch `PersonaResolutionError` (Tier-3 timeout) and return HTTP 403 (fail-closed, recommended) or 500 (fail-open). Decision: suggest 403 + log at ERROR level. Document in story DECISIONS.md: "2026-08-31 PersonaResolutionError handling: return HTTP 403 (fail-closed) + log at ERROR level. Rationale: fail-closed aligns with AC4 (unmapped role → deny). Timeout is operationally indistinguishable from an unmapped role from the client's perspective."

2. **Specify log event payloads** (Risk #3): Before implementation, define exact field set per event (allowlist-style, like AUTH-02's TC-15):
   - `rbac_check_org_access`: `{user_id, persona, outcome, timestamp}`
   - `rbac_check_governance_visibility`: `{user_id, persona, outcome, timestamp}`
   - `individual_view_denied`: `{user_id, target_user_id, outcome, timestamp}`
   - `member_view_denied`: `{user_id, program_id, target_member_id, outcome, timestamp}`
   - Add a unit test per event, asserting the payload key set equals the allowlist exactly (no PII, no extra fields).

3. **Document AC3 open-aggregate risk** (Risk #1): Confirm with PO that AUTH-03 implements AC3 as specified (any auth'd session passes, no persona check, program_id unused for gating) and that this is an accepted architectural risk per A-004 / PRD R-003. Update PLAN with: "2026-08-31 AC3 open-aggregate model is per ADR A-004 and tracked as risk R-003 in the PRD. AUTH-03 implements the check as specified. Downstream route handlers must not confuse the check's pass-through for an affirmative 'program in my programs list'; use CurrentUser.programs for the roster."

4. **Specify outcome field semantics** (Risk #9): Define the `outcome` field in log events (suggest: `"authorized" | "denied"` as strings), and optionally add a `reason` field for enriched audit trails (e.g., `reason: "role is not in {architect, product-manager, developer}"`).

5. **Write unit tests before implementation** (test-driven):
   - One test per check (5 core checks): pass and deny branches, logging event emission, persona resolution happy path
   - Edge cases: empty groups, missing persona (PersonaNotFoundError), Tier-3 timeout (PersonaResolutionError)
   - AC5 chaining test: program_visibility denial cascades to member_in_program_visibility
   - AC6 hardcoded list test: each persona in/out of the list is correctly gated
   - AC7 chaining test: governance_visibility calls program_visibility when program_id is present
   - PII audit test (like TC-15): each log event contains exactly the allowlisted fields, no request context or email/groups leakage

---

## Synthesis

**AUTH-03 is a well-scoped, achievable RBAC library story with stable upstream contracts and proven patterns in the codebase.** The five checks branch on `persona` (from AUTH-02's resolver) and `role`/`groups` (from AUTH-01's session), both production-ready and tested. The main complexity is **observability**: exact logging payloads per event, PII audit, outcome field semantics. Domain complexity is **moderate**: five checks with two cascading gates (AC5 → program_visibility, AC7 → program_visibility), hardcoded persona list, AC3's intentional open-aggregate model. Integration is **straightforward**: in-process, no I/O, no new dependencies, error handling seam in place. Performance is **excellent**: all checks are O(1), persona resolution is cached with <1ms warm-hit latency.

**Conditions are straightforward** (decide PersonaResolutionError handling, specify log payloads, document AC3 risk, test-drive the implementation). **No architectural blockers, no missing upstream code, no new external dependencies.** Downstream contract is locked (16 stories depend on this library); implementation must match the contract exactly. **Proceed to /arh-plan-requirements after conditions are resolved.**

---

## Top 3 Risks

1. **High: PersonaResolutionError handling undefined** (Integration, HIGH) — Tier-3 timeout or connectivity failure could raise `PersonaResolutionError`; story does not specify whether to return 403 (fail-closed, safe) or 500 (fail-open, unsafe). **Mitigation**: Decide and document before implementation (recommend: 403 + log at ERROR level, fail-closed aligns with AC4).

2. **High: Log event payload PII compliance** (Observability, HIGH) — Each check emits events; payload must never include email, groups claim, session ID, request context. If an implementation accidentally logs a sensitive field, it violates NFR-011 + security-baseline. **Mitigation**: Specify exact allowlist per event before implementation; write a unit test per event (like TC-15) asserting payload keys match allowlist exactly; code-review gate for PII leakage.

3. **High: Persona resolution N+1 under multiple checks per request** (Performance, HIGH) — If a route applies multiple RBAC checks (org_access + governance), both resolve(role) and could hit Tier-3 multiple times. While AUTH-02's cache mitigates for the same role, cold calls are still possible. **Mitigation**: Document the warm-cache latency (<1ms) in REQUIREMENTS.md; test and monitor persona resolution cache hit rate during validation; defer request-scope memoization to a post-launch optimization story if latency becomes a bottleneck.

---

## Top 3 Recommendations

1. **Lock the contract and test payloads before implementation** — Write a unit test per log event (5 core checks × 2-4 events = 8-10 tests) that asserts the exact payload structure (allowlist-style, like AUTH-02's TC-15). This forces clarity and prevents PII leakage.

2. **Fail closed on PersonaResolutionError** — Return HTTP 403 (not 500) when the persona resolver times out or has connectivity issues. This aligns with AC4's fail-closed philosophy and avoids encouraging retry for a persistent misconfiguration. Document the decision in PLAN.

3. **Test AC5 and AC7 chaining explicitly** — Member_in_program_visibility must call program_visibility first; governance_visibility must call program_visibility when program_id is present. Write test cases for each cascading path to catch missing calls at code-review time, not at validation.

---

## Clarifications

No new clarifications surfaced during this assessment. The story is validated (`needs_clarification_count: 0`) and the 2026-08-31 decision log entry has resolved the governance-visibility logging scope (emits both outcomes, locked in the `rbac-checks` contract). All ACs are clear and testable.

---

## State Write (Mandatory)

The following state fields for `docs/state/features.json["AUTH-03"]` are now updated:

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-08-31T00:00:00Z"
}
```

**Preserved fields** (not modified): `story`, `story_priority`, `story_independent_test`, `needs_clarification_count`, `rtm_source_sha`, `tracker_story`.

---
