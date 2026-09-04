# Research Assessment: PGD-01 — Program Detail page shell (header, summary cards, switch/back nav)

**Story ID**: PGD-01  
**Epic**: PGD  
**Priority**: P1  
**Upstream dependencies**: BED-01 (db-schema), BED-02 (api-conventions), AUTH-03 (rbac-checks), AUTH-04 (programs-api)  
**Downstream dependencies**: ARC-01, DEV-01, PMD-01, EMD-01 — all consume the `program-detail-api` contract  
**Assessment Date**: 2026-09-03  
**Assessed by**: Claude Code Research Agent  

---

## Upstream Dependency Summary

**All four upstream dependencies complete and verified on main branch:**

- **BED-01** (research verdict: GO-WITH-CONDITIONS, phase: review): provides the `db-schema` contract with `program_summary` table containing all header fields (`icon, name, type, description`) and all 7 summary-card metrics (`tokens, features, releases, repos_with_harness_installed, commands_executed, lines_of_code_generated, user_stories_delivered`). Schema deployed via Alembic migrations; ORM models exist and tested.
- **BED-02** (research verdict: GO-WITH-CONDITIONS, phase: review): provides `api-conventions` contract with `format_number()` utility for M/K formatting of numeric values server-side. Function exists at `app/utils/format.py:74-105`, fully tested, with complete boundary-behaviour documentation.
- **AUTH-03** (research verdict: GO-WITH-CONDITIONS, phase: security-review): provides `rbac-checks` contract with `program_visibility(current_user, program_id)` open-aggregate check that passes for any authenticated session (no persona resolution, no program-scoping). Implementation exists at `app/core/rbac.py:28-41`, verified by test coverage (TC-03, TC-04, TC-27, TC-28).
- **AUTH-04** (research verdict: GO-WITH-CONDITIONS, phase: review): provides `programs-api` contract (`GET /api/programs`) that returns switcher-list shape `{program_id, label, href, dotStyle}` — endpoint fully implemented at `app/api/programs.py`, tested, and live on main. This endpoint is the data source for the "Switch program" selector in PGD-01's header.

**No architectural blockers.** All upstreams are live, tested, and stable. The DB schema is deployed; the format utility is available; RBAC and programs endpoints are operational.

---

## Exploration Log

### Repository State & Toolchain
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean except `docs/activity/activity.jsonl` already modified, and expected agent files in `.claude/`)
- **Git branch**: main, last commit d15525a (fix(web): close SHP-01's code gaps)
- **Python**: 3.9.6 available; FastAPI scaffold fully operational
- **Stack**: FastAPI 0.115, SQLAlchemy 2.0+, Pydantic 2.9+, Next.js 15.5.24, React 19.1.0, pnpm, vitest

### Design Reference (Mockup Extraction)
- **Mockup file**: `docs/design/mockups/Program Detail.html`
- **Markup decoded successfully** — mockup is a bundler output (JSON-escaped HTML); extracted markup confirms:
  - **Header section** (sticky, translucent): contains program avatar, name, type chip, scope/description, "← Back" link, "Switch program" selector dropdown
  - **Project Summary section**: 7 cards arranged in auto-fit grid (minmax 200px), each with: glyph (15px icon-tile), pre-formatted value (25px KPI size), label (12px secondary)
  - **Daily Token Consumption section**: chart + total + avg/day rollup
  - **Releases, Commands, Team sections** (downstream from PGD-02..06, out of scope for PGD-01's shell)
- **Bindings verified**:
  - Header: `prog.avatar`, `prog.name`, `prog.typeChip`, `prog.ptype`, `prog.scope`, `prog.dotStyle`, `toggleProg`, `progOpen`, `progOptions` (list with `o.label`, `o.href`, `o.dotStyle`, `o.current`, `o.rowStyle`)
  - Summary cards: `summary` list with `s.glyph`, `s.value`, `s.label` (loop via `hint-placeholder-count="7"`)
  - Design tokens**: card padding 18px 19px, 16px grid gap, KPI min-column 190px, fonts Plus Jakarta Sans (sans) + JetBrains Mono (numerics)

### Backend State (API / Database)

#### Models & Schema
- **`app/models/rollup.py::ProgramSummary`** — all fields present on main:
  - Header fields: `program_id` (unique), `name`, `icon`, `type`, `description`
  - 7 summary-card fields: `tokens` (BigInteger), `features` (Integer), `releases` (Integer), `repos_with_harness_installed` (Integer), `commands_executed` (Integer), `lines_of_code_generated` (BigInteger), `user_stories_delivered` (Integer)
  - Additional fields supporting other sections: `monthly_token_sparkline` (JSONB), `active_contributors`, `intervention_count`, `tool_rejections`, `as_of_timestamp`
  - Verification: file at `/services/api/app/models/rollup.py:64-86`

#### API Endpoint
- **`GET /api/programs`** — fully operational (AUTH-04 complete):
  - Endpoint: `app/api/programs.py:69-164`
  - Response: `ProgramsListResponse` with `programs: [ProgramEntry]` where each entry is `{program_id, label, href, dotStyle}`
  - Scoping: CIO sees all programs; other personas scoped to `current_user.programs` (session.groups with prefix parsing)
  - RBAC: calls `program_visibility()` with sentinel `program_id` (open-aggregate veto gate that passes all authenticated)
  - Links to program-detail: `href = f"/api/overview/program-detail/{row.program_id}"` (line 132)

#### Missing Endpoint
- **`GET /api/overview/program-detail/{program_id}`** — **does not exist yet**, needs to be created for PGD-01
  - Contract defined at `docs/requirements/api.md:124-133`:
    ```yaml
    endpoint: "GET /api/overview/program-detail/{program_id}"
    fields: "header (icon, name, type, description) + 7 to-date summary cards (tokens, features, releases, repos, commands, LOC, stories)"
    invariant: "byte-identical response regardless of CIO vs Engineering Manager caller; no persona-branching logic"
    ```
  - No router module exists at `app/api/overview.py`; path `/api/overview/` is reserved in `programs.py` href but not yet mounted

#### Utilities
- **`app/utils/format.py:74-105`** — `format_number(value)` function:
  - Full M/K bucketing logic implemented with promotion rules
  - Tested for boundary cases (999 → "999", 2500 → "2.5K", 999_999 → "1.0M")
  - Preserves sign for negatives; one decimal place always (incl. trailing .0)
- **`app/utils/format.py:132-153`** — `dot_style_for_program(program_id)` function:
  - Deterministic per-program colour via SHA256 hash of program_id
  - Returns pre-formatted CSS string `"background-color: #hexcode;"`
  - Palette: 5 colours from design tokens (primary, success, accent-purple, accent-terracotta, ink)

#### Error Handling & Auth
- **Error envelope** (`app/core/errors.py`): single shape `{"error": {"code": "http_NNN", "message", "details"}}` — all exceptions routed through registered handlers
- **RBAC check** (`app/core/rbac.py:program_visibility`): open-aggregate, passes any authenticated session, logs no events (no denial path to log)
- **Auth dependency** (`get_current_user`): injects `CurrentUser` with `user_id, email, role, groups, programs` fields (JWT-validated via OIDC or dev-bypass)

### Frontend State (Next.js / React)

#### Components Existing
- **`apps/web/src/components/PersonaDashboardShell.tsx`** — persona header + program context (SHP-01, complete):
  - Accepts `program: {icon, name, type, description}` as prop
  - Renders persona tag, identity bar, program context
  - No fetching; presentational only
- **`apps/web/src/components/ProgramContext.tsx`** — program-context display component
- **`apps/web/src/lib/programStyle.ts`** — derives `avatarStyle`, `typeChip` colors from `program.type` string
- **`apps/web/src/lib/formatPersonaTag.ts`** — maps persona role to display string + colours

#### Missing Components
- **Program Detail page** — no `src/app/program-detail/page.tsx` or similar route
- **Program Detail header** — no component for the sticky header (program avatar, name, type, "Back" link, "Switch" selector)
- **Program Summary cards** — no component for the 7-card grid
- **Navigation controls** — no "Back to program board" or "Switch program" implementations

### Test Coverage
- **Backend test files exist**:
  - `services/api/tests/unit/test_programs.py` — AUTH-04 tests (programs list endpoint)
  - No tests yet for `GET /api/overview/program-detail/{program_id}` (endpoint doesn't exist)
- **Frontend test files exist**:
  - `apps/web/src/components/PersonaDashboardShell.test.tsx`
  - `apps/web/src/components/ProgramContext.test.tsx`
  - No tests for Program Detail page or header/cards components

### Logging & Observability
- **Existing patterns** (`app/core/logging.py`):
  - Hand-rolled `JSONFormatter` with `{timestamp, level, logger, message, exc_info?}` shape
  - No structured fields passed to logger yet; supports `extra` dict for field injection
  - Story requires `program_drilldown` (on page open) + `program_switch` (on switcher selection) events (NFR-011)

### Dependency Graph & Contracts
Per `docs/requirements/api.md`:
- **program-detail-api** (produced by PGD-01, consumed by ARC-01/DEV-01/PMD-01/EMD-01):
  - Endpoint: `GET /api/overview/program-detail/{program_id}`
  - Fields: header (icon, name, type, description) + 7 summary cards (tokens, features, releases, repos, commands, LOC, stories)
  - Invariant: byte-identical CIO / Engineering Manager response (no persona-branching)
- **programs-api** (produced by AUTH-04, consumed by PGD-01 for "Switch program" selector):
  - Already live; returns switcher list shape
- **api-conventions** (produced by BED-02, consumed by PGD-01):
  - Formatting utilities already available (`format_number`)

---

## Pattern Map

### Existing Code to Extend

1. **`app/api/programs.py`** — extend or reference from new overview module:
   - Pattern of RBAC check (line 82: `await program_visibility(...)` with sentinel) already established
   - Pattern of fail-closed persona resolution (lines 87-112) established
   - Can import the same `dot_style_for_program` utility (line 52)

2. **`app/core/auth.py::get_current_user`** — existing dependency already injects `CurrentUser`:
   - New endpoint will declare `current_user: CurrentUser = Depends(get_current_user)` same as programs.py

3. **`app/core/rbac.py`** — reuse `program_visibility()` open-aggregate check:
   - Called once per request with sentinel `program_id` for session validation

4. **`app/utils/format.py`** — reuse `format_number()`:
   - Already imported in programs.py (line 52); new endpoint will import from same module
   - Apply to all 7 numeric summary-card values

5. **`app/schemas/`** — extend for new response schema:
   - Pattern: in/out models split (`ActivityEventIn`/`ActivityEventOut`)
   - New: `ProgramDetailResponse` Pydantic model for endpoint response

6. **`apps/web/src/components/PersonaDashboardShell.tsx`** — already accepts program prop:
   - New PGD-01 page will pass this prop (already present)

7. **`apps/web/src/lib/programStyle.ts`** — already derives program styling:
   - New components will reuse this utility for avatar/typeChip styling

### Existing Patterns to Follow

1. **Router pattern** (`app/api/programs.py`):
   - Thin async function named `<verb>_<noun>` (e.g., `get_program_detail`)
   - Dependency injection: `current_user`, `db`, optionally `persona_resolver`
   - Single `select()` statement; no N+1 queries
   - Response model returned directly (Pydantic handles JSON serialization)

2. **Error handling** (`app/core/errors.py`):
   - Raise `HTTPException` for 404 (program not found), 403 (access denied)
   - Let the registered handler produce the standard error envelope

3. **RBAC pattern** (`app/core/rbac.py`):
   - Call `program_visibility()` exactly once, pass current_user + sentinel program_id
   - No per-program gating; the open-aggregate check is session-validity only

4. **Response formatting**:
   - All numeric values pre-formatted via `format_number()` server-side
   - Pre-formatted CSS via `dot_style_for_program()`
   - All values must be strings (already done) for display binding

5. **Frontend component pattern** (`PersonaDashboardShell.tsx`):
   - Accept data as props; no fetching
   - Presentational only; no branching on persona (already resolved server-side per story AC-6)

### New Files to Create

**Backend:**
1. **`services/api/app/api/overview.py`** — new router module
   - Path: `/api/overview/`
   - Handlers: `get_program_detail(program_id: str, ...)`
   - Response model: `ProgramDetailResponse` (defined in schemas)

2. **`services/api/app/schemas/program_detail.py`** (or extend existing `programs.py`):
   - Define `ProgramDetailResponse` with:
     - `header: {icon: str, name: str, type: str, description: str}`
     - `summary_cards: list[{glyph: str, value: str, label: str}]`
   - Each value field is a pre-formatted string (no raw numerics)

**Frontend:**
3. **`apps/web/src/app/program/[program_id]/page.tsx`** — Program Detail page shell
   - Route segment: dynamic `[program_id]` (Next.js App Router)
   - Server Component by default
   - Fetches `GET /api/overview/program-detail/{program_id}`
   - Passes resolved data to child components

4. **`apps/web/src/components/ProgramDetailHeader.tsx`** — header component
   - Displays: avatar, name, type chip, scope/description
   - Contains: "← Back" link, "Switch program" selector (fetches from GET /api/programs)
   - Sticky positioning, translucent background per design tokens

5. **`apps/web/src/components/ProgramSummaryCards.tsx`** — 7-card grid component
   - Maps over summary_cards array
   - Each card: glyph (icon tile), value (25px KPI), label (secondary text)
   - Grid layout: auto-fit minmax 200px

6. **`apps/web/src/types/program.ts`** — TypeScript types (or extend existing `persona.ts`)
   - `type ProgramDetail = {icon, name, type, description, summaryCards}`
   - Re-export from OpenAPI-generated types (future integration point)

### Shared Code at Risk

1. **`app/core/rbac.py::program_visibility`** — used by 2+ endpoints (programs.py + new overview.py):
   - Changes to the sentinel logic or session-validity check ripple to all callers
   - Mitigation: this is a sealed contract (AUTH-03); no changes expected through PGD-01's impl phase

2. **`app/models/rollup.py::ProgramSummary`** — data source for both programs list and detail:
   - Column additions/removals ripple (e.g., if a new summary-card metric is added)
   - Mitigation: Alembic migrations are the gating mechanism; schema versioning is explicit

3. **`app/utils/format.py::format_number`** — applied to 7 values in PGD-01:
   - Bug in format_number surfaces across all consumers
   - Mitigation: full test coverage already exists; considered stable (BED-02 PASS)

4. **`docs/design/tokens.md` + `docs/design/mockups/Program Detail.html`** — UI contract:
   - If design tokens or mockup markup change, frontend must track
   - Mitigation: mockups are immutable artefacts (bundler outputs); design tokens are semantic and versioned

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Dependency | HIGH | Program-detail endpoint response schema untested against downstream consumers (ARC-01, DEV-01, PMD-01, EMD-01) — each expects identical byte-signature (FR-PD-17). Divergence discovered only at /arh-validate-feature, not during impl. | Include test fixtures in `/arh-plan-implementation` that mock all 4 downstream consumer payloads; validate schema matches mockup bindings exactly before code review. |
| 2 | Integration | HIGH | GET /api/programs used by PGD-01 header for "Switch program" selector — endpoint is live but versioning/contract changes in AUTH-04-downstream phase ripple to PGD-01 frontend. | Test the full switcher flow (programs list → detail page switch) as an integration test; AUTH-04 is locked (phase=review), lowering this risk to MED after Phase 1. |
| 3 | Domain | MED | 7 summary-card values from `program_summary` are pre-aggregated rollup data; frontend shows "to-date" (FR-PD-04 wording), but no refresh/staleness indicator is rendered (mockup shows no "as of: <timestamp>" label). Users may assume real-time. | In `/arh-plan-requirements`, decide whether to surface `as_of_timestamp` from program_summary; add to response schema if needed. Design shows no such field; confirm this is accepted. |
| 4 | Performance | MED | Three DB queries anticipated: (1) get program_summary row, (2) fetch programs list for switcher, (3) implicit joins for persona resolution. No pagination on switcher list (only 6 placeholder slots, but open question if real prod has 100s of programs). | Benchmark with realistic data set (100+ programs) in /arh-validate-feature; page load target is 3s per NFR-001. Cache switcher list on frontend or add pagination if needed. |
| 5 | Compatibility | ~~MED~~ **RESOLVED (C-2)** | Frontend uses App Router; no middleware/intercepting routes yet. Program Detail page route must be `/program/[program_id]` or `/programs/[program_id]` — need to decide path convention before impl (not yet settled in codebase). | Align with any existing OVW-01/OVW-04 route conventions in next-patterns SKILL or ADR-0002. Use singular `program` (matches mockup domain language) vs plural `programs` (matches api/programs endpoint). |
| 6 | Security | ~~MED~~ **RESOLVED (C-3)** | RBAC check is open-aggregate (passes all authenticated sessions). No per-program membership gating. If user manually edits URL to `/program/other-users-program`, backend returns 200 with full data. Frontend cannot prevent this; per story AC-1, it's intended (any authenticated user can see any program via the board). But UX implication: "unauthorized view" is not a visible error state. | Document in REQUIREMENTS.md that this is role-agnostic access (any authenticated user gets full program detail, not just their own programs). Confirm with PM. No code mitigation needed if this is by design. |
| 7 | Integration | LOW | `format_number()` applied to all 7 metrics — if any metric is nullable/optional in the DB, frontend must handle null rendering (no "null" string display). ProgramSummary model shows only `intervention_count` and `tool_rejections` as nullable; the 7 summary-card columns are non-nullable (Integer, BigInteger, no nullable=True). | Verify in schema (rollup.py) that all 7 columns are non-nullable. Add a migration test fixture to ensure at least one program_summary row exists with all 7 metrics populated. |
| 8 | Domain | ~~LOW~~ **RESOLVED (C-1)** | 3 sections after summary cards (Daily Token Consumption, Releases, Commands) are owned by PGD-02, PGD-03, PGD-04. PGD-01 story says "shell" but does not specify if those sections are part of the shell or separate. Mockup shows all 4 sections on one page; unclear which story builds which section. | Confirm story scope: does PGD-01 shell include only the header + 7 cards, or the full page down to Releases? Likely out of scope (PGD-02/03/04 cover those), but clarify in `/arh-plan-requirements`. |
| 9 | Integration | **HIGH** | **AUTH-04's `href` is unusable as the switcher's link target.** `services/api/app/api/programs.py:132` emits `href=f"/api/overview/program-detail/{row.program_id}"` — the JSON API path — but the mockup binds it as a page navigation (`<a href="{{ o.href }}">`, mockup data `'Program Detail.dc.html?p=' + k`), and ADR-0005 §2 derives the active row by comparing `href` to the current route. Bound as specified, a switcher click navigates the browser to raw JSON, and the active-row comparison can never match. Pinned by a passing test (`services/api/tests/unit/test_programs.py:604`), so it will not surface on its own. Found 2026-09-03 while resolving C-2; not visible to the original scan, which read the contract docs rather than diffing them against the mockup binding. | Fix in AUTH-04, not here: emit `href=f"/programs/{row.program_id}"` and update TC-07's assertion. AUTH-04 is at `phase=review` with `review: PASS`, **Superseded 2026-09-03 by the PGD-01 Product Gate decision: folded into PGD-01's implementation as a discrete task with its own DECISIONS.md entry, rather than a separate `bugfix/AUTH-04` PR — an accepted exception to surgical-changes.** Recorded as CF-05. Blocks PGD-01 AC-5 (switcher reload) if unresolved by implementation time. |

---

## Score & Verdict

### Dimension Scores (0–100 scale)

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| **Integration** | 80 | 4 upstreams all live & complete (BED-01/02, AUTH-03/04); programs endpoint proven; GET /api/programs works end-to-end. Risk #1 (downstream validation) and #2 (versioning ripple) are addressable in planning. Risk #4 (perf/pagination on switcher) is open but mitigatable with data-driven bench. |
| **Compatibility** | 85 | No browser/version concerns (Next.js 15 + React 19 baseline). Desktop-only mockup (no mobile breakpoints); no responsive work needed for MVP. Frontend route path not yet decided (minor decision point, not a blocker). PersonaDashboardShell already built and tested (SHP-01 complete). |
| **Domain** | 82 | 7 summary-card metrics all present in schema with correct types (non-nullable). "To-date" wording clear; staleness (Risk #3) is a design decision (no timestamp in mockup). RBAC is explicitly open-aggregate (by spec), not a hidden assumption. One ambiguity (Risk #8: which sections does shell include?) is a story-scope question, not a code risk. |
| **Performance** | 75 | Target 3s page load per NFR-001. Anticipated 3 queries (program_summary, programs list, persona resolution) are O(1) for program detail, O(N) for switcher list (N=program count, unknown scale). format_number is pure function (negligible cost). No profiling yet; benchmark during validation. |
| **Dependency** | 88 | All 4 upstream stories complete, tested, live. BED-01 schema locked. BED-02 format utility stable. AUTH-03 & AUTH-04 in review/security phases; low churn risk. No external service dependencies. DB connectivity via existing `get_db()` seam. |

**Weighted Total: (80×0.25 + 85×0.20 + 82×0.20 + 75×0.15 + 88×0.20) / 1.00 = 82.35 → 82/100**

### Verdict

**GO-WITH-CONDITIONS**

The story is feasible and can proceed to `/arh-plan-requirements`. All upstream dependencies are shipped and stable. The data model is complete, the API utilities are ready, and the design reference is clear. Conditions for planning phase:

1. **Clarify story scope** (Risk #8): confirm whether PGD-01 shell includes only header + 7 cards, or full page down to Releases/Commands/Team sections. Section 1 is the shell; sections 2+ belong to PGD-02/03/04.
2. **Decide frontend route path**: `/program/[program_id]` vs `/programs/[program_id]` (minor, but must be consistent with OVW stories).
3. **Resolve program visibility UX**: confirm that open-aggregate RBAC (any user sees any program) is the intended behaviour per AC-1, and that no "access denied" UX is needed.
4. **Plan integration test for downstream consumption**: `/arh-plan-requirements` must spec how ARC-01/DEV-01/PMD-01/EMD-01 will consume and validate the program-detail-api response (byte-identity requirement per FR-PD-17).

### Synthesis

PGD-01 ships a Program Detail page header and 7 to-date summary cards, gated by any-authenticated-user access (per RBAC open-aggregate) and populated from the `program_summary` rollup table. All upstream dependencies (BED-01 schema, BED-02 formatting, AUTH-03 RBAC, AUTH-04 programs list) are live and tested on main. The backend endpoint `GET /api/overview/program-detail/{program_id}` must be created from scratch; the frontend page and header/cards components are new. The three open questions — story scope, route path convention, and visibility UX — were resolved by the user on 2026-09-03 (§ Clarifications C-1..C-3): shell = header + 7 cards + switcher + back link; route = `/programs/[program_id]`; visibility stays open-aggregate. Resolving C-2 surfaced one new HIGH defect (Risk #9): AUTH-04's `href` emits an API path where the mockup binds a page route, which must be fixed in AUTH-04 under its own PR before PGD-01's switcher can be built to the mockup. Performance target (3s page load) is achievable with the anticipated 3-query footprint, pending benchmark validation.

### Conditions for Downstream (GO-WITH-CONDITIONS)

Three of the original four conditions are now settled decisions (§ Clarifications) rather than open items. What PLAN.md must still carry:

1. **Scope boundary** (settled, C-1): header + 7 summary cards + switcher + back link. The daily token chart, releases, commands, team table and session chart are PGD-02/03/04/05/06 — out of scope here.
2. **Frontend route** (settled, C-2): `/programs/[program_id]`.
3. **Program visibility** (settled, C-3): open-aggregate, no membership filtering in this story. Detail is unscoped; the switcher list is membership-scoped upstream by AUTH-04.
4. **AUTH-04 `href` fix is a hard prerequisite** (new, Risk #9 / CF-05): PGD-01's switcher binds `o.href` per the mockup. Until `services/api/app/api/programs.py:132` emits `/programs/{program_id}`, that binding navigates to raw JSON. Sequence the AUTH-04 bugfix PR **before** PGD-01 implementation, or PGD-01 AC-5 cannot pass. Do not patch AUTH-04 from inside PGD-01's branch.
5. **Downstream validation** (unchanged): test fixtures for ARC-01/DEV-01/PMD-01/EMD-01 verifying byte-identical response schema per FR-PD-17.

---

## Clarifications

All three resolved 2026-09-03 by the user, during `/arh-research` Phase 2 follow-up. No markers remain; this file no longer blocks the `phase-preconditions` clarification gate.

| # | Question | Resolution |
|---|----------|-----------|
| C-1 | Does the PGD-01 "shell" include only the header + 7 summary cards, or also the sections below? | **Shell only** — header, 7 to-date summary cards, "Switch program" selector, "← Back to program board" link. The four sections below the cards are already owned: PGD-02 (daily token chart), PGD-03 (releases), PGD-04 (commands), PGD-05 (team table), PGD-06 (session chart). Grounded in RTM § Decisions 2026-08-26 (line 62): PGD-01..06 are six distinct backend resources, each independently testable with its own range-toggle refresh. Resolves Risk #8. |
| C-2 | Frontend route path convention — `/program/[program_id]` or `/programs/[program_id]`? | **`/programs/[program_id]`** — plural, matching the `/api/programs` collection and the Next.js App Router convention for a collection-item route. No prior convention existed to match (`apps/web/src/app/` holds only `layout.tsx` and `page.tsx`). Resolves Risk #5. |
| C-3 | Is open-aggregate program visibility the final intended UX, or should membership scoping be added here? | **Open-aggregate, as built** — unchanged. Any authenticated session may load any program's detail; the switcher *list* stays membership-scoped (PRD line 528, FR-AUTH-10), so the asymmetry is intentional, not a gap. RTM § Decisions line 59 already records this as CONFIRMED (Q-001/A-004). PRD R-003/Q-001 stay open as a tracked risk owned by `/arh-security-review`, not by PGD-01. Resolves Risk #6. |

### Defect surfaced while resolving C-2

C-2 exposed a live contract defect in shipped AUTH-04 code, recorded as **Risk #9** below and as carry-forward **CF-05** on `docs/features/AUTH-04/state.json`. PGD-01 cannot bind the switcher as the mockup specifies until it is fixed.

---

## Next Step

Clarification gate is clear — zero unresolved-clarification markers remain (all three resolved 2026-09-03, § Clarifications).

→ `/arh-plan-requirements PGD-01`

Carry into planning: the four conditions above, in particular the AUTH-04 `href` prerequisite (Risk #9 / CF-05) — folded into PGD-01's own implementation by the Product Gate decision of 2026-09-03, as a discrete task.
