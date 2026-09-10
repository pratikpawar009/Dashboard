# Feasibility Assessment: OVW-01 — Org summary cards + adoption indicator

**Story**: OVW-01 (Validated, P1)  
**Epic**: OVW — Adoption Overview page  
**Upstream Dependencies**: BED-01 (db-schema), AUTH-03 (rbac-checks), BED-02 (api-conventions), BED-04 (freshness-api)  
**Assessment Date**: 2026-09-09  

---

## Upstream Dependency Summary

| Story | Phase | Contract | Status |
|-------|-------|----------|--------|
| BED-01 | review | db-schema (`org_summary_rollup`, `system_metadata` tables) | ✓ impl complete, validated |
| AUTH-03 | security-review | rbac-checks (`org_access` check) | ⚠ impl complete, validated, but security review NOT finished |
| BED-02 | review | api-conventions (`format_number()`, `compute_adoption_percent()`) | ✓ impl complete, validated |
| BED-04 | review | freshness-api (`FreshnessAccessor`) | ✓ impl complete, validated |

**Caveat — AUTH-03 gate status**: AUTH-03 is at phase `security-review` with `security` field set to `null` (not PASS). The story's implementation (`rbac.py`, `persona_resolver.py`, etc.) is complete and validated (`review: PASS`), but its security review is not. The upstream gate (phase-preconditions) requires `impl: complete` and `review: PASS` (both met); security review completion is not a hard gate for downstream stories but represents an open audit item upstream. The `org_access` check this story will use is part of AUTH-03's shipped implementation, not a future change.

---

## Exploration Log

### Backend Stack: What exists, what to build

- **Route file**: `services/api/app/api/overview.py` already exists, owns `GET /api/overview/program-detail/{program_id}` (PGD-01). New endpoint `GET /api/overview/summary` will be added to this same module.
- **Schema models**: Pydantic request/response models live in `services/api/app/schemas/`. Program detail uses `ProgramDetailResponse` with cards; `org-summary-api` will need a new schema (e.g., `OrgSummaryResponse` with summary cards array + adoption info).
- **ORM models**: `OrgSummaryRollup` exists at `services/api/app/models/rollup.py` with fields matching the schema contract: `programs_using_ai_count`, `programs_total`, `total_token_consumption`, `lines_of_code_generated`, `releases_using_harness`, `repos_with_harness_installed`, `repos_total`, `as_of_timestamp`.
- **Derived-value functions**: `compute_adoption_percent()` already exists in `services/api/app/services/rollup_compute.py` — takes an `OrgSummaryRollup` instance and returns a dict with `adoption_percent` computed (None when `programs_total == 0`).
- **Formatting**: `format_number()` in `services/api/app/utils/format.py` — converts integers to M/K format strings. Used by ProgramDetailView's `_build_summary()` for the 7 program-detail cards.
- **RBAC**: `org_access` check from `app.core.rbac` (AUTH-03) — callable as `await org_access(current_user)`, raises 403 on denial.
- **Freshness**: `FreshnessAccessor` in `services/api/app/services/freshness.py` — instantiable, has `async def get_last_successful_run(self) -> datetime` method, raises HTTPException 500 if row absent. Callers construct their own instance; no app.state singleton exists yet.
- **Tests**: Unit tests exist at `services/api/tests/unit/test_overview.py` for the program-detail endpoint; new tests needed for summary endpoint.

### Frontend Stack: What exists, what to build

- **Route structure**: Next.js 15 App Router at `apps/web/src/app/`. No `/overview` route exists yet; root page redirects to `ADOPTION_OVERVIEW_ROUTE = "/overview"` (currently 404).
- **Page pattern**: `apps/web/src/app/programs/[program_id]/page.tsx` is the model — Server Component entry point, fetches data server-side with `tokenStore.callWithAuth()`, hands result to a client component (`ProgramDetailView`).
- **Client component pattern**: `ProgramDetailView.tsx` is a "use client" component that renders the fetched data and handles client-side interactions. Owns loading/error states in-component, no route-level `error.tsx` / `not-found.tsx`.
- **API client pattern**: Fetches go through `@/lib/programDetailApi.client` and `@/lib/programDetailApi`, which call frontend-owned `/api/proxy/*` Route Handlers (AUTH-05). No direct FastAPI calls from client components.
- **Auth storage**: `@/lib/tokenStore` holds the session's access token and refresh logic (`callWithAuth`). Client components never touch tokens directly.
- **Layout**: `PersonaDashboardShell.tsx` is the shared wrapper for all persona dashboards (SHP-01). Takes `signedInUser`, `persona`, `program` props (all optional/undefined on load).
- **Design tokens**: `docs/design/tokens.md` has color, spacing, typography, radius, shadow tokens. OVW mockup uses these (primary #2a6fdb, success #1f8a5b, text colors, card radius 16px, etc.).

### Mockup Contract: OVW (CIO Portfolio Dashboard)

The extracted HTML from `dashboards/CIO Portfolio Dashboard.html` shows:

1. **Organization summary section** (lines 408-427):
   - Title "Organization summary" with "— all programs · To date" subtitle
   - Grid of cards with `hint-placeholder-count="5"` (5 placeholder rows)
   - Each card: `{{ k.glyph }}` icon in colored tile, `{{ k.value }}` (25px font, pre-formatted), `{{ k.label }}` (12px), optional `{{ k.sub }}` (green, 11px)
   - Bindings suggest 5 distinct cards (not itemized by name in HTML, but implied by data structure)

2. **Adoption Level section** (lines 469-493):
   - Headline: `{{ adoptionHeadline }}` (26px, bold)
   - Subtitle: "programs using AI SDLC · {{ adoptionPct }} of the org"
   - Progress bar: two divs with `{{ adoptionBarUsing }}` and `{{ adoptionBarNot }}` inline styles (width, background)
   - Legend: loop `{{ adoptionLegend }}` with `{{ h.color }}`, `{{ h.count }}`, `{{ h.label }}`

3. **Freshness timestamp**: Appears to be rendered on the page somewhere (story AC-6) but mockup location not explicitly marked in the extracted HTML section above.

### Story Acceptance Criteria Alignment with Mockup

| AC # | Requirement | Mockup Evidence | Coverage |
|------|-------------|-----------------|----------|
| AC-1 | GET /api/overview/summary returns org summary fields | N/A (backend only) | ✓ scope clear |
| AC-2 | No row → all-zero response, not error | N/A (backend only) | ✓ scope clear |
| AC-3 | Non-CIO → 403 no data body | N/A (backend/auth) | ✓ AUTH-03 available |
| AC-4 | Adoption indicator renders `<count>/<total> — <pct>%` with bar + legend | Mockup lines 469-493: adoption headline, progress bar, legend loop | ✓ exact match |
| AC-5 | Summary cards: icon, value (M/K format), label, optional sub | Mockup lines 416-425: cards grid with glyph, large value, label, optional sub | ✓ exact match |
| AC-6 | Freshness timestamp renders as as-of time | Mentioned in story, not explicitly visible in extracted mockup section | ⚠ location TBD |
| AC-7 | Missing freshness row → "ingestion job may not have run yet" error | N/A (backend error handling) | ✓ BED-04 contract |
| AC-8 | rbac_check_org_access logged on every check | N/A (backend logging) | ✓ AUTH-03 provides logging |

**Summary**: Mockup aligns with story requirements. AC-6 freshness timestamp location not yet pinned (likely somewhere on the page header or footer), but BED-04's `FreshnessAccessor` contract is clear on the backend.

---

## Pattern Map

### Existing code to extend

- `services/api/app/api/overview.py` — add `GET /api/overview/summary` route handler alongside existing `GET /api/overview/program-detail/{program_id}`.
- `services/api/app/schemas/` — add `OrgSummaryResponse` schema (following `ProgramDetailResponse` pattern: card list + adoption info).
- `services/api/app/utils/format.py` — `format_number()` already exists; will be used for card values.
- `services/api/app/services/rollup_compute.py` — `compute_adoption_percent()` already exists; will be used for adoption calculation.
- `apps/web/src/app/` — create new `/overview` route segment (page.tsx + page.module.css).

### Existing patterns to follow

- **Backend route pattern** (fastapi-patterns): Router in `app/api/<resource>.py`, thin async handler, business logic in services layer. Dependencies via `Depends()`. Response envelope via Pydantic schema.
- **Backend auth pattern** (AUTH-03, RBAC): Call `await org_access(current_user)` at route entry; raises 403 on denial.
- **Backend response shape** (ProgramDetailResponse pattern): Fixed glyphs/labels (owned by server), values pre-formatted by `format_number()`, no client-side formatting.
- **Frontend page pattern** (Program Detail): Server Component (`page.tsx`) does initial fetch with `callWithAuth()`, Client Component renders result + handles client-side updates.
- **Frontend auth pattern** (AUTH-05): Fetch via `@/lib/programDetailApi` → `/api/proxy/*` Route Handlers, never direct FastAPI.
- **Styling** (CSS Modules): Per-route CSS Module co-located with page (`page.module.css`), import as `styles`, apply via `className={styles.x}`.

### New files to create

| Path | Purpose |
|------|---------|
| `services/api/app/schemas/org_summary.py` | `OrgSummaryCard`, `OrgSummaryResponse` Pydantic models |
| `apps/web/src/app/overview/page.tsx` | Server Component entry point (auth + initial fetch) |
| `apps/web/src/app/overview/page.module.css` | Route-local styles (layout, spacing, tokens) |
| `apps/web/src/components/AdoptionOverview.tsx` | Client component (render org cards + adoption indicator) |
| `services/api/tests/unit/test_org_summary.py` | Unit tests for GET /api/overview/summary |
| `apps/web/src/app/overview/page.test.tsx` | Server-side fetch test (auth flow, error cases) |

### Shared code at risk

- `services/api/app/services/rollup_rebuild.py` — `org_summary_rollup` is rebuilt by `rebuild_org_rollups()` on every activity ingest. The story reads a singleton row; the writer is `rollup_rebuild`. BED-05 recently added statement-level timeout (`_STATEMENT_TIMEOUT_MS = 5000`), which is the looser bound compared to BED-04's freshness accessor's 3.0s timeout. High-frequency reads could contend if the rebuild is slow, but this is an existing concern (tracked in risk register below).
- `services/api/app/core/auth.py` — `get_current_user()` is a dependency used by all protected routes. No changes needed for this story, but any auth regression upstream will block.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Dependency | HIGH | AUTH-03's security review is incomplete (`phase: security-review`, `security: null`). Upstream impl is done and tested, but audit is open. | Proceed with implementation; the `org_access` check is part of completed implementation. Security review completion upstream will not affect this story's integration. Document the caveat in PR comments. |
| 2 | Domain | MED | `org_summary_rollup` is a singleton rebuilt on every ingestion. If the row doesn't exist (fresh DB, no ingest yet), story must return all-zero values gracefully (AC-2). | Explicitly handle `SELECT ... WHERE org_id = 'org-1'` returning no rows: construct and return an all-zero response envelope. Test with an empty DB state in the test suite. |
| 3 | Performance | MED | org_summary_rollup singleton + concurrent ingestion rebuilds could create lock contention. BED-05's engine-level timeout (5s) is looser than BED-04's freshness accessor (3s), masking a slow rebuild. | Use the existing query pattern: simple `SELECT org_id, programs_using_ai_count, ...` with no joins. BED-05's timeout already in place. If rebuild performance becomes an issue, it's upstream (out of scope). Estimated query time: <100ms on a 1-row table with indexes. |
| 4 | Integration | MED | FreshnessAccessor is instantiated per-story; no app.state singleton. This story will construct its own instance in the route handler. If multiple consumers do the same, per-instance cache TTL (300s) means each instance misses independently. | Acceptable: each route independently calls FreshnessAccessor; no cross-route cache coherence is expected. Per-instance TTL is short enough (5min) that stale-freshness is not critical for an overview page. Document this limitation in code comments. |
| 5 | Integration | MED | Frontend `/overview` route doesn't exist. Must create new page segment from scratch. Risk: forgetting the server-side auth flow or the persona shell wrapper. | Follow ProgramDetailView pattern exactly: (1) Server Component with `callWithAuth()` → initial fetch, (2) Client Component for render, (3) wrap in PersonaDashboardShell. Use ProgramDetailView as template; grep for patterns before writing. |
| 6 | Compatibility | LOW | The mockup is desktop-only per `docs/design/README.md`. Responsive breakpoints in existing pages use ad hoc media queries (e.g. `@media (max-width: 600px)` in ProgramDetailView). No design-token breakpoint scale exists yet. | This story is UI-only (no new API contracts to backcompat). Desktop-first render is acceptable per the design constraint. Add a note in the page component: "Desktop-only for now; responsive breakpoints pending a token system design (SHP-01 / design-system story)." |
| 7 | Domain | LOW | Adoption percentage can be null when `programs_total == 0` (BED-02 contract). The adoption-indicator UI must handle null gracefully (show a "No programs registered" state, or render N/A). | Story's AC-5 doesn't specify the null render; accept it as out-of-scope for AC-5 (which covers the happy path). Add a test case for `programs_total=0` to ensure no crash. Frontend can render "—" or a disabled state; document in component. |

---

## Score & Verdict

### 5-Dimension Rubric

| Dimension | Weight | Evidence | Score | Comment |
|-----------|--------|----------|-------|---------|
| **Integration** | 25% | All four upstreams shipped, contracts available. AUTH-03 security review open but impl complete (Risk #1 mitigated). FreshnessAccessor pattern clear, no blocking external services. | 82/100 | AUTH-03 caveat noted; path forward clear. |
| **Compatibility** | 20% | No backward-compat concerns (new route, new frontend page). Responsive design is out of scope per design constraint. Existing pattern in codebase for auth flow + client-side render. | 90/100 | Desktop-only acceptable per design brief. Pattern-match with ProgramDetailView is strong. |
| **Domain** | 20% | All business logic (adoption %, rollup lookup, all-zero fallback) already exists or is straightforward. Edge cases enumerated (null adoption %, missing row, stale freshness timestamp). No hidden invariants. | 85/100 | All-zero fallback (AC-2) is simple to implement. Adoption % null-handling documented. |
| **Performance** | 15% | Single-row read on singleton `org_summary_rollup` table, no joins, no pagination needed. 3s dashboard render budget (NFR-001) easily met by a ~1-5ms query + serialization. BED-05's timeout already protects against slow rebuilds. | 90/100 | No N+1 risk, no unbounded fan-out, bounded query. Timeout in place. |
| **Dependency** | 20% | All four upstreams complete and integrated. No downstream stories blocked. AUTH-03 impl available (just security-review pending). Contracts available in `docs/requirements/`. | 78/100 | AUTH-03 security review not done (caveat). No other blockers. |

**Weighted Total**: (82 × 0.25) + (90 × 0.20) + (85 × 0.20) + (90 × 0.15) + (78 × 0.20) = 20.5 + 18 + 17 + 13.5 + 15.6 = **84.6 / 100**

**Verdict**: **GO-WITH-CONDITIONS**

---

## Conditions for GO-WITH-CONDITIONS

Promoted from an inline bold list to a proper section on 2026-09-09 so
`/arh-plan-requirements` Phase 0's GO-WITH-CONDITIONS enforcement can locate and inject them
mechanically — it looks for this heading, and would otherwise have silently dropped every condition,
which is the exact failure the verdict exists to prevent.

1. **AUTH-03 upstream caveat**: security review is open (`phase: security-review`, `security: null`)
   but the implementation is complete and tested (`impl: complete`, `review: PASS`). Proceed, and
   document the caveat in the PR. If AUTH-03's review later surfaces issues in `org_access()`, they
   apply to all downstream consumers rather than to this story, and belong upstream.
2. **Adoption % null handling**: the route must handle `adoption_percent = None` when
   `programs_total == 0`. Document the null case in the response schema and add a test covering it —
   this is the fresh-database path and is easy to miss.
3. ~~**Freshness timestamp rendering**~~ — **RESOLVED 2026-09-09, no longer a condition.** This was
   clarification C-1. The answer is that **nothing renders**: AC-6 is backend-only. The mockup shows
   no as-of timestamp anywhere, PGD-01 decided the same for the analogous component
   (`apps/web/src/components/ProgramSummaryCards.tsx:19-21`), and `CLAUDE.md` § Design system forbids
   inventing UI the mockups do not show. AC-7 is unaffected and still required. See § Resolved
   clarifications and the story's Decision log. **Carried here only so the trail is visible — the PRD
   must address conditions 1 and 2, not this one.**

---

## Synthesis

OVW-01 builds a new org-level overview page and API endpoint on top of four completed upstream stories. The backend implementation is straightforward: a single query against an existing singleton rollup table, two existing formatting/computation functions, and one auth check already in place. The frontend follows the proven ProgramDetailView pattern and will reuse the PersonaDashboardShell component. The design contract (mockup) aligns with acceptance criteria. The primary caveat is AUTH-03's incomplete security review upstream, but its implementation is shipped and tested, so integration risk is low. One condition requires clarification on the freshness timestamp rendering location (mentioned in AC-6 but not pinned in the mockup). With these conditions addressed in the plan phase, this story is ready for implementation.

---

## Clarifications

<!-- None open. C-1 was resolved on 2026-09-09; see "Resolved clarifications" below. -->

### Resolved clarifications

- **C-1 — Freshness timestamp placement (AC-6)** — **RESOLVED 2026-09-09: no timestamp renders;
  AC-6 becomes backend-only.** The question was where on the page the `last_successful_run_at`
  timestamp should appear. The answer is nowhere, and it was settled from evidence rather than
  preference:
  1. The `OVW` design contract — `CIO Portfolio Dashboard.html`, per `docs/design/schema.json` —
     contains **no** as-of / last-updated / freshness string anywhere. The only `UTC` matches in the
     file are random substrings inside its base64 bundle payload, confirmed by inspecting them.
  2. **PGD-01 already decided this identically** for the analogous component:
     `apps/web/src/components/ProgramSummaryCards.tsx:19-21` records "there is no range toggle and no
     as-of timestamp anywhere in this story", against DESIGN.md Region 4. Rendering one on the org
     page would make the two summary pages visibly inconsistent.
  3. `CLAUDE.md` § Design system is explicit: "If a story seems to need something the mockups do not
     show, stop and raise it. **Do not design it.**" The header-placement option this report
     originally recommended would have been exactly that.

  **AC-7 is unaffected and still required** — the endpoint must still read freshness through the
  `freshness-api` accessor and raise the "ingestion job may not have run yet" error when no
  `system_metadata` `ingestion` row exists. That is backend behaviour the mockup has no opinion on.
  Recorded in the story's Decision log. If freshness should become user-visible, that is a follow-up
  story once a mockup shows where it belongs.

## Top 3 Recommendations

1. **Use ProgramDetailView.tsx as a strict template**: Copy its auth flow (`callWithAuth`), error handling, and client-side structure. Do not invent custom patterns.
2. **Test the empty-DB case explicitly**: Write a unit test where `org_summary_rollup` has no rows, and verify the all-zero response is returned (AC-2). This is easy to miss and critical for a fresh-DB experience.
3. **Pin the freshness timestamp location early in planning**: The mockup doesn't show it explicitly; get clarity from UX/PO during `/arh-plan-requirements` to avoid rework.

---

## State Write

```json
{
  "research": "complete",
  "research_verdict": "GO-WITH-CONDITIONS",
  "phase": "research",
  "last_updated": "2026-09-09T19:45:00Z"
}
```
