# Research: AUTH-06 — Roster-sourced program membership

## Upstream dependency summary

| Upstream | Artifact | State | Evidence |
|----------|----------|-------|----------|
| ING-10 | `program-roster-schema` contract (`docs/requirements/data.md#program-roster-schema`) | `research_verdict=GO-WITH-CONDITIONS`, `phase=security-reviewed`, shipped via PR #244 (commit badb925) | Table `program_roster` live in `services/api/migrations/versions/003_program_roster.py`; ORM model at `services/api/app/models/roster.py` (id, program_id, email, name, role, source, removed_at, created_at, updated_at; unique on (program_id, email); email indexed; soft-delete via removed_at IS NULL filtering on every read) |
| AUTH-01 | `session` contract (`docs/requirements/auth.md#session`) | `research_verdict=GO-WITH-CONDITIONS`, `phase=review`, complete | `CurrentUser` dataclass at `services/api/app/core/auth.py:57-72` carries (user_id, email, role, groups, programs); `get_current_user` dependency verified and returns CurrentUser; dev-bypass route at `services/api/app/auth/dev_bypass.py` constructs groups claim from caller-supplied programs via prefix; all auth flow complete and tested |

Both upstreams' code is present on main; read from the real implementations.

## Exploration Log

### _parse_programs callers and groups-claim infrastructure
- **Where**: `services/api/app/core/auth.py:175-188` (definition), `:236` (call), `config.py:57` (Settings field)
- **What**: Function strips `program_group_prefix` from each groups claim entry; `get_current_user` calls it at line 236 to populate `CurrentUser.programs` from `groups`
- **Surprises**: None — simple string-list comprehension, fail-soft to empty list on zero match (D-10). Call site is the only producer of `programs` field.
- **Open**: Will be deleted entirely; callers must switch to roster query.

### program_group_prefix usage blast radius
- **Where**: `config.py:57` (Settings default), `auth.py:236` (call in get_current_user), `dev_bypass.py:98` (group construction for dev token), tests (multiple)
- **What**: Settings field `program_group_prefix: str = "program-"` is used in auth.py to parse groups claim, and in dev_bypass.py to construct the `groups` claim on a dev token so it can be parsed back by the same code when the token verifies
- **Surprises**: dev_bypass.py has a reverse dependency: when caller supplies `programs: ["alpha", "beta"]`, dev_bypass constructs `groups: ["program-alpha", "program-beta"]` so that `get_current_user` parsing recovers the list. AC-4 requires this to still work, meaning dev-bypass path cannot query roster.
- **Resolved**: dev-bypass token generation changes — it drops the prefix-reconstructed `groups` and mints an explicit top-level `programs` claim instead. See Clarifications.

### programs.py endpoint — AC-8 zero-change claim
- **Where**: `services/api/app/api/programs.py:69-164`
- **What**: Route handler `list_programs` uses `current_user.programs` at line 122 to scope the query: `where(ProgramSummary.program_id.in_(current_user.programs))` for non-cio personas, no filter for cio
- **Surprises**: None — the claim is literally true. The field is already the "scoping source", regardless of where it comes from. AC-8 correctly identifies this as a black box from programs.py's perspective.
- **Open**: None — confirmed.

### PersonaResolver caching pattern (AUTH-02 precedent)
- **Where**: `services/api/app/core/persona_resolver.py:86-226`
- **What**: Three-tier fallthrough (env → YAML → Postgres), cached per-key with TTL 300s, guarded by asyncio.Lock, Tier-3 query timeout 3.0s via wait_for, miss path re-checks under lock to bound concurrent queries to one per role, emits structured `persona_mapping_loaded` event (no PII: only role/persona/tier/timestamp + tier3_latency_ms on fresh query)
- **Surprises**: TTL uses `time.monotonic()` (not wall-clock), cached value stored as tuple `(persona, tier, expiry_ts)`, lock is asyncio.Lock not threading.Lock (event-loop-only)
- **Open**: This is the template AUTH-06 should follow: replace `role` key with `email`, replace `persona` value with `list[str]` (program_id list), keep the same guard/timeout/caching/logging pattern.

### DB session availability in auth dependency
- **Where**: `services/api/app/core/db.py:21-24` (get_db dependency), `auth.py:191-237` (get_current_user signature)
- **What**: `get_db()` is an async FastAPI dependency that yields AsyncSession. `get_current_user` is also an async dependency with signature including `credentials`, `settings`, `jwks_cache`; no DB session is currently injected
- **Surprises**: get_current_user can accept additional FastAPI-injected dependencies per its D-07 design (inline comment at auth.py:191). The dependency is async and runs on the event loop, so adding `db: AsyncSession = Depends(get_db)` is safe and follows existing patterns (e.g., programs.py uses it)
- **Open**: Confirmed safe to add DB session; no import cycle or layering issue.

### Test coverage for groups-derived programs
- **Where**: `services/api/tests/unit/test_auth_groups.py` (main test file, 12.3 KB, 276+ lines)
- **What**: Tests pinned TCs 05/18/19/20 for claim → field mapping via end-to-end app wiring; boundary cases call `_parse_programs` directly; custom prefix test builds a second app with `program_group_prefix='team-'`. Many assertions key on groups claim being parsed to programs field.
- **Surprises**: None — comprehensive coverage of string-matching logic, duplicate/ordering, bare-prefix remainder, case sensitivity. All will need refactoring once groups parsing is deleted.
- **Open**: Test breakage scope: all `test_auth_groups.py` tests assert on the parsed result; they will need to be rewritten to mock/fixture a roster table instead. dev_bypass tests that supply `programs` in the request will need adjustment if the token no longer carries reconstructed groups.

### dev_bypass token claim structure
- **Where**: `services/api/app/auth/dev_bypass.py:82-110`
- **What**: Handler constructs `groups` claim by mapping `payload.programs` through the prefix: `groups = [f"{settings.program_group_prefix}{program}" for program in programs]`. Token carries this groups claim unchanged; when verification runs, `_parse_programs` recovers the list by stripping the prefix
- **Surprises**: dev_bypass path is lossy in the opposite direction (programs → groups → programs); it has no roster to query. AC-4 explicitly requires dev-bypass to "keep working in an allow-listed environment with no roster seed data required"
- **Resolved**: the program list moves INSIDE the token claims — `dev_bypass.py` adds a top-level `programs` claim and `get_current_user` reads it on the `kid == DEV_BYPASS_KID` branch. The email-matching alternative was rejected: `payload.email` is caller-supplied. See Clarifications.

### OIDC_SCOPE default and groups scope requirement
- **Where**: `services/api/app/core/config.py:56` (default `"openid profile email groups"`), `.env.example:46` (same default), `README.md:56` (docs explaining it requires a Keycloak client scope with Group Membership mapper)
- **What**: OIDC_SCOPE default includes `groups` because Keycloak will not return the claim if the scope is not requested. AC-6 requires removing this from the default since groups is no longer used for membership.
- **Surprises**: Removing `groups` from the default is correct — the raw groups claim will still land on CurrentUser when Keycloak sends it (via the claim itself, not a scope), but it won't be REQUESTED from Keycloak anymore, so `groups` will be empty for most deployments unless a different story needs it for another purpose
- **Open**: Confirmed: AC-6 default change is straightforward.

### Config retirement scope (AC-6)
- **Where**: `services/api/app/core/config.py:57`, `.env.example:47`, `README.md:47-58` (three rows in the env-var table: `OIDC_SCOPE`, `PROGRAM_GROUP_PREFIX`, one bullet about groups scope in Keycloak requirements)
- **What**: Settings field `program_group_prefix` (unused after _parse_programs is deleted), OIDC_SCOPE default changed from `"openid profile email groups"` to `"openid profile email"`, documentation about Keycloak groups client scope and Group Membership mapper removed
- **Surprises**: `Settings.program_group_prefix` field must be deleted (not just left unused), else it lingers in serialization/env-parsing. The env var `PROGRAM_GROUP_PREFIX` should remain in `.env.example` commented out (documenting the old way) but removed from documented list in README.
- **Open**: Clean deletion required; no deprecation window needed (internal config, not a public API).

### README AC-7 scope — Keycloak client requirements section
- **Where**: `README.md:63-72` (Keycloak client requirements section)
- **What**: Bullet 4 ("A **`groups` client scope** with a Group Membership mapper…") and the explanation in the OIDC_SCOPE row (README.md:56, explaining why groups is needed) must be removed per AC-7
- **Surprises**: None — these are deployment docs, not runtime code. Removal is documentation hygiene.
- **Open**: Confirmed straightforward.

### Design system — epic in schema.json?
- **Where**: `docs/design/schema.json`
- **What**: AUTH epic has no entry (backend-only, no UI surface)
- **Surprises**: None — per CLAUDE.md, a story with no epic in schema.json may set `design: n/a`
- **Open**: Confirmed AUTH-06 has no design requirement.

## Pattern map

### Existing code to extend
- `services/api/app/core/auth.py::get_current_user` — add DB session dependency, replace `_parse_programs` call with new roster-lookup call
- `services/api/app/core/config.py::Settings` — delete `program_group_prefix` field, change `oidc_scope` default (no groups)
- `services/api/app/auth/dev_bypass.py::dev_bypass_sign_in` — drop the synthetic `groups` construction (line 98) and mint a top-level `programs` claim instead (AC-4/AC-6, resolved; see Clarifications)

### Existing patterns to follow
- `services/api/app/core/persona_resolver.py::PersonaResolver` — the caching/timeout/lock/logging pattern (300s TTL, asyncio.Lock, wait_for 3.0s timeout, structured PII-free event)
- `services/api/app/core/db.py::get_db` — FastAPI async dependency pattern for DB session injection
- `services/api/app/models/roster.py::ProgramRoster` — the ORM model, already live, with email index and removed_at soft-delete

### New files to create
- `services/api/app/core/program_resolver.py` (or rename PersonaResolver's pattern to a shared mixin?) — a new resolver module mirroring PersonaResolver's structure but for program membership (email → list of program_ids). Alternative: add a method to PersonaResolver or create a separate `program_membership_resolver.py` with identical structure.
- Test fixtures/mocks for `program_roster` table in `services/api/tests/` (roster state factories, sample data)

### Shared code at risk
- `services/api/tests/unit/test_auth_groups.py` — all 276 lines; tests assert on programs field derived from groups claim. Will need wholesale refactoring to mock/fixture roster instead.
- `services/api/tests/unit/test_auth_dev_bypass.py` — dev-bypass tests build tokens with a groups claim that is parsed back; they move to asserting the explicit `programs` claim (AC-4, resolved)
- `services/api/tests/unit/test_auth_config.py` — Settings tests include `program_group_prefix` default assertion; needs field removal
- `services/api/tests/perf/test_programs_perf.py` — performance test comments reference groups claim and PROGRAM_GROUP_PREFIX; docs only, comment cleanup

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|------------|
| 1 | Integration | HIGH | `get_current_user` must query `program_roster` table for every request; if DB is slow/down, auth path breaks. Currently async-safe but adds latency to every authenticated request. | Cache with 300s TTL + asyncio.Lock (mirroring PersonaResolver) + 3.0s query timeout per AC-5/NFR; must fit in AUTH-04's existing p95 < 300ms budget since auth runs under every request. Add observability: emit `program_membership_resolved` event with cache_hit/db_query tier + program_count (no email). Profile in PLAN phase to confirm budget fit. |
| 2 | Domain | HIGH | Roster table has 300s per-worker/per-process TTL; a manifest re-push via ING-10's POST /api/ingest/manifest is invisible for up to 5 min, and inconsistently across uvicorn workers. Operators may expect immediate membership changes. | Document the TTL and the eventual-consistency trade-off in the solution's PLAN/REQUIREMENTS (NFR section). ING-10's POST endpoint could optionally invalidate the cache (future work, out of scope here), but AUTH-06 itself has no cache-invalidation mechanism — TTL expiry and app restart are the only levers. Accept this as a known limitation for MVP; future cross-story invalidation hook can be added later. |
| 3 | Domain | ~~HIGH~~ RESOLVED | AC-4 (dev-bypass) required dev-bypass tokens to work without roster data while `_parse_programs` is deleted. Old mechanism: dev-bypass built `groups: ["program-<id>"]` which `get_current_user` parsed back. | **RESOLVED 2026-09-08** — dev-bypass mints `programs` as its own top-level JWT claim; `get_current_user` branches on `kid == DEV_BYPASS_KID` (already computed there, already used by `_claims_options`, `auth.py:161`) and skips the roster query on that branch only. Not keyed on claim presence (a Keycloak token carrying `programs` would silently skip the roster) and not keyed on `email == "dev-bypass@local"` (`payload.email` is caller-supplied). `dev_bypass.py` is now named in AC-6's file list; story Decision log records it. Residual work is mechanical and now scoped in AC-6: delete `dev_bypass.py:98`, add the claim, update `test_auth_dev_bypass.py`. |
| 4 | Dependency | MED | `_parse_programs` function is used in tests directly (boundary cases) and in dev_bypass.py. If deleted without updating all call sites, import errors. Grep output shows ~15 references across auth.py, dev_bypass.py, config.py, and tests. | Comprehensive grep/replace during PLAN: search for `_parse_programs`, `program_group_prefix`, `PROGRAM_GROUP_PREFIX` across services/api. Delete function from auth.py only AFTER all tests are rewritten and dev_bypass.py is updated per AC-4 mitigation. Use a temporary deprecation marker if needed (unlikely, internal function only). |
| 5 | Performance | MED | New resolver adds one synchronous/async boundary (asyncio.Lock, wait_for timeout) and a DB query to the auth path. If the 300s TTL is not enough and cache misses are high, every request becomes a DB round-trip. | Implement exactly per PersonaResolver's pattern: lock+TTL+wait_for(timeout=3.0s) per AC-5 NFR. Monitor cache hit rate in logs (emit tier: cache_hit vs tier: db_query on every session construction per observability NFR). If p95 latency exceeds budget in validation, increase TTL or add Redis caching (future story). Start with 300s per the story's own precedent/assumption. |
| 6 | Compatibility | MED | Tests assert on behavior that changes: `test_auth_groups.py` builds tokens with a groups claim, tests that it parses to programs, verifies case-sensitivity, duplicates, prefixes, etc. All those tests must be rewritten to test roster lookup instead of claim parsing. No old behavior to preserve backward compat with (internal API). | Refactor `test_auth_groups.py` to mock/fixture `program_roster` table state instead of building JWT claims. Keep test intent (match/zero-match/removed-row cases per AC-1..3, dev-bypass per AC-4). Fixture a sample roster state with known emails and program memberships, then verify the resolver returns the correct list. Rename/reorganize tests to reflect new domain (auth → roster membership resolution). |
| 7 | Security | LOW | Email is PII. AUTH-02's PersonaResolver omits email from logs (only logs role/persona/tier). AUTH-06's program resolver must follow the same rule: never log email in roster-lookup path. Per `.claude/rules/security-baseline.md`, no email logged ever. | Emit `program_membership_resolved` event with `{tier, program_count, timestamp}` only (no email, no program_id list). Mirrors AUTH-02's `persona_mapping_loaded` pattern exactly. Review the new resolver implementation before shipping to ensure no email escapes to logs/errors. |
| 8 | Integration | LOW | dev_bypass.py imports Settings to access `program_group_prefix` (auth/dev_bypass.py:98). Once the field is deleted from Settings (AC-6), this line fails. AC-4 mitigation (explicit programs claim in JWT) also removes this dependency. | Settled by the AC-4 resolution: `dev_bypass.py` no longer constructs a groups claim, so line 98 is deleted outright and the `Settings.program_group_prefix` dependency goes with it. AC-6 now names `dev_bypass.py` explicitly, so this is in scope rather than discovered mid-implementation. |
| 9 | Domain | LOW | ING-10's reminder: roster lives in `program_roster`, not `program_members`. `program_members` is rebuilt from `usage_events` on every ingest (BED-03's rebuild_program_rollups) and would wipe any write to it. AUTH-06 reads `program_roster` only (correct per AC-9); care needed if any future story tries to use `program_members` for membership. | No action in AUTH-06: the contract and model are already clear. Confirm during PLAN that the query is `FROM program_roster`, not `program_members`. Add a comment to the resolver referencing ADR-0010's decision if needed. Document in the REQUIREMENTS that `program_members` is not consulted for membership (by design, to avoid cache-wipe on every rollup rebuild). |

## Score + verdict

| Dimension | Weight | Passing criterion | Score | Notes |
|-----------|--------|-------------------|-------|-------|
| Integration | 25 | All upstream contracts available; failure modes known + bounded | 85 | ING-10 roster table live + indexed; AUTH-01 session complete. AC-5 adds DB query to auth path (highest risk); mitigated by caching + timeout + lock. Risk #1/2 (latency budget, TTL visibility) are known constraints, not unknowns. Profile budget fit in PLAN. |
| Compatibility | 20 | Backward compat plan exists for each affected client/version | 60 | Test breakage is internal (no backward compat needed). OIDC_SCOPE default change (groups removed) is runtime-breaking for existing deployments that rely on groups claim for other purposes — but story doesn't name any such purpose. No migration/deprecation window documented. Works for greenfield; existing deployments with custom group-based logic outside dashboard must adjust env var (low risk, documented). |
| Domain | 20 | Edge cases enumerated; no hidden invariants | 90 | AC-1..3 (match/zero/removed) are explicit. AC-4's dev-bypass mechanism is now decided and written into the story (explicit `programs` claim, `kid`-discriminated), and AC-6 names `dev_bypass.py`. AC-9 (use program_roster, not program_members) is clear. Removed-row soft-delete semantics confirmed (AC-3). No open domain question remains. |
| Performance | 15 | Story has explicit perf budget; estimated work fits | 70 | NFR specifies 300s TTL, 3.0s timeout, must fit in AUTH-04's p95 < 300ms end-to-end budget. No profile data yet (will run in PLAN phase). Cache pattern from AUTH-02 is proven (in production, used for every persona resolution). Single email → program_id list query is simpler than persona resolver's three-tier fallthrough, likely faster. Acceptable risk; PLAN must validate budget via prototype. |
| Dependency | 20 | All upstream stories complete; no blocking external work | 85 | ING-10 shipped (research_verdict=GO-WITH-CONDITIONS, complete, PR #244 on main). AUTH-01 shipped (research_verdict=GO-WITH-CONDITIONS, phase=review, complete). No external dependencies (Keycloak groups scope is eliminated, not harder to set up). The one internal blocker — AC-4's dev-bypass mechanism — is resolved at research time rather than deferred to PLAN. |

**Total: 78/100 → GO-WITH-CONDITIONS**  
_(was 74; Domain 75→90 and Dependency 80→85 after the AC-4 clarification was resolved on 2026-09-08. Compatibility stays at 60 pending an operator-facing note — see Condition 3.)_

### Conditions for GO-WITH-CONDITIONS

1. **Profile AUTH-04 p95 latency budget fit in PLAN.** AC-5 NFR + story's own performance requirement state the query must fit inside AUTH-04's existing p95 < 300ms end-to-end budget. The 300s TTL + asyncio.Lock + 3.0s wait_for pattern is proven from AUTH-02, but a prototype query latency measurement is required to confirm the db_query tier (cache miss) stays within budget on the dev database.

2. **Test refactoring scope review in PLAN.** test_auth_groups.py will require substantial refactoring (fixture roster state, rewrite assertions, rename tests). Estimate the effort and ensure it is accounted for in the PLAN phase's work breakdown.

3. **Document OIDC_SCOPE default change and eventual-consistency TTL as known limitations.** Both are acceptable (no show-stoppers), but must be explicit in PLAN/REQUIREMENTS and communicated to operators: groups scope is no longer requested (existing deployments must remove it from env var if they don't use it elsewhere); roster membership changes are visible after 300s per-worker/per-process TTL + the next cache expiry.

## Synthesis

AUTH-06 is **GO-WITH-CONDITIONS**: the story's scope is clear, both upstreams are shipped and working, and the implementation pattern is proven (PersonaResolver's caching/timeout/lock pattern is the exact template). The one blocker found — AC-4's dev-bypass mechanism — was resolved during research: dev-bypass mints an explicit `programs` claim and `get_current_user` skips the roster on the `kid == DEV_BYPASS_KID` branch, and AC-6 was widened to name `dev_bypass.py`, whose line 98 would otherwise have broken silently. Three conditions remain: a prototype latency measurement is needed to confirm the roster query fits inside AUTH-04's p95 < 300ms budget, and test refactoring (160+ lines in test_auth_groups.py) must be scoped/estimated. The roster table is live on main with proper indexing (email), the ORM model exists, and both upstream contracts are stable. Risks are known and bounded: cache TTL eventual-consistency (documented limitation, mirrors AUTH-02's trade-off), test breakage (internal, manageable), and config cleanup (straightforward deletion). No design work required (backend-only, no UI epic). Proceed to PLAN-REQUIREMENTS with the latency budget as the highest-priority item.

## Clarifications

<!-- None open. Resolved items are recorded under "Resolved clarifications" below. -->

## Resolved clarifications

**Resolved 2026-09-08 — AC-4 dev-bypass mechanism.** Raised as: should dev-bypass tokens carry an explicit `programs` claim, or should the resolver special-case dev-bypass by email?

The story's Decision log had already chosen the claim-based direction; what was genuinely undecided was the discriminator, and what the story had missed is that `dev_bypass.py:98` currently synthesizes `groups` from `settings.program_group_prefix` — so AC-6's deletion of that setting breaks dev-bypass, yet AC-6 did not list the file.

Resolution: dev-bypass mints `programs` as a top-level JWT claim; `get_current_user` branches on `kid == DEV_BYPASS_KID`, already computed there and already used by `_claims_options` (`auth.py:161`), and skips the roster query on that branch only. Rejected — branching on the presence of a `programs` claim (a Keycloak token carrying one would silently skip the roster) and branching on `email == "dev-bypass@local"` (`payload.email` is caller-supplied, so any caller could assert it).

Applied to `docs/stories/AUTH-06.md`: AC-4 names the mechanism and the discriminator, AC-6 adds `services/api/app/auth/dev_bypass.py` and the line-98 removal, Test mapping adds unit cover for it, and the Decision log records the rejected alternatives.

---

## State write

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-09-08T13:28:05Z"
}
```
