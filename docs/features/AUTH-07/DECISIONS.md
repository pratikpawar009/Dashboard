# AUTH-07 — Decisions

Story-level decision log for session identity (`GET /api/me`), app-wide logout, and deterministic
case-insensitive persona resolution. PLAN.md §1 points here; entries are append-only.

### D-01: `_LOGOUT_PATH = "/protocol/openid-connect/logout"`, sibling constant to `_AUTHORIZE_PATH`/`_TOKEN_PATH` · blast:feature · rev:mechanical · adr:—

**Context**: `GET /auth/logout` needs a Keycloak realm-relative end-session path, string-built the same
way `_AUTHORIZE_PATH`/`_TOKEN_PATH` already are in `app/auth/oidc.py` — no discovery fetch, no new HTTP
client shape. `AUTH-07-FR-4` pins the literal path and constant name; recorded here as the plan's own
greppable entry rather than only living in prose.

**Decision**: Add `_LOGOUT_PATH = "/protocol/openid-connect/logout"` as a new module-level constant in
`services/api/app/auth/oidc.py`, alongside the two shipped constants. `GET /auth/logout` string-builds
`{issuer}{_LOGOUT_PATH}?client_id={oidc_client_id}&post_logout_redirect_uri={frontend_login_url}` and
returns `302` — never `id_token_hint` (T-09).

### D-02: `name` claim fallback chain `name -> given_name+family_name -> preferred_username -> None` · blast:feature · rev:mechanical · adr:—

**Context**: `CurrentUser` needs a display name for `GET /api/me`, reusing the SAME "claims.get(field)
with a default, then type-check" idiom `_parse_role`/`_parse_groups` already use (no new claim-parsing
helper). `AUTH-07-FR-2` pins the exact fallback order; recorded here so the choice is greppable at the
plan level, not only in the FR prose.

**Decision**: `get_current_user` populates `CurrentUser.name` via `claims.get("name")` →
(`claims.get("given_name")` + `" "` + `claims.get("family_name")`, only when BOTH are present and
non-empty) → `claims.get("preferred_username")` → `None`. Never composed from `email`. Additive field
only (T-07); a dev-bypass token carries no profile claims, so `name` is `None` there by construction.

### D-03: Same-tier case collision reuses `PersonaResolutionError(role, reason="ambiguous_case_collision")` — no new exception subtype · blast:feature · rev:mechanical · adr:—

**Context**: A tier whose keys differ only by case (e.g. both `Developer` and `developer` — a live
condition in the Apexon realm) becomes ambiguous once lookup is casefolded, and must fail loudly rather
than silently pick one (AC-22). `rbac-checks`' call sites already catch `PersonaResolutionError` before
deciding fail-request vs. deny-and-log, so a new exception TYPE would need every one of those 16
consumers re-audited for a catch-clause gap — a blast radius this story explicitly must not touch.

**Decision**: Reuse the existing `PersonaResolutionError(role, reason)` base class with a new, fixed
`reason="ambiguous_case_collision"` string. Tier-1/Tier-2 collisions raise at `PersonaResolver.__init__`
(startup, propagating uncaught through `create_app()` exactly like a malformed Tier-2 YAML file already
does); Tier-3's query casefolds in its `WHERE` clause and raises the same error at resolve time if the
result set carries more than one distinct persona (T-03).

### D-04: `persona_mapping_not_found` observability event — name, fields, and dual emission point · blast:feature · rev:mechanical · adr:—

**Context**: The 2026-09-10 live finding was that an unmapped role and an RBAC-denied mapped role logged
byte-identically (`rbac_check_org_access outcome=denied`, no distinguishing field). AC-25 requires a
distinct, grep-able signal; the event fires from TWO call shapes that must agree on schema: (a) the
existing single-role `resolve(role)` path (`_resolve_uncached`'s own all-3-tier-miss, used directly by
`rbac-checks` consumers and exercised directly by `AUTH-07-TC-02`), and (b) the new multi-role precedence
path (`get_current_user`'s role selection, which must aggregate ALL surviving roles into one event, not
one per failed candidate, or a token with roles `['qa', 'architect']` would spuriously log a
`persona_mapping_not_found` for `qa` even though `architect` succeeds).

**Decision**: `logger.info("persona_mapping_not_found", extra={roles, tiers_consulted, timestamp})` —
`roles` is the full list of surviving roles ATTEMPTED for that call (a 1-element list `[role]` when fired
from the single-role `resolve()` path; the full survivor list when fired from the multi-role precedence
path after every candidate has been tried and none produced a persona), `tiers_consulted` is always
`["tier-1-env", "tier-2-yaml", "tier-3-postgres"]` in that order. No `user_id`/`email`/`name`/`groups`,
mirroring `persona_mapping_loaded`'s PII invariant (T-06).

### D-05: Persona precedence — new `persona_precedence` table + in-process 300s cache, promoted to ADR-0011 · blast:data · rev:medium · adr:ADR-0011

**Context**: FR-6's Tier-3 needs a durable, ordered store the existing `persona_config` table's schema
cannot represent (see ADR-0011 § Context). This is a schema/migration change (`blast:data`), which per
the `decide` skill's promotion rule requires a full ADR regardless of reversibility.

**Decision**: See ADR-0011 in full. Summary: new table `persona_precedence(rank int primary key, persona
str not null)`, additive migration `005_persona_precedence.py`; Tier-3 precedence is queried
`ORDER BY rank` and cached in-process for 300s using the resolver's existing TTL/lock pattern (a
dedicated cache slot, never colliding with a real role's cache entry) so steady-state operation issues at
most one Tier-3 precedence query per 300s per worker — this is also what keeps the NFR-performance
invariant ("casefold comparison and precedence ranking run in-process against already-fetched tier
data, adding no new query or I/O") true in the common case (T-02, T-05).

### D-06: `get_current_user` gains a `PersonaResolver` dependency; a new resolver-level method performs multi-role precedence selection · blast:service · rev:mechanical · adr:—

**Context**: FR-6's selection algorithm ("the resolver maps every surviving role to a candidate persona
via the existing tier lookup, then picks the winner as the first persona in precedence order among the
candidates") requires knowing, for EVERY surviving role, which persona it maps to — including a possible
Tier-3 Postgres lookup for a role absent from Tier-1/Tier-2. That computation only exists today inside
`PersonaResolver`, which `get_current_user` (in `app/core/auth.py`) has never depended on: today, `role`
is chosen synchronously and purely positionally (`_parse_role`), and only DOWNSTREAM consumers
(`rbac.py`, `app/api/programs.py`, the new `app/api/me.py`) call `persona_resolver.resolve(current_user
.role)`. Naively calling the existing `resolve()` once per surviving role and discarding the losers would
ALSO spuriously emit `persona_mapping_not_found` for every non-winning role that happens to be genuinely
unmapped (see D-04) — an operator-facing false-positive-noise regression for the ordinary case of a token
carrying one persona role plus several unrelated business roles.

**Decision**: `get_current_user` (`app/core/auth.py`) adds `persona_resolver: PersonaResolver =
Depends(get_persona_resolver)` as one more FastAPI-injected dependency (T-07), mirroring how it already
takes `db`/`program_roster_resolver`. `PersonaResolver` gains a new, additive method (working name
`resolve_precedence(roles: list[str]) -> str`, exact name is an implementation-agent naming choice, not
pinned here) that: (1) for each surviving role, in original token order, attempts each tier via a shared,
NON-raising internal lookup helper (a refactor of `_resolve_uncached`'s tier fallthrough that returns
`persona | None` instead of raising on a miss); (2) collects `(role, persona)` candidates; (3) picks the
winning persona as the first entry in precedence order present among the candidates; (4) returns the
CASEFOLDED winning role string (never the persona) — preserving the frozen contract that `role` "stays a
str and stays one of the token's own roles." Only if NO surviving role produces a candidate across all 3
tiers does this method emit ONE aggregated `persona_mapping_not_found` (D-04) and raise
`PersonaNotFoundError`. The existing public `resolve(role: str) -> str` signature, behavior, and its own
independent `persona_mapping_not_found` emission on a single-role all-tiers-miss are UNCHANGED — this is
a pure addition, so all 16 `rbac-checks` consumers and `AUTH-07-TC-02`'s direct `resolve()` call keep
working unmodified (T-06, T-07).

### D-07: Test-file placement for new/extended modules · blast:feature · rev:mechanical · adr:—

**Context**: `docs/stories/AUTH-07.md`'s own Decision log flags the `app/api/me.py` test path as "a
plan-time decision, not fixed here," and the story's Test mapping names aspirational paths
(`tests/core/test_persona_resolver.py`, `tests/core/test_auth.py`) that do not match this repo's actual
`tests/unit/`-flat, topic-suffixed convention (`test_persona_resolver.py`, `test_auth_jwt_validation.py`,
`test_auth_groups.py`, ...). A competent reviewer could reasonably create new files instead of extending
existing ones.

**Decision**: Follow the repo's real convention — extend, don't fork. `name`-fallback (AC-2/AC-6) and
precedence/`roles`-list (AC-19/AC-24) tests extend the EXISTING `tests/unit/test_auth_jwt_validation.py`
(it already owns `realm_access.roles`/`_parse_role` coverage, T-07). Tier-1/2/3 casefold, collision,
precedence-loading, and `persona_mapping_not_found` tests extend the EXISTING
`tests/unit/test_persona_resolver.py` (T-03, T-05, T-06). New route/handler tests get new, topic-named
files matching the new modules they cover: `tests/unit/test_me.py` (T-08), `tests/unit/test_auth_logout
.py` (T-09), `apps/web/src/app/logout/route.test.ts` (T-10, mirrors `login/route.test.ts`'s sibling
placement).

### D-08: `dashboard_logout`'s `user_id` is sourced by forwarding the pre-clear access token as a bearer header to `GET /auth/logout` · blast:feature · rev:mechanical · adr:—

**Context**: `AUTH-07-FR-4`/NFR-Observability say `GET /auth/logout` emits `dashboard_logout` carrying
`user_id` only, but neither the FR nor the story's Decision log states HOW the route obtains a `user_id`
— unlike `/auth/callback`/`/auth/refresh`, `GET /auth/logout` takes no request body and (per FR-5) the
frontend's `/logout` handler calls `clearSession()` BEFORE relaying to it, so the session cookie is
already gone by the time the backend request is even made. Emitting the event with no `user_id` at all,
or inventing a second identity channel, are both live alternatives a reviewer might pick instead.

**Decision**: The frontend's `/logout` Route Handler reads the (still-valid, not-yet-cleared) session via
`tokenStore.readSession()` FIRST, then calls `clearSession()`, then fetches `GET /auth/logout` with
`Authorization: Bearer <accessToken>` attached using the just-read (pre-clear) access token — the cookie
being cleared does not invalidate the token value itself (AC-16 already documents that an issued access
token survives cookie-clear until its own expiry). The backend route decodes it via the SAME
JWKS-verified path `_log_dashboard_login` already uses (`_peek_kid` + `jwks_cache.get_signing_key` +
`jwt.decode().validate()`), tolerating any decode failure by falling back to `user_id="unknown"` — a
failed decode must never block the redirect, exactly mirroring `_log_dashboard_login`'s existing
never-500-on-logging contract (T-09, T-10).
