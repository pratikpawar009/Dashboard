# Feature: OVW-05 — CIO shell regions: signed-in identity block + org page-title header

## Problem

A CIO landing on `/overview` (OVW-01) sees org summary data but no confirmation of *who* they are
signed in as, or that they are viewing the org-wide CIO dashboard rather than a persona view:
`AdoptionOverview` renders `PersonaDashboardShell` with `persona`/`signedInUser`/`program` all
omitted, so the shell's `isLoading` gate permanently suppresses the already-built identity block
and header regions (`persona-shell` `identity_block_unblocked`). Separately, a signed-in user has
no in-UI way to end their session (only a raw `/logout` URL), and an unauthenticated visitor
hitting `/login` is bounced straight to Keycloak with no dashboard-owned screen — including right
after logout, since `FRONTEND_LOGIN_URL` is Keycloak's own registered post-logout redirect URI.

## Outcome

A CIO on `/overview` sees their name, "Chief Information Officer" job title, and a `#0f1a2e`
initials avatar in the brand bar, plus an org-level header reading "Adoption Overview" / "CIO /
CXO" / "Organization-wide AI-in-SDLC adoption, spend & impact" — sourced from a real,
server-confirmed `GET /api/me` call, never a hardcoded `persona="cio"`. The same identity block
carries a keyboard-reachable "Sign out" control wired to the existing `/logout` handler. An
unauthenticated visitor reaches a branded `/login` sign-in page (logo, product name, tagline,
single "Sign in with SSO" action) instead of an immediate IdP redirect; a visitor who already
holds a session passes straight through without seeing that action.

## Constraints

- `cio` becomes a fifth entry in `VALID_PERSONAS`/`PERSONA_DISPLAY` — additive only;
  `architect`/`developer`/`product-manager`/`engineering-manager` behavior is unchanged
  (`persona-shell` `cio_persona_note`).
- `jobTitle` is always composed frontend-side from `PERSONA_DISPLAY[persona].jobTitle`;
  `session-identity-api` ships only `{name, persona}` and must never be extended to carry it
  (`persona-shell` `job_title_source_note`; research risk #2).
- Job-title literals deliberately diverge from two of the six mockups ("Architect"/"Developer",
  not "Principal Architect"/"Senior Developer") — the system holds no seniority data anywhere
  (`docs/design/README.md` § Recorded divergences, `persona-shell` `job_title_divergence_note`).
- The sign-out control and the `/login` sign-in page are **recorded, user-confirmed deviations**
  from the six mockups (story Decision log 2026-09-11) — no further UI is invented beyond what
  those two decisions describe.
- `/login` cannot hold both `page.tsx` and `route.ts` in the same Next.js App Router segment; the
  existing OAuth relay moves to `login/start/route.ts`, body unchanged (story Decision log
  2026-09-11).
- No new persona-literal conditional may be added inside `PersonaDashboardShell.tsx` — the
  org-header variant is selected purely by `pageTitle` prop presence with `program === undefined`
  (`persona-shell` `org_header_region`, AC-8).

## Solution sketch

Extend the shipped persona system additively (`cio` entry, `jobTitle` field on all five
`PERSONA_DISPLAY` entries), fetch `GET /api/me` server-side in
`apps/web/src/app/overview/page.tsx` alongside the existing `overview-summary-api` call, and pass
the resolved `persona`/`signedInUser`/`pageTitle="Adoption Overview"` down to the already-built
(but currently suppressed) `PersonaDashboardShell` identity block and a new org-header variant.
Add a keyboard-accessible sign-out affordance to that same identity block, linking to the existing
`/logout` handler. Split `/login`'s single `route.ts` into a branded `page.tsx` (new) plus
`start/route.ts` (existing handler, relocated, body unchanged), with a server-side session check
that passes an already-authenticated visitor straight through.

## Addressing Research Conditions

- **Condition 1 (Risk #2, HIGH, Domain)** — `jobTitle` must never be read from `GET /api/me`; it
  is composed frontend-side only via `PERSONA_DISPLAY[persona].jobTitle`. Mitigation:
  `session-identity-api`'s `MeResponse` already ships `extra="forbid"` (AUTH-07 — no `jobTitle`
  field exists on the wire to read); this PRD requires a test (per **OVW-05-FR-3**) that mocks a
  `GET /api/me` response and asserts the rendered `jobTitle` equals
  `PERSONA_DISPLAY[persona].jobTitle` regardless of any extra key present in the mock — proving
  composition, not pass-through.
- **Condition 2 (Risk #5 residuals, Compatibility)** — three carried items, each pinned to an
  FR below: (a) all 7 shipped `redirect("/login")` call sites are unchanged — **OVW-05-FR-2**
  pins the relay's relocation as a pure file move with no call-site edits, verified by the
  existing test suite continuing to redirect through `/login`; (b) `login/start/route.ts`'s
  docstring correction (the false `OIDC_REDIRECT_URI` "must exact-match this path" claim) is
  pinned in **OVW-05-FR-2** and Documentation requirements; (c) `login/page.tsx`'s server-side
  session check is pinned in **OVW-05-FR-1**.
- **Condition 3 (Risk #8, LOW, Dependency)** — frontend `VALID_PERSONAS` and backend
  `persona_resolver` must stay in sync. Mitigation: Documentation requirements below adds a
  sync-obligation comment on `PERSONA_DISPLAY`'s header; any future persona addition is a single
  change touching both `apps/web/src/types/persona.ts` and the backend persona-role map, never
  one without the other.

## Scope

- In:
  - `cio` as a fifth `VALID_PERSONAS`/`PERSONA_DISPLAY` entry, `jobTitle` field on all five
    entries (AC-1..4).
  - `GET /api/me` wiring into `/overview`'s existing server-side fetch, composed
    `signedInUser`/`persona` passed to `PersonaDashboardShell` (AC-5..7).
  - `PersonaDashboardShell`'s new `pageTitle` prop + org-header variant, mutually exclusive with
    the program-header variant (AC-8..10).
  - Docstring corrections on `persona.ts`/`PersonaDashboardShell.tsx`/`formatPersonaTag.ts`
    (AC-4, AC-11).
  - Sign-out control in the signed-in identity block, linked to the existing `/logout` handler
    (AC-12..15).
  - Branded `/login` sign-in page + `login/start/route.ts` relay relocation + already-authenticated
    pass-through (AC-16..19).
- Out:
  - Any change to `GET /api/me`'s response shape (frozen, AUTH-07) or to `AUTH-05`'s PKCE/token-exchange
    mechanics.
  - `PGD-07`'s Program Detail brand-bar retrofit — downstream consumer of this story's persona-map
    addition, deferred to that story.
  - `ARC-01`/`DEV-01`/`PMD-01`/`EMD-01` fetching their own `GET /api/me` — not yet planned, per
    `session-identity-api` `under_declared_edge`.
  - Any new backend route, schema, or logging event.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/OVW-05.md` for canonical wording.
New impl constraints introduced below:

**OVW-05-FR-1** — `login/page.tsx` already-authenticated pass-through *(extends AC #18 with:
exact check + redirect target)*

The page reads the session via the existing `readSession()` helper
(`apps/web/src/lib/tokenStore.ts`, the same helper `GET /logout` already calls) — no new
session-parsing logic, no new cookie. A valid session `redirect()`s to `ADOPTION_OVERVIEW_ROUTE`
(`/overview`, `apps/web/src/lib/routes.ts`) before any sign-in markup renders; an absent or
invalid session renders the branded page normally. No `?next=`/return-URL param is introduced —
none of today's 7 `redirect("/login")` call sites carry one, so there is no captured destination
to restore (assumption: `/overview` is the app's default authenticated landing route, not a claim
that it is the only one).

**OVW-05-FR-2** — `login/route.ts` → `login/start/route.ts` relocation *(extends AC #17 with:
file-move mechanics + docstring correction)*

The file moves verbatim one segment down; the handler body (server-to-server relay to `GET
/auth/login`) is byte-identical. Only the file's own docstring changes: the false claim that
`OIDC_REDIRECT_URI` "must exact-match this path" is corrected to name the actual owner of that
constraint (`/callback`, `AUTH-05-FR-3`; `OIDC_REDIRECT_URI=http://localhost:3000/callback`). The
new sign-in page's SSO action targets `/login/start`. No other file changes — all 7 shipped
`redirect("/login")` call sites are unaffected because they now resolve to the new `page.tsx`,
which is the intended behavior change (AC-16), not a side effect requiring their own edit.

**OVW-05-FR-3** — `GET /api/me` fetch call site *(extends AC #5/#6/#7/#9 with: exact file +
prop composition)*

The fetch is added to `apps/web/src/app/overview/page.tsx` (the existing Server Component that
already calls `fetchOverviewSummary()` via `tokenStore.callWithAuth()`), not inside
`AdoptionOverview.tsx` — mirroring the page/component split OVW-01 already established (fetch at
page level, presentational component receives resolved props). The response is composed into
`signedInUser = data.name ? { name: data.name, jobTitle: PERSONA_DISPLAY[data.persona].jobTitle }
: undefined` and passed to `AdoptionOverview` alongside `persona={data.persona}` and
`pageTitle="Adoption Overview"`; `AdoptionOverview` forwards all three unchanged to
`PersonaDashboardShell` and performs no fetching of its own. A `GET /api/me` failure follows the
same `callWithAuth`/`SessionExpiredError` pattern as the existing `overview-summary-api` call
(research risk #7) — no new error state is invented.

## Non-functional requirements

- Performance: shares the page's existing ≤3s render budget (NFR-001, per OVW-01) — no separate
  budget for the added `GET /api/me` call (assumption, no source gives one; story NFR).
  `session-identity-api`'s `resolve()` is already process-cached 300s (sourced, `session-identity-api`
  `perf`), so repeat loads inside that window add no new backend latency.
- Security: Per `.claude/rules/security-baseline.md`: applies to the new `/login` page and the
  relocated `/login/start` relay (neither introduces new secret handling — both reuse existing
  token-store/session code). `AdoptionOverview` never hardcodes `persona="cio"` (sourced, story
  NFR-Security) — `persona` is always the server-confirmed value from `session-identity-api`.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the sign-out control
  and the SSO sign-in action (both new interactive elements) and the org-header composition (new
  UI region, no new interactive control). The neutral-avatar fallback stays `aria-hidden="true"`
  (AC-7); the shell's existing FR-5 no-flash/no-skeleton behavior is preserved (sourced,
  `persona-shell` states).
- Observability: no new logging event is introduced (sourced, story NFR-Observability) —
  `rbac_check_org_access` (OVW-01) is unaffected; `session-identity-api`'s own 401/403 logging is
  AUTH-07's concern.

## Screen inventory

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Adoption Overview — brand-bar identity + org header | /overview | server (initial load, no client refetch) | Show the signed-in CIO's name/job title/avatar + sign-out control in the brand bar, and an org-level "Adoption Overview" / "CIO / CXO" title header above the existing summary cards | Populated (persona + name resolved) / Loading (persona undefined — brand-bar-only, no identity/header, no flash, AC-10) / Empty (name null → neutral avatar fallback, AC-7) / Error (persona resolution fails → existing neutral "Persona unavailable" badge) | AC-1..15 |
| Branded sign-in page | /login | server | Pre-auth landing screen carrying the app's brand identity (logo, "AgentRise Harness", "AI SDLC Governance") plus a single "Sign in with SSO" action; an already-authenticated visitor is redirected onward before render | Populated (unauthenticated — sign-in action shown) / N/A (authenticated — server redirect, no page render) | AC-16..19 |

## Visual spec

See [DESIGN.md](./DESIGN.md).

## Rollout plan

- **Strategy**: bang-bang — additive persona entry, two new UI regions on an existing page, one
  new page plus a relocated (not rewritten) route handler; no existing behavior changes for the
  four non-CIO personas or any of the 7 `redirect("/login")` call sites. Per
  `.claude/rules/reusability-baseline.md`, no config-switch is introduced to fork the call graph.
- **Feature flag**: none — no flag infrastructure exists in this codebase, and the change is a
  code-level revert away from backing out.
- **Backout plan**: `git revert` the PR. `login/start/route.ts` moves back to `login/route.ts`
  (no data/schema change to unwind); `PERSONA_DISPLAY`/`VALID_PERSONAS` lose the `cio` entry,
  which only ever renders for a `cio`-resolved session (no other persona is affected); `/overview`
  reverts to omitting `persona`/`signedInUser`/`pageTitle`, restoring today's suppressed-identity-block
  state.
- **Success signal**: a signed-in CIO session on `/overview` renders name/job-title/avatar and the
  org header with no console error, verified in staging before wider rollout; all 7 existing
  `redirect("/login")` call sites still land on a working sign-in flow (manual smoke — `test_e2e`
  is empty in `docs/config/project-commands.yaml`).

## Documentation requirements

- **README updates**: `README.md`'s route table (the `/login`, `/callback`, `/api/proxy/*`,
  `/logout` Route Handlers row) — split the `/login` description into the new branded page and
  the relocated `/login/start` relay, since the table currently documents `/login` as solely the
  OAuth relay.
- **Runbook**: none.
- **API reference**: none — no backend route changes; `GET /api/me` is already documented in
  `README.md` (AUTH-07).
- **Inline code comments**: `login/start/route.ts`'s docstring — correct the false
  `OIDC_REDIRECT_URI` exact-match claim (**OVW-05-FR-2**, research condition 2).
  `apps/web/src/types/persona.ts` / `PersonaDashboardShell.tsx`'s `SignedInUser`/`signedInUser`
  docstrings — drop the "PROVISIONAL, pending AUTH-01 amendment" framing (AC-11).
  `apps/web/src/lib/formatPersonaTag.ts`'s `PERSONA_DISPLAY` map header — add a one-line
  sync-obligation comment: a new persona key requires a matching update to the backend
  persona-role map in the same change (research condition 3).
- **Examples / how-to**: none.

## Open questions

Decisions logged in `docs/stories/OVW-05.md` § Decision log.

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| Product Owner | Pratik Pawar (pratik.pawar@apexon.com) | 2026-09-11 | **APPROVE** |

Gate run: `/arh-plan-requirements OVW-05`, Phase 4. Design (`DESIGN.md`) complete at time of
approval; research verdict GO-WITH-CONDITIONS with all three conditions mitigated in
§ Addressing Research Conditions.

### Approved with a recorded exception — test-case coverage

One gate checklist item did **not** pass and was approved as an explicit, recorded exception
rather than being waived silently:

> `[ ] Test-case coverage audit shows zero uncovered AC/FR/NFR ids`

`docs/test-cases/OVW-05.json` carries **2 test cases** against **26** requirement ids —
**24 uncovered (7.7% coverage)**. The cap of two was an explicit user directive on the
`/arh-plan-requirements` run, not an agent decision or an oversight.

| | Covered | Uncovered |
|---|---|---|
| Acceptance criteria (19) | AC-6, AC-18 | AC-1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19 |
| Functional requirements (3) | — | FR-1, FR-2, FR-3 |
| Non-functional requirements (4) | — | NFR-performance, -security, -accessibility, -observability |

The two cases were chosen to guard the highest-risk surfaces, not for convenience:

- `OVW-05-TC-01` → AC-6 — `jobTitle` is composed frontend-side from `PERSONA_DISPLAY` and never
  read from `GET /api/me` (research risk #2, the sole HIGH).
- `OVW-05-TC-02` → AC-18 — an already-authenticated visitor at `/login` is redirected
  server-side and never sees the sign-in action (the `/login` routing split).

**Consequence accepted at this gate.** `/arh-plan-implementation` must raise test tasks for the
24 uncovered ids; the `plan-validation` rubric reads this manifest, so the gap is visible there
rather than lost. Two specific defects now ship without a guarding test and are called out so
they are not rediscovered late:

1. **AC-12 branch placement** — the sign-out control must be a sibling *outside* the
   `signedInUser ? … : …` ternary in `PersonaDashboardShell`. AC-12 requires it in both the
   populated and the neutral-fallback branch; placing it inside either branch silently drops it
   in the other (`DESIGN.md` § Recorded deviation A).
2. **Pre-auth contrast exposure** — `#8a93a1` at 3.10:1 (fails AA) now renders on `/login`, the
   first unauthenticated surface to carry an inherited token-level contrast failure. Carried,
   not fixed: the fix has global-token blast radius (`DESIGN.md` § Design QA).
