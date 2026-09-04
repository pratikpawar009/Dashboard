# PGD-01 — Decisions

Decision log for the Program Detail page shell. Entries D-01/D-02/D-03 record the three design
items the user settled at the Product Gate (2026-09-03) — not re-opened here, recorded per that
instruction. D-04 records the mandatory AUTH-04 `href` edit. D-05..D-09 are implementation-planning
decisions made while filling `program-detail-api`'s concrete shape and the frontend fetch layer.

### D-01: Omit the static `CIO / CXO` persona chip (mockup L396) · blast:feature · rev:mechanical · adr:—

**Context**: `Program Detail.html` L396 renders a static `CIO / CXO` chip as a sibling of the type
chip (DESIGN.md § Region 2, "Design gap — the persona chip"). AC-6 requires a byte-identical
response across personas and forbids persona-branching in `program-detail-api`, so the endpoint
cannot source this chip. SHP-01's `apps/web/src/lib/formatPersonaTag.ts` deliberately throws
`PersonaTagError` for `cio` (its own D-03 invariant — the CIO Portfolio mockup has no persona-tag
region), so extending it to cover `cio` here would violate that shipped invariant.

**Decision**: PGD-01 does not render the chip. No data source is added, and `formatPersonaTag.ts`
is not extended. Carried forward (`pending_carry_forward` item `persona-chip-omission`, this
feature's `state.json`) for whichever future story owns a CIO-specific portfolio shell to decide
whether/how to render it — none is scheduled today.

### D-02: Back-to-board link target is a single named route constant, value `/overview` · blast:feature · rev:mechanical · adr:—

**Context**: The mockup's back-link target is `href="CIO Portfolio Dashboard.html"` — a canvas file
reference, not a route. The Adoption Overview page (OVW epic) has no route yet. The link must
still render normally and be keyboard-reachable today; pointing it at `/` would silently succeed
against the current Next.js starter homepage (`apps/web/src/app/page.tsx`), masking the fact that
the real Adoption Overview page doesn't exist yet — the opposite of what an honest "not built yet"
link should do.

**Decision**: `ADOPTION_OVERVIEW_ROUTE = "/overview"`, exported once from
`apps/web/src/lib/routes.ts`, consumed only by `BackToProgramBoard.tsx`. This 404s today (no
`/overview` route exists) — accepted and visible, not a defect. OVW-01 flips this one constant when
it ships its real route. Carried forward (`pending_carry_forward` item
`back-to-board-route-placeholder`, owner OVW-01).

### D-03: 404 error state — inline panel, shell retained, built from existing tokens · blast:feature · rev:mechanical · adr:—

**Context**: AC-7 requires an error state instead of a blank shell for an unknown `program_id`; the
mockup has no error treatment to copy (DESIGN.md § States). A concrete rendering had to be
authored, not left to "decide at implementation" a second time.

**Decision**: On a 404, `BackToProgramBoard` and the sticky header wrapper still render.
`ProgramDetailHeader` omits the avatar/name/type-chip/description/switcher (there is no program row
to source them from) and shows only a plain fallback line, "Program not found" (13px/500,
`#7a828f` — `docs/design/tokens.md` text-600, matching Region 1's description token weight). The
summary-cards region is replaced by `ProgramDetailErrorPanel`: a single bordered panel reusing the
card recipe verbatim (`docs/design/tokens.md` § Card recipe: `1px solid #e6e9ef`,
`border-radius:16px`, `padding:18px 19px`, `box-shadow:0 1px 2px rgba(15,26,46,.04)`) containing the
message "This program could not be found." (13px/500, `#5b6472` — text-700). No new screen is
invented; every token used already exists in `docs/design/tokens.md`. The switcher's own
`GET /api/programs` fetch is skipped entirely in this state (no valid current program to compare
against for the active-row highlight, and the mockup's switcher scope doesn't cover a broken URL).

### D-04: AUTH-04 `href` fix ships inside PGD-01's branch · blast:service · rev:mechanical · adr:—

**Context**: `services/api/app/api/programs.py:132` emits
`href=f"/api/overview/program-detail/{row.program_id}"` — a JSON API path — but the mockup binds
`href` as a page-navigation target and ADR-0005 §2 derives the switcher's active row by comparing
`href` to the current route (research Risk #9 / AUTH-04 `state.json` `pending_carry_forward` item
CF-05). Bound as shipped, a switcher click navigates to raw JSON and the active-row match never
fires — PGD-01's FR-4 cannot pass until this is fixed. The Product Gate (2026-09-03) decided this
ships inside PGD-01's branch rather than a separate `bugfix/AUTH-04` PR, an accepted, recorded
exception to `.claude/rules/surgical-changes.md` against a `review: PASS` story.

**Decision**: `services/api/app/api/programs.py:132` changes to
`href=f"/programs/{row.program_id}"`; `services/api/tests/unit/test_programs.py:604`
(`test_href_routes_to_program_detail_api_path_tc07`) updates its assertion to match. This is its
own task (T-04), touching only these two files, so it is reviewable on its own terms in the diff —
`/arh-review` should expect an AUTH-04-owned file in PGD-01's diff. Checked
`README.md`'s `/api/programs` row for the same `href` semantics: it does not spell out the literal
path pattern (only the field-set shape), so no README edit is needed for this fix specifically —
folded instead into T-14's broader `/api/overview/program-detail/*` documentation task.
`docs/features/AUTH-04/state.json` `pending_carry_forward` CF-05 should be marked resolved via
`harness carry-forward resolve --for AUTH-04 CF-05` once T-04 lands (not done here — that record is
AUTH-04's own, mutated at implementation/commit time, not at PGD-01 planning time).

### D-05: Header `avatarStyle`/`typeChip` stay client-derived, not shipped server-side · blast:feature · rev:mechanical · adr:—

**Context**: DESIGN.md Region 2 (hand-authored, pre-implementation) reads the mockup literally and
notes `prog.avatarStyle`/`prog.typeChip` as "pre-formatted server-side" bindings. But
`persona-shell`'s already-shipped `program_context` contract (SHP-01,
`docs/requirements/api.md#persona-shell`) explicitly ships `program: {icon, name, type,
description}` as **data only** and derives `avatarStyle`/`typeChip` client-side via
`apps/web/src/lib/programStyle.ts::getProgramStyle(type)`, ignoring any style field the prop might
carry (`ProgramContext.tsx` destructures exactly `{icon, name, type, description}`, `programStyle.test.ts`
asserts an injected style field is never read). Shipping the same two style fields from
`program-detail-api` too would create a second, divergence-prone source of the same color pair.

**Decision**: `program-detail-api`'s `header` stays `{icon, name, type, description}` — no
`avatarStyle`/`typeChip`. `ProgramDetailHeader.tsx` calls the existing, already-tested
`getProgramStyle(type)` for its avatar/type-chip color pair, same as `ProgramContext.tsx` — one
source of truth for program-type colors (`docs/design/tokens.md` § Program type colors) across
every consumer, present and future.

### D-06: `summary` is an ordered array of `{glyph, value, label}`, glyph/label server-owned · blast:system · rev:medium · adr:ADR-0007

**Context**: Two shapes were viable for the 7 to-date summary cards — flat named fields (matching
`docs/test-cases/PGD-01.json`'s own, self-disclaimed "not a confirmed schema" naming) vs. an ordered
array mirroring the mockup's `sc-for` binding with glyph/label baked in server-side. `program-detail-api`
is `consumed_by: [ARC-01, DEV-01, PMD-01, EMD-01]` — none built yet — and per
`docs/design/README.md`'s screen inventory, all four (plus PGD-01 itself) render this same 7-card
section, EMD-01 "As Program Detail" verbatim.

**Decision**: See ADR-0007 for the full analysis. `summary: [{glyph, value, label}, ...]`, exactly 7
entries, mockup order load-bearing; glyph/label are fixed presentation constants owned by
`app/api/overview.py`, not re-derived by any of the 5 consumer stories. `header` stays as decided in
D-05. Promoted to a full ADR: this decision reaches beyond PGD-01 into 4 sibling, not-yet-built
features sharing one sealed contract — the same category ADR-0005 already promoted for
`programs-api`.

### D-07: `program_switch` vs `program_drilldown` distinguished via an optional `X-Program-Switch-From` request header · blast:feature · rev:mechanical · adr:—

**Context**: PGD-01-FR-5 requires both `program_drilldown` (page open) and `program_switch`
(switcher selection) as structured log events, but `docs/test-cases/PGD-01.json`'s own
`generation_note`/`audit_notes` disclose that neither the PRD nor the story specifies how the
single-shape endpoint (`GET /api/overview/program-detail/{program_id}`, identical for an initial
load and a switcher reload) tells the two triggers apart — and explicitly declines to fabricate a
mechanism for TC-04's purposes. Leaving FR-5's `program_switch` half permanently unimplementable
was judged worse than designing a minimal, additive mechanism.

**Decision**: `app/api/overview.py` reads an optional request header, `X-Program-Switch-From`
(`Header(default=None)`, FastAPI). Absent (the initial-load case): logs `program_drilldown
{program_id}`. Present and non-empty (the frontend's switcher-triggered reload sends it, set to the
previously-viewed `program_id`): logs `program_switch {from_program_id, to_program_id}` instead.
Exactly one of the two fires per successful (200) request; neither fires on a 404. This changes
request headers and server-side logging only — the response body is untouched, so FR-PD-17's
byte-identical invariant is unaffected regardless of which persona or which trigger path is taken.
`services/api/app/main.py`'s CORS `allow_headers` list must include `X-Program-Switch-From` (a
non-simple header triggers a preflight) — folded into T-03, the same task that registers the new
router.

### D-08: Frontend fetches omit the `Authorization` header (accepted auth-flow gap) · blast:feature · rev:mechanical · adr:—

**Context**: `GET /api/overview/program-detail/{program_id}` and `GET /api/programs` both require a
bearer JWT (`get_current_user`). No frontend token-acquisition mechanism exists anywhere in
`apps/web` today — SHP-01's `signedInUser`/`persona` props are themselves PROVISIONAL, pending an
AUTH-01 session-contract amendment, and SHP-01 explicitly declined to wire a page/route around them
("that would fabricate scope the PRD explicitly excludes"). PGD-01's own test-cases (TC-03) mock the
fetch boundary entirely, sidestepping the header question; no PRD/DESIGN artifact for this story
specifies a token source.

**Decision**: `apps/web/src/lib/programDetailApi.ts`'s fetch calls send no `Authorization` header —
consistent with the rest of this codebase's current, whole-of-repo state (zero frontend fetch code
exists anywhere yet; PGD-01 is simply the first to add real fetch calls and the first to hit this
gap). In any real (non-mocked) deployment against a live backend, these calls will receive `401`
until a future frontend auth/session story wires token acquisition into this fetch layer. Carried
forward explicitly (`pending_carry_forward` item `frontend-auth-token-gap`) rather than silently
built around. `fetchProgramDetail`/`fetchPrograms`'s signatures take an options object
(`{switchedFrom?}` today) specifically so a future `{accessToken?}` addition is additive, not a
breaking rename.

### D-09: Frontend fetch/router mocking via native `vitest` mocks, not MSW · blast:feature · rev:mechanical · adr:—

**Context**: `docs/test-cases/PGD-01.json` TC-03's preconditions mention "Fetch mock (e.g. MSW)" as
an illustrative example, not a mandate. `apps/web/package.json` has no HTTP-mocking library
installed, and no existing frontend test in this repo mocks a network boundary yet (every current
test is pure-render, e.g. `ProgramContext.test.tsx`) — PGD-01 is the first to need it.

**Decision**: `ProgramDetailView.test.tsx` mocks the network boundary via `vi.stubGlobal("fetch",
vi.fn())` (or an equivalent module-level `vi.mock` of `programDetailApi.ts`) and mocks
`next/navigation`'s `useRouter` via `vi.mock("next/navigation", ...)` — both already available
through the installed `vitest`/`@testing-library/react` stack. No new dependency is added (avoids a
Config-drift C1 trigger for a single test file's convenience).
