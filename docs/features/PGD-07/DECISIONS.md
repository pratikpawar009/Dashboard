# PGD-07 — Decisions

Decision log for Program Detail brand bar (shell retrofit). Both entries are feature-local — this
story composes frozen, already-shipped contracts (`session-identity-api`, `persona-shell`) and
introduces no new schema, dependency, or cross-service surface.

### D-01: Reuse OVW-05's `PERSONA_RESOLUTION_ERROR` sentinel literal, not a new symbol · blast:feature · rev:mechanical · adr:—

**Context**: FR-3 requires a non-guessed placeholder value for `persona` when `GET /api/me` does not
return `status: "ok"`. OVW-05 already defined a local `const PERSONA_RESOLUTION_ERROR =
"persona-resolution-error"` in `overview/page.tsx` and `PersonaDashboardShell.test.tsx` already
exercises that exact literal via its `PersonaTagError` catch path. Two options: export the constant
from a shared module for both pages to import, or re-declare the same literal locally in
`programs/[program_id]/page.tsx`.

**Decision**: Re-declare the identical local `const PERSONA_RESOLUTION_ERROR =
"persona-resolution-error"` in `programs/[program_id]/page.tsx` (T-01), matching OVW-05's own
module-local placement rather than extracting a shared constant. Two call sites sharing one literal
string is not yet the third repetition that justifies extraction
(`.claude/rules/reusability-baseline.md`); `PersonaDashboardShell`'s `PersonaTagError` catch is
structural (any unresolvable string triggers it), so the two pages do not need to import from a
common source to stay correct — only to stay byte-identical, which the shared test assertion in T-08
enforces instead.

### D-02: Page-level test harness structurally mirrors `overview/page.test.tsx` · blast:feature · rev:mechanical · adr:—

**Context**: `programs/[program_id]/page.tsx` has no existing page-level test file (unlike
`overview/page.tsx`, which OVW-05 added `app/overview/page.test.tsx` for). PGD-07 adds the first
`Promise.all`/`callWithAuth`/`SessionExpiredError` composition test for this route, and a competent
reviewer could reasonably choose to test only through `ProgramDetailView` (component-level, as
`ProgramDetailView.test.tsx` and `ProgramDetailView.authFlow.test.tsx` already do) rather than adding
a page-level harness.

**Decision**: Add `apps/web/src/app/programs/[program_id]/page.test.tsx` (T-08), mirroring
`overview/page.test.tsx`'s exact mocking idiom — `callWithAuth` replaced with a fake that invokes the
real `makeRequest`, `SessionExpiredError` re-exported via `importOriginal`, `next/navigation`'s
`redirect()` mocked to throw and assert-called. This is the only place FR-1/Condition C-4 (the
coordinated-redirect behavior across both concurrent fetches) can be exercised — `ProgramDetailView`
never imports `meApi`/`fetchMe` or issues its own fetch, so a component-level test cannot reach the
`Promise.all` coordination logic at all.
