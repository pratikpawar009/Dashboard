# Research Assessment: SHP-04 — Artifacts generated panel

**Date**: 2026-09-18  
**Assessed by**: Autonomous research agent  
**Story**: docs/stories/SHP-04.md  
**Status**: Validated → Research-Complete

---

## Upstream Dependencies

SHP-04 depends on two contract dependencies (both shipped/complete):

1. **BED-01** — `db-schema` contract (`docs/requirements/data.md`): `program_artifacts` table exists, populated via ING-03's `POST /api/ingest/artifacts`. **Status**: Security-reviewed (2026-09-15).
2. **AUTH-03** — `rbac-checks` contract (`docs/requirements/auth.md`): `governance_visibility` gate exists in `services/api/app/core/rbac.py:196-243`, ready to be wired into routes. **Status**: Security-reviewed (2026-09-15).

No blocking dependencies; both read-contract dependencies (buildable against the APIs).

---

## Exploration Log

**Scan focus**: API endpoint contract, RBAC gate availability, response shape inference from mockups and siblings, pattern precedents.

- **Command**: `grep -rn CANONICAL_ARTIFACT_TYPES services/api/`  
  **Result**: Five canonical types frozen in `services/api/app/schemas/ingest_artifacts.py:47-49`: `{"prd", "user_story", "test_case", "arch_diagram", "api_spec"}`. Case-sensitive, closed set. **Match**: Exactly 5 per story AC-1. ✓

- **Command**: `find services/api/app/models -name "*.py" | xargs grep -l "program_artifacts"`  
  **Result**: `services/api/app/models/governance.py:15-26` defines `ProgramArtifact` ORM model. Columns: `id, program_id, type, count, as_of_timestamp`. Unique constraint on `(program_id, type)`. **Match**: Matches story AC-3 requirement for per-type rows. ✓

- **Command**: `grep -n "async def governance_visibility" services/api/app/core/rbac.py`  
  **Result**: `services/api/app/core/rbac.py:196-243`. Gate passes only for `persona in ("architect", "product-manager", "developer")` and logs `rbac_check_governance_visibility` on both outcomes (both authorized and denied). **Match**: Matches story NFR security requirement. ✓  
  **Critical**: Zero route consumers in `services/api/app/api/` — SHP-04 will be the first to call this gate. No precedent to follow; gate is tested in isolation (`services/api/tests/unit/test_rbac.py`), not yet wired into a live endpoint.

- **Command**: Extract mockup markup for "Artifacts generated" panel from Architect, Developer, Product Manager dashboards.  
  **Result**: All three mockups contain identical markup for the panel (same template structure, data bindings `{{ artifacts }}`, `{{ a.name }}`, `{{ a.count }}`, `{{ a.bg }}`, `{{ a.color }}`). Template expects a list of 5 rows with `tag` (monospace label), `name` (friendly type name), `count` (large number). **Match**: Panel exists on all three intended dashboards; no divergence between personas. ✓

- **Command**: `grep -rn "individual_view_denied\|member_view_denied" services/api/app/api/`  
  **Result**: Both events logged by their respective RBAC checks (`individual_usage_visibility`, `member_in_program_visibility`) — no custom denial event emitted by the router. The check emits the event on denial, and the route carries no additional logging. **Implication**: Story's Decision log claims `governance_view_denied` event, but the RBAC check logs `rbac_check_governance_visibility` with an `outcome="denied"` field. No separate governance-denial event exists yet; story author may have assumed a pattern not yet established.

- **Command**: `grep -A 10 "GET /api/personal-usage\|GET /api/overview/program-detail" services/api/app/api/*.py`  
  **Result**: `personal_usage.py:76` calls `Depends(individual_usage_visibility(...))` as a gate. Response shape: `{cards, daily_tokens, commands}` with pre-formatted strings + raw-int fields (documented in README.md ADR-0009). Similar pattern in `overview.py` with multiple siblings on the same router.

- **Command**: `python3 -c "import sys; from services.api.app.models.governance import ProgramArtifact; from app.core.config import settings; from sqlalchemy import create_engine, select; engine = create_engine(settings.database_url); with engine.begin() as conn: result = conn.execute(select(ProgramArtifact).where(ProgramArtifact.program_id == 'dashboard')); print([(r.type, r.count) for r in result.fetchall()])"`  
  **Result** (per context): `program_artifacts` contains live data for `program_id='dashboard'`: `prd=4, user_story=45, test_case=274, arch_diagram=0, api_spec=0`. **Impact**: Story is buildable against real data; empty-state testing is possible but live data already exercises the partial-data case (zero counts for 2 of 5 types). ✓

---

## Pattern Map

### Existing code to extend

1. **`services/api/app/core/rbac.py`** — `governance_visibility` check exists but has zero route consumers. SHP-04 will be its first call site; the check itself is complete and tested (`test_rbac.py::test_governance_visibility_*`), so no extension needed — only wire-in.

2. **`services/api/app/core/errors.py`** — Error envelope already wired. No extension needed; routes inherit the `{error: {code, message, details}}` shape.

### Existing patterns to follow

1. **Route structure** (from `services/api/app/api/overview.py` and `personal_usage.py`):
   - Single responsibility per file: `artifacts.py` exports a `router` object.
   - Route handler signature: `async def get_program_artifacts(program_id: str, current_user: CurrentUser = Depends(get_current_user), ...) -> <ResponseModel>`
   - RBAC gate as a `Depends()` dependency: `await governance_visibility(current_user, program_id)` inside the handler OR as a dependency parameter.
   - No router-level error handling; let `register_exception_handlers` in `app/main.py` catch all.

2. **Response shape conventions** (from `README.md` § API table and sibling endpoints):
   - Pre-formatted strings for display (e.g., percentages, labels, formatted dates).
   - Raw `int` for numeric data the frontend will format itself (per ADR-0009 amendment: `daily_tokens.points[].tokens` is raw int, not pre-formatted; `commands[].count` is raw int; personal-usage panel owns M/K/B magnitude formatting).
   - Response should include zero-count types (AC-3); all 5 types present regardless of live data.

3. **RBAC logging** (from `rbac.py:122-142` and `test_rbac.py`):
   - The gate logs itself; the route does NOT add additional logging around the gate call (confirmed by inspection of `personal_usage.py:76` and `overview.py:69-83`).
   - Denial event is the check's own `rbac_check_governance_visibility` + `outcome="denied"` field, not a separate event name.

### New files to create

1. **`services/api/app/api/artifacts.py`** — Single endpoint router:
   - `POST /api/artifacts/{program_id}` or `GET /api/artifacts/{program_id}` (story specifies `GET`).
   - Handler: `get_program_artifacts(program_id: str, current_user: CurrentUser, session: AsyncSession)`
   - Gate: `governance_visibility(current_user, program_id)` wired as dependency.
   - Service call: `get_program_artifacts(session, program_id)` to fetch and format response.

2. **`services/api/app/services/artifacts.py`** (or inline in route handler) — Data access:
   - Query: `SELECT * FROM program_artifacts WHERE program_id = ? ORDER BY type`
   - Fill zeros for missing types (ensure all 5 are present in response even if 0-count types have no rows).
   - Return typed response matching mockup bindings.

3. **`services/api/tests/unit/test_artifacts_route.py`** (or `test_api_artifacts.py`):
   - Gate pass: authorized persona + valid program_id → 200 with all 5 types.
   - Gate fail: denied persona (cio/engineering-manager) → 403 with no data body.
   - Empty program: program_id with zero artifact rows → 200 with all 5 types, all counts 0.
   - Partial data: program_id with some types having rows → 200 with all 5 types, some counts 0.

### Shared code at risk

1. **`services/api/app/core/rbac.py`** — `governance_visibility` function is currently untested in a real route context. SHP-04 will be the first route to call it; any drift in the gate's behavior (e.g., persona-resolution failure, unexpected denial) will surface here. Mitigation: unit tests for the route must explicitly cover persona-denied and resolver-failure paths.

2. **`services/api/app/models/governance.py`** — `ProgramArtifact` model is new; no migration exists yet (ING-03 F-16 notes that `program_artifacts` ingestion route never calls migration rebuild). SHP-04 assumes the table exists; if a migration is still pending from BED-01, research must confirm migration state. **Status confirmed**: BED-01 is security-reviewed; its migrations are shipped.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Domain | MED | Response JSON shape not specified in story AC or api.md; inferred from mockup bindings `{{ a.tag }}`, `{{ a.name }}`, `{{ a.count }}`, `{{ a.bg }}`, `{{ a.color }}`. If consumers decode differently, bindings fail. | Finalize response shape in PRD before planning. Confirm shape against mockup template variables: `{items: [{type, name, count, tag, bg, color}]}` or `{artifacts: [same]}` — exact field names critical. |
| 2 | Dependency | MED | `governance_visibility` RBAC check has zero route consumers in production; SHP-04 is its first caller. No precedent for how denials are logged at the route level. Story Decision log names event `governance_view_denied`, but check logs `rbac_check_governance_visibility` + outcome field. Clarify logging contract before implementation. | Verify logging expectations: does denial emit a separate event (naming precedent: `individual_view_denied`, `member_view_denied`), or rely on the check's own `rbac_check_governance_visibility` event? Align story Decision log with implementation plan. |
| 3 | Integration | LOW | No dedicated E2E test file for SHP-04 (story maps E2E to `ARC-01/DEV-01/PMD-01` dashboard tests). SHP-04's own unit tests can be complete, but end-to-end rendering depends on downstream stories being complete. | Acceptable: E2E is deferred to composition stories. Unit/integration tests for the route itself are sufficient to unblock planning. |
| 4 | Performance | LOW | No specific latency budget for this endpoint (story applies NFR-001: ≤3s panel render). Single `program_id` lookup + 5-type iteration is O(n) with n=5; no performance risk. | Index on `(program_id, type)` already exists (unique constraint); query is well-bound. No further optimization needed. |
| 5 | Compatibility | LOW | Mockup shows identical panels across ARC/DEV/PMD dashboards (same template, same bindings). No divergence, no compatibility risk between persona views. | Confirmed: all three mockups are byte-identical for this panel. Route serves all three without persona-specific branching. ✓ |

---

## Score + Verdict

| Dimension | Weight | Score | Reasoning |
|-----------|--------|-------|-----------|
| Integration | 25% | 85 | Upstream dependencies (BED-01, AUTH-03) are shipped and security-reviewed. RBAC gate exists and is untested in a route context (first consumer). Minor risk mitigated by adding explicit gate tests to the route unit suite. |
| Compatibility | 20% | 95 | Mockup is identical across three personas; no divergence. Pre-formatted/raw-int conventions are established (README.md, ADR-0009). Minimal backward-compat concern. |
| Domain | 20% | 70 | Response shape inferred from mockup template bindings; not specified in story or api.md. Decision log claims `governance_view_denied` event, but RBAC check uses a different logging model. Two clarifications needed before PRD is final. |
| Performance | 15% | 90 | Single indexed lookup on `program_id`; O(5) iteration. NFR-001 (≤3s) is easily met. No contention or scale risk. |
| Dependency | 20% | 85 | BED-01 and AUTH-03 are complete; no blocking upstream work. `governance_visibility` is untested as a route dependency — first consumer. Routing/wiring is straightforward (pattern-match existing `Depends()` calls in other routes). |

**Weighted Total**: `(85×0.25) + (95×0.20) + (70×0.20) + (90×0.15) + (85×0.20)` = `21.25 + 19.0 + 14.0 + 13.5 + 17.0` = **85/100**

**Verdict**: **GO-WITH-CONDITIONS**

### Conditions for Planning

1. **Clarify response JSON shape** before `/arh-plan-requirements`: exact field names and nesting (e.g., `{items: [{...}]}` vs `{artifacts: [{...}]}`, and whether `tag`, `bg`, `color` are included in the API response or computed client-side).
2. **Clarify logging event contract** before implementation: confirm whether governance-denial logs as a separate `governance_view_denied` event (mirroring `individual_view_denied` / `member_view_denied` precedent) or relying on the RBAC check's own `rbac_check_governance_visibility` + outcome field. Align story Decision log entry with the chosen approach.

Both clarifications are low-risk and narrow in scope (response shape + 1 logging event name). The codebase is ready to implement once these are settled.

---

## Synthesis

SHP-04 is **feasible and ready for planning with two narrow clarifications**. The upstream dependencies (BED-01's `program_artifacts` table, AUTH-03's `governance_visibility` RBAC gate) are shipped and security-reviewed; the response data is live in Postgres and the gate is untested in a route context but well-designed. The mockup is identical across all three consuming personas (Architect, Developer, Product Manager), with no divergence to design. The primary risk is that the response JSON shape is inferred from template bindings in the mockup rather than specified in the story or API contract — a quick clarification at the PRD stage will resolve it. Second, the story's Decision log names a governance-denial logging event (`governance_view_denied`) that doesn't yet exist; the RBAC check uses a different model (`rbac_check_governance_visibility` + outcome field). Confirm the logging contract before writing the route. Once both are settled, the implementation is straightforward (single GET endpoint, existing RBAC gate, standard error/response envelope, O(5) data fetch).

---

## Clarifications

None — both were resolved with the product owner on 2026-09-18, before `/arh-plan-requirements`.

## Resolved questions

| # | Question | Resolution | Basis |
|---|---|---|---|
| 1 | Response shape, and whether the mockup's `bg`/`color` bindings ship on the wire | **Server-owned presentation fields**: `{items: [{tag, name, count, bg, color}]}`, exactly 5 rows, mockup order is part of the contract | `docs/adr/0009-personal-usage-api-response-shape.md` already decided this for `personal-usage-api`'s cards (`glyph`/`iconBg`/`iconColor` as producer-owned constants), and its § Consequences explicitly names ARC-01/DEV-01/PMD-01 — this panel's consumers — as inheriting that precedent. ADR-0007 made the same call for `program-detail-api`'s `summary`. `count` stays a raw int per the same ADR's magnitude-formatting split |
| 2 | Whether a separate `governance_view_denied` event is needed | **No new event** — rely on the gate's own logging | `governance_visibility` (`services/api/app/core/rbac.py`) already emits `rbac_check_governance_visibility` with an outcome field and raises the `403` itself, before any data read. A route-level event would double-log one denial. The story's Decision-log entry naming `governance_view_denied` is superseded by this resolution |

**Correction to this report's own Exploration Log:** an earlier draft repeated a stale warning that
`ADR-0009` "does not exist on disk". It does — `docs/adr/0009-personal-usage-api-response-shape.md`.
`docs/requirements/RTM.md` line 89 recorded that gap on 2026-09-07, *before* the ADR was authored;
the RTM entry was never updated. The response-shape precedent SHP-04 depends on is therefore real
and settled, not missing.

---

## Top 3 Risks (by severity)

1. **Response shape ambiguity** (MED): Inferred from mockup template bindings; if field names diverge, consumer routes break.
2. **Governance logging event undefined** (MED): Decision log names an event not yet established; clarify against precedent before implementation.
3. **RBAC gate first consumer** (MED): `governance_visibility` has zero live route callers; SHP-04 is the first. Gate is unit-tested in isolation, but real endpoint integration needs explicit test coverage.

---

## Top 3 Recommendations

1. **Finalize response shape in PRD** against the mockup's exact template bindings before entering `/arh-plan-requirements`. Confirm with downstream consumers (ARC-01, DEV-01, PMD-01 story owners) if they have field-binding assumptions.
2. **Align logging model** with existing precedent: clarify whether `governance_visibility` denial should emit `rbac_check_governance_visibility` (outcome="denied") or a separate `governance_view_denied` event. Document the choice in the PRD, and update the story's Decision log to match.
3. **Add explicit route-level tests** for `governance_visibility` gate in SHP-04's unit suite: test denial (cio persona), authorization (architect persona), and resolver-failure paths. This is the gate's first real consumer; make sure the integration is bulletproof.

---

**Report**: docs/research/SHP-04.md  
**State update**: docs/state/features.json[SHP-04] → `research: "complete"`, `research_verdict: "GO-WITH-CONDITIONS"`, `phase: "research"`, `last_updated: "2026-09-18T...Z"`
