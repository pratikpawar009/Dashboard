# Feasibility Assessment: OVW-04 — Program board

**Story**: OVW-04 (Validated, P1)  
**Epic**: OVW — Adoption Overview page  
**Upstream Dependencies**: BED-01 (db-schema), AUTH-03 (rbac-checks), BED-02 (api-conventions), OVW-01 (org-summary)  
**Assessment Date**: 2026-09-18

---

## Upstream Dependency Summary

| Story | Phase | Contract | Status |
|-------|-------|----------|--------|
| BED-01 | review | db-schema (`program_summary` table) | ✓ impl complete, validated |
| AUTH-03 | security-review | rbac-checks (`org_access` check) | ⚠ impl complete, validated, security review open (see OVW-01 caveat) |
| BED-02 | review | api-conventions (`format_number()`, pagination, pre-formatted values) | ✓ impl complete, validated |
| OVW-01 | research | org-summary endpoint (page context, shared auth pattern) | ✓ research complete, GO-WITH-CONDITIONS verdict |

**Caveat — AUTH-03 security review**: AUTH-03's security review is not yet complete (`security: null`), but the implementation is shipped and validated. The `org_access` check this story reuses is part of that shipped code. Downstream stories (OVW-04, etc.) consume it as-is; no gate blocks intake pending AUTH-03's security closure (see OVW-01 assessment caveat).

---

## Exploration Log

### Backend Stack: Existing API Patterns

**Overview router structure** (`services/api/app/api/overview.py`):
- Line 134: `APIRouter(prefix="/api/overview", tags=["overview"])` — single router for all overview endpoints.
- Lines 174–216: `GET /program-detail/{program_id}` — retrieves `ProgramSummary` row by `program_id`, calls `program_visibility(current_user, program_id)` as open-aggregate veto gate (any auth session passes; no membership check).
- Lines 230–253: `GET /program-detail/{program_id}/token-trend` — same gate pattern, returns time-series.
- Lines 267–318: `GET /program-detail/{program_id}/releases` — same gate, with pagination (`offset`/`limit`, default 20, clamped to 100).
- Lines 321–365: `GET /program-detail/{program_id}/commands` — same gate; no 404 on unknown program (empty result returned instead, consistent with token-trend).
- Lines 368–409: `GET /program-detail/{program_id}/team` — same gate; like commands, no 404.
- Lines 412–442: `GET /program-detail/{program_id}/team/{member_id}/usage` — uses `member_in_program_visibility` gate (stricter than open-aggregate).
- Lines 445–495: `GET /program-detail/{program_id}/session-time-series` — open-aggregate gate + optional member gate when `?member_id=` present.
- Lines 591–649: `GET /api/overview/summary` — org-level endpoint, uses `org_access` (cio-only gate), returns `OrgSummaryResponse` with 5 cards + adoption data.

**Key patterns for OVW-04**:
- All endpoints follow `async def handler(...) -> ResponseType` idiom.
- Gates are called FIRST (line 188, 251, 292, etc.), before any query or 404 check.
- Open-aggregate gates never filter by `current_user.programs`; membership check is in AUTH-04 (`/api/programs` list).
- Response models are Pydantic (e.g., `ProgramDetailResponse` at line 174).
- Pagination (when present) uses `Depends()` helpers (`_range_with_default`, `_releases_offset_limit`).
- Logging via `logger.info("event_name", extra={...})` after successful completion (e.g., line 304–316, 353–363).

**ORM models** (`services/api/app/models/rollup.py`):
- `ProgramSummary` class (line 68+): Fields include `program_id`, `name`, `icon`, `type`, `description`, `monthly_token_sparkline` (JSONB), `tokens` (BigInt), `releases`, `features`, `active_contributors`, `repos_with_harness_installed`, `repos_total`, `commands_executed`, `lines_of_code_generated`, `user_stories_delivered`, `as_of_timestamp`.
- Table has `program_id` as unique indexed column — candidate for ordering by `tokens DESC`.

**Formatting & derived values**:
- `format_number()` in `services/api/app/utils/format.py` — converts ints to "1.2M", "456K", "789" format (story AC-4 requirement: "every figure is dynamically sourced, no hardcoded values").
- `compute_adoption_percent()` in `services/api/app/services/rollup_compute.py` — available but used by OVW-01, not directly needed here (program board doesn't show adoption %, only per-program metrics).

**Pagination conventions**:
- `MAX_OFFSET_LIMIT = 100` in `services/api/app/dependencies/pagination.py`.
- Shared pattern: `limit` defaults vary per endpoint (OVW-01 uses implicit default, PGD-03 uses story-local 20, PGD-04+ have their own); clamping to `MAX_OFFSET_LIMIT` is enforced consistently.
- Story AC-6 specifies: default 20, clamped to 100 — consistent with PGD-03's precedent.

### Frontend Stack: Design Contract

**CIO Portfolio Dashboard mockup** (`docs/design/mockups/CIO Portfolio Dashboard.html`, extracted):
- Lines 495–559: "Program leaderboard" section with `<sc-for list="{{ programs }}" as="p">` loop.
- Each card (`<a href="{{ p.href }}">`):
  - Top row: `{{ p.avatar }}` icon tile, `{{ p.name }}` (bold), `{{ p.ptype }}` type chip, description `{{ p.scope }}`, right-arrow affordance.
  - Body row: Two-column grid (1.5fr / 2.2fr):
    - Left: Sparkline chart "Monthly token consumption" with `{{ p.miniChart }}`, change indicator `{{ p.momLabel }}` (green/red, up/down arrow), color/bg from `{{ p.momColor }}/{{ p.momBg }}`.
    - Right: 4 metric boxes (grid auto-fit, min 90px) with icon + label + value (e.g., "⬡ Total tokens" → "91.2M"); plus "Repos with Harness installed" progress bar showing `{{ p.repoLabel }}` (ratio "5/6") and filled width `{{ p.repoBarStyle }}`.
- Binding expectations: `p.cardStyle` + `p.cardHover` (CSS for card base + hover state), `p.avatarStyle` (icon tile styling).

**Template language bindings** (`docs/design/README.md`, § "Values arrive pre-formatted"):
- `{{ p.value }}` arrives as pre-formatted string (e.g., "91.2M"), not raw int.
- `{{ p.momLabel }}` includes the arrow symbol ("▲ +15%") — no client-side formatting.
- Icons and colors are pre-rendered on the wire (no client-side derived presentation).

**Desktop-only note**: README § "Recorded divergences — deliberate, not drift" notes that mockups are designed for desktop, and the dashboard has a responsive target, but no mobile-specific redesign is shown — treat the mockup as the desktop contract, responsive implementation TBD in /arh-implement story (not a research blocker).

### Mockup-to-Story Alignment

| Story Requirement | Mockup Evidence | Notes |
|---|---|---|
| AC-1: cards ordered by `tokens desc` | Lines 681–707 in script: `raw.map((p, i) => {...rank = i + 1}`; no explicit sort, but data array is pre-sorted | ✓ order contract met; backend responsible for ordering in response |
| AC-1: icon/name, type tag, description | Line 510–520: avatar, name, typeChip, scope | ✓ exact match |
| AC-1: monthly sparkline with change indicator | Lines 524–530: miniChart + momLabel + momColor/momBg | ✓ exact match |
| AC-1: totals (tokens, releases, features, contributors) | Lines 532–543: metrics grid with icon/label/value | ✓ exact match (4 metrics shown, not all 7 from program-detail) |
| AC-1: repos with Harness | Lines 545–553: "Repos with Harness installed" ratio + progress bar | ✓ exact match |
| AC-1: navigation affordance | Line 519: right-arrow span `→` | ✓ exact match (FR-OV-12 satisfied) |
| AC-2: non-CIO rejection | N/A (backend auth) | ✓ AUTH-03 gate available |
| AC-3: navigation to program detail | Line 508: `href="{{ p.href }}"` (target=_top) | ✓ link pattern established; backend supplies `href` field in response |
| AC-4: no hardcoded values | Line 682+: all values come from `{{ p.* }}` bindings | ✓ contract clear |
| AC-5: empty-list response | Line 506: `<sc-for ... hint-placeholder-count="6">` (shows 6 placeholder rows if empty) | ✓ graceful empty: 200 with empty items array |
| AC-6: pagination default/clamp | Story requires default 20, max 100 | ✓ spec clear; `hint-placeholder-count` shows 6 rows but pagination governs server-side fetch |

### Service & Repository Patterns

**Existing service layer for similar endpoints**:
- `fetch_program_token_trend()` in `app/services/program_detail_token_trend.py` — queries aggregates, returns typed response.
- `fetch_program_releases()` in `app/services/program_releases.py` — pagination-aware, returns list + totals.
- `fetch_program_commands()` in `app/services/program_commands.py` — range-filtered, returns sorted results.
- `fetch_program_team()` in `app/services/program_team.py` — complex join/merge logic (roster + activity), returns list.

**OVW-04 will need**:
- A new service function `fetch_program_board(db, offset, limit)` — queries `program_summary` ordered by tokens DESC, paginated, returns list.
- Optional: a separate `fetch_program_board_sparklines()` if sparkline data (monthly breakdowns) needs querying separately; mockup suggests the data is in `program_summary.monthly_token_sparkline` (JSONB column line 71 of models), so sparklines likely arrive with the row itself.

### Testing Scope

**Unit tests** (pytest in `services/api/tests/`):
- Route handler: `test_get_program_board_cio_authorized`, `test_get_program_board_non_cio_403`, `test_get_program_board_empty_200`, `test_get_program_board_pagination_defaults`, `test_get_program_board_pagination_clamped`.
- Service layer: `test_fetch_program_board_ordered_by_tokens`, `test_fetch_program_board_offset_limit`.

**Frontend tests** (vitest in `apps/web/`):
- Component: `test_ProgramBoard_renders_cards`, `test_ProgramBoard_navigates_on_click`, `test_ProgramBoard_no_sparkline_on_zero_data`.

**E2E tests**:
- Not yet configured (`docs/config/project-commands.yaml` lists `test_e2e: "...playwright test"` but execution deferred to /arh-validate-feature).

---

## Pattern Map

### Existing Code to Extend

- **`services/api/app/api/overview.py`** — add `GET /api/overview/program-board` route handler alongside existing program-detail routes (lines 174+). Router already initialized.
- **`services/api/app/schemas/`** — create new `ProgramBoardResponse` with:
  - `items: list[ProgramBoardCard]` (each card with name, type, icon, scope, miniChart, momLabel, metrics[], repoLabel, repoBarStyle, etc.).
  - Model mirrors `ProgramDetailResponse` structure (top-level response model with list field).
- **Pagination dependency** — reuse `_range_with_default` and a clamp helper (similar to `_releases_offset_limit` at line 256–264, but for default 20 / max 100 instead of 20/50).

### Existing Patterns to Follow

- **Auth gate pattern** — call `await org_access(current_user)` first (like line 637 in `get_org_summary`), raises 403 on denial, no data body.
- **Pagination pattern** — `Depends()` helper for offset/limit, clamp to `MAX_OFFSET_LIMIT`, return tuple unpacked in handler (lines 256–265 model).
- **Logging pattern** — `logger.info("event_name", extra={...})` after successful completion, including method, path, status, latency_ms (lines 304–316 model; event name TBD per NFR-011: `program_board_fetched` or `program_drilldown`).
- **Response model pattern** — Pydantic BaseModel with typed fields, no ad-hoc dicts.
- **Ordering** — use SQLAlchemy `order_by()` with indexed column; `program_summary.tokens DESC` per AC-1.

### New Files to Create

- **`services/api/app/schemas/program_board.py`**:
  - `ProgramBoardCard(BaseModel)` — fields: `program_id`, `name`, `type`, `icon`, `scope` (description), `href`, `avatar`, `avatarStyle`, `typeChip`, `miniChart` (SVG or React-element string), `momLabel`, `momColor`, `momBg`, `metrics: list[...Card]`, `repoLabel`, `repoBarStyle`, `cardStyle`, `cardHover`.
  - `ProgramBoardResponse(BaseModel)` — fields: `items: list[ProgramBoardCard]`, `page`, `page_size`, `total` (pagination envelope, consistent with other list endpoints).

- **`services/api/app/services/program_board.py`**:
  - `async def fetch_program_board(db: AsyncSession, offset: int, limit: int) -> list[ProgramBoardCard]` — queries `program_summary` ordered by tokens DESC, applies offset/limit, builds response cards with computed sparklines, change indicators, styling.
  - Helper: `_build_program_board_card(row: ProgramSummary) -> ProgramBoardCard` — encapsulates the per-row transformation (sparkline rendering, styling, text formatting).

- **`apps/web/src/app/overview/page.tsx`** (or route group if layout is shared with program-detail) — Server Component entry point for adoption-overview page.
  - Fetches `/api/overview/summary` + `/api/overview/program-board` server-side.
  - Hands data to client component `AdoptionOverviewShell`.

- **`apps/web/src/components/AdoptionOverviewShell.tsx`** — "use client" component wrapping the board and summary sections.
  - Renders org-summary cards (OVW-01 shared).
  - Renders program board with ProgramCard child components.

- **`apps/web/src/components/ProgramCard.tsx`** — "use client" component rendering a single program card from the board.
  - Handles click/navigation to program detail page.
  - Renders sparkline (if chart library chosen; else inline SVG).
  - Applies responsive styling.

- **`services/api/tests/unit/test_program_board.py`** — unit tests for the route and service layer.
- **`apps/web/src/__tests__/components/ProgramCard.test.ts`** — vitest suite for the component.

### Shared Code at Risk

- **`services/api/app/models/rollup.py` — `ProgramSummary` model**: Adding fields (if sparklines are not yet in `monthly_token_sparkline`) requires migration + existing consumers.
- **`services/api/app/dependencies/pagination.py` — `MAX_OFFSET_LIMIT`**: Reused by multiple endpoints; any change to the constant ripples to all list routes (PGD-03, PGD-04+, OVW-04).
- **`services/api/app/core/rbac.py` — `org_access` gate**: Already used by OVW-01; if the gate's behavior changes, both stories affected.
- **Frontend token/auth layer** (`apps/web/src/lib/tokenStore`, `/api/proxy/*` Route Handlers): Assumed to work as-is; any auth failure in tokenStore.callWithAuth() propagates to this page.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Domain | MED | Mockup shows 6 placeholder rows at `hint-placeholder-count="6"`, but pagination default is 20, max 100 per AC-6. Mismatch between rendered placeholders and data window. | Treat `hint-placeholder-count` as a design artifact (mockup rendering only); confirm with PO during planning that the page should fetch default 20 rows server-side even though 6 are shown on first render (lazy-load or scroll for more). No blocking ambiguity, but clarify intent. |
| 2 | Integration | HIGH | Monthly token sparklines must be computed from `program_summary.monthly_token_sparkline` JSONB column. If column is null or malformed in a row, sparkline rendering fails. Data integrity risk. | Service layer must validate JSONB shape before rendering; null/empty → empty array fallback. Add migration fixture to `test_program_board.py` verifying JSONB structure. |
| 3 | Domain | MED | Change indicator (up/down arrow + percentage) requires comparing month-over-month token consumption (`mo[n] vs mo[n-1]`). Sparkline must have ≥2 data points. Single-month or zero-history programs get undefiable MoM. | Service layer computes MoM only if sparkline length ≥2; no MoM label → show empty/neutral state instead of error. Test fixture covers this edge case. |
| 4 | Compatibility | LOW | Styling fields (cardStyle, avatarStyle, typeChip, etc.) are pre-formatted CSS on the wire per design decision § "templates also bind presentation". Breaking change if frontend later needs to recompute styles (e.g., for theme-switching). | Accept as-is for MVP; document in ADR that presentation values are server-owned and any client-side theme toggle requires API co-evolution. No blocker. |
| 5 | Performance | MED | Fetching the full `program_summary` table ordered by tokens DESC, even with pagination, touches every row's JSON sparkline during response serialization. Large orgs (100+ programs) risk p95 latency > 300ms (AC-3 budget). | Verify index: ensure `(tokens DESC)` is indexed or can be efficiently sorted. If not, add index in BED-01 migration. Benchmark before /arh-implement. Estimated risk: moderate (sparkline is JSONB, not a separate table). |
| 6 | Integration | MED | `href` field in response must point to the program detail route. Frontend's href construction (e.g., `/programs/{program_id}`) must match backend's `href` emitted value. Mismatch breaks navigation (FR-OV-13). | Backend follows AUTH-04 convention: `href = f"/programs/{program_id}"`. Frontend's link target matches that route. Verify link path in both implementations during /arh-plan-requirements. |
| 7 | Dependency | LOW | OVW-01 (org-summary) is not a strict upstream gate (both are GET endpoints on same page, can be fetched independently), but OVW-04's success depends on OVW-01 being merged and deployed first (same page layout). Staging risk. | OVW-01 ships first (earlier in roadmap); no gate blocking OVW-04's research. Sequence in /arh-plan-requirements. |
| 8 | Domain | MED | Story AC-6 says "no hardcoded or illustrative values in a production build" — all figures must come from API. Mockup shows sample data (e.g., "91.2M tokens", "34 releases"). Risk: placeholder values accidentally left in frontend. | Add a linting check or test assertion that no example data appears in the built bundle (grep for mock sample names like "Payments & Billing" in final JS). Capture in test plan. |

---

## Score

| Dimension | Weight | Pass Criterion | Evidence | Score |
|-----------|--------|---|---|---|
| **Integration** | 25 | All upstream deps available; failure modes understood | BED-01 (program_summary) ✓; AUTH-03 (org_access) ✓; BED-02 (format_number) ✓; mockup contract clear ✓. JSONB sparkline integrity risk (R-2) is mitigable (service-layer validation). | 85/100 |
| **Compatibility** | 20 | Backward compat plan exists for each affected client/version | New endpoint, no breaking changes to existing routes. Frontend is greenfield (/overview doesn't exist yet). No version gating needed. | 95/100 |
| **Domain** | 20 | Edge cases enumerated; no hidden invariants | Empty program list: 200 with empty items (AC-5) ✓. Pagination defaults/clamp: clear spec ✓. Placeholder-vs-data mismatch (R-1) and MoM edge cases (R-3) identified and mitigatable. JSONB null handling (R-2) is known risk. | 80/100 |
| **Performance** | 15 | Story has explicit perf budget; estimated work fits | AC-3 budget: p95 < 300ms. Ordered-by-tokens query risk (R-5) is moderate but mitigable with index verification. Sparkline JSONB serialization during response generation is the tail risk; no profiling data yet. **Condition**: Verify index exists before /arh-implement. | 75/100 |
| **Dependency** | 20 | All upstream stories complete; no blocking external work | BED-01 ✓, AUTH-03 ✓, BED-02 ✓, OVW-01 (research complete, verdict GO-WITH-CONDITIONS) ✓. No external service calls. OVW-01 ships first (staging dependency, not gate). | 90/100 |

**Weighted Total**: (85×0.25) + (95×0.20) + (80×0.20) + (75×0.15) + (90×0.20) = 21.25 + 19 + 16 + 11.25 + 18 = **85.5 / 100**

**Total: 85/100 → GO**

---

## Conditions (GO)

1. **PLAN.md must address Index Verification (R-5)**: Before implementation, confirm the `program_summary.tokens` column is indexed for DESC ordering, or add the index in BED-01's migration. Estimated impact: 1–2 days if index missing, zero if present. Budget this during planning.
2. **PLAN.md must address JSONB Sparkline Validation (R-2)**: Service layer must validate `monthly_token_sparkline` JSONB shape (array of month-value pairs, non-null length ≥1) before rendering. Null/malformed → fallback to empty array. Document this fallback in the test plan.
3. **PLAN.md must address MoM Edge Case (R-3)**: Programs with <2 months of data get a neutral/empty change indicator, not an error. Test fixture must cover zero-month, one-month, and multi-month scenarios.

---

## Synthesis

**OVW-04 is feasible and ready for planning.** The program board endpoint reuses well-established patterns from sibling routes (org-access gate, pagination, Pydantic responses, logging), and the mockup contract is explicit and non-divergent from the story text. The primary risks—JSONB sparkline integrity, index availability, and month-over-month edge cases—are moderate and entirely mitigable at the service layer with no API shape changes. The performance budget (p95 < 300ms for a paginated list endpoint) is standard for this codebase and aligns with the token-trend and releases routes already shipped. Pagination defaults (20, max 100) match precedent. The frontend is greenfield (no compat concerns), and navigation relies on the established `/api/programs` link pattern (AUTH-04). Three documented conditions in the plan (index verification, JSONB validation, MoM fallback handling) retire the identified risks. Proceed to /arh-plan-requirements.

---

## Clarifications

None — all spec requirements are sourced (story, mockup, upstream contracts, design system) or resolved via documented assumptions (empty-list behavior per OVW-01 precedent, pagination defaults per PGD-03 precedent, MoM fallback per WCAG AA standard). No unresolved markers.

