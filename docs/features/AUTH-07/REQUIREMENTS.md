# Feature: AUTH-07 — Session identity endpoint, app-wide logout, and deterministic case-insensitive persona resolution

## Problem

Three related gaps sit on top of the shipped, frozen `session`/`persona-resolver` contracts:

- Nothing in the shipped API tells the frontend "who am I signed in as, and which dashboard do I get." `PersonaDashboardShell`'s identity block and `AdoptionOverview` (OVW-01 D-04) both render nothing today because no endpoint returns `{name, persona}`.
- Users have no way to end their session app-wide. No route anywhere in `apps/web/src` or `services/api/app` contains logout/signout. A local cookie clear alone fails the requirement because the live Keycloak SSO cookie silently re-authenticates `/login` on the next hop.
- Persona resolution is exact-case and positionally accidental. Live 2026-09-10: a real token's `realm_access.roles = ['Architect', 'Developer', 'developer']`. `Architect` fails closed against the shipped lowercase `architect` Tier-2 key, and once case-insensitivity is added on its own, all three roles would then match — Keycloak does not guarantee array order, so the same account could land on a different dashboard between logins with no account change. Operators also cannot distinguish an unmapped role from a matched-but-RBAC-denied one: both produce `rbac_check_org_access outcome=denied` with nothing indicating which.

## Outcome

- `GET /api/me` returns `200 {name, persona}` for any authenticated session; OVW-05/PGD-07 render the identity block against a frozen, server-derived contract — no page infers its own persona.
- Navigating to `/logout` clears the frontend cookie session, ends the Keycloak SSO session, and lands the browser on `/login` showing Keycloak's own form (not a silent re-authentication). Any of the six dashboard routes requested afterward with no new sign-in independently redirects through sign-in.
- A token carrying several mappable roles resolves to the same persona on every call, chosen by an explicit, ops-configurable precedence order — never token-array position. `Architect`/`architect`/`developer` all match regardless of case.
- An all-tiers-miss for a role emits a `persona_mapping_not_found` event distinguishable in logs from both a successful resolution and an RBAC denial.

## Constraints

- AUTH-01 (`session`), AUTH-02 (`persona-resolver`), AUTH-05 (frontend token store + relay pattern) are shipped and frozen. This story changes their internal semantics behind unchanged public interfaces — `resolve(role: str) -> str` and `CurrentUser.role: str` stay exactly as they are; none of `rbac-checks`' 16 consumers need a code change.
- No new UI. AC-15: no mockup's brand bar gains an `<a>`, `<button>`, or `cursor:pointer` affordance — `/logout` is direct-URL-navigation only, and CLAUDE.md forbids inventing UI the mockups don't show.
- No Keycloak realm/scope/mapper change. `OIDC_SCOPE`'s shipped `profile` default already covers `name`/`given_name`/`family_name`/`preferred_username`. Program membership continues to come from `program_roster` (`.harness/program.yaml`), never Keycloak groups (AUTH-06, unchanged).
- `_GOVERNANCE_PERSONAS` (`services/api/app/core/rbac.py:196`) is not widened to include `cio`, and `governance_visibility` does not become `CurrentUser.roles`-aware — settled 2026-09-10 at the research gate (see `## Resolved questions`).
- No local Keycloak in `docker-compose.yml` and `test_e2e` is empty in `docs/config/project-commands.yaml` (no Playwright/Cypress) — the full RP-initiated end-session round trip (SSO termination, `/login` re-rendering its own form rather than auto-signing-in) is verified manually against the real Apexon realm, not automated.
- Sourced budgets carried forward unchanged, none newly invented: persona-resolver's 300s per-role cache TTL, the 3.0s Tier-3 `asyncio.wait_for` timeout, and the Apexon realm's 300s access-token `expires_in` default (a test-fixture value; the implementation reads `expires_in` from Keycloak's response and never hardcodes it).

## Solution sketch

Add one new read-only identity endpoint that hands the frontend the resolver's own persona output and a claims-derived display name; add one new additive, route-only session-termination path that chains a frontend cookie clear to a backend-constructed Keycloak RP-initiated end-session redirect; and rework the persona resolver's tier-lookup internals so role matching is case-insensitive, multi-role selection is deterministic via a configurable precedence order, and an all-tiers-miss is observable and distinguishable from a denial. All three mechanisms extend existing, frozen contracts rather than introducing new ones.

## Addressing Research Conditions

Research verdict: GO-WITH-CONDITIONS, 78/100. `docs/research/AUTH-07.md` § "Conditions for Planning" carries 5 numbered conditions:

1. **Frontend-origin config (AC-10/AC-12)** — new `Settings.frontend_login_url` field, env var `FRONTEND_LOGIN_URL`, default `None` (unset), documented in `services/api/.env.example`. Unset, `GET /auth/logout` returns `501` via the same standard error envelope as the existing `config_completeness_gate` — `frontend_login_url` joins the OIDC triple as a fourth required value for this one route, rather than deriving a guessed URL from `OIDC_REDIRECT_URI` (a different route, the frontend's `/callback`). See **AUTH-07-FR-3**.
2. **Persona precedence schema (AC-20)** — Tier-1 `PERSONA_PRECEDENCE_ORDER` env var (JSON array of persona strings, parsed once at `Settings` load alongside `PERSONA_ROLE_MAP`, same fail-open-to-unset behavior on a parse error); Tier-2 a new root-level `precedence:` list key in `services/api/config/persona_role_map.yaml`, loaded once at `PersonaResolver.__init__`; Tier-3 a new `persona_precedence` table (`rank int primary key, persona str`), queried `ORDER BY rank` through the same `session_factory`/3.0s timeout as the existing `persona_config` lookup. All three unset falls back to the hardcoded default `["cio", "architect", "product-manager", "engineering-manager", "developer"]`. See **AUTH-07-FR-6**.
3. **Case-collision handling (AC-22)** — Tier-1/Tier-2 keys are casefolded and collision-checked once at load time (`Settings` load / `PersonaResolver.__init__`); a same-tier collision raises `PersonaResolutionError(role, reason="ambiguous_case_collision")` at startup, propagating uncaught through `create_app()` exactly as a malformed Tier-2 YAML file already does — never reachable at request time for these two tiers. Tier-3's Postgres query casefolds the incoming role in its `WHERE` clause and raises the same error at resolve time if the result set carries more than one distinct persona value, since Tier-3 data can change without a restart. See **AUTH-07-FR-7**.
4. **Test strategy for AC-25** — confirmed: reuse the existing `_RecordCapturingHandler` pattern from `tests/unit/test_persona_resolver.py`, attached directly to `app.core.persona_resolver`'s logger. `caplog`/`capsys` are not used, because Alembic's `fileConfig(disable_existing_loggers=True)` sweep disables every `app.*` logger process-wide and would make such an assertion pass vacuously. See **AUTH-07-FR-8**.
5. **AC cross-check** — this run's `test-case-agent` invocation is capped at 2 test cases (orchestrator-set for this run), which cannot cover all 26 ACs. The 2 cases are directed at the two highest-risk mechanisms this research flagged (persona precedence plumbing, Risk #2; unmapped-role observability, Risk #5): (a) case-insensitive, precedence-driven persona resolution — collapsing AC-18, AC-19, AC-20, AC-21, AC-23, AC-26 into one deterministic-selection test that reproduces the live `['Architect', 'Developer', 'developer']` token, and (b) the `persona_mapping_not_found` event (AC-25). The residual gap — ACs 1–17, 22, 24 with no test case mapped this run — is recorded as an accepted limitation in `## Open questions`, not papered over.

## Scope

- In:
  - `GET /api/me` (new route, `services/api/app/api/me.py`) returning `{name, persona}` (AC-1–AC-7)
  - `CurrentUser.name: str | None` and `CurrentUser.roles: list[str]` additive fields; `app/core/auth.py` name-claim fallback chain and role-selection rewrite (AC-2, AC-6, AC-19, AC-24)
  - `GET /auth/logout` (new route, `app/auth/oidc.py`, new `_LOGOUT_PATH` constant) plus new `Settings.frontend_login_url` (AC-10–AC-13, AC-16, AC-17)
  - `apps/web/src/app/logout/route.ts` (new Route Handler) (AC-8, AC-9)
  - Persona-resolver rework: casefolded tier lookup + cache key, same-tier case-collision detection, config-driven precedence across all 3 tiers, `persona_mapping_not_found` observability event (AC-18, AC-20–AC-23, AC-25, AC-26)
  - README updates: Keycloak client requirements bullet, API table rows, environment variable row (Documentation requirements below)
- Out:
  - Any visible logout link, button, or hover affordance in any of the six mockups — AC-15 forbids it outright; not deferred, rejected.
  - A new signed-out landing page — never planned; `post_logout_redirect_uri` is the frontend's existing `/login` (AC-12).
  - Widening `_GOVERNANCE_PERSONAS` to include `cio`, or making `governance_visibility` `CurrentUser.roles`-aware — rejected 2026-09-10 at the research gate (see `## Resolved questions`).
  - Resolving a role list to a persona set — explicitly rejected; one persona decides one landing page, `resolve()` keeps returning a single `str`.
  - `ARC-01`/`DEV-01`/`PMD-01`/`EMD-01` consumption of `session-identity-api` — deferred to those stories when next touched, per the contract's `under_declared_edge` note; they are `validated` rows this story does not edit.
  - Automated E2E of the full Keycloak SSO round trip — deferred to a manual verification step (Test mapping); no local Keycloak or Playwright/Cypress exists to drive one.
  - Mitigating the stale-access-token-after-logout limitation (AC-16) — stated as an accepted, inherent property of stateless bearer JWTs with no server-side session store, not engineered around here.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-07.md` for canonical wording. New implementation constraints introduced below:

**AUTH-07-FR-1** — `GET /api/me` response construction *(extends AC-1, AC-3, AC-4, AC-5 with: route structure, error-catch order, response-shape enforcement)*

New route in `services/api/app/api/me.py`, mirroring `app/api/programs.py`'s dependency-injection shape (`current_user: CurrentUser = Depends(get_current_user)`, resolver from `app.state.persona_resolver`). The handler calls `persona_resolver.resolve(current_user.role)`, catching `PersonaNotFoundError` before `PersonaResolutionError` and raising `HTTPException(403)` for either — the same catch order `app/api/programs.py:87-112` already uses. On success it returns `{"name": current_user.name, "persona": persona}` exactly, via a response model that forbids extra fields, so no `email`/`groups`/`programs`/`jobTitle` can leak in. No route-owned cache: every call re-invokes `resolve()`, riding the resolver's own 300s TTL.

**AUTH-07-FR-2** — `name` claim fallback chain *(extends AC-2, AC-6 with: exact fallback order and claim-parsing pattern)*

`get_current_user` populates `CurrentUser.name` via `claims.get("name")` → (`claims.get("given_name")` + `" "` + `claims.get("family_name")`, only when both are present and non-empty) → `claims.get("preferred_username")` → `None` — the same `claims.get(field)`-with-default-then-type-check pattern `_parse_role`/`_parse_groups` already use; no new claim-parsing helper. Never composed from `email`. Additive field; no existing `CurrentUser` field is renamed or removed.

**AUTH-07-FR-3** — Frontend-origin config for logout *(extends AC-10, AC-12 with: env var name, default, unset behavior — Condition 1)*

New `Settings.frontend_login_url: str | None`, env var `FRONTEND_LOGIN_URL`, default `None` (unset), added to `services/api/.env.example` alongside the existing OIDC vars. `GET /auth/logout` folds `frontend_login_url` into `config_completeness_gate` as a fourth required value: unset, the route returns `501` via the same standard error envelope the OIDC triple already produces (assumption: no story AC pins this specific unset behavior; extending the existing fail-closed gate is the lowest-risk default and keeps "unset any one var to back out without a redeploy" true for this value too). When set, `post_logout_redirect_uri` is `frontend_login_url` verbatim — never derived from `OIDC_REDIRECT_URI`, which names a different route (`/callback`).

**AUTH-07-FR-4** — `GET /auth/logout` end-session URL construction *(extends AC-10, AC-11, AC-13, AC-16 with: constant name, param set, no-discovery-fetch constraint)*

New `_LOGOUT_PATH = "/protocol/openid-connect/logout"` constant in `services/api/app/auth/oidc.py`, sibling to `_AUTHORIZE_PATH`/`_TOKEN_PATH`. The route string-builds `{issuer}{_LOGOUT_PATH}?client_id={oidc_client_id}&post_logout_redirect_uri={frontend_login_url}` and returns `302` — no discovery fetch, no server-side call to Keycloak, mirroring `/auth/login`'s shipped mechanism. Never includes `id_token_hint`. An already-issued access token remains valid until its own `expires_in`-derived expiry (AC-16, stated as a limitation, not fixed here).

**AUTH-07-FR-5** — Frontend `/logout` Route Handler *(extends AC-8, AC-9 with: call ordering and relay pattern)*

New `apps/web/src/app/logout/route.ts`. Calls `tokenStore.ts`'s existing `clearSession()` first, then fetches `GET /auth/logout` with `redirect: "manual"`, then relays the resulting `302`'s `Location` header to the browser — mirroring `apps/web/src/app/login/route.ts:39-59`'s shipped 5s-timeout, generic-502-on-failure pattern verbatim. No shipped route (`/login`, `/callback`, `/auth/login`, `/auth/callback`) is modified.

**AUTH-07-FR-6** — Persona precedence config schema *(extends AC-19, AC-20 with: exact Tier-1/2/3 shapes — Condition 2)*

- Tier-1: `PERSONA_PRECEDENCE_ORDER` env var, JSON array of persona strings, e.g. `["cio","architect","product-manager","engineering-manager","developer"]`, parsed once at `Settings` load alongside `PERSONA_ROLE_MAP`. Unparseable JSON, a non-array value, or a non-string element is logged as a warning and treated as unset (falls through to Tier-2) — the same fail-open parse behavior `PERSONA_ROLE_MAP` already has.
- Tier-2: new root-level `precedence:` key in `services/api/config/persona_role_map.yaml`, an ordered YAML list, loaded once at `PersonaResolver.__init__` alongside the existing role map. A malformed `precedence:` value is a startup error propagating uncaught through `create_app()` — the same fail-fast behavior the existing malformed-YAML case has.
- Tier-3: new `persona_precedence` table (`rank: int primary key`, `persona: str not null`), queried `ORDER BY rank` through the same injectable `session_factory` and 3.0s `asyncio.wait_for` timeout as the existing `persona_config` lookup.
- All three tiers unset: hardcoded default `["cio", "architect", "product-manager", "engineering-manager", "developer"]` — no working deployment must configure anything to get today's intended order.
- Selection: the resolver maps every surviving role (post `_is_keycloak_system_role` filtering) to a candidate persona via the existing tier lookup, then picks the winner as the first persona in precedence order that appears among the candidates.

**AUTH-07-FR-7** — Case-insensitive lookup, casefolded cache key, same-tier collision detection *(extends AC-18, AC-21, AC-22, AC-23 with: exact fail points — Condition 3)*

Tier-1/Tier-2 dict keys are casefolded once at load time. If two distinct original keys in the same tier casefold to the same string, `PersonaResolver.__init__` raises `PersonaResolutionError(role=<casefolded key>, reason="ambiguous_case_collision")` immediately at startup — Tier-1/Tier-2 collisions are never reachable at request time. Tier-3's query casefolds the incoming role in its `WHERE` clause; if the result set carries more than one distinct `persona` value, the same error is raised at resolve time (Tier-3 data can change without a restart). The per-role cache key is the casefolded role string, so `Architect` and `architect` share one entry and never alternate between hit and miss on casing alone. Lookup-side normalization only — no stored tier value is rewritten, and every mapping that resolves today under exact-case matching still resolves to the identical persona (AC-21).

**AUTH-07-FR-8** — `persona_mapping_not_found` observability event *(extends AC-25, AC-26 with: exact event name, fields, emission point)*

When every surviving role fails to resolve across all 3 tiers (post case-folding), the resolver emits `logger.info("persona_mapping_not_found", extra={roles, tiers_consulted, timestamp})` before raising `PersonaNotFoundError` (fail-closed, unchanged). `roles` is the full surviving-role list attempted; `tiers_consulted` is `["tier-1-env", "tier-2-yaml", "tier-3-postgres"]` in the order tried; no `user_id`/`email`/`name`/`groups`, mirroring the existing `persona_mapping_loaded` event's PII invariant. Grep-distinguishable from both `persona_mapping_loaded` (different event name) and `rbac_check_org_access outcome=denied` (different event name, no `roles`/`tiers_consulted` fields).

## Non-functional requirements

- Performance: Per `.claude/rules/performance-baseline.md`: `GET /api/me` and `GET /auth/logout` each do at most one persona-resolver call, riding the existing 300s per-role cache TTL and 3.0s Tier-3 `asyncio.wait_for` timeout — both unchanged budgets, not new ones. Logout adds no discovery fetch and no server-side call to Keycloak (URL string-build only); no new latency budget beyond ordinary page navigation for either mechanism.
- Security: Per `.claude/rules/security-baseline.md`: applies to both new routes (`GET /api/me`, `GET /auth/logout`). `name` is PII and must never appear in a log line (mirrors `dashboard_login`'s `user_id`-only invariant); `persona_mapping_not_found` and `dashboard_logout` carry only role slugs/tier names and `user_id` respectively — never email, name, groups, or token values. Fail-closed preserved: an all-tiers-miss still raises `PersonaNotFoundError` (AC-26); a same-tier case collision raises rather than silently picking one (AC-22). Multi-role precedence never widens `_GOVERNANCE_PERSONAS` or makes `governance_visibility` roles-aware (Constraints, `## Resolved questions`).
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: N/A across all three mechanisms — no rendered UI surface is introduced by this story (`design: n/a`; `docs/design/schema.json` has no `AUTH` key).
- Observability: `persona_mapping_loaded` (existing, unchanged) plus new `persona_mapping_not_found` (role(s) attempted, tiers consulted, no PII) on the resolver. New `dashboard_logout` structlog JSON event on `GET /auth/logout` carrying `user_id` only, mirroring `dashboard_login`'s existing invariant. `GET /api/me` emits no dedicated event of its own — a second event would duplicate the resolver's existing success/failure signal (`.claude/rules/reusability-baseline.md`). Cache invalidation: none newly owned by this story — the 300s TTL is persona-resolver's own, unchanged, TTL-expiry-only, per `.claude/rules/performance-baseline.md`.

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan

- **Strategy**: bang-bang — additive fields and routes, backward-compatible (`persona-resolver`/`CurrentUser` interfaces unchanged), low blast radius.
- **Feature flag**: none. The OIDC triple plus the new `FRONTEND_LOGIN_URL` are the natural kill-switch for logout specifically — unset any one to force `GET /auth/logout` back to `501` without a redeploy. `GET /api/me` and the persona-resolution changes extend already-live resolution behavior and carry no separate flag.
- **Backout plan**: revert the PR. For logout alone, unset `FRONTEND_LOGIN_URL` to disable `/auth/logout` (returns `501`) without a redeploy or touching the OIDC triple.
- **Success signal**: zero unexpected `persona_mapping_not_found` events for a role that previously matched under exact-case comparison (AC-21 regression signal) over the first 24h post-deploy, and a manual smoke test confirms the live `realm_access.roles = ['Architect', 'Developer', 'developer']` token resolves to `architect` on every call.

## Documentation requirements

- **README updates**: `README.md` § "Keycloak client requirements" gains a bullet stating the frontend's `/login` route must be registered under the Keycloak client's **Valid post logout redirect URIs**, additive alongside the existing Valid Redirect URIs bullets AUTH-05 documented (AC-17). § "API" table gains two rows — `GET /api/me` (request: none besides bearer; response: `200 {name, persona}`, `403` on persona-resolution failure, `401` on missing/invalid bearer) and `GET /auth/logout` (request: none; response: `302` to `{issuer}/protocol/openid-connect/logout` carrying `client_id`/`post_logout_redirect_uri`, `501` if OIDC config or `FRONTEND_LOGIN_URL` is incomplete). § "Environment variables" gains a `FRONTEND_LOGIN_URL` row (`services/api/.env.example`, default unset, required for `GET /auth/logout` to return anything other than `501`).
- **Runbook**: none — no new operational procedure beyond the README bullets above; a case-collision failure surfaces as an ordinary startup or resolve-time exception.
- **API reference**: FastAPI's generated `/docs` covers both new routes automatically — no separate OpenAPI file to maintain by hand.
- **Inline code comments**: `app/core/persona_resolver.py`'s tier-loader functions get a docstring stating the precedence-selection algorithm (FR-6) and the two case-collision fail points (FR-7).
- **Examples / how-to**: none — the three mechanisms extend existing, already-documented seams (`session`, `persona-resolver`, `session-identity-api`); no new integration guide is warranted.

## Open questions

- Given this run's 2-test-case cap, `test-case-agent` (Phase 2) covers only two mechanisms: (a) case-insensitive, precedence-driven persona resolution (collapsing AC-18, AC-19, AC-20, AC-21, AC-23, AC-26 into one deterministic-selection test against the live `['Architect', 'Developer', 'developer']` token) and (b) the `persona_mapping_not_found` event (AC-25). This is a stated, accepted limitation of this planning run, not a judgment that the other ACs are lower-risk: **AC-1 through AC-17, AC-22, and AC-24 have no test case mapped** in this run's `docs/test-cases/AUTH-07.json` — the session-identity endpoint, both logout ACs, `roles: list[str]` ordering, and Tier-3 same-tier case-collision raising are all uncovered. `/arh-plan-implementation` must either widen the cap or carry this gap into `PLAN.md` tasks explicitly, mirroring the `SHP-02`/`BED-05` precedent of committing an FR with no covering test case.

Decisions logged in `docs/stories/AUTH-07.md` § Decision log.

## Resolved questions

- **Dual-role user + `governance_visibility` (FR-AUTH-09) interaction** — RESOLVED 2026-09-10 at the `/arh-research` gate (user decision), carried forward from the story's `## Clarifications` (single prior item, now empty) and Decision log. A user holding both a `cio`-mapped and a `developer`-mapped role, once precedence resolves them to `cio`, does not need governance-panel access restored: `Compliance & guardrails` and `Organization Constitution` occur only on the Architect, Developer, and Product Manager mockups — never the CIO Portfolio or Engineering Manager mockups — so `_GOVERNANCE_PERSONAS` mirrors the per-persona page layout rather than encoding an independent privilege ladder, and a `cio`-resolved user lands on a page with no governance panel to lose. Consequence, all three deliberate: `_GOVERNANCE_PERSONAS` is **not** widened to include `cio`; `governance_visibility` does **not** become `CurrentUser.roles`-aware; AUTH-03's shipped check is untouched. A deployment wanting a dual-role user to land on an Architect/Developer page instead re-orders precedence through the Tier-1/2/3 config this story ships (AC-20) — an ops change, no code.

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| Product Owner | Pratik Pawar | 2026-09-10 | APPROVE — Product Gate passed. The coverage audit's 25 uncovered ids (AC-1–AC-17, AC-22, AC-24, FR-1–FR-5, NFR-performance) are knowingly accepted as a limitation of this run's user-directed 2-test-case cap, not a judgment that those ACs are low-risk; see `## Open questions`. `/arh-plan-implementation` must widen the cap or carry the gap into `PLAN.md` tasks explicitly. |
| Designer | — | — | N/A — `design_mode = none`; no `AUTH` epic in `docs/design/schema.json` and this story ships no rendered UI |
| BA | Pratik Pawar | 2026-09-10 | APPROVE — Edge cases, `## Open questions`, and test-case automation feasibility (2/2 automatable) confirmed as part of the single Product Gate verdict above. |

Gate checks verified at Phase 4 (2026-09-10), all passing except one, which was weighed and accepted: no-placeholder grep clean (0 hits); unresolved `[NEEDS CLARIFICATION]` count 0; all 5 GO-WITH-CONDITIONS research conditions addressed in `## Addressing Research Conditions`; the resolved dual-role/governance question recorded in `## Resolved questions` and not dropped; every test case carries a `requirement_id` resolving to a real AC. **Failed and accepted:** the test-case coverage audit — `docs/test-cases/AUTH-07.json` `coverage_audit.uncovered` holds 25 ids under this run's 2-test-case cap. Approved with that gap open and inherited by `/arh-plan-implementation`.
