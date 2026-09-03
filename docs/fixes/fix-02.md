# FIX-02 — close the remaining coverage gaps in SHP-01's merged code

- Date: 2026-09-03
- Input: gaps remaining across the implemented stories, after a manual smoke run of all ten
- Branch: `bugfix/FIX-01-session-identity`
- For feature: SHP-01

## Scope decision — the backend had no gaps to close

The smoke run listed several modules as "not exercised": `rollup_compute`, `guardrail_compute`, the
AUTH-03 RBAC checks, `/activities` pagination. Checking before fixing, every one of them already has
real coverage — `rbac` across 5 test files including a perf suite, `persona_resolver` across 8,
`ingest_auth` 3, `freshness` 2, `rollup_compute` and `guardrail_compute` 1 each, and `/activities`
via `tests/unit/test_pagination.py` (BED-02 owns that route). Those were gaps in the **smoke run**, not
in the code. 431 backend tests pass and nothing there was touched.

That left SHP-01 as the only implemented story with genuine gaps.

## Root cause

**A deferral whose stated reason did not apply produced two untested code paths, because
`docs/test-cases/SHP-01.json` justified skipping FR-3 as "initials derivation depends on the same
unlanded `signedInUser.name` shape as FR-1" when `deriveInitials(name: string)` takes a plain string
and has no dependency on the prop shape, field name, or the AUTH-01 amendment at all.**

`deriveInitials.ts` was consequently the only SHP-01 source file with no direct test. Separately,
`getProgramStyle` was covered only indirectly, through a rendered `ProgramContext`, and only for types
that exist in `tokens.md` — so its unknown-type fallback branch, the fail-soft counterpart to
`formatPersonaTag`'s fail-loud throw, had no coverage, and neither did REVIEW.md F-3's shared object
reference.

FR-1's deferral, by contrast, is sound: its prop shape really does ride the amendment, so it stays
uncovered and is still listed in `coverage_audit.uncovered`.

## Fix

Two new test files plus one small source change:

- `apps/web/src/lib/deriveInitials.test.ts` (`SHP-01-TC-05`) — the four mockup identities, >2-token
  names, lower-case input, whitespace runs, and the single-token assumption logged in
  `docs/stories/SHP-01.md` § Decision log. Empty/whitespace input is asserted as *documenting current
  behaviour*, explicitly labelled unspecified, so a future decision is free to change it.
- `apps/web/src/lib/programStyle.test.ts` (`SHP-01-TC-06`) — all four `tokens.md` pairs asserted
  against the token values rather than the function's own output, the unknown-type Migration fallback,
  and the never-throws contrast with `formatPersonaTag`.
- `apps/web/src/lib/programStyle.ts` — **REVIEW.md F-3 closed.** `avatarStyle` and `typeChip` were one
  object aliased into both keys; they are now two independent objects with identical values. Harmless
  while both were only read, but a caller mutating either mutated both.

`docs/test-cases/SHP-01.json` records TC-05/TC-06, moves FR-3 to covered with the reasoning above, and
notes that the two cases exceed the original ≤4 cap deliberately — they cover already-merged code
rather than widening story scope.

Files:
- `apps/web/src/lib/deriveInitials.test.ts` (new)
- `apps/web/src/lib/programStyle.test.ts` (new)
- `apps/web/src/lib/programStyle.ts`
- `docs/test-cases/SHP-01.json`
- `docs/features/SHP-01/state.json`

## Regression test

The F-3 source change is locked by `programStyle.test.ts` → "returns independent objects for
avatarStyle and typeChip", **confirmed to fail against the pre-fix aliased implementation** (1 failed /
32 passed) and pass after (33 passed). The two new suites are themselves the coverage, so they have no
separate regression pair.

## Evidence

typecheck ✓ (0 errors) · unit ✓ (33/33 web, up from 16; api 431/431 untouched) · lint ✓ (0 errors) ·
compile ✓ (`next build` — Compiled successfully)

## Gaps deliberately left open

- **`SHP-01-FR-1`** — populated-identity render. Genuinely rides the AUTH-01 amendment; deferral stands.
- **`SHP-01-icon-field-mockup-mismatch`** (REVIEW.md F-1, HIGH) — you chose to carry this forward
  because correcting it amends an approved PRD (FR-4) and a certified story. Not reversed here.
- **`SHP-01-mockup-contrast-below-AA`** — 13 of 22 pairs below their WCAG bar, all inherited from the
  mockups. A design decision, not a code fix.
- **`R-01` / `R-02`, `AF-05-carry`, `AF-07-carry`** — unowned future work or unverifiable until the
  consuming pages exist; none is a defect in merged code.
- **`RCA-01`** — the rollup-rebuild IntegrityError. Architectural (DB schema + contradicts
  `BED-01/DATA-DESIGN.md:22`); routed to `/arh-intake`, see `docs/fixes/RCA-01.md`.
- **AUTH-01's real token exchange / refresh success path** — needs interactive Keycloak credentials.
