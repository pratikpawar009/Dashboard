# Feasibility Assessment: SHP-03 — Personal session-wise usage list (paginated)

**Story**: SHP-03  
**Tracker**: [pratikpawar009/Dashboard#31](https://github.com/pratikpawar009/Dashboard/issues/31)  
**Certified**: 2026-08-26  
**Research date**: 2026-09-18

## Upstream dependency summary

| Story | Phase | Verdict | Status |
|-------|-------|---------|--------|
| BED-01 | security-reviewed | GO-WITH-CONDITIONS | user_sessions table, indexes (user_id, started_at) |
| AUTH-01 | security-reviewed | GO-WITH-CONDITIONS | CurrentUser, get_current_user() |
| AUTH-03 | security-reviewed | GO-WITH-CONDITIONS | individual_usage_visibility() gate (self OR cio) |
| BED-02 | security-reviewed | GO-WITH-CONDITIONS | validate_range(), get_page_params() pagination helpers |

All four are shipped on origin/main.

## Exploration Log

**Scan strategy**: Top-down from story → existing sibling SHP-02 → pagination patterns → RBAC → schema → API contract.

- `git ls-tree -r origin/main --name-only | grep -E "(user_sessions|personal_usage)" | head -20` → confirmed on main: models/rollup.py, api/personal_usage.py, schemas/personal_usage.py, migrations/001_initial_schema.py
- `grep -n "personal-sessions-api" docs/requirements/api.md` → line 276; endpoint + minimal field names documented, no full response shape yet
- `grep -rn "get_page_params" services/api/app/` → dependencies/pagination.py; clamps page_size to 100, defaults page=1
- `grep -rn "individual_usage_visibility" services/api/app/` → core/rbac.py lines 116–141; (self → pass) else (resolve persona → pass only "cio")
- `git show origin/main:services/api/app/api/personal_usage.py | wc -l` → 83 lines; SHP-02 exists, no sessions endpoint
- `grep -A3 "def list_activities" services/api/app/api/activities.py` → stub returns `{items, page, page_size, total}`; pagination response shape is clear

**Key findings**:

| Topic | Finding | Confidence |
|-------|---------|-----------|
| Database | user_sessions table exists, indexed on (user_id, started_at); schema complete per BED-01 | HIGH |
| Sibling route | SHP-02 (GET /api/personal-usage/{user_id}) exists; uses same RBAC gate + logging pattern | HIGH |
| Pagination lib | get_page_params() clamps page_size ≤ 100, defaults page=1; returns tuple (page, page_size) | HIGH |
| RBAC gate | individual_usage_visibility() raises HTTPException(403), logs individual_view_denied on denial only | HIGH |
| Response shape | api.md lists fields only (name/description, identifier, date, duration, tokens); full schema must come from story + mockup | HIGH |
| Precedent | activities.py stub shows paginated-list response shape: {items[], page: int, page_size: int, total: int} | HIGH |

**Resolved uncertainties**:
- Story Decision log §5 clarifies "name/description" (AC-1 prose) maps to single `user_sessions.name` column (no separate description field).
- Story Decision log §1–2 confirm RFC 403 / page=1 defaults from api-conventions precedent.
- Story Decision log §4 assumes ordering is most-recent-first (started_at DESC) — reasonable, not conflicting with any upstream.

## Pattern map

### Existing code to extend

- **services/api/app/api/personal_usage.py** — add `GET /{user_id}/sessions` route handler below the existing `get_personal_usage()` function (line 83). Route handler follows same thin-wrapper pattern: call `individual_usage_visibility()`, then delegate to a service function.
- **services/api/app/services/personal_usage.py** — add `fetch_sessions_paginated(db, user_id, page, page_size) → {items[], page, page_size, total}` service function. Reuse the existing pattern (single SELECT with COUNT OVER window function or LIMIT/OFFSET + separate count query).
- **services/api/app/core/rbac.py** — already has `individual_usage_visibility()`. No changes needed (gate applies to both SHP-02 and SHP-03).

### Existing patterns to follow

- **Pagination response shape** (activities.py precedent): `{items: list, page: int, page_size: int, total: int}` — not a dict-wrapping envelope, keys at top level.
- **Route handler thin-wrapper pattern** (SHP-02, PGD routes): call RBAC gate bare → raises on denial; then call service layer; return response.
- **Query discipline** (SHP-02 pattern): single SELECT for items (with LIMIT/OFFSET), separate COUNT or use window function. No N+1.
- **Pydantic schema** (personal_usage.py): BaseModel per item, ConfigDict for aliases, Field descriptions, populate_by_name=True on camelCase aliases.
- **Ordering** (consistent with daily-token tables): older rows first is the ascending convention; reversed for "most recent first" requires `ORDER BY started_at DESC`.
- **Per-user scoping**: all queries filtered by `user_id` at the WHERE clause, never post-fetch filtering.

### New files to create

- **services/api/app/schemas/personal_sessions.py** — Pydantic models for the sessions endpoint:
  - `PersonalSessionEntry(model_config, fields: name, identifier, date, duration_seconds, tokens, ...)`
  - `PersonalSessionsResponse(items: list[PersonalSessionEntry], page: int, page_size: int, total: int)`
- **tests/unit/test_personal_sessions_route.py** — unit tests for the endpoint (RBAC denial, pagination, zero-sessions case, etc.)

### Shared code at risk

- **services/api/app/core/rbac.py** — any change to `individual_usage_visibility()` affects both SHP-02 and SHP-03; none planned.
- **services/api/app/models/rollup.py** — UserSessions ORM model carries the `index` on (user_id, started_at); confirm index is used by the new query (EXPLAIN ANALYZE).
- **services/api/app/dependencies/pagination.py** — `get_page_params()` is a shared dependency; same clamping behavior applies to SHP-03.
- **services/api/app/core/errors.py** — error envelope; any HTTPException(403) from `individual_usage_visibility()` routes through here.

**Dependency graph** (simplified):

```
GET /api/personal-usage/{user_id}/sessions?page=&page_size=
  └─ FastAPI Depends()
     ├─ get_page_params() → (page, page_size)
     ├─ get_current_user() → CurrentUser (bearer token validation)
     └─ get_db() → AsyncSession
  └─ individual_usage_visibility(current_user, user_id) → 403 or None
  └─ fetch_sessions_paginated(db, user_id, page, page_size)
     └─ UserSessions ORM model
        └─ user_sessions table (indexed on user_id, started_at)
```

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | **Domain** | MED | Story prose says "name/description" (AC-1), schema has only `name`. Row renders one field, not two — mockup may expect two bindings. | Verify mockup rendering in ARC/DEV/PMD dashboard stories (ARC-01, DEV-01, PMD-01 contain the actual UI). If mockup shows only one, story prose is already clarified (Decision log). If mockup shows two fields, escalate. |
| 2 | **Performance** | MED | Pagination without explicit order-by—rows may arrive in arbitrary order, defeating "most recent first" UX. LIMIT/OFFSET without ORDER BY is unpredictable, potentially expensive. | Enforce `ORDER BY started_at DESC` in query. Add test asserting order; include EXPLAIN ANALYZE in PR to verify index usage. |
| 3 | **Integration** | LOW | `individual_usage_visibility` gate logs `individual_view_denied` on denial only (not authorized). Might confuse a reader expecting symmetric logging. | Document in the route handler (comment on line calling the gate) that this is intentional per AUTH-03-FR-2 — denial-only events reduce noise. |
| 4 | **Compatibility** | LOW | Pagination defaults (page=1, page_size=20) differ from api-conventions' 100-max. Some older clients may not handle the clamp-to-100 behavior correctly. | Document clamp behavior in PR body and OpenAPI schema. No action needed in code — get_page_params() already handles it. |
| 5 | **Domain** | LOW | Empty sessions list (zero rows) must return 200 {items: [], page: 1, page_size: 20, total: 0} not 404 or error. Story AC-5 clarifies this; easy to miss in implementation. | Test explicitly: call endpoint for user with no sessions, assert 200 with empty items, total=0. |

## Score + verdict

| Dimension | Weight | Evidence | Score |
|-----------|--------|----------|-------|
| **Integration** | 25% | All four upstreams complete; user_sessions table, RBAC gate, pagination dependency all exist and shipped. No external API, no MCP, no vendor uncertainty. | 95 |
| **Compatibility** | 20% | Route added to existing `/api/personal-usage/{user_id}` sibling; no schema breaking changes, no client-facing API version bump needed. Pagination clamp behavior is established pattern. | 90 |
| **Domain** | 20% | Story dependencies (story prose vs schema vs mockup) are clear. Single uncertainty (name/description → name) is resolved in Decision log. AC-5 (empty-result handling) is documented. Ordering assumption is reasonable. | 85 |
| **Performance** | 15% | Pagination has explicit limit/offset or keyset-cursor pattern in precedent (activities.py stub). Query cost is single SELECT per request, bounded by page_size ≤ 100. Index (user_id, started_at) is present. | 90 |
| **Dependency** | 20% | BED-01, AUTH-01, AUTH-03, BED-02 all GO-WITH-CONDITIONS and shipped; no waiting. No story-to-story sequencing risk. | 95 |

**Total: 90/100 → GO**

**Conditions for GO**: None. All upstreams shipped; all dependencies resolved; risk register documented; precedent is clear.

## Synthesis

SHP-03 is a tightly-scoped, low-risk addition to the existing personal-usage endpoint family. The route handler and service layer can follow established patterns (SHP-02 for RBAC, activities.py for pagination shape). The data model is complete (user_sessions table, index on user_id/started_at); the query is straightforward (WHERE user_id + page/limit). The single domain uncertainty (story prose says "description" but schema has only "name") is resolved in the story's own Decision log and poses no implementation risk. Ordering must be explicit (started_at DESC) to ensure "most recent first"; test explicitly to verify index usage. The RBAC gate reuses individual_usage_visibility (self OR cio, 403 on cross-user non-cio access) and logs denial-only, matching SHP-02's contract. **Proceed to /arh-plan-requirements without blockers.**

## Clarifications

None. All ambiguities in the story have been resolved in the story's Decision log (name/description → name; default page=1/page_size=20; 400 on page_size > 100; empty-list handling).

---

## Research state

```json
{
  "research": "complete",
  "research_verdict": "GO",
  "phase": "research",
  "last_updated": "2026-09-18T00:00:00Z"
}
```
