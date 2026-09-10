# Code Review — feature/OVW-01

- Date: 2026-09-10T07:49:17Z
- Mode: current (GATE MODE — report-only, snapshot `710ddbaf`)
- Files reviewed: 19 (3 backend source/test, 1 backend schema, 12 frontend, 3 docs) — see note below on diff scope
- Verdict: **PASS**

**Diff-scope correction, checked before anything else**: `git diff main...HEAD` (the ref given) is
inflated — local `main` is stale at `badb925` (ING-10), 3 merged PRs behind `origin/main`
(`81c89d8`, BED-05). Diffing against stale `main` pulls in ~13.8K already-merged AUTH-06/BED-05/
ING-02 lines (e.g. README's OIDC_SCOPE/`groups` rewrite, `rollup_rebuild.py`) that are not this
story's changes. `git diff origin/main` (HEAD is a clean 1-commit descendant of `origin/main`)
scopes correctly to OVW-01: 19 files, matching `tasks.json` `file_plan` F-01..F-24 (backend:
`org_summary.py`, `overview.py`, `test_overview.py`, `test_overview_perf.py`; frontend: 4 component
trios + `overviewApi.ts` + `types/overview.ts` + `app/overview/page.tsx` + `PersonaDashboardShell.*`;
docs: `api.md`, `tokens.md`, `README.md`) plus the expected per-story paperwork
(`DECISIONS.md`/`DESIGN.md`/`PLAN.md`/`REQUIREMENTS.md`/`DATA-DESIGN.md`/`state.json`/`tasks.json`/
`FLAGS.md`/research/test-cases docs). **No scope-creep** — every changed line traces to a task.
`docs/activity/activity.jsonl`'s one rewritten historical row (BED-05's `/arh-security-review`
entry, stats corrected after that run actually finished) was checked explicitly per this repo's own
"activity log can mutate historical rows" convention — benign, not a finding.

## Executive summary

Five order-locked org-summary cards + an adoption-level indicator on a new `/overview` page, backed
by one new `GET /api/overview/summary` route reading two existing read-only singleton tables. The
implementation is unusually well-disciplined: every one of the six risk areas flagged for this
review holds up under direct inspection, the null-vs-zero contract (`adoption_percent`) is enforced
structurally end-to-end rather than by convention, and the FR-2 "no color on the wire" test is a
genuine proof (asserts against the fixture's own serialized JSON), not a tautology. One real defect:
`DATA-DESIGN.md` §1's data-model table was never updated for D-02's card-5 correction and now
describes a design the shipped code does not implement. Everything else is solid.

🟢 5 order-locked cards, adoption headline/bar/legend, freshness-first-so-AC-7-beats-AC-2 ordering, `get_freshness_accessor` DI seam, D-04 shell widening, redirect-in-catch placement, FR-2 color-derivation proof — all verified correct
⚠️ `DATA-DESIGN.md` stale on card 5 (MEDIUM); AF-07 (a11y tooling gap) judged non-blocking for *this* diff's non-interactive surface — see below
🛑 none

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 | contract-drift-adjacent (1) |
| LOW | 0 | — |

## Detailed findings

### MEDIUM

#### F-1 — `DATA-DESIGN.md` §1 data-model table contradicts the shipped card-5 behavior
- Category: contract-drift (DATA-DESIGN.md, not a `docs/requirements/*.md` contract file in the
  strict sense the skill defines, but it is the normative data-model artifact this diff is
  supposed to honor, and it now doesn't match the diff it ships alongside)
- Path: `docs/features/OVW-01/DATA-DESIGN.md:21-22`
- Source: `DECISIONS.md` D-02 (2026-09-10 correction) vs. `DATA-DESIGN.md` (unrevised)
- Description: The table still reads `repos_with_harness_installed` → "card 5 ratio numerator, NOT
  format_number()" and `repos_total` → "card 5 ratio denominator" — the *pre-correction* design
  D-02 explicitly reversed. The shipped code (`_build_org_summary_cards`,
  `services/api/app/api/overview.py:223,227`) computes card 5 as
  `format_number(row.repos_with_harness_installed)` only — a plain count — and never reads
  `repos_total` anywhere in the route. `docs/requirements/api.md`, `DECISIONS.md`, `tasks.json`,
  and `test_overview_perf.py`'s/`test_overview.py`'s own comments all correctly state the corrected
  behavior; only `DATA-DESIGN.md` was missed when D-02 propagated. Confirmed via direct grep —
  `repos_total` has zero references in `app/api/overview.py`.
- Suggested fix: Update `DATA-DESIGN.md:21-22` to match `api.md`'s corrected wording — card 5 is a
  plain `format_number()` count of `repos_with_harness_installed`; `repos_total` is unused by this
  story's card-building logic (leave a one-line note that it exists on the row but isn't read here,
  so a future reader doesn't wonder why it's in the table at all).

## Six flagged areas — verified

1. **Step ordering (FR-3, AC-2 vs AC-7)** — genuinely robust, not merely first-by-coincidence.
   `get_org_summary` calls `org_access` → **unconditioned** `await freshness.get_last_successful_run()`
   → the rollup `SELECT`, with no branch or try/except between steps 2 and 3
   (`services/api/app/api/overview.py:294-300`). `test_org_summary_fully_fresh_database_still_raises_freshness_error_tc04`
   proves this with a call-count spy (`len(freshness_calls) == 1`) on a DB with **neither** row —
   not just a status-code assertion, which a rollup-first reordering could still satisfy by luck. A
   plausible "helpful" refactor (check rollup first, only call freshness on a miss) would fail this
   test immediately. Solid.
2. **`adoption_percent` null-not-zero** — holds everywhere checked. Backend: `ProgramsUsingAi.adoption_percent: float | None = Field(...)` is a *required* nullable (not defaulted), forcing every construction site to pass it explicitly (`org_summary.py:53-55`); `_programs_using_ai` sets `None` on the `row is None` branch and delegates the real case to `compute_adoption_percent` (not re-derived). Frontend: `AdoptionIndicator` does `data ?? {count:0,total:0,adoption_percent:null}` — an **object-level** default — then narrows on `adoption_percent === null` directly, never a per-field `??`/`||`. `AdoptionOverview` passes `result.data.programs_using_ai` through untouched. `overviewApi.ts`/`types/overview.ts` type it `number | null` with no coalescing anywhere in the fetch path. No leak point found.
3. **`get_freshness_accessor` DI seam** — sound, and the docstring's own justification checks out: it retires two independent monkeypatch variants (confirmed both `test_overview.py` and `test_overview_perf.py` now share one `_override_freshness_accessor`/`app.dependency_overrides[get_freshness_accessor]` mechanism, the same pattern already used for `get_db`). Still constructed per-request (R-04's accepted trade-off unchanged) — the change only makes the construction site swappable, it doesn't introduce caching, a singleton, or a new lifecycle hazard.
4. **`PersonaDashboardShell` widening / `program` reaching `ProgramContext`** — cannot happen. The header-region guard is `{!isLoading && program !== undefined && (...)}` (`PersonaDashboardShell.tsx:122`); `ProgramContext` is only reached inside that block, so an `undefined` `program` never reaches it. Verified against `PersonaDashboardShell.test.tsx`'s new OVW-01 D-04 cases (program-omitted → no `<header>`; program-provided → unchanged render) and confirmed the 6 pre-existing `SHP-01-TC-02` assertions are untouched.
5. **`redirect()` placement in `page.tsx`** — correct and, on inspection, more defensive than the docstring's own framing suggests: `redirect()` is only ever invoked inside `catch`, gated on `error instanceof SessionExpiredError`; every other error (including a stray `NEXT_REDIRECT` from elsewhere) falls to the `else` branch's `throw error`, so nothing is silently swallowed regardless of exactly where within the try/catch a future edit might move things. The real risk this guards against — a refactor that converts *all* caught errors into an in-page error render instead of re-throwing — is not present here.
6. **FR-2 colour-derivation test** — not trivially satisfiable. `AdoptionOverview.test.tsx`'s test asserts `serialisedFixture` (the fixture's own `JSON.stringify`) contains **none** of the hex/rgba literals actually found in the rendered DOM's `style` attributes, plus that the fixture itself contains no `#`/`rgba(`/the substring `"color"` at all. A test that only asserted "a colour is present" would pass whether the colour came from the wire or the client; this one would fail if any component started trusting a server-supplied colour field. Genuine proof of FR-2.

## Accessibility (AF-07) — explicit judgment, as requested

**Not a blocker for this diff.** The four new components ship zero interactive elements — no
buttons, links, inputs, or focus targets anywhere in `OrgSummaryCards`/`AdoptionIndicator`/
`OverviewErrorPanel`/`AdoptionOverview` — so keyboard-reachability and focus-order, the sharpest
edges of WCAG 2.2 AA, are structurally not-applicable to what actually shipped here. The one
place this story *could* have violated "color is not the sole indicator" (the adoption legend) pairs
every swatch with a count and a label in the same code path (`AdoptionIndicator.tsx`'s `<li>`
entries) — verified in source, not assumed. A rough contrast check on the two new tokens
(`#2a6fdb` vs. `#dfe3e9`, the two adjacent bar segments) comes out near 3.7:1, clearing the 3:1
non-text/UI-component bar. None of that constitutes automated proof, and AF-07's underlying gap
(no `axe-playwright`/`pa11y-ci` wired) is real — but escalating it to BLOCKED here would be
penalizing this story for a project-level tooling decision against a surface that has nothing for
a screen-reader/keyboard user to get stuck on. **This flips for OVW-02/03/04** (leaderboard,
filters, presumably links/sorting) — recommend the tooling decision lands before those, not before
this one ships.

## What went well

- Six-condition GO-WITH-CONDITIONS research verdict fully honored: Condition 1 (AUTH-03 caveat)
  carried into the route docstring, not silently dropped; Condition 2 (null-not-zero) enforced at
  the schema layer as a required-nullable field, not merely a convention.
- `AF-04`'s DI-seam fix retires two independent test workarounds in favor of one shared mechanism —
  exactly the kind of found-independently-by-two-workers signal that's worth accepting.
- D-02's mockup-vs-approved-PRD discrepancy (three separate points, not the two an earlier revision
  caught) was resolved by going back to the mockup's own sample-data script rather than trusting
  the already-approved PRD — and then propagated correctly into code, tests, and `api.md` (only
  `DATA-DESIGN.md` missed it, F-1 above).
- `OverviewErrorPanel`'s single generic message for forbidden/unauthorized/error is a deliberate,
  documented application of the same non-enumeration principle `security-baseline.md` applies to
  404-over-403 for foreign-owned resources.

## Recommendation

**PASS.** One MEDIUM (stale `DATA-DESIGN.md` table) — fix in this PR or immediately after; it is
documentation-only and has no runtime consequence, but it is a self-inconsistency within the diff's
own artifacts and should not linger. No HIGH/CRITICAL. All 7 already-triaged agent flags (AF-01
through AF-07) stand as recorded in `state.json`; none is re-opened here. AF-07 is judged
non-blocking for this specific diff's non-interactive surface, with an explicit recommendation to
close the tooling gap before OVW-02/03/04.
