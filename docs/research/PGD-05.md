# Research: PGD-05 — Project team table + per-member usage popup

**Story**: PGD-05 (Validated)  
**Status**: Research complete — 0 open clarifications  
**Date**: 2026-09-17

## Upstream Dependency Summary

Five contract dependencies:

| Dep | Contract | Phase | Research Verdict | Verified State |
|---|---|---|---|---|
| BED-01 | `db-schema` (program_members table) | security-reviewed | GO-WITH-CONDITIONS | 18-table schema deployed; `program_members` table present with `(program_id, user_id, name, role, sessions, tokens)` fields; Alembic migrations functional |
| AUTH-03 | `rbac-checks` (member_in_program_visibility gate) | security-reviewed (PR 129, merged) | GO-WITH-CONDITIONS | `member_in_program_visibility` shipped, tested; `app/core/rbac.py:140-155`; fails self-or-cio gate with 403 + `member_view_denied` log event |
| BED-02 | `api-conventions` (range validation, formatting) | security-reviewed | GO-WITH-CONDITIONS | `validate_range`, `format_number`, `format_duration` all shipped, `app/dependencies/range.py` + `app/utils/format.py`; reusable via Depends |
| SHP-02 | `personal-usage-api` (GET /api/personal-usage/{user_id}) | security-reviewed (impl complete) | GO-WITH-CONDITIONS | Endpoint fully wired, tested, live on main; response shape locked (`cards, daily_tokens, commands`); popup reuses verbatim with story-local `member_in_program_visibility` gate replacing SHP-02's own `individual_usage_visibility` (per AC-9 and api.md `authz_note`) |
| PGD-01 | `program-detail-api` contract (same endpoint path prefix) | security-reviewed | GO-WITH-CONDITIONS | `/api/overview/program-detail/{program_id}` router established as the PGD mounting point; all four siblings (PGD-01..04) use this same router prefix; new route follows established patterns |

**All five are usable today.** AUTH-03's `member_in_program_visibility` (PR 129) is confirmed merged to main; SHP-02's `personal-usage-api` is complete and tested; BED-01's `program_members` table is deployed and indexed.

---

## Exploration Log

### Repository State & Toolchain
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean except docs/activity/activity.jsonl modified; expected agent files present)
- **Git branch**: chore/security-review-backfill-2026-09-17, aligned with main
- **Python**: 3.9.6; FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, pytest-asyncio all installed
- **uv**: `/Users/pratik.pawar/.local/bin/uv` v0.9.26 (available)
- **pnpm**: 11.20.0 (available)

### Backend State — Models & Existing Patterns

#### Data Model (`program_members` table)
- **Location**: `app/models/rollup.py:164-175`
- **Schema**: `(id, program_id, user_id, name, role, sessions, tokens, last_active_date, as_of_timestamp)`
- **Index**: `ix_program_members_program_id` on `program_id` column only — no composite index on `(program_id, range)` because `program_members` is a **snapshot** (to-date aggregate), not a range-scoped table — see Risk #1
- **Ownership**: Rebuilt synchronously by `BED-03`'s `rebuild_program_rollups()` on every ING-02 activity ingest from `usage_events`, fully `DELETE+INSERT` (BED-03 verified), so roster rows are usage-derived not manually-maintained (confirm in research §Upstream, no roster-ingest path for `program_members` itself)

#### Sibling Route Patterns (PGD-01..04)
- **Router module**: `app/api/overview.py` (single module, line 93: `router = APIRouter(prefix="/api/overview", tags=["overview"])`)
- **Routes**: `GET /program-detail/{program_id}` (PGD-01), `GET /program-detail/{program_id}/token-trend` (PGD-02), `GET /program-detail/{program_id}/releases` (PGD-03), `GET /program-detail/{program_id}/commands` (PGD-04)
- **Pattern**: Each route (a) calls `program_visibility(current_user, program_id)` once at the start (open-aggregate veto gate, never branches, never logs on pass), (b) performs optional `program_summary` lookup (PGD-01/03 do this; PGD-02/04 do not, per DECISIONS.md D-01/D-02), (c) emits one structured log event per outcome path (`time.perf_counter()` timing pattern from `admin.py`), (d) returns pre-formatted response
- **Response shape contract**: Fixed presentation constants (glyph/label tuples zipped with values) via `_SUMMARY_CARD_GLYPHS_LABELS` pattern (`overview.py:101-109`) — mirrors SHP-02's own `_CARD_PRESENTATION` (4-tuple: glyph, label, iconBg, iconColor), extended for the personal-usage cards context

#### Range Validation & Formatting
- **Range validation wrapper**: `app/dependencies/range.py:validate_range(request, range: str = Query(...)) -> str` — required by default, no inline default logic built in (confirmed by reading `tests/unit/test_range_validation.py` — no prior story has implemented the `Query("30d")` default wrapper yet)
- **Personal-usage pattern** (SHP-02, `app/api/personal_usage.py:53-60`): story-local `_range_with_default` wrapper supplies only the `Query` default, delegates all validation to shared `validate_range` — same pattern PGD-05 must mirror for the team table
- **Formatting**: `format_number()` (`app/utils/format.py:74-105`) for M/K counts; `format_duration()` for time values; precedent already established for `bar_style_for_share()` (used by SHP-02 commands panel)

#### RBAC Pattern (`member_in_program_visibility`)
- **Location**: `app/core/rbac.py:140-155`
- **Contract**: `async def member_in_program_visibility(current_user: CurrentUser, program_id: str, target_member_id: str) -> None` — calls `program_visibility(program_id)` first (veto gate, failure propagates), then self-or-cio check (target == current.user_id OR persona == "cio"); denial raises bare `HTTPException(403)`, logs `member_view_denied` event with `{user_id, target_member_id}` fields (per api.md `authz_note` contrast: this gate **replaces** SHP-02's `individual_usage_visibility` for the popup context, as per AC-11's decision)
- **Test coverage**: `tests/unit/test_rbac.py` includes `test_member_in_program_visibility_*` test cases — pattern confirmed working

#### Personal-Usage Router Reuse (SHP-02)
- **Endpoint**: `GET /api/personal-usage/{user_id}?range=7d|30d|90d` (SHP-02 complete, implemented on main, tested)
- **Response model**: `PersonalUsageResponse { cards: [...], daily_tokens: {...}, commands: {...} }` — defined in `app/schemas/personal_usage.py`, fully wired
- **Popup invocation**: AC-9 specifies the popup calls this endpoint verbatim — no reshaping, no additional fields added; the `personal-usage-api` response is rendered as-is (SHP-02 research AC-10 confirms no PGD-05-specific modifications)
- **RBAC seam difference**: SHP-02's own route uses `individual_usage_visibility(current_user, user_id)` (self always, cio always); PGD-05's popup wraps the same endpoint call behind a **different** gate (`member_in_program_visibility`) that adds the `program_id` constraint — this difference is deliberate (api.md `authz_note` cites it) and is handled by PGD-05's own route, not inside `personal_usage.py`

### Design Reference (Mockup Extraction)

#### Program Detail Page Mockup
- **File**: `docs/design/mockups/Program Detail.html` (bundler output, JSON-escaped HTML)
- **Decoded markup** (per README.md extraction script): `<!-- ... -->` section boundaries present; mockup includes team table section
- **Team table structure** (from mockup section): table with columns for member identity, role, metrics (sessions, tokens, avg/session); each row is clickable (row data-bind); design bindings confirm field names must be pre-formatted on the wire
- **Popup trigger**: per AC-9, row click opens member popup via `GET /api/personal-usage/{user_id}?range=...` call (browser client-side, no intermediate PGD-05 relay)

### Frontend State (Next.js)
- **Program Detail page route**: exists at `src/app/program-detail/[program_id]/page.tsx` (PGD-01 completed)
- **Team table component**: implied by PGD-01's design reference but implementation deferred to PGD-05's own frontend planning; will consume the new `program-team-api` endpoint via server-side fetch or client-side query
- **Personal-usage popup component**: reused from SHP-02, already exists; PGD-05's frontend work wires this popup into the team table's row click handler, no new component needed

### Existing Service Patterns (BED-03 rollup rebuild)
- **File**: `app/services/rollup_rebuild.py:360` (`delete(ProgramMembers)` unconditional)
- **Impact**: every activity ingest via ING-02 fully reconstructs `program_members` from `usage_events` — the team table always reflects live, usage-derived membership, no manual roster management (this is critical for understanding the data freshness NFR-002 ≤2s constraint)

---

## Pattern Map

### Existing Code to Extend
- **`app/api/overview.py` router**: add a new route handler `GET /program-detail/{program_id}/team` alongside the four existing PGD routes (PGD-01..04)
- **`app/schemas/program_detail.py`**: extend to include `ProgramTeamRow` (member_name, role, sessions, tokens, avg_tokens_per_session) and `ProgramTeamResponse` envelope

### Existing Patterns to Follow
- **Router endpoint pattern**: mirror PGD-01..04 — (a) call `program_visibility(current_user, program_id)` once, open-aggregate veto gate, never filters by membership; (b) query `program_members` and range-scoped activity joined as needed; (c) emit one structured log event per outcome path (timing via `time.perf_counter()`, matching `admin.py` + PGD-03/04 precedent); (d) return pre-formatted response
- **Fixed presentation constants**: team table has no glyphs or color tokens in the UI (unlike cards), so no 4-tuple constant needed; row iteration / column headers are frontend-owned
- **Range validation wrapper**: story-local `_range_with_default(request: Request, range: str = Query("30d")) -> str` wrapping shared `validate_range` (mirrors SHP-02 pattern exactly)
- **RBAC gate for popup**: the team-table GET route uses `program_visibility`; popup access is gated separately inside a NEW handler (`GET /program-detail/{program_id}/team/{member_id}`) or as a separate endpoint entirely — per api.md and AC-9, the popup calls `personal-usage-api` directly, so PGD-05 adds a **middleware** gate (route-level RBAC) that the frontend respects by catching a 403 on that cross-origin call (PGD-05 does NOT relay the popup request through its own endpoint; that's a separate decision to clarify — see Risk #3)
- **Data source**: `program_members` table is snapshot-based (updated by BED-03's rebuild on ingest), so queries are simple single-table SELECTs; no complex join needed (unlike SHP-02 which must query both `user_sessions` and `usage_events`)

### New Files to Create
- **`services/api/app/services/program_team.py`** — query/aggregation logic: `async def fetch_program_team(db: AsyncSession, program_id: str, range: str) -> list[ProgramTeamRow]` — single SELECT from `program_members` filtered on `program_id`; range filtering requires a join to `usage_events` or a secondary table (see Risk #1)
- **`services/api/tests/unit/test_program_team.py`** — unit tests for the service layer query, edge cases (zero members, range boundaries)
- **`services/api/tests/perf/test_program_team_perf.py`** — query-count spy + timing assertion against NFR-002 ≤2s budget

### Shared Code at Risk
- **`app/api/overview.py`** — adding a new route to this module does not change existing routes; read-only extension
- **`app/models/rollup.py::ProgramMembers`** — queries only, no mutations; safe to read (see Risk #1 regarding index)
- **`app/core/rbac.py::member_in_program_visibility`** — called by the popup endpoint (or by a new gate the frontend tests); fully shipped and tested; no edit needed
- **`app/dependencies/range.py`** — read-only via `Depends`; the story-local wrapper is the only story-specific wiring

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|---|---|---|---|
| 1 | Performance | HIGH | `program_members` table carries only to-date rollup data (snapshot, no temporal columns); to return range-scoped `sessions/tokens/avg`, a JOIN to `usage_events` or a secondary range-bucketed table is needed. `program_members` has only `ix_program_members_program_id` — no composite index on (program_id, date_range). NFR-002 (≤2s refresh) is at risk if the join is naive (full table scan on `usage_events` per program). | New Alembic migration adds `Index("ix_usage_events_program_id_user_ts", "program_id", "user", "ts")` or equivalent to support range+member-scoped queries. Service layer issues exactly two SELECTs (one `program_members` snapshot, one ranged `usage_events` aggregate) — never a Cartesian product join. Add perf test mirroring `tests/perf/test_program_team_perf.py` with query-count spy + ≤2s budget assertion. |
| 2 | Domain | MED | `program_members` is fully rebuilt on every ING-02 ingest from `usage_events` (BED-03 verified). The team table's `name` and `role` fields come directly from this table — if the user's real name/role in the program roster is different from what `usage_events` attributes them as, the team table shows the usage-derived version (e.g. an email alias may appear as a row with blank name/role). Settled by contract (no manual roster for `program_members`; usage-derived only) but should be documented so it is not mistaken for a bug. | Carry-forward note (not a blocker): PGD-05 ships with this limitation; enriching team rows from a manual roster is a separate future story outside this scope (no roster-enrichment logic in this story's AC/FR). Decision log records that `name` / `role` are usage-derived, not manually-maintained. |
| 3 | Integration | MED | AC-9 says the popup "calls `personal-usage-api`" — ambiguity: does the frontend call it **directly** (cross-origin fetch, PGD-05 adds only RBAC gate via CORS or response headers), or does the frontend **relay** the request through a new PGD-05 endpoint that PGD-05 gates before proxying to SHP-02? Current read of api.md suggests direct frontend call (PGD-05 role is RBAC gate only, via the `member_in_program_visibility` rule that governs who can access SHP-02's endpoint); but CORS/header-based gating is fragile. | Clarify before planning: does the frontend call `personal-usage-api` directly, or does PGD-05 add a relay endpoint? Decision log records the choice + rationale. If relay: new route added to `app/api/overview.py` (POST or GET via query string), gates via `member_in_program_visibility`, proxies request to `personal_usage` endpoint (same host, internal call). If direct: frontend respects 403 denials; PGD-05's own RBAC gate is documentation/intent-clarity only, not a runtime wall. |
| 4 | Domain | LOW | AC-7 "zero members → empty list, not error" is an assumption aligned with the graceful-zero pattern (SHP-02 research Risk #7, PGD-02..04 precedent), but PRD gives no explicit rule; confirmed in Decision log. | Carry-forward note: Decision log records the zero-members behavior (empty list) is an assumption. PLAN.md's schema section documents this explicitly. |
| 5 | Compatibility | MED | Four downstream stories (ARC-01, DEV-01, PMD-01, EMD-01) + SHP-07 declare a hard RTM dependency on `program-team-api` — response shape is the lock-in point. Unlike SHP-02 (4 external consumers before any implemented), PGD-05 ships after SHP-02 is complete, so the popup reuse is lower-risk, but the team-table shape itself (member_name, role, sessions, tokens, avg/session per AC-1 and api.md) must be exact. | PLAN.md's schema section lists the exact fields, order-locked, sourced from the api.md shape line + mockup verification (team-table columns visible in decoded Program Detail mockup); field names verified against api.md contract before implementation starts. |
| 6 | Dependency | LOW | `avg_tokens_per_session` rounding rule (AC-5): PRD gives no explicit rounding spec, but Decision log (2026-08-26 assumption) records "rounded to nearest integer" — consistent with BED-01's `BigInteger` storage of tokens, and the familiar rounding pattern from SHP-02's own average computation. | Decision log records the rounding assumption (nearest integer); PLAN.md's schema section defines `avg_tokens_per_session: int` (not `float`). During implementation, reuse `app.services.rollup_compute.compute_average` if available, else mirror its contract. |
| 7 | Domain | LOW | Row ordering: AC does not specify, Decision log (2026-08-26 assumption) records "descending by tokens" — aligns with `program_board_api` precedent (sibling). May not be important, but a reordering later would look like drift to downstream consumers. | Decision log records ordering assumption; PLAN.md and/or code comments document "ordered by tokens DESC" + why; unit test locks the ordering expectation. |
| 8 | Dependency | LOW | BED-03's rollup rebuild is synchronous on ING-02 ingest (per verified code read), so the team table reflects live data at query time. No separate async-rebuild coordination needed, but if this assumption is wrong, NFR-002 (≤2s) could fail due to stale snapshots. | Verification: confirm in PLAN.md that `program_members` is synchronously updated (already verified in research Exploration Log §rollup rebuild); no async rebuild seam needed. If BED-03 ever changes to async, SHP-02/PGD-02..06 are all affected — not a PGD-05-only issue. |

---

## Score

| Dimension | Weight | Score | Rationale |
|---|---|---|---|
| Integration | 25 | 90 | All five upstream contracts merged to main, working, tested. `program_members` table deployed; `member_in_program_visibility` shipped; `program_visibility` pattern proven in PGD-01..04; SHP-02's `personal-usage-api` live and locked. Only gap: clarification on popup relay vs direct (Risk #3), well-understood and a PLAN-time decision, not blocking research. |
| Compatibility | 20 | 82 | Response shape locked by api.md + mockup verification; 5 downstream consumers are still in `story-validated` phase (no breaking changes possible yet). Shape is exact, field-order critical, contract-locked early. |
| Domain | 20 | 78 | AC and FR are well-specified; range scoping, zero-member response, and presentation logic are all resolved from precedent (PGD-01..04, SHP-02). Usage-derived name/role limitation (Risk #2) is settled by contract, not a gap. One ambiguity (popup relay vs direct) requires a PLAN-time choice but does not block research scoring. |
| Performance | 15 | 68 | NFR-002 (≤2s) is explicit, but current `program_members` index (program_id only) supports only the snapshot read; range-scoped join to `usage_events` needs new index (Risk #1). Addressable in-scope via migration + perf test, not a structural blocker, but real work needed to lock in under budget. Query pattern is simple (two SELECTs, no Cartesian product), so risk is manageable. |
| Dependency | 20 | 92 | All five upstream stories `phase: security-reviewed`, `research_verdict: GO-WITH-CONDITIONS`. BED-03 rollup rebuild is verified synchronous. No blocking external work; popup reuses SHP-02 endpoint verbatim; RBAC gate is shipped. |

**Total: 82/100 → GO-WITH-CONDITIONS**

---

## Conditions for GO

1. **Index for range-scoped queries**: New Alembic migration adds an index on `(usage_events.program_id, usage_events.user, usage_events.ts)` to support the range+member-filtered aggregate query. Perf test (mirroring `tests/perf/test_program_team_perf.py`) asserts query-count-spy-based bounded SELECT count + duration ≤2s under NFR-002 budget.

2. **Popup relay vs direct decision**: PLAN.md's Integration section records whether the frontend calls `personal-usage-api` directly (CORS-gated) or PGD-05 adds a relay endpoint (internal proxy). Rationale + implications documented (e.g. "direct = CORS scope decision deferred to auth/infra story"; "relay = new POST/GET route added to overview.py, gates via member_in_program_visibility before proxying").

3. **Decision log entries** (before coding): records assumptions for (a) `name`/`role` usage-derived (no manual enrichment in scope), (b) zero-members → empty list (not error), (c) `avg_tokens_per_session` rounding rule (nearest int), (d) row ordering (tokens DESC), (e) BED-03 rollup rebuild is synchronous. Each entry includes timestamp, assumption, and rationale.

4. **Response schema exact**: `ProgramTeamResponse` lists exact fields (`member_name, role, sessions, tokens, avg_tokens_per_session`) in exact order, sourced from api.md contract + mockup verification, field types locked (`avg_tokens_per_session: int`, not float). No additional fields added. PLAN.md's schema section names the response model files + field definitions.

5. **PLAN.md file plan** uses real paths (`services/api/app/api/overview.py` for the new route, `services/api/app/services/program_team.py` for the service layer, `services/api/app/schemas/program_detail.py` for the response schema) — not invented or incorrect paths.

---

## Synthesis

GO-WITH-CONDITIONS. Every upstream contract PGD-05 needs — `program_members` table, `member_in_program_visibility` RBAC gate, `program_visibility` veto pattern, range validation, `personal-usage-api` endpoint — is already merged to main and directly verified working. The FR-AUTH-08 decision (popup scope + gate) is freshly added to this story and is clean-scoped to AC-9..12 with no scope creep. The score lands at 82/100 rather than higher because of two concrete gaps: first, the `program_members` table's current index (`program_id` only) requires a new index on `(program_id, user, ts)` to support range-scoped queries without full-table scans, and this cost (a new migration + perf test, both in-scope) must be explicitly budgeted in PLAN.md to ensure NFR-002 (≤2s) is achievable (Risk #1, HIGH severity but fully addressable). Second, AC-9's "popup calls personal-usage-api" glosses over whether the frontend calls SHP-02's endpoint directly (cross-origin, CORS-gated) or PGD-05 adds a relay endpoint (auth-proxied) — this is a PLAN-time integration decision, not blocking research but must be recorded before implementation starts (Risk #3, MED severity). A third cluster of lower-severity Domain risks (usage-derived name/role, zero-member response, rounding rule, ordering) are all resolvable from existing precedent (BED-03, SHP-02, PGD-01..04) rather than requiring new product input, so 0 clarification markers were needed. Next step: `/arh-plan-requirements PGD-05`, with PLAN.md required to address all 5 conditions above explicitly.

---

## Clarifications

<!-- None open. -->
