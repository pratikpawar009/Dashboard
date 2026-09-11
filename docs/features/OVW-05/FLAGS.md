# OVW-05 — Agent flags

Observations raised by implementation workers during `/arh-implement`. Ids are
assigned by the orchestrator (single writer). Triaged by `/arh-human-review`.

### AF-01: T-10's relay relocation breaks two out-of-plan test files

- **kind**: risky-pattern
- **task**: T-10
- **source**: `apps/web/src/components/ProgramDetailView.authFlow.test.tsx:14`, `apps/web/src/lib/tokenStore.security.test.ts:169,356`
- **status**: triaged — resolved 2026-09-11 by user direction during `/arh-implement` Step 1

T-10 moved `apps/web/src/app/login/route.ts` → `apps/web/src/app/login/start/route.ts`
per OVW-05-FR-2. Two pre-existing AUTH-05-era test files import that handler
**directly by module path** rather than exercising it through navigation:

- `ProgramDetailView.authFlow.test.tsx:14` — `import { GET as loginGET } from "@/app/login/route"`
- `tokenStore.security.test.ts:169,356` — `await import("@/app/login/route")`

Both now fail to resolve (`TS2307`) and fail at test-run time. Neither file appears
in `tasks.json` `file_plan`, and T-10's own notes assert "No call-site edits anywhere
else" — the plan anticipated only the five `redirect("/login")` **URL** call sites that
T-13 guards, not direct **module-path** imports of the relocated file.

The fix is a one-line import-path update in each (`@/app/login/route` →
`@/app/login/start/route`); no assertion or behaviour change. Recorded here rather
than applied silently, because both files sit outside the PLAN.md scope.

**Resolution (user-directed, 2026-09-11).** The orchestrator surfaced this as a scope
question rather than widening the plan unilaterally. The user chose to fix the imports
now. Applied: `@/app/login/route` → `@/app/login/start/route` in both files — three
lines total, no assertion, fixture, or behaviour change. The five `redirect("/login")`
URL call sites that condition C-2(a) protects are untouched and remain guarded by T-13.

Recorded here because these two files sit outside `tasks.json` `file_plan`; they belong
in the PR body's `## Carry-forward` section as plan drift the DAG did not anticipate.

### AF-02: `PersonaHeader.tsx` docstring is stale about `cio`

- **kind**: risky-pattern
- **task**: T-03
- **source**: `apps/web/src/components/PersonaHeader.tsx:8-10`
- **status**: triaged — accepted as carry-forward 2026-09-11 by user direction

`PersonaHeader`'s docstring still states that a persona "not one of the **4** valid
personas … covers `'cio'`", framing a `cio` value reaching it as an invariant violation.
T-01 admitted `cio` as a fifth valid persona — `VALID_PERSONAS` includes it and
`formatPersonaTag("cio")` no longer throws — so the premise is now false.

The equivalent stale text in `formatPersonaTag.ts` and `PersonaDashboardShell.tsx` WAS
corrected (AC-4 and AC-11 own those two files). `PersonaHeader.tsx` carries the same
premise but is not in this feature's `file_plan` (F-01..F-23), and DECISIONS.md D-04
explicitly directs this story not to edit it. So no task owns the fix.

Comment text only — no behavioural defect. `PersonaHeader` degrades correctly for any
unresolvable persona regardless of what its docstring claims, and `cio` now simply takes
the valid path. Carry-forward for whichever story next touches that file.

### AF-03: `design_check` evidence dimension is N/A — no tool wired

- **kind**: evidence-na
- **task**: evidence-pass
- **source**: `docs/config/project-commands.yaml`
- **status**: triaged — accepted as carry-forward 2026-09-11 by user direction

`design_check:` is empty in `docs/config/project-commands.yaml`. No automated
accessibility, visual-diff, or console-error tool has been chosen or installed for the
`html-mockup` design provider, so the dimension cannot run and is recorded N/A rather
than PASS.

This is a standing project-level gap, not an OVW-05 defect — the same N/A every story in
this repo has hit. It matters slightly more here because OVW-05 ships two brand-new
interactive controls (sign-out, SSO) carrying the codebase's **first** `:focus` rules, and
`DESIGN.md` § Design QA records one inherited AA contrast failure now reaching a pre-auth
surface (carry-forward DQA-1). Please confirm the N/A.

### AF-04: runtime evidence proves boot, not render

- **kind**: evidence-na
- **task**: evidence-pass
- **source**: `docs/config/project-commands.yaml`
- **status**: triaged — accepted as carry-forward 2026-09-11 by user direction

The `runtime` dimension PASSed on route status codes and clean boot logs: `/login` → 200,
`/login/start` → 307 relay to Keycloak, `/overview` → 307 → `/login` with no session, api
`/health` → 200. That is genuine evidence the routing split works.

It is **not** evidence that the DOM mounted the elements `DESIGN.md` specifies. No E2E or
browser tool is installed (`test_e2e:` empty; ADR-0001 declares none), so nothing asserted
that the branded card, the org header, or the sign-out control actually paint. The vitest
component tests cover that at the unit level, but not in a real browser.

Recommend `/arh-human-review` eyeball `/login` and `/overview` before merge.


---

## Triage record (2026-09-11)

All four flags are triaged; none blocks commit-PR.

| Flag | Decision |
|---|---|
| AF-01 | **Fixed.** User directed the import-path update; applied in both files. |
| AF-02 | **Accepted as carry-forward.** Comment text only; D-04 bars this story from editing `PersonaHeader.tsx`. |
| AF-03 | **Accepted as carry-forward.** `design_check` N/A confirmed — no a11y/visual tool wired project-wide. |
| AF-04 | **Accepted as carry-forward.** Runtime evidence is boot + route status, not render; no E2E tool exists (ADR-0001). A human visual check of `/overview` before merge is recommended, not required. |

Each is mirrored into `state.json.pending_carry_forward` and restated in the PR body.
