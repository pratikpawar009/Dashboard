# Code Review — feature/PGD-07

- Date: 2026-09-16T12:17:00Z
- Mode: branch (GATE MODE — report-only, dispatched from `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 7 (6 modified, 1 new)
- Verdict: PASS WITH WARNINGS

## Executive summary

PGD-07 wraps `ProgramDetailView` in the existing `PersonaDashboardShell` and adds a concurrent `GET /api/me` fetch in `page.tsx`, giving Program Detail the same brand bar, identity block, and sign-out control every other dashboard page already has. Implementation matches PLAN.md/DECISIONS.md closely: D-01 (sentinel reuse) and D-02 (page-test harness mirroring `overview/page.test.tsx`) are both honored verbatim, all four research conditions (C-1..C-4) have dedicated, correctly-targeted tests, and ADR-0008 (no access token to client JS) holds — `ProgramDetailView` is a Client Component but only receives the already-composed `persona`/`SignedInUser` strings, never a token or raw `/api/me` payload. The one authorized scope deviation into `PersonaDashboardShell.tsx` (AF-01, fixing AC-5's badge/`aria-live` unreachability on this route) is structurally sound: the added guard (`personaColor === null && program === undefined && pageTitle === undefined`) is mutually exclusive by construction with both existing header-region gates, so no double-render is possible, and it reuses existing CSS classes (`.orgPillNeutral`, `.visuallyHidden`) rather than introducing new ones. Full suite (184/184) and `tsc --noEmit` pass clean, independently re-run.

🟢 the AF-01 shell fix is minimal, exhaustively guarded against the double-render it explicitly warns about, and is proven safe by both existing OVW-05/SHP-01 regression tests and new inverted assertions
🟢 D-01/D-02/C-1..C-4 all honored with correctly-scoped tests, not just declared
⚠️ the badge/announcement copy is now duplicated in three places in one file with no shared helper — accepted per `reusability-baseline`'s "third repetition" rule but worth a MEDIUM flag for whoever adds a fourth consumer
⚠️ AF-01's blast radius (editing an OVW-05/PRD-frozen file) is real, even though authorized and well-executed — recorded as scope-creep at MEDIUM given the explicit authorization on file, not HIGH/CRITICAL
🛑 none

## Findings summary

| Severity | Count | Category distribution                                    |
|----------|-------|------------------------------------------------------------|
| CRITICAL |   0   | —                                                            |
| HIGH     |   0   | —                                                            |
| MEDIUM   |   2   | scope-creep (1), design-patterns (1)                        |
| LOW      |   1   | testability (1)                                              |

## Detailed findings

### MEDIUM

#### F-1 — scope-creep: `PersonaDashboardShell.tsx` modified despite REQUIREMENTS.md § Scope "Out:"
- Category: scope-creep
- Path: `apps/web/src/components/PersonaDashboardShell.tsx:106-135`
- Source: `docs/features/PGD-07/REQUIREMENTS.md` § Scope "Out:" ("Any change to `PersonaDashboardShell.tsx` ... all consumed as-is, frozen contracts") vs. `docs/features/PGD-07/FLAGS.md` AF-01
- Description: This file is outside `tasks.json`'s `file_plan` (F-01..F-07 cover only `page.tsx`, `ProgramDetailView.tsx`/`.test.tsx`, `page.test.tsx`, `PersonaDashboardShell.test.tsx`, `composeSignedInUser.test.ts` — the shell's own implementation file is not among them) and outside REQUIREMENTS.md's declared scope. FLAGS.md AF-01 documents explicit user authorization for this exact widening (AC-2/AC-5 being jointly unsatisfiable without it), and the fix itself is well-scoped: 28 added lines, guarded to fire only where no header region mounts, verified to not regress OVW-05/SHP-01 (184/184 tests green, including the two regression suites AF-01 names). Rated MEDIUM rather than HIGH because the authorization is on record and the blast radius was independently re-verified in this review (guard logic re-derived by hand, full suite re-run), not because the deviation is costless — it does touch an OVW-05-owned, PRD-frozen file, and AF-01 itself flags a carry-forward for that file's owner.
- Suggested fix: None required to merge — already the minimal correct fix per this review's independent check. Carry-forward (already captured in AF-01): if `PersonaDashboardShell`'s header regions are ever refactored, the identity-block fallback guard at line 122-124 must be revisited alongside them.

#### F-2 — design-patterns: badge/announcement JSX now triplicated with no shared helper
- Category: design-patterns
- Path: `apps/web/src/components/PersonaDashboardShell.tsx:122-135` vs. `:264-275` (`renderOrgHeaderContent`'s catch) vs. `PersonaHeader.tsx`'s own catch (not in this diff)
- Source: `.claude/rules/reusability-baseline.md` ("Three similar lines is better than a premature abstraction. Extract on the third repetition, not the first.")
- Description: The "Persona unavailable" badge + `aria-live="assertive"` announcement markup is now written three times in the persona-shell surface (identity-block fallback added here, `renderOrgHeaderContent`'s inline catch, and `PersonaHeader`'s own catch). This diff's addition is the third occurrence, which is exactly the rule's stated extraction trigger — not a violation yet, but the next touch to this markup is.
- Suggested fix: No action needed in this PR (rule permits the third repetition as-is). Flag for the shell's owner (OVW-05) as a follow-up: extract a small `<PersonaUnavailableBadge />` shared by all three call sites so a future copy edit can't drift between them the way `AF-01`'s own writeup mentions as a live risk.

### LOW

#### F-3 — testability: `page.test.tsx` NFR-performance assertion uses a real timer window
- Category: testability
- Path: `apps/web/src/app/programs/[program_id]/page.test.tsx:184-189`
- Source: `.claude/rules/pytest-patterns`-equivalent testability dimension (no direct rule citation; general flakiness risk under CI load)
- Description: `PGD-07-NFR-performance-TC-01` asserts `Math.abs(programDetailResolveTime - meResolveTime) < 10` using real `setTimeout`/`Date.now()` rather than fake timers. The test acknowledges this tradeoff in its own comment ("generous bound avoids test flakiness"), and it passed cleanly in this review's run, so this is a LOW note rather than a blocking issue.
- Suggested fix: Consider `vi.useFakeTimers()` if this test becomes flaky under CI load in the future; not required now.

## What went well

- D-01/D-02 traced and verified against the actual diff, not just cited in DECISIONS.md — both hold exactly as described.
- All four research conditions (C-1 decoy-jobTitle non-cio persona, C-2 sign-out-in-both-branches under Program Detail's exact prop shape, C-3 persona-parameterized jobTitle/colour, C-4 coordinated-redirect code comment) have tests that actually exercise the condition, not just a test with a matching name.
- ADR-0008 verified by inspection: `fetchMe`/`meApi` calls happen only in the server-side `page.tsx`; the client `ProgramDetailView` receives only derived display strings.
- AF-01's guard was independently re-derived (not taken on faith) and confirmed mutually exclusive with both pre-existing header-region gates — no double-render is possible by construction, and the regression suites it claims to protect (SHP-01-TC-02, OVW-05 AC-8/9/10) are present and passing.
- Full vitest suite (184/184, 31 files) and `tsc --noEmit` re-run clean by this review, independent of the implementation's own reported numbers.

## Recommendation

PASS WITH WARNINGS. No CRITICAL or HIGH findings — ship as-is. Two MEDIUM findings are non-blocking: the authorized `PersonaDashboardShell.tsx` scope widening (F-1) is already minimal and verified safe, and the badge-markup triplication (F-2) is a legitimate but non-urgent extraction opportunity for OVW-05's owner. Surface both in the PR body as warnings; no fix loop required.
