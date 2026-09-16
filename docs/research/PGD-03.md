# Research: PGD-03 — Releases list (paginated)

## Upstream dependencies

| Feature | Verdict | Status | Notes |
|---------|---------|--------|-------|
| BED-01 | GO-WITH-CONDITIONS | complete | `program_releases` table exists; schema matches story requirements (version, type, date, story_count, pr_count) |
| BED-02 | GO-WITH-CONDITIONS | complete | Range validation pattern (`validate_range` dependency returning 400) shipped; story reuses for `range={7d,30d,90d}` |
| AUTH-03 | GO-WITH-CONDITIONS | complete | `program_visibility` open-aggregate veto gate shipped; byte-identical cross-persona response contract established by PGD-01 |

All upstreams are gate-complete; no blocking external work.

## Exploration Log

### Story & Endpoint Route
- Story declares endpoint: `GET /api/program-detail/{program_id}/releases` (AC-1, Test mapping)
- PGD-01 (sibling) shipped as: `GET /api/overview/program-detail/{program_id}` (app/api/overview.py:104, README API table)
- PGD-02 (sibling) shipped as: `GET /api/overview/program-detail/{program_id}/token-trend` (app/api/overview.py:160)
- README: no releases endpoint documented yet; sibling routes live under `/api/overview` router prefix
- **Pattern discrepancy**: story names endpoint without `/overview` prefix; siblings use `/overview`

### Database
- `program_releases` table: exists in BED-01's 001_initial_schema.py, columns: id (PK), program_id, version, type, date, story_count, pr_count, as_of_timestamp
- ORM model: app/models/rollup.py::ProgramReleases (mapped, index on program_id, no soft-delete)
- Schema shape matches AC-1 field list (version, type, date, story_count, pr_count) ✓

### RBAC & Auth
- `program_visibility(current_user, program_id)` check: open-aggregate veto gate, passes for any authenticated session (AC-4)
- Byte-identical cross-persona response: PGD-01 AC-6 contract, story AC-4 mirrors (no persona branching)
- `get_current_user()` dependency available; used by PGD-01, PGD-02
- 401 on missing/invalid bearer token: baseline established by AUTH-01 `session` contract

### Range Validation & Pagination
- `validate_range(request, range)` custom dependency exists (app/dependencies/range.py, per BED-02 implementation)
- PGD-02 pattern: `_range_with_default` helper returning 30d, wrapped via `Depends()`, delegates validation to `validate_range`
- Story requires: `range=30d` default, `offset=0` default, `limit=20` default, `limit` clamped to 50 (AC-2)
- Invalid `range`: 400 (not 422) per AC-3, BED-02 resolved pattern
- Total row count window constraint: story AC-1 specifies `total_count` reflects same range filter

### Design Validation
- Mockup path: `dashboards/Program Detail.html` (per user pinned instruction). Bundler output — markup extracted per `docs/design/README.md` before grepping.
- **Releases panel EXISTS.** Section title "Releases via Harness", subtitle `Releases shipped with Harness · {{ relRangeLabel }}`, header stat `{{ relTotal }}` / "releases shipped", and a 3-button range switcher (`{{ relRanges }}`, `hint-placeholder-count="3"` → 7d/30d/90d).
- Row list: `<sc-for list="{{ releases }}" as="r" hint-placeholder-count="6">` inside `max-height:296px;overflow:auto` — this is the scroll container AC-7/FR-PD-10 describe. Six-row empty/loading placeholder.
- Column headers: Version | Release | Date | Stories | PRs merged. Per-row bindings: `r.ver`, `r.label`, `r.dot`, `r.tagColor`, `r.tagBg`, `r.date`, `r.stories`, `r.prs`.
- Values arrive pre-formatted: `r.date` is `"Jul 15"` (no year), `r.stories`/`r.prs` are `String(...)`, `relTotal` is `String(relCount)`. The mockup's `genReleases` never formats client-side.
- The mockup binds CSS as well as data: `r.dot`, `r.tagColor`, `r.tagBg` are colour literals consumed directly in `style=`/`background:` attributes.
- Summary strip (PGD-01, already shipped) separately carries `⤴ Releases done via Harness` — a program-lifetime count, distinct from this panel's range-scoped `relTotal`.

### Error Handling & Logging
- 404 on unknown `program_id`: story AC-6 assumption, matches PGD-01 convention (HTTPException 404, "program not found" detail)
- 401 on unauthenticated caller: story AC-5 assumption, baseline bearer-JWT behavior (AUTH-01)
- Structured logging: method, path, program_id, range, offset, limit, status, latency (NFR-011)
- `program_visibility` check does not emit a dedicated audit log per README AUTH-03 contract

### Test Coverage
- Unit tests required: range validation (valid/invalid), pagination (offset/limit), clamping (limit > 50), 404 on unknown program, RBAC (passes for any persona), byte-identical cross-persona, total_count window consistency
- E2E: not configured (`test_e2e` unset in project-commands.yaml)
- Fixtures: no `program_releases` seed fixtures observed in existing tests

### Toolchain & Patterns
- FastAPI router pattern: single `APIRouter(prefix=...)` per resource (app/api/overview.py:64 for PGD-01/02)
- Async handler signature: matches `get_program_detail` (async, Depends for db/user/headers)
- Query bounds: offset/limit Query(default=..., ge=0, le=50) pattern (app/api/activities.py:17-18)
- Formatting: `format_number()` utility for display values (app/utils/format.py)
- Response model: Pydantic BaseModel with typed fields

## Pattern map

### Existing code to extend
- `app/api/overview.py` — add `/releases` subroute on the same `overview` router as PGD-01/02 (if prefix resolved to `/api/overview/...`)
- `app/dependencies/range.py` — range validation already exists; reuse via `_range_with_default` helper pattern
- `app/core/rbac.py` — `program_visibility` check exists; call same as PGD-02 does
- `app/utils/format.py` — `format_number()` for pre-formatted display values

### Existing patterns to follow
- Router prefix: `/api/overview` (established by PGD-01, PGD-02) — pattern consistency within Program Detail family
- Response shape: Pydantic model with typed fields (ProgramReleasesResponse)
- Pagination bounds: Query(default=..., ge=0, le=50) clamping pattern
- Error envelope: `app/core/errors.py` registered handlers produce `{error: {code, message, details}}` (app/core/errors.py:9-10)
- Logging: `logger.info(event_name, extra={...})` with structured extras (app/api/overview.py:140-144)
- Async engine + SQLAlchemy 2.0 select (app/core/db.py, app/models/rollup.py)

### New files to create
- `app/schemas/program_releases.py` — Pydantic models:
  - `ProgramReleaseItem` (version, type, status_indicator, date, story_count, pr_count)
  - `ProgramReleasesResponse` (items: list, total_count: int, offset, limit)
- `apps/web/src/app/[program]/releases/page.tsx` — frontend page (or integrate into existing program-detail page)
- `apps/web/src/components/ReleasesList.tsx` — paginated list component (scroll behavior)
- `services/api/tests/unit/test_program_releases_list.py` — unit tests for range, pagination, RBAC, errors

### Shared code at risk
- `app/dependencies/range.py` — this module is called by PGD-02, PGD-03, and potentially other future endpoints; if clamping logic changes, multiple callers are affected
- `app/core/rbac.py::program_visibility` — open-aggregate veto gate; any bug here affects all program-detail-family endpoints (PGD-01, PGD-02, PGD-03, downstream ARC-01/DEV-01/PMD-01/EMD-01)
- `app/utils/format.py::format_number()` — used for display value pre-formatting; any change in formatting rules affects response consistency across routes

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Integration | RESOLVED | Route prefix discrepancy: story named `GET /api/program-detail/{program_id}/releases`, siblings PGD-01/PGD-02 shipped `/api/overview/program-detail/...`. | **Resolved 2026-09-16 (user decision):** use `/api/overview/program-detail/{program_id}/releases` on the existing `overview` router. Update story AC-1 + Test mapping and the README API table during `/arh-plan-requirements`. |
| 2 | Domain | MED | Naming drift, not a design gap: the mockup's row model is `{ver, label, dot, tagColor, tagBg, date, stories, prs}` — it has no `type` field and no `version`/`story_count`/`pr_count` spelling. The story names `version`, `type`, `date`, `story_count`, `pr_count` (BED-01 column names). The wire contract must be settled against the mockup, which is authoritative per CLAUDE.md § Design system. | Map explicitly in the PRD: `version`→`ver`, `story_count`→`stories`, `pr_count`→`prs`. `date` ships pre-formatted as `"Jul 15"`, not ISO. Decide whether the API emits mockup spellings directly or the frontend adapts; PGD-01/PGD-02 precedent is that the API emits the mockup's shape verbatim. |
| 3 | Domain | MED | "Status indicator" resolved by the mockup, but NOT as the story assumed. The mockup renders a coloured dot + human label from a 4-entry kind vocabulary — `Feature release` (#1f8a5b), `Patch release` (#2a6fdb), `Hotfix` (#d1495b) — NOT the story Decision log's `major\|minor\|patch`. Separately, `r.ver` carries its own `tagColor`/`tagBg`, which in the mockup are the *program*'s theme colours, not per-release. | Adopt the mockup vocabulary: wire fields `label` + `dot`, pre-formatted server-side (PGD-01 precedent). Correct the story's Decision-log assumption, which does not match the design. Confirm whether `tagColor`/`tagBg` are program-level (hoisted out of the row) or per-row; the mockup passes them in per row but sources them from the program theme. |
| 4 | Dependency | MED | Frontend scope: Test mapping lists `ReleasesList.tsx` but no separate frontend story exists. The mockup settles the *placement* — a panel on the existing Program Detail page, between the token-trend chart (PGD-02) and the Commands+Team section — so this is a scoping question, not a design one. | Confirm the component ships inside PGD-03 rather than a separate story, and that it mounts on the existing Program Detail page. Also decide the range-switcher wiring: the panel has its own independent 7d/30d/90d control, separate from PGD-02's chart switcher. |
| 5 | Dependency | MED | Shared code at risk: `validate_range` (app/dependencies/range.py) is called by PGD-02, PGD-03, future endpoints; any change in validation logic or error messaging affects all consumers. No centralised test suite enforces consistency across all callers. | BED-02 research identified this (Risk 7): create a shared test suite (test_range_validation.py) exercising range validation across multiple endpoints; reference in PLAN.md. Run as part of unit test gate. |
| 6 | Domain | MED | `total_count` window consistency: AC-1 specifies `total_count` reflects releases within the `range` filter. Implementation must ensure `count(*)` query includes the same `date` window as the paginated results. Inconsistency (e.g., total count unbounded while results are bounded) is a subtle bug. | Add explicit test case: `total_count == (unbounded count of releases in range)` for a populated program. Assert on every range value (7d, 30d, 90d). Document in service-layer code that total_count and results use identical date predicates. |
| 7 | Performance | MED | No index analysis for range queries: `program_releases(program_id, date)` is queried via offset/limit over a date window. BED-02 flagged (Risk 6) that no current evidence of index coverage exists for date-range queries on usage_events or rollup tables. Same risk applies here. | Check if migration 001 or later migrations created an index on `program_releases(program_id, date)`. If absent, add a compound index during BED-01 follow-up or as a mitigation before PGD-03 implementation. Measure query time with representative data during validation phase (5000+ releases per program). |
| 8 | Compatibility | LOW | RBAC logging: Story NFR-011 requires structured logging; `program_visibility` check does not emit a dedicated audit log (per README AUTH-03 contract). This is by design (open-aggregate check = no audit event), but a reviewer expecting "every RBAC check logs" may flag it. | Document in PLAN.md and PR that `program_visibility` is intentionally not logged (not a per-user/per-resource decision, just session validity); only request-level logging captures the access event (method, program_id, status, latency). Cite README AUTH-03 contract as justification. |

## Score

| Dimension | Weight | Score | Rationale |
|-----------|--------|-------|-----------|
| Integration | 25 | 70 | Upstreams complete and gate-passed (BED-01 table, BED-02 range validation, AUTH-03 RBAC). **Deduction**: route prefix discrepancy (HIGH risk) unresolved; unclear whether endpoint is `/api/program-detail/...` (story) or `/api/overview/program-detail/...` (pattern consistency). Must resolve before implementation starts. |
| Compatibility | 20 | 85 | Design contract is fully settled: the mockup carries the complete releases panel — section, range switcher, scroll container (`max-height:296px;overflow:auto`, AC-7), five columns, six-row placeholder, per-row bindings. **Deduction**: mockup row spellings (`ver`/`stories`/`prs`, pre-formatted `date`) differ from the story's BED-01 column names, so the wire contract needs an explicit mapping in the PRD. |
| Domain | 20 | 75 | Story AC, FR, and NFR are well-specified (range validation, pagination, RBAC, logging), and the mockup resolves the status indicator concretely (dot colour + label, 4-entry kind vocabulary). **Deductions**: (1) the mockup's vocabulary contradicts the story Decision log's `major\|minor\|patch` assumption, so the story needs correcting; (2) `total_count` window consistency needs a deliberate test. |
| Performance | 15 | 75 | Story includes 2s latency budget (NFR-002, sourced). Pagination pattern established (offset/limit clamping). **Deduction**: no index evidence for `program_releases(program_id, date)` range queries; mitigation depends on BED-01 follow-up work. Query performance unknown without representative data. |
| Dependency | 20 | 75 | All upstream stories complete and shipped (gate-passed); the mockup settles where the frontend component mounts. **Deductions**: (1) frontend scope not formally assigned to a story; (2) shared range-validation test suite incomplete (BED-02 Risk 7, not yet mitigated); (3) RBAC logging (low risk, by design). |

**Total: 77/100 → GO-WITH-CONDITIONS**

**Conditions**: Any single dimension < 40? No. Score 70–84 → **GO-WITH-CONDITIONS**.

## Conditions for GO

1. **Route prefix — DECIDED.** Register the endpoint as `GET /api/overview/program-detail/{program_id}/releases`, a subroute on the existing `overview` router alongside PGD-01/PGD-02. Update story AC-1, the story's Test mapping, and the README API table to this path.
2. **Wire contract follows the mockup, not the story's field list.** Record in the PRD the exact response shape implied by `dashboards/Program Detail.html`: row fields `ver`, `label`, `dot`, `tagColor`, `tagBg`, `date`, `stories`, `prs`; `date` pre-formatted (`"Jul 15"`, no year); counts emitted as strings; range-scoped total rendered as `relTotal`. Correct the story's `major|minor|patch` status Decision-log entry — the mockup's vocabulary is `Feature release` / `Patch release` / `Hotfix` with a dot colour.
3. **Index coverage.** Confirm an index on `program_releases(program_id, date)` exists (BED-01 migration 001 or later); if absent, record the mitigation in the PRD so the NFR-002 ≤2s budget is not left unevidenced.

## Synthesis

PGD-03 is a well-supported extension of a shipped pattern: BED-01's `program_releases` table, BED-02's `validate_range` 400-on-invalid dependency, AUTH-03's open-aggregate `program_visibility`, and two sibling Program Detail endpoints (PGD-01, PGD-02) that already establish the router, the range-default helper, the byte-identical cross-persona contract, and the pre-formatted response convention. The Program Detail mockup carries the releases panel in full — section, independent range switcher, scroll container, five columns, and per-row bindings — so the UI contract is settled rather than open. What remains is not feasibility but specification hygiene: the story's route prefix predates the `/api/overview/...` pattern its siblings shipped, and its field names and `major|minor|patch` status assumption both disagree with the authoritative mockup. Both are decidable in the PRD without a spike.

## Clarifications

None open.

Resolved during this assessment:
- **Route prefix — RESOLVED 2026-09-16 (user decision):** the endpoint is `GET /api/overview/program-detail/{program_id}/releases`, a sibling subroute on the same `overview` router as PGD-01 and PGD-02. Chosen for pattern consistency within the Program Detail resource family; the story's `/api/program-detail/...` wording predates that pattern shipping and is superseded. Story AC-1, Test mapping, and the README API table follow this path.
- Releases panel in the Program Detail mockup — **exists**; see § Design Validation for its bindings.
- Status indicator shape — **pre-formatted `label` + `dot` colour** from the mockup's 4-entry kind vocabulary (`Feature release`, `Patch release`, `Hotfix`), not the story's `major|minor|patch`.
