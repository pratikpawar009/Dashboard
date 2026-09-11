# Feasibility Assessment: AUTH-07

**Story**: AUTH-07 — Session identity endpoint, app-wide logout, deterministic persona resolution  
**Status**: Research  
**Assessment Date**: 2026-09-10  
**Verdict**: GO-WITH-CONDITIONS  

## Upstream Dependencies

All three upstreams shipped and frozen (AUTH-01 bearer JWT + `CurrentUser`, AUTH-02 persona-resolver, AUTH-05 frontend token store + server relay pattern):
- AUTH-01: `/auth/login`, `/auth/callback`, `/auth/refresh`, `/auth/dev-bypass` (shipped; this story co-produces `session` contract)
- AUTH-02: `PersonaResolver`, 3-tier config, fail-closed semantics (shipped; this story extends tier plumbing and adds case-insensitivity + precedence)
- AUTH-05: `tokenStore.clearSession()`, `/login` route handler `redirect: "manual"` pattern (shipped)

Per phase-preconditions gate: all upstreams `research_verdict: GO-WITH-CONDITIONS` and phase `review` / `security-reviewed` — gate passes.

## Exploration Log

### Scanning CurrentUser consumers

**Search**: `grep -r "get_current_user|CurrentUser" app/api/`

**Result**: Three routes consume `CurrentUser`:
- `app/api/programs.py:71` — `current_user: CurrentUser = Depends(get_current_user)`; reads `.role` → `persona_resolver.resolve(current_user.role)` (line 88)
- `app/api/overview.py` — same pattern: `Depends(get_current_user)`, `.role` read for persona resolution
- `app/api/personal_usage.py:64` — same pattern

**Finding**: All three read the singular `role: str` field to invoke the persona resolver. AC-24's addition of `roles: list[str]` is a sibling field that does not break these callers (they continue reading `.role` post-story; the plural field is audit-only in `CurrentUser`).

### Tier-loader structure and config plumbing

**Code**: `app/core/persona_resolver.py` lines 168–173 (Tier-1 and Tier-2 lookups):
```python
tier1_map = self._settings.persona_role_map  # dict[str, str] | None
if tier1_map and role in tier1_map:
    return tier1_map[role], _TIER1_ENV, None

if role in self._tier2_map:  # dict[str, str] from YAML safe_load
    return self._tier2_map[role], _TIER2_YAML, None
```

**Configuration loading**:
- Tier-1: `settings.persona_role_map` is `dict[str, str] | None`, parsed from `PERSONA_ROLE_MAP` env JSON once at `Settings` load-time (app/core/config.py:23)
- Tier-2: YAML `safe_load(handle) or {}` at `PersonaResolver.__init__` (line 105) — produces `dict[str, str]`
- Tier-3: Postgres query `select(PersonaConfig).where(PersonaConfig.role == role).limit(1)` (line 189) — `PersonaConfig.role` is the primary key

**Finding**: All three tiers are currently hardcoded to `dict[str, str]` (role → persona). AC-20 requires a precedence order (`cio > architect > product-manager > engineering-manager > developer`) sourced from the same 3-tier mechanism. **The tier loaders must be restructured to carry BOTH a mapping dict AND an ordered precedence list**, or a separate precedence lookup must be added alongside the existing role→persona maps.

### Frontend origin for post_logout_redirect_uri

**Search**: `grep -r "OIDC_REDIRECT_URI\|frontend.*origin\|post_logout" services/api/.env.example`

**Result**:
- `OIDC_REDIRECT_URI=http://localhost:3000/callback` exists (for the frontend's own callback)
- **NO** env var for the frontend's origin or `/login` URL exists anywhere

**Code Check**: `app/core/config.py` `Settings` class — only `oidc_redirect_uri`, `oidc_client_id`, `oidc_client_secret`, `oidc_issuer` are auth-related env vars. No frontend-origin field.

**Finding**: AC-10/AC-12 require `post_logout_redirect_uri` to be the frontend's `/login` absolute URL (e.g., `http://localhost:3000/login`). The API has no way to know this value. **HIGH RISK** — missing config surface. Mitigation must include adding a new `FRONTEND_LOGIN_URL` or `OIDC_FRONTEND_ORIGIN` env var to `Settings`.

### Cache key structure (AC-23)

**Code**: `app/core/persona_resolver.py` lines 140–144 (cache lookup):
```python
cached = self._cache.get(role)
if cached is not None and time.monotonic() < cached[2]:
    persona, tier, _ = cached
```

**Finding**: The cache is keyed on the raw `role` string. AC-23 requires the cache key to be the **casefolded** role (lowercased form), so `Architect` and `architect` hit the same cache entry. The current code does not casefold.

### Alembic fileConfig logger trap

**Code**: `tests/conftest.py` docstring (AF-11 reference):
> Alembic's `fileConfig(disable_existing_loggers=True)` sweep disables every `app.*` logger process-wide.

**Test Pattern**: `tests/unit/test_persona_resolver.py` uses a custom `_RecordCapturingHandler` attached directly to the real logger and force-enabled/depropagated to work around the fileConfig trap. Same pattern in `tests/test_auth_logging_security.py`.

**Finding**: AC-25's new `persona_mapping_not_found` log event needs a test strategy that survives the fileConfig trap. The documented workaround is to attach a handler directly, not to rely on capsys or pytest's caplog.

### CurrentUser.name field population

**Code**: `app/core/auth.py` lines 228–231 (existing `_parse_role` function):
```python
groups_claim = claims.get("groups")
groups = list(groups_claim) if isinstance(groups_claim, list) else []
email = str(claims.get("email", ""))
```

**Finding**: The pattern for handling absent claims is already established: `claims.get("field")` with a default, then a type check and fallback. AC-2's `name` field must follow the same pattern (name → given_name+family_name → preferred_username → None).

### Personas and routes consuming `role`

**Search**: `grep -r "\.role" services/api/app --include="*.py" | grep -v test`

**Result**: 22 references total. Subset of real consumer code:
- `app/api/programs.py:88` — `persona_resolver.resolve(current_user.role)`
- `app/core/rbac.py` — `await persona_resolver.resolve(current_user.role)` (shared by 16 consumers per contract)

**Finding**: All consumers pass `current_user.role` (singular) to the resolver. The resolver's interface stays `async def resolve(self, role: str) -> str`, so backwards compatibility is maintained internally.

### Governance visibility check

**Code**: `app/core/rbac.py` line 196 (per story mention):
> `_GOVERNANCE_PERSONAS` is defined there

**Decision**: Per story Decision log (2026-09-10, RTM Decisions), `_GOVERNANCE_PERSONAS` is NOT widened and `governance_visibility` does NOT become `CurrentUser.roles`-aware. A `cio`-resolved user lands on the CIO Portfolio page, which has no governance panels, so there is nothing to lose. This scope **is not widened** by this story.

## Pattern Map

### Existing code to extend

- **`app/core/auth.py`** — `CurrentUser` dataclass: add `name: str | None` field (AC-6); modify `get_current_user` to populate it per AC-2 claim fallback logic
- **`app/core/auth.py`** — `_parse_role` function: replace positional first-role logic with multi-role precedence selection (AC-19, AC-24); build `roles: list[str]` field
- **`app/core/persona_resolver.py`** — `PersonaResolver.__init__` and tier loaders: support casefolded lookup and case-collision detection (AC-18, AC-22); casefolded cache key (AC-23); precedence config loading (AC-20)
- **`app/auth/oidc.py`** — add `_LOGOUT_PATH` constant (AC-10); new `GET /auth/logout` route (AC-10, AC-11)
- **`app/core/config.py`** — add `oidc_frontend_login_url` or `frontend_login_url` setting (mitigation for AC-10 config gap)

### Existing patterns to follow

- **One router per resource**: `app/api/me.py` mirrors `app/api/programs.py` / `personal_usage.py` structure (3 Depends injections: `current_user`, `persona_resolver`, `db`)
- **Persona resolution error handling**: `app/api/programs.py:87–112` shows the pattern — catch `PersonaNotFoundError` before `PersonaResolutionError`, raise `HTTPException(403)`
- **Server-to-server relay pattern**: `apps/web/src/app/login/route.ts:39–59` (manual redirect, 5s timeout, generic 502 on failure) must be mirrored in new `/logout` handler
- **Session management**: `apps/web/src/lib/tokenStore.ts:173–176` (`clearSession()` function) already exists; `/logout` handler calls it before relaying redirect
- **Structured logging**: `app/core/persona_resolver.py:218–226` shows the `logger.info()` pattern with `extra={}` dict for JSON fields; new `persona_mapping_not_found` event follows same shape

### New files to create

- **`services/api/app/api/me.py`** — new `GET /api/me` route (AC-1, AC-2, AC-3, AC-4, AC-5)
- **`apps/web/src/app/logout/route.ts`** — new Next.js Route Handler (AC-8, AC-9)
- **Test files**: `services/api/tests/unit/test_persona_resolver_case_insensitive.py` or extend existing `test_persona_resolver.py` with case-insensitive TCs; `services/api/tests/unit/test_me.py`; `services/api/tests/unit/test_auth_logout.py`; frontend tests for `/logout` handler

### Shared code at risk

- **`app/core/persona_resolver.py`** — the entire module is reshaped:
  - `_resolve_uncached` must handle multi-role precedence and case normalization
  - Cache key structure changes from `role` to `casefold(role)`
  - Tier loaders must support both role→persona mappings AND a precedence order
  - New logic for same-tier case collision (AC-22)
- **`app/core/auth.py`** — `_parse_role` is replaced with a new role-selection algorithm that considers all roles and precedence
- **`app/core/config.py`** — new Setting field for frontend login URL will be read by `/auth/logout`

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Integration | HIGH | AC-10/AC-12: No frontend-origin config exists. API cannot construct `post_logout_redirect_uri = frontend_login_url`. The shipped `OIDC_REDIRECT_URI` is the frontend's `/callback`, not `/login`, and specifying one URL does not derive the other. | Add `FRONTEND_LOGIN_URL` (or `OIDC_FRONTEND_ORIGIN`) env var to `Settings`; default to `None` / unset; document as required for logout to work. Plan-time decision on env-var name. Mitigation lowers severity to MED. |
| 2 | Domain | HIGH | AC-19/AC-20: Persona precedence config plumbing is not yet implemented. The 3-tier resolver today carries only `dict[str, str]` (role→persona), not a parallel precedence ordering. Tier-1 (JSON env), Tier-2 (YAML), and Tier-3 (Postgres) all lack a `precedence:` or `precedence_order:` field. Story assumes it rides "the same 3-tier mechanism" but the mechanism must be designed at plan time. | Plan must specify the schema for each tier: Tier-1 JSON structure (e.g., `{"cio": "cio", "_precedence": ["cio", "architect", ...]}`?), Tier-2 YAML (separate `precedence:` key at root?), Tier-3 schema (new column or separate table row?). Default fallback if all three unset must be the hardcoded default `cio > architect > product-manager > engineering-manager > developer`. |
| 3 | Domain | HIGH | AC-22/AC-23: Case-collision detection and casefolded cache key require tier-loader rework. Current code: simple `if role in tier_map`, exact-case match only. Must become: normalize all keys at load time, detect collisions (two keys that casefold to the same value), and key cache by casefolded form. If a collision is detected at resolver initialization, startup fails loudly. | Implement `_casefold_keys` helper in `PersonaResolver.__init__` to normalize Tier-1/Tier-2 keys and detect same-tier collisions before caching. Tier-3 (Postgres) lookup must also casefold the incoming role before the WHERE clause. New exception: `PersonaResolutionError(role, reason="ambiguous_case_collision")` per Decision log. |
| 4 | Domain | MED | AC-24: Adding `roles: list[str]` to `CurrentUser` while keeping `role: str`. The three existing API route consumers (`programs.py`, `overview.py`, `personal_usage.py`) all read `.role` only, so the new field is additive. However, the schema must be clear about order: is it the order from the token's own `realm_access.roles` array (after system-role filtering), or sorted? | Specify in AC-24 test case: `roles` is the **original order from the token**, never sorted, for audit. All three routes continue reading `role` (singular, the precedence-selected winner); `roles` is informational only. |
| 5 | Integration | MED | AC-25: New `persona_mapping_not_found` log event needs to survive Alembic's `fileConfig(disable_existing_loggers=True)`. The existing test pattern uses `_RecordCapturingHandler` attached directly to `app.core.persona_resolver` logger. | Use the documented `_RecordCapturingHandler` pattern from `test_persona_resolver.py` for any test asserting the new log event. No new pattern needed; precedent already exists. |
| 6 | Performance | LOW | AC-7: `GET /api/me` rides the existing 300s persona-resolver cache. Every call does a persona resolution, but no new cache is added. Latency is the resolver's 300s TTL; no new budget. | No action; mitigated by scope. |
| 7 | Compatibility | LOW | AC-21 (backward-compatibility): A mapping that resolves today under exact-case matching must still resolve post-story to the **identical** persona. Case-insensitive lookup can only add matches, never break existing ones. | Test case: a role `developer` mapping to `developer` under case-sensitive matching must map to `developer` under case-insensitive too. Verify no previously-working config regresses. |

## Score

| Dimension | Weight | Assessment | Score |
|-----------|--------|-----------|-------|
| **Integration** | 25 | HIGH risk on frontend-origin config missing; mitigated by adding env var. Persona precedence plumbing unbuilt but designable. Server relay pattern is precedent (AUTH-05). | 70 |
| **Compatibility** | 20 | Backward-compat invariant (AC-21) clear; new `name` and `roles` fields are additive to `CurrentUser`; `role` stays singular; persona-resolver interface unchanged. Logout does not affect existing tokens (AC-16). | 85 |
| **Domain** | 20 | Multi-role precedence (AC-19/AC-20) and case handling (AC-18/AC-22) are well-specified in ACs; no hidden edge cases. Persona-to-page mapping verified against six mockups (Decision log). One resolved concern (governance panels). | 75 |
| **Performance** | 15 | No new latency budget needed; leverages shipped 300s cache. Logout is URL-string construction only, no new I/O beyond the redirect to Keycloak. | 90 |
| **Dependency** | 20 | All three upstreams shipped and frozen. No blocking work on OVW-05/PGD-07 (they consume only `{name, persona}` shape, not the logout or resolver semantics). Independent test: true. | 85 |

**Total: 78 / 100 → GO-WITH-CONDITIONS**

## Conditions for Planning

1. **Frontend-origin config (AC-10/AC-12)**: Plan must add a new env var to `Settings` (name TBD: `FRONTEND_LOGIN_URL` or `OIDC_FRONTEND_ORIGIN`) and document it as required for logout to function. Default unset; if unset, `/auth/logout` must handle it gracefully (either 501 if required, or compute it defensively from `OIDC_REDIRECT_URI` if possible — decision in plan).

2. **Persona precedence schema (AC-20)**: Plan must specify the exact structure for carrying the `cio > architect > ...` order through each tier:
   - Tier-1: JSON env-var syntax for a list (e.g., `PERSONA_PRECEDENCE_ORDER=["cio","architect",...]`)
   - Tier-2: YAML key (root-level `precedence:` list?)
   - Tier-3: Postgres storage (new column in `persona_config`? new table? separate query?)
   - Unset at all three tiers: hardcoded default `["cio", "architect", "product-manager", "engineering-manager", "developer"]`

3. **Case-collision handling (AC-22)**: Plan must design the collision-detection logic:
   - At `PersonaResolver.__init__` (Tier-1 and Tier-2), or at every resolve call (Tier-3)?
   - Fail on init (fast-fail startup) or on first access (lazy-fail)?
   - Recommended: fail on init for Tier-1/Tier-2, raise on Tier-3 query result deduplication.

4. **Test strategy for AC-25 (unmapped-role event)**: Confirm use of `_RecordCapturingHandler` from existing precedent, no new test infrastructure.

5. **Acceptance criteria cross-check**: Plan must verify every AC (1–26) has a concrete test case mapped. Three mechanisms (session identity, logout, resolver) must be tested as independent units, not bundled into one test suite.

## Synthesis

**Verdict: GO-WITH-CONDITIONS**

This story bundles three independently shippable mechanisms (session identity endpoint, app-wide logout, persona resolution enhancements) into one large row per user direction. The merged scope is feasible and well-specified: the frontend auth flow is proven (AUTH-05 precedent), the persona resolver has an unambiguous extension path (case-insensitive + precedence, both data-driven), and the logout contract mirrors the shipped `/login` server-relay pattern. 

The single critical gap is the missing frontend-origin environment variable for the logout redirect. This is a configurability issue, not an architectural one — adding an env var to `Settings` is routine work. Secondary design decision (persona precedence schema across three tiers) is specifiable and straightforward.

**Blockers**: None. Ambiguities and assumptions are surfaceable within plan scope.

**Biggest risk**: Persona precedence configuration plumbing. If the plan underestimates the complexity of storing/loading an ordered list through Tier-1 JSON, Tier-2 YAML, and Tier-3 Postgres without breaking backward compatibility, implementation will stall. Mitigation: plan the schema fully before implementation starts; test precedence mutations across all three tiers.

**Top 3 recommendations**:
1. Early in plan, settle the exact env-var name and schema for `FRONTEND_LOGIN_URL`; default to unset; decide whether `/auth/logout` returns 501 or computes a fallback if unset.
2. Specify persona-precedence storage (Tier-1 JSON syntax, Tier-2 YAML key, Tier-3 schema) before implementation; ensure unset at all tiers correctly falls back to hardcoded default.
3. Test persona precedence mutations (change order in Tier-1 env, verify next resolve picks new winner) in isolation before bundling into the full three-mechanism validation suite.

## Clarifications

None open. All assumptions and shape-changing unknowns from the story (user direction 2026-09-10) have been resolved through RTM Decisions or recorded as plan-time decisions above.

