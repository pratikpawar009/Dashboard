# Feature: AUTH-06 — Roster-sourced program membership (retire groups-claim scoping)

## Problem

Program membership is derived today from the OIDC `groups` claim (`_parse_programs`,
`services/api/app/core/auth.py:175-188`, called at `:236`; prefix `PROGRAM_GROUP_PREFIX`,
`config.py:57`): onboarding a new program means creating a Keycloak group plus a Group
Membership mapper — realm administration for what this project has decided should be a
reviewed file change. That decision is a standing project boundary, not new scope: Keycloak/OIDC
is authentication only here; per-program membership and roles belong to each program's own
committed `.harness/program.yaml` roster. ING-10 already shipped the `program_roster` table on
that basis (PR #244, live on `main`), but nothing reads it yet — every session still authorizes
off Keycloak groups, and onboarding a program still means opening a Keycloak admin console
first.

## Outcome

`session.programs` is the distinct set of `program_id`s matched from `program_roster` by the
session's `email` — primary or any alias row, soft-deleted rows excluded — never from `groups`.
Onboarding a program's dashboard access becomes a roster file change alone (ING-10's ingest
endpoint); no Keycloak group or mapper is created or maintained for it. `GET /api/programs`
and every other consumer of `session.programs` inherit the new source with zero code change
(AC-8). The groups-claim scoping mechanism — `_parse_programs`, `PROGRAM_GROUP_PREFIX`, the
`groups` entry in `OIDC_SCOPE`'s default — is deleted from the codebase and its documentation.

## Constraints

- Roster read pattern is fixed by ING-10's shipped `program-roster-schema` contract:
  `program_roster(id, program_id, email, name, role, source, removed_at, created_at,
  updated_at)`, unique on `(program_id, email)`, one row per alias — sourced,
  `docs/requirements/data.md#program-roster-schema`; table live in
  `services/api/migrations/versions/003_program_roster.py`, ORM model at
  `services/api/app/models/roster.py`.
- Must land inside AUTH-04's existing `p95 < 300ms` end-to-end budget for `GET /api/programs`
  — sourced, AUTH-04 NFR — since `get_current_user` runs beneath every authenticated request.
- Zero contract-shape change for any consumer: `GET /api/programs` (`app/api/programs.py`)
  requires no code edit (AC-8); `user_roles` (ING-08, reference/audit only) is never consulted
  (AC-9).
- Standing project boundary (user-set 2026-09-08): Keycloak/OIDC is authentication only;
  per-program membership and roles come from each program's own committed
  `.harness/program.yaml` roster, never Keycloak groups. This story is the mechanism that
  retires the groups-claim path and brings the code into line with that boundary — the
  strategic point of the story, not an incidental refactor.
- Dev-bypass (AUTH-01) must keep working in its existing allow-listed environments with zero
  roster seed data (AC-4); the resolution mechanism (explicit `programs` claim,
  `kid`-discriminated skip) was decided during research and is not re-opened here.
- No new runtime dependency: the cache/lock/timeout pattern reuses `asyncio.Lock` /
  `asyncio.wait_for`, already in the stack via `services/api/app/core/persona_resolver.py`
  (AUTH-02) — no Redis, no new library.

## Solution sketch

A new resolver, mirroring AUTH-02's `PersonaResolver` caching pattern, replaces
`_parse_programs` inside `get_current_user`: on every non-dev-bypass request it resolves the
session's `email` to the distinct set of `program_id`s from `program_roster` (soft-delete
filtered), cached per-email for `300s` behind an `asyncio.Lock`-guarded, `3.0s`-timeout DB read.
Dev-bypass mints `programs` as its own top-level JWT claim, and `get_current_user` skips the
roster entirely on the `kid == DEV_BYPASS_KID` branch already used to select signing keys.
`Settings.program_group_prefix`, `_parse_programs`, the synthetic `groups` construction in
`dev_bypass.py`, and the `groups` entry in `OIDC_SCOPE`'s default are deleted; `README.md`'s
Keycloak `groups`-client-scope guidance is removed.

## Addressing Research Conditions

Research verdict GO-WITH-CONDITIONS, 78/100. Three conditions, `docs/research/AUTH-06.md` §
Conditions for GO-WITH-CONDITIONS:

- **1. Profile AUTH-04 p95 latency budget fit in PLAN.** Mitigation: Non-functional
  requirements § Performance pins the `3.0s` timeout and the `300s`/AUTH-04-budget constraint
  as the spec; `/arh-plan-implementation`'s work breakdown must include a dedicated prototype
  task that measures the cache-miss (`db_query`) tier's latency against the dev database before
  implementation sign-off — the PersonaResolver pattern is proven, but this story's own query
  has not been measured yet. This PRD does not claim the budget is met; it specifies the budget
  and requires PLAN to prove fit before code is written.
- **2. Test refactoring scope review in PLAN.** Mitigation: Scope § In names the three affected
  test files (`test_auth_groups.py` — 276 lines, `test_auth_dev_bypass.py`,
  `test_auth_config.py`) explicitly rather than leaving them implicit; `/arh-plan-implementation`
  must carry a scoped, estimated task for fixturing `program_roster` state and rewriting
  claim-based assertions against it, sized as its own unit of work rather than folded silently
  into the resolver task.
- **3. Document OIDC_SCOPE default change and eventual-consistency TTL as known limitations.**
  Mitigation: Non-functional requirements § Performance/Observability state the `300s` TTL and
  "TTL expiry is the sole invalidating event" explicitly; Documentation requirements' README
  update adds an operator-facing note that (a) deployments relying on `groups` for a purpose
  other than program-membership scoping must add it back to their own `OIDC_SCOPE` value after
  this change, and (b) a roster re-push via ING-10's `POST /api/ingest/manifest` becomes visible
  only after the next per-worker/per-process TTL expiry (up to `300s`), with an app restart as
  the only faster lever.

## Scope

**In:**
- Roster-backed `session.programs` derivation in `get_current_user` — match / zero-match /
  removed-row / alias cases (AC-1/AC-2/AC-3, FR-1); `program_roster` is the only table read
  (AC-9, FR-1).
- Per-email cache/lock/timeout resolver mirroring `PersonaResolver` (AC-5, FR-2).
- Dev-bypass explicit top-level `programs` JWT claim plus `kid == DEV_BYPASS_KID`-discriminated
  roster skip (AC-4, FR-3).
- Retirement: delete `Settings.program_group_prefix` (`config.py:57`); drop `groups` from
  `OIDC_SCOPE`'s default; delete `_parse_programs` (definition and the `auth.py:236` call site);
  replace `dev_bypass.py:98`'s synthetic `groups` construction with the FR-3 claim (AC-6).
- `README.md`: remove the `groups` client-scope/mapper bullet and the
  `PROGRAM_GROUP_PREFIX`/`OIDC_SCOPE`-groups env-var rows; add the TTL eventual-consistency
  operator note (AC-7, Condition 3).
- Test refactor: `test_auth_groups.py`, `test_auth_dev_bypass.py`, `test_auth_config.py`
  rewritten against fixtured `program_roster` state instead of JWT-claim construction
  (Condition 2).

**Out:**
- `GET /api/programs` code changes — zero, verified unchanged (AC-8).
- Cross-worker / cross-process cache coherence (e.g. Redis) — per-process TTL only; documented
  limitation (Condition 3).
- Cache invalidation triggered by ING-10's `POST /api/ingest/manifest` — future work; this
  story's only levers are TTL expiry and an app restart (research Risk #2 mitigation).
- `user_roles` wiring into session scoping — stays reference/audit only, untouched (AC-9).
- Any change to `program_members` — membership reads only ever hit `program_roster`; `
  program_members` is rebuilt from `usage_events` on every ingest and is not this story's read
  path (ADR-0010).
- Preserving the `groups` OIDC scope for consumers unrelated to program membership —
  deployments that use `groups` for another purpose must re-add it to their own `OIDC_SCOPE`
  value; this story does not special-case that (Condition 3, documented limitation).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-06.md` for canonical wording.
New impl constraints introduced below:

**AUTH-06-FR-1** — Roster query shape and exclusive table *(extends AC-1/AC-2/AC-3/AC-9 with:
the exact query and table)*

Session construction issues exactly one query on the non-dev-bypass path:
`SELECT DISTINCT program_id FROM program_roster WHERE email = :session_email AND removed_at IS
NULL`. Only `program_roster` is read — `program_members` (rebuilt from `usage_events` on every
ingest, ADR-0010) and `user_roles` (ING-08 AC-4: reference/audit only) are never consulted on
this path. A zero-row result sets `session.programs = []` and construction still succeeds — no
401/500.

**AUTH-06-FR-2** — Cache/resolver algorithm mirrors `PersonaResolver` *(extends AC-5 with: exact
caching mechanics)*

The new resolver caches `email -> (list[program_id], expiry_ts)` per-process, keyed by
`session_email`, TTL `300s` measured via `time.monotonic()` (not wall-clock) — matching
`services/api/app/core/persona_resolver.py:86-226`. Read path: a cache hit within TTL returns
immediately (`tier=cache_hit`). On a miss, an `asyncio.Lock` (event-loop-only, not
`threading.Lock`) guards a double-checked re-read — a second caller that waits on the lock
re-checks the cache before querying, bounding concurrent queries for the same email to one —
then the DB read runs under `asyncio.wait_for(..., timeout=3.0)`; a timeout raises rather than
hanging. Every non-dev-bypass session construction emits
`program_membership_resolved {tier: cache_hit|db_query, program_count}` — no `email`, no
`program_id` list (PII, `.claude/rules/security-baseline.md`).

**AUTH-06-FR-3** — Dev-bypass roster-skip is `kid`-discriminated only *(extends AC-4/AC-6 with:
the forbidden alternatives, as a durable regression guard)*

`get_current_user` skips the roster query if and only if `kid == DEV_BYPASS_KID` — the same
computed value `_claims_options` already branches on (`app/core/auth.py:161`) — the sole
discriminator. It is explicitly **not** the presence of a `programs` claim (a Keycloak-issued
token carrying one would silently skip the roster and grant caller-declared membership) and
**not** `payload.email` (caller-supplied on the dev-bypass request body, forgeable). A future
change that widens this check to either rejected alternative is a security regression, not a
refactor — flag it at review.

## Non-functional requirements

- Performance: Per `.claude/rules/performance-baseline.md`: applies to the roster resolver
  introduced by this story. Explicit `3.0s` `asyncio.wait_for` timeout bounds every
  `program_roster` query — no unbounded wait. Cache TTL `300s` per email is the sole
  invalidating event; an app restart is the only faster-than-TTL lever (no auto-invalidation
  hook from ING-10's ingest endpoint in this story's scope). Feature-specific budget: this
  lookup must land inside AUTH-04's existing `p95 < 300ms` end-to-end budget for
  `GET /api/programs`, since `get_current_user` runs beneath every authenticated request —
  Condition 1 requires a PLAN-phase prototype measurement of the cache-miss (`db_query`) tier
  against the dev database before implementation sign-off.
- Security: Per `.claude/rules/security-baseline.md`: applies to the roster resolver and
  `get_current_user`. `email` (PII) is never logged in the roster-lookup path —
  `program_membership_resolved` (FR-2) carries `tier`/`program_count` only. The dev-bypass
  roster-skip branches on `kid == DEV_BYPASS_KID` exclusively (FR-3) — not claim presence, not
  `payload.email` — because either alternative lets a caller forge scope; this is a
  security-relevant discriminator choice, not a style preference, and a future widening of it is
  a regression, not a refactor.
- Accessibility: N/A — backend session-construction change, no UI surface (mirrors AUTH-04
  precedent; `AUTH` epic has no entry in `docs/design/schema.json` →
  `designSystem.pages.features`).
- Observability: `program_membership_resolved {tier: cache_hit|db_query, program_count}` emitted
  on every non-dev-bypass session construction (FR-2) — no `email`, no `program_id` list.
  Dev-bypass sessions (FR-3) emit no roster-resolution event, since no roster query runs on that
  branch.

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan

- **Strategy**: bang-bang — internal swap of `session.programs`' data source with no external
  contract change (AC-8 keeps `GET /api/programs` byte-identical); single deploy, no cohort
  needed.
- **Feature flag**: none — `Settings.program_group_prefix` is deleted outright, not toggled.
- **Backout plan**: revert the PR — restores `_parse_programs`, `PROGRAM_GROUP_PREFIX`, and the
  `groups` `OIDC_SCOPE` default. Any deployment that removed `groups` from its own `OIDC_SCOPE`
  value in response to this story's default change (Condition 3) must re-add it manually on
  backout; this is a manual step, not automated by the revert.
- **Success signal**: post-deploy, real (non-dev-bypass) sessions' `session.programs` matches
  the same program memberships previously derived from `groups` for existing rostered users,
  with zero session-construction `401`/`500` regressions, and `GET /api/programs`'s measured
  p95 stays under `300ms` (Condition 1 validated in production).

## Documentation requirements

- **README updates**: `README.md` § Keycloak client requirements — remove the `groups`
  client-scope/Group-Membership-mapper bullet (AC-7). `README.md` § Environment variables —
  remove the `PROGRAM_GROUP_PREFIX` row and update `OIDC_SCOPE`'s documented default to
  `openid profile email` (AC-6/AC-7); add a note that deployments relying on `groups` for a
  purpose other than program-membership scoping must re-add it to their own `OIDC_SCOPE` value,
  and that a roster re-push via `POST /api/ingest/manifest` becomes visible after the next `300s`
  per-worker/per-process TTL expiry, not immediately (Condition 3).
- **Runbook**: none — the only operational lever for a faster-than-TTL refresh is an app
  restart, documented inline in the README note above (Condition 3; research Risk #2
  mitigation).
- **API reference**: none — `GET /api/programs`'s OpenAPI documentation is unchanged (AC-8); no
  new route is added by this story.
- **Inline code comments**: the new resolver module's docstring documents the `PersonaResolver`
  precedent it mirrors and the TTL-only invalidation trade-off (FR-2); `get_current_user`'s
  `kid == DEV_BYPASS_KID` branch gets an inline comment recording the two rejected discriminators
  (FR-3) so a future edit does not silently widen it.
- **Examples / how-to**: none.

## Open questions

<!-- None open. needs_clarification_count: 0. docs/research/AUTH-06.md § Clarifications reads    -->
<!-- "None open." (resolved items recorded under § Resolved clarifications). All three            -->
<!-- GO-WITH-CONDITIONS conditions are addressed above in § Addressing Research Conditions. No new -->
<!-- ambiguity surfaced while drafting this PRD.                                                   -->
<!-- Decisions logged in docs/stories/AUTH-06.md § Decision log.                                   -->
<!--                                                                                                -->
<!-- Kept as a comment deliberately, matching AUTH-02/AUTH-04/ING-10 in this repo: the              -->
<!-- phase-preconditions clarification gate treats any non-blank, non-comment line in this section  -->
<!-- as an unresolved open question and aborts the next phase.                                      -->

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| Product Owner | Pratik Pawar | 2026-09-08 | APPROVE |
| Designer | — | 2026-09-08 | N/A — `design_mode = none`; `AUTH` has no epic in `docs/design/schema.json`, so `design: n/a` per `CLAUDE.md` (matches AUTH-01/04/05) |
| BA | Pratik Pawar | 2026-09-08 | APPROVE, with the coverage gap below accepted deliberately |

Gate checks at approval: no-placeholder grep **0 hits**; unresolved `[NEEDS CLARIFICATION]`
**0**; all three GO-WITH-CONDITIONS conditions addressed in § Addressing Research Conditions;
3/3 test cases carry a `requirement_id` resolving to a real declared id.

### Accepted at gate: test-case coverage gap

`docs/test-cases/AUTH-06.json` `coverage_audit.uncovered` is **non-empty** — `AUTH-06-AC-6`,
`AUTH-06-AC-7` and `AUTH-06-AC-8` have no backing test case. Approved anyway, deliberately:

- The user set a hard cap of 2–3 test cases for this run, against 9 ACs, 3 delta FRs and 4 NFR
  topics. The three cases were spent on the highest-risk behaviour: the roster swap itself
  (`AUTH-06-TC-01` → AC-1/2/3/9 + FR-1), the `kid == DEV_BYPASS_KID` security discriminator
  (`AUTH-06-TC-02` → AC-4 + FR-3 + NFR-security), and the cache/lock/timeout mechanics
  (`AUTH-06-TC-03` → AC-5 + FR-2 + NFR-performance + NFR-observability).
- That covers **all 3 delta FRs** and **3 of 4 NFR topics** (accessibility is N/A per the story).
- The three uncovered ACs are the cheapest to verify without automation: AC-6 and AC-7 are
  code- and doc-presence assertions (`Settings.program_group_prefix` deleted, `.env.example` and
  `README.md` rows struck, `dev_bypass.py:98` removed), and AC-8 is a zero-code-change guarantee
  on `GET /api/programs` best confirmed by a no-diff check on `app/api/programs.py`.
- Carry-forward: `/arh-validate-feature` must confirm AC-6, AC-7 and AC-8 by inspection, since no
  automated case will fail if they regress.
