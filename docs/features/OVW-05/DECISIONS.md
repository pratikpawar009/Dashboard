# OVW-05 — Decisions

Decision log for CIO shell regions (signed-in identity block + org page-title header). One entry per non-trivial implementation-time choice; full ADRs only when `blast:`/`rev:` cross the promotion bar (none do here).

### D-01: `meApi.ts` extraction, mirroring `overviewApi.ts` · blast:feature · rev:mechanical · adr:—

**Context**: Research left the `GET /api/me` fetch location undecided ("inline in `page.tsx` or an extracted `meApi.ts` — either is acceptable", `docs/research/OVW-05.md` Pattern Map). This codebase's dominant pattern for a FastAPI-resource fetch used by exactly one Server Component is a dedicated `lib/<resource>Api.ts` module (`overviewApi.ts` for `overview-summary-api`, `programDetailApi.ts` for `program-detail-api`) — `.claude/rules/pattern-consistency.md` requires following the dominant pattern over inventing an ad hoc inline fetch.

**Decision**: Add `apps/web/src/lib/meApi.ts` exporting `fetchMe()`, mirroring `overviewApi.ts::fetchOverviewSummary`'s status-mapping and timeout conventions exactly (403 → `forbidden` checked before 401 → `unauthorized`, before the generic `!response.ok` → `error` branch; 5000ms `AbortSignal.timeout`). Backed by a co-located `apps/web/src/types/me.ts` (`MeData`/`MeResult`), matching `types/overview.ts`'s precedent. Called only from `overview/page.tsx` inside `tokenStore.callWithAuth()` — `AdoptionOverview.tsx` never fetches.

### D-02: Concurrent `GET /api/me` + `GET /api/overview/summary` via `Promise.all` · blast:feature · rev:mechanical · adr:—

**Context**: Research risk #3 (MED, Integration) flags latency stacking from two sequential fetches sharing the page's one ≤3s render budget (NFR-001); no separate budget is granted to the new call.

**Decision**: Issue both `callWithAuth()`-wrapped fetches concurrently via `Promise.all` in `overview/page.tsx`. Safe because `tokenStore`'s existing single-flight refresh guard (FR-1, module-level `refreshPromise`) already dedupes a concurrent proactive-refresh race between the two calls — no new concurrency primitive is added. Either call's `SessionExpiredError` is caught by the existing single `try/catch` and redirects to `/login`, unchanged in shape from today's one-call version.

### D-03: Persona-resolution-failure sentinel on `/overview` · blast:feature · rev:mechanical · adr:—

**Context**: `REQUIREMENTS.md` § Screen inventory's "Error (persona resolution fails → existing neutral badge)" state requires `page.tsx` to hand `PersonaDashboardShell` an unresolvable `persona` value when `GET /api/me` returns 403 (`forbidden`) — no source names the literal to pass.

**Decision**: Define `const PERSONA_RESOLUTION_ERROR = "persona-resolution-error"` locally in `overview/page.tsx` (the same literal `PersonaDashboardShell.test.tsx` already exercises for this exact scenario) and pass it as `persona` whenever the `GET /api/me` result is not `"ok"`; `signedInUser` is `undefined` in that branch. The shell's own existing `PersonaTagError` catch (unchanged) renders the neutral badge — no new error UI is invented.

### D-04: Org-header `PersonaTagError` catch duplicated, not extracted · blast:feature · rev:mechanical · adr:—

**Context**: `DESIGN.md` § Open design items (item 3) flags a share-vs-duplicate call for the org-header variant's neutral-badge path. `.claude/rules/reusability-baseline.md` sets the extraction bar at the **third** repetition; this is only the **second** occurrence of the "neutral pill + `aria-live` announcement" JSX shape (the first is `PersonaHeader.tsx`, shipped and reviewed under SHP-01). `.claude/rules/surgical-changes.md` also weighs against editing `PersonaHeader.tsx` for a change this story does not otherwise need there.

**Decision**: Duplicate the try/catch + neutral-badge JSX inline in `PersonaDashboardShell.tsx`'s new org-header variant rather than extracting a shared helper. Carried forward (§ 6) for extraction if a third occurrence ever appears.

### D-05: Org-header padding via modifier class · blast:feature · rev:mechanical · adr:—

**Context**: `DESIGN.md` § Open design items (item 1) — the CIO mockup's `HEADER` region pads `20px 34px`; the shipped `.headerRegion` rule (used by the four persona dashboards) pads `18px 34px 20px`. `CLAUDE.md` § Design system makes the mockup the contract on any disagreement.

**Decision**: Add a `.headerRegionOrg` modifier class in `PersonaDashboardShell.module.css`, applied alongside `.headerRegion` only for the org variant, overriding `padding: 20px 34px`. The shipped `.headerRegion` rule itself is untouched, so the four (not-yet-built) persona dashboards keep their existing padding.

### D-06: Sign-in card width = 400px · blast:feature · rev:mechanical · adr:—

**Context**: `DESIGN.md` § Open design items (item 2) — no source (the six mockups, `docs/design/tokens.md`) specifies a sign-in card width; `content-max-width: 1360px` is a page-column value, not a card width, and a concrete number is needed to build the card.

**Decision**: `max-width: 400px` on `/login`'s card, centered via the page's flex column (`display:flex; align-items:center; justify-content:center`). A conventional single-column auth-card width, consistent with the card's own padding/radius/shadow already specified in `DESIGN.md`'s Card-recipe citation — not derived from any mockup measurement, since none exists.
