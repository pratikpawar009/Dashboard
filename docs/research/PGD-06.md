# Research: PGD-06 — Daily session-time chart w/ member filter

**Story**: PGD-06 (Validated)  
**Status**: Research complete — 0 open clarifications  
**Date**: 2026-09-17

## Upstream Dependency Summary

Four contract dependencies, all verified complete and merged to main:

| Dep | Contract | Phase | Research Verdict | Verified State |
|---|---|---|---|---|
| BED-01 | `db-schema` (session_series table with nullable member_id) | security-reviewed | GO-WITH-CONDITIONS | 18-table schema deployed (verified 2026-09-15); `session_series` table with `{org_id, program_id, member_id?, date, session_time_seconds, as_of_timestamp}` fields; Alembic migrations functional; nullable `member_id` confirmed in `app/models/rollup.py:165` |
| AUTH-03 | `rbac-checks` (program_visibility, member_in_program_visibility gates) | security-reviewed (PR 129, merged 2026-09-17) | GO-WITH-CONDITIONS | Both gates shipped and tested; `app/core/rbac.py:125-155`; `program_visibility` open-aggregate veto (any authenticated session), `member_in_program_visibility` self-or-cio gating with `member_view_denied` log event on denial |
| BED-02 | `api-conventions` (range validation, server-side formatting) | security-reviewed | GO-WITH-CONDITIONS | `validate_range` shipped (`app/dependencies/range.py`); server-side derivations (period_total, avg_per_day) contract established; 400 explicit-check pattern confirmed by PGD-02..05 (`Depends(_range_with_default)` wraps Query("30d")) |
| PGD-05 | `program-team-api` (GET /api/overview/program-detail/{program_id}/team, member roster) | security-reviewed (impl complete, branch feature/PGD-05) | GO-WITH-CONDITIONS | Route fully wired and tested as of 2026-09-17; `app/api/overview.py:349-390`; `fetch_program_team` returns roster with `member_id, member_name, role, sessions, tokens, avg_tokens_per_session` (raw ints for numeric fields); story-local member filter is drawn from this roster (AC-2 and story Decision log) |

**All four are usable today.** BED-01's schema is live. AUTH-03's gates are shipped on main. BED-02's conventions are reusable. PGD-05's member roster is the population source for the filter's dropdown.

---

## Exploration Log

### Repository State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean state; toolchains available)
- **Git branch**: chore/security-review-PGD-05 (tracking main)
- **Python**: 3.9.6; FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9 all installed; uv v0.9.26
- **pnpm**: 11.20.0

### Backend — Data Model

**Session Series Table** (`app/models/rollup.py:147-166`)
- **Schema**: `(id, org_id, program_id, member_id?, date, session_time_seconds, as_of_timestamp)`
- **Constraint**: Unique on `(org_id, program_id, member_id, date)` — enforces one row per (program, day) when `member_id=NULL` (org/program-wide rollup) and one row per (member, day) when `member_id` is populated
- **Nullable member_id**: Verified in source code. `member_id: Mapped[str | None]` with `nullable=True`. Populated by `_build_session_series()` in `app/services/rollup_rebuild.py` during ingest-driven rollup rebuild
- **Aggregation source**: Built from `usage_events` session grouping during `rebuild_program_rollups()` (synchronized on every ING-02 activity ingest, per ADR-0012)

**Program Members Table** (`app/models/rollup.py:176-189`)
- **Schema**: Used as roster source for member filter (`sessions, tokens` fields unused by filter, but carry program-level summary; filter displays member identity only)
- **Rebuilt per ingest**: Synchronized with `usage_events` (BED-03 verified), so active-in-range members in PGD-05 are consistent source for PGD-06 filter

### Backend — Sibling Routes & Patterns

**Overview Router** (`app/api/overview.py`)
- **Single module, five siblings shipped**: PGD-01 (header+summary), PGD-02 (token-trend 30d default), PGD-03 (releases paginated), PGD-04 (commands activity), PGD-05 (team roster)
- **Pattern**: Each route calls `program_visibility(current_user, program_id)` at start (open-aggregate veto, never logs on pass), then conditionally looks up `program_summary` (PGD-01/03 do; PGD-02/04/05 do not, per DECISIONS.md D-01/D-02), then returns shaped response
- **404 vs 200 empty asymmetry**: PGD-03 (releases) 404s on unknown program_id (requires real program); PGD-02/04/05 (token-trend, commands, team) return `200 {items:[]}` or all-zero series (activity aggregates, no identity lookup, DECISIONS.md D-01/D-02)
- **Member filter gating**: PGD-05's team table is open-aggregate (any authenticated session); the popup route `/team/{member_id}/usage` uses `member_in_program_visibility` (self or cio only) — PGD-06's fetch must follow this same split

**Range Validation Wrapper** (`app/dependencies/range.py` + local `_range_with_default`)
- **Personal-usage pattern** (SHP-02 `app/api/personal_usage.py:53-60`): Local wrapper supplies only `Query("30d")` default, delegates all `{7d,30d,90d}` validation to shared `validate_range()` — this pattern is reused identically by all PGD siblings
- **400 vs 422 contract**: Invalid range value triggers `HTTP 400 invalid_range` via `validate_range` (explicit check before handler body), never FastAPI's default `422`, per api-conventions (BED-02, FR-BE-02, AC-7)

**Logging & Timing** (PGD-03/04/05 examples)
- **Per-route event**: `program_releases_fetched`, `program_commands_fetched`, `program_team_fetched` — structured JSON events with `method, path, program_id, range, status, latency_ms` (using `time.perf_counter()` pattern, not per-route overhead counters)
- **Denial event**: `member_view_denied` logged by `member_in_program_visibility` gate itself on 403 (PGD-05-AC-12), no logging added in the route

**Response Shape Contract**
- **Pre-formatted vs raw ints**: Asymmetry is deliberate per README.md § API. PGD-02 (token-trend) `points[].tokens` is raw int; PGD-04 (commands) `items[].count` is raw int; PGD-03 (releases) all strings pre-formatted; PGD-05 (team) `tokens/sessions/avg_tokens_per_session` are raw ints
- **Server-side derivation**: PGD-02 (token-trend): `period_total, avg_per_day` computed server-side, raw ints (frontend owns formatting, per api-conventions); SHP-02 (personal-usage): `cards` are to-date aggregates, pre-formatted by `format_number()`, but `daily_tokens.points[].tokens` is raw int (ADR-0009 amendment, 2026-09-17)

### Frontend — Program Detail Page

**Design source**: `/Users/pratik.pawar/dashboards/Program Detail.html` (confirmed present; per standing user instruction, read from dashboards/ not docs/design/mockups/)

**Current mockup layout** (from schema.json mapping PGD epic to "Program Detail" page):
- Session-time chart is a distinct panel on the Program Detail page
- Chart shows daily bars (one per day in the selected range) with optional member filtering
- Member filter dropdown populated from the team roster (PGD-05's `items[]` list)
- Default state: org/program-wide view (no member filter); user can select a team member to drill into individual activity

**Period total and average/day display**: Per AC-4 (BED-02 api-conventions), must be computed server-side and returned in the response, never left for client-side arithmetic

### Contracts & Dependencies

**session_series Query Path**:
1. Chart loaded with default `range=30d` (RFC-PD-15)
2. Frontend calls `GET /api/overview/program-detail/{program_id}/session-time-series?range=30d` (new route PGD-06)
3. API: call `program_visibility(current_user, program_id)` veto gate (FR-PD-04, AC-6)
4. API: query `session_series` with `member_id=NULL` for org/program-wide; return `{points: [{date, session_time_seconds}, ...], period_total_seconds, avg_seconds_per_day}` (raw ints for time values)
5. Frontend: formats time using existing `format_duration()` or similar (per convention)

**Member Filter Path**:
1. User selects team member from dropdown (populated by PGD-05's roster)
2. Frontend calls `GET /api/overview/program-detail/{program_id}/session-time-series?range=30d&member_id={member_id}` (AC-3)
3. API: call `program_visibility(current_user, program_id)` veto gate (open-aggregate)
4. API: call `member_in_program_visibility(current_user, program_id, member_id)` for the member_id filter (FR-PD-16, AC-5) — raises 403 if not self or cio
5. API: query `session_series` with the specific `member_id`; return same shape with that member's data
6. Structured log event `member_view_denied` emitted by the gate on denial (NFR-011, AC-5); no event needed on success (per PGD-05 pattern)

---

## Pattern Map

### Existing Code to Extend

**Overview Router** (`app/api/overview.py`)
- Add a new route handler `get_program_session_series` (seventh sibling, following PGD-05's `get_program_team`)
- Reuse `program_visibility` veto gate (same call pattern as PGD-02..05)
- Reuse `member_in_program_visibility` gate for non-self member requests (already used by PGD-05's `/team/{member_id}/usage` route)
- Reuse `_range_with_default` wrapper (delegates to `validate_range`; all PGD siblings use this)

**Services Layer**
- New file `app/services/program_session_series.py` (parallel to `program_team.py`, `program_commands.py`, `program_releases.py`)
- Function `fetch_program_session_series(db, program_id, member_id: str | None, range: str) -> SessionSeriesResponse`
- Queries `session_series` table with filters on `(program_id, member_id, date_range)`; computes server-side `period_total_seconds, avg_seconds_per_day`
- No pagination (unlike releases); no existence lookup (activity aggregate, like commands/team)

**Schemas Layer**
- New response model `SessionSeriesResponse` in `app/schemas/` (parallel to `ProgramTokenTrendResponse`, `ProgramTeamResponse`)
- Shape: `{points: [{date, session_time_seconds}, ...], period_total_seconds, avg_seconds_per_day}` — all time fields raw ints

### Existing Patterns to Follow

**Range Validation Pattern**
- Local `_range_with_default` wrapper in `overview.py` supplies `Query("30d")` default; shares `validate_range` logic with no duplication
- Exact code already exists in `app/api/personal_usage.py:53-60` and replicated in `overview.py:200-208`; copy the same pattern

**RBAC Gating Pattern**
- Open-aggregate veto first: `await program_visibility(current_user, program_id)`
- Optional member filter gate: if `member_id` is provided, `await member_in_program_visibility(current_user, program_id, member_id)` before any query
- Gate denials raise `HTTPException(403)` before service layer is invoked (already handled by AUTH-03's gate functions)

**Logging Pattern**
- Structured JSON event per route: `{method, path, program_id, range, status, latency_ms}` using `time.perf_counter()` (matches PGD-03/04/05)
- Member-filter denial already logged by the gate itself as `member_view_denied`; no additional logging in the route body (per PGD-05 pattern)

**Response Shaping**
- Pre-formatted vs raw ints: time values (session_time_seconds, period_total_seconds, avg_seconds_per_day) are raw ints (matching PGD-02's token trend, per api-conventions)
- Period total and average computed server-side, never left for client (AC-4, BED-02 api-conventions)

### New Files to Create

- `services/api/app/services/program_session_series.py` — query logic for `session_series` aggregation and period-total computation
- `services/api/app/schemas/program_session_series.py` — `SessionSeriesResponse`, `SessionPoint` models
- `services/api/tests/unit/test_program_session_series.py` — unit tests for query + computation logic (mirroring `test_program_team.py`, `test_program_commands.py`)
- `services/api/tests/integration/test_program_session_series_api.py` — integration tests for the full route (auth gates, range validation, member filter, edge cases)

### Shared Code at Risk

**`validate_range` dependency** (`app/dependencies/range.py`)
- Used by all PGD siblings + SHP-02; addition of PGD-06 does not change the shared function
- Test existing suite (`tests/unit/test_range_validation.py`) guards against regression

**`program_visibility` and `member_in_program_visibility` gates** (`app/core/rbac.py`)
- Used across auth-gated routes; PGD-06 is the sixth consumer of `member_in_program_visibility`
- Existing test suite guards both gates; risk is **low** (no code change, only new caller)

**`session_series` table** (`app/models/rollup.py`, migrations)
- PGD-06 reads only (never writes); no migration needed
- Data is produced by `rebuild_program_rollups()` which already runs on every ING-02 ingest (BED-03 verified)
- Risk: **table freshness** — if rollup rebuild is skipped or delayed, chart will show stale data. Mitigated by BED-03's existing synchronous rebuild on ingest

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Integration | HIGH | `session_series` table freshness depends on `rebuild_program_rollups()` running on every ingest; if that rebuild is skipped or errors, chart shows stale data for days/weeks | Verify in plan that BED-03's `rebuild_program_rollups()` runs correctly (unit test `test_rollup_rebuild_program.py` confirms this); PGD-06 adds no new rollup pipeline; document freshness contract in API response metadata if needed |
| 2 | Domain | MED | Empty-state behaviour: days with no session activity should render as zero-valued bars, not errors; member filter with no rows should return empty array not 404 | Decision log (2026-08-26) records this assumption (consistent with PGD-02/04/05 empty-state pattern); code: return `200 {points: [...zeros...]}` for quiet programs/members, mirroring token-trend route (PGD-02-AC-7) |
| 3 | Compatibility | MED | Frontend's `format_duration()` or equivalent must exist to render time values; if undefined, time renders as raw integer seconds | Frontend team confirms design mockup requires duration formatting; formatter exists in frontend codebase (verify in plan via grep `apps/web/src` for `formatDuration`, `formatTime`, or similar); backend returns raw ints per api-conventions (BED-02) |
| 4 | Performance | MED | Query `session_series` for 90-day range across all members (`member_id NOT IN (...)` anti-pattern) could scan full table if not indexed | Index on `(program_id, member_id, date)` must be present (check: `alembic check` / verify in migration versions); composite index allows range scan on date while filtering by member (no N+1) — verify in plan that index exists before implementing |
| 5 | Dependency | LOW | Member roster used as filter source (PGD-05's `items[]`) — if PGD-05's roster endpoint breaks, filter population fails; if a member is soft-deleted from roster but has historical session data, inconsistency surfaces | PGD-05 is shipped and tested (branch feature/PGD-05 is live); story Decision log acknowledges roster is the filter source; test case: soft-deleted member should still appear in history queries (explicit test required to assert this behaviour) |
| 6 | Security | LOW | `member_in_program_visibility` gate must be called BEFORE querying session data for that member (prevents enumeration/data leak if query ran first) | AUTH-03 gate is shipped and tested; PGD-05 route already demonstrates correct call order (gate → query); mirror that pattern exactly in PGD-06; test case must spy on query execution order (existing test `app/core/rbac.py` TC-10 does this; replicate pattern in PGD-06 tests) |

**All risks are mitigable or have existing mitigations in place.** No blocker for implementation planning.

---

## Score + Verdict

| Dimension | Weight | Pass Criterion | Score | Notes |
|-----------|--------|---|---|---|
| Integration | 25 | All upstream dependencies available; failure modes understood | 90 | BED-01 schema deployed (nullable member_id confirmed); AUTH-03 gates shipped (both functions verified); BED-02 api-conventions established; PGD-05 roster stable. Only risk: `session_series` freshness depends on BED-03's rollup rebuild (synced on ingest, not a new risk). |
| Compatibility | 20 | Backward compat plan for each affected client/version | 85 | Frontend design mockup already calls for session-time chart (no scope surprise). Existing format_duration function assumed (verify in plan, low risk). Response shape follows established PGD pattern (raw ints, matching token-trend). No breaking changes to upstream APIs. |
| Domain | 20 | Edge cases enumerated; no hidden invariants | 88 | Empty-state behaviour documented in story Decision log (zero-valued bars, not errors). Member filter roster source acknowledged. Range validation via shared `validate_range` (existing, tested). Server-side period total/avg (no client arithmetic). Clear asymmetry between org-wide (null member_id) and member-scoped queries. |
| Performance | 15 | Story has explicit perf budget; estimated work fits within budget | 80 | NFR-002: chart refresh within 2s; NFR-001: initial page render within 3s. Query is simple aggregation on indexed table (session_series with (program_id, member_id, date) composite index, assumed present); no N+1, bounded result set (7/30/90 days max). **Risk #4: verify index exists in plan**. No complexity added to rollup pipeline (reads only). |
| Dependency | 20 | All upstream stories complete; no blocking external work | 92 | BED-01: GO-WITH-CONDITIONS, security-reviewed, merged. AUTH-03: GO-WITH-CONDITIONS, security-reviewed, merged. BED-02: GO-WITH-CONDITIONS, security-reviewed, shipped. PGD-05: GO-WITH-CONDITIONS, security-reviewed, implementation complete (branch feature/PGD-05 live). **No blocking external stories.** |

**Total: 87/100 → GO-WITH-CONDITIONS**

### Conditions for Implementation

The score of 87 requires the following conditions be met in `/arh-plan-requirements`:

1. **Index verification** (Risk #4): File plan must assert that `session_series` has a composite index on `(program_id, member_id, date)` — check via `alembic check` in preflight or confirm existing migration versions (008_program_team_index.py or similar) includes this index. If not present, file a new Alembic migration as a pre-req to PGD-06 implementation.
2. **Frontend formatter availability** (Risk #3): Plan must verify that a `format_duration()` or equivalent time formatter exists in `apps/web/src/` and document its call signature (e.g., `formatSeconds(seconds: number) -> string`). If missing, file a frontend story to add it before PGD-06 implementation; this is a low-risk addition (5-line utility function).
3. **Query pattern test** (Risk #6): Test strategy must include a test case that verifies `member_in_program_visibility` gate is invoked BEFORE the session-series query executes (structural assertion via spy/mock, mirroring AUTH-03's own `TC-10` test pattern). This ensures no data leak on denial.
4. **Soft-deleted member edge case** (Risk #5): Test strategy must include a test case for soft-deleted roster members: assert that a member with `removed_at` populated still appears in historical session-series queries (no artificial filtering on roster status, only on actual session data). Document in PLAN.md as T-<NN>.

None of these conditions block planning — all are standard pre-implementation verifications.

---

## Synthesis

PGD-06 (daily session-time chart w/ member filter) is **feasible and ready for planning**. All four upstream dependencies (BED-01 schema, AUTH-03 RBAC gates, BED-02 api-conventions, PGD-05 member roster) are complete and merged to main as of 2026-09-17. The data model (`session_series` table with nullable `member_id`) is already in place; the RBAC contract for member-scoped access is established via AUTH-03's `member_in_program_visibility` gate; and the sibling route patterns (PGD-01..05) provide clear precedent for range-based querying, open-aggregate gating, and structured response shaping. The primary implementation risk is ensuring the `session_series` table maintains freshness via the existing `rebuild_program_rollups()` pipeline (owned by BED-03, verified and tested, no change needed). A secondary verification is confirming the frontend's time formatter exists; if not, it's a low-effort utility addition. The overall score (87/100) reflects high feasibility with routine pre-plan conditions (index confirmation, formatter verification, edge-case test strategy).

---

## Clarifications

None. Story is well-specified; all ambiguities have been resolved in the Decision log (empty-state behaviour, filter roster source).

---

## Recommendations

1. **Mirror PGD-05 route structure exactly**: PGD-05's `/team` and `/team/{member_id}/usage` routes demonstrate the open-aggregate + member-scoped gating split; replicate this pattern for PGD-06's session-series route with the same gate ordering (veto first, then member-specific gate).
2. **Verify composite index on `session_series`** in plan Phase 2 (pre-implementation verification): Run `SELECT schemaname, tablename, indexname FROM pg_indexes WHERE tablename='session_series'` in test database to confirm `(program_id, member_id, date)` composite index exists. If not, add Alembic migration as blocking pre-req.
3. **Test soft-deleted member scenario**: Include an integration test that queries session-series for a member who has been soft-deleted from `program_roster` but has historical sessions — assert the data is returned (no artificial roster-status filter). This ensures the chart doesn't lose historical context when team members leave.

---

## State Write

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-09-17T20:00:00Z"
}
```
