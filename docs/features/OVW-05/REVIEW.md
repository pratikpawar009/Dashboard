# Code Review — feature/OVW-05 (working tree vs main)

- Date: 2026-09-11T07:34:27Z
- Mode: current (GATE MODE — report-only, dispatched by `/arh-implement` Validate ∥ Review gate)
- Source snapshot: `4fe4d04d`
- Files reviewed: 24 (13 modified + 2 renamed + 10 created; excludes pre-existing planning-phase changes noted below)
- Verdict: **PASS**

## Executive summary

OVW-05 wires `GET /api/me` into `/overview`, admits `cio` as a fifth persona, adds an org-header shell variant, a sign-out control, and a branded `/login` page (with the OAuth relay relocated to `/login/start`). The diff matches `PLAN.md`/`tasks.json`/`DECISIONS.md` almost exactly: every changed file traces to `file_plan` F-01..F-23 plus the two pre-approved AF-01 import-path fixes. All six scrutiny points in the dispatch (D-04 duplication bar, AC-8 no-persona-literal, NFR-Security no hardcoded `cio`, AC-12 sign-out placement, D-02 concurrency/redirect placement, contract-drift on `persona-shell`) verified clean against the actual code, not just the docstrings claiming them. `tsc --noEmit`, `eslint .`, and `vitest run` (167/167) all pass clean on the working tree.

🟢 Strengths: D-02's `Promise.all`-inside-original-`try`/`redirect`-in-`catch` placement is correct and load-bearing-comment-verified; AC-12's sign-out control is a true sibling of the `signedInUser` ternary; no persona-literal conditional exists in `PersonaDashboardShell.tsx`; `docs/requirements/api.md`'s contract update is additive per its own supersede-don't-rewrite precedent; test suite covers the two highest-risk ACs (AC-6 jobTitle-never-from-wire, AC-18 already-authenticated pass-through) with real decoy-key assertions.

⚠️ Warnings: none rising above LOW.

🛑 Blockers: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — |
| MEDIUM   |   0   | — |
| LOW      |   1   | design-patterns (1) |

## Detailed findings

### LOW

#### F-1 — design-patterns: `.orgPill`/`.visuallyHidden` geometry duplicated from `PersonaHeader.module.css` rather than shared
- Category: design-patterns
- Path: `apps/web/src/components/PersonaDashboardShell.module.css:118-131,152-163`
- Source: `DECISIONS.md` D-04 (accepted duplication of the JSX catch); the CSS duplication is a direct, necessary consequence of that same decision (a CSS Module cannot import a class from another CSS Module) and is explicitly commented as such in the diff.
- Description: `.orgPill`/`.orgPillNeutral`/`.visuallyHidden` restate `PersonaHeader.module.css`'s `.pill`/`.pillNeutral`/`.visuallyHidden` rules byte-for-byte. This is the CSS-side shadow of the already-accepted D-04 JSX duplication, not a new, undecided choice — flagging for completeness rather than as an unaddressed defect, since D-04's "revisit at the 3rd occurrence" carry-forward already covers it.
- Suggested fix: none required now; when a 3rd occurrence of this shape appears, extract both the JSX catch and its CSS together, per the existing D-04 carry-forward in `PLAN.md` § 6.

## What went well

- D-02 concurrency: `Promise.all` sits inside the original `try`, `redirect("/login")` stays in the `catch` only on `SessionExpiredError` — verified in `apps/web/src/app/overview/page.tsx:76-99`, not just asserted in the docstring.
- AC-12 sign-out placement: the `<form action="/logout">` block is a sibling of the `signedInUser ? … : …` ternary, both inside the single `{!isLoading && (…)}` gate (`PersonaDashboardShell.tsx:104-149`) — renders in both the populated and D-05 neutral-fallback branches, matching the story's own flagged-as-shipping-untested defect being closed correctly.
- AC-8/research condition C-7: grepped `PersonaDashboardShell.tsx` for `'cio'`/`"cio"` — the only hit is inside a docstring describing the constraint; the org-header variant is selected purely by `pageTitle !== undefined && program === undefined && !isLoading`.
- NFR-Security: `overview/page.tsx` never assigns a literal `"cio"` to `persona`; it is always `meResult.data.persona` or the `PERSONA_RESOLUTION_ERROR` sentinel.
- D-04: confirmed genuinely the 2nd occurrence — `PersonaHeader.tsx:18-43` (shipped, SHP-01) is the 1st; `PersonaDashboardShell.tsx`'s new `renderOrgHeaderContent()` (`:203-249`) reproduces the identical try/catch + neutral-badge + `aria-live` shape, matching the decision's own description exactly.
- Contract drift: `docs/requirements/api.md`'s `page_title_prop`/`sign_out_control` keys (new, additive) accurately describe the shipped selection rule and control markup — verified against the actual `PersonaDashboardShell.tsx` code, not just restated from `DESIGN.md`.
- Scope discipline: every changed/created file resolves to `tasks.json` `file_plan` F-01..F-23, except `ProgramDetailView.authFlow.test.tsx` and `tokenStore.security.test.ts`, both accounted for by `FLAGS.md` AF-01 (user-approved one-line import-path fix) — no unexplained file is touched. `services/api` has zero changes, matching the frontend-only `DATA-DESIGN.md` scope.
- T-10 relocation: `login/start/route.ts` diffed against the prior `login/route.ts` — only the docstring's `OIDC_REDIRECT_URI` claim changed; the handler body is byte-identical, per OVW-05-FR-2.
- Verification run (not just static read): `pnpm -C apps/web exec tsc --noEmit` clean, `pnpm -C apps/web exec eslint .` clean, `pnpm -C apps/web test` — 30 files / 167 tests passed.
- Known/accepted items correctly NOT re-raised: AF-01..AF-04, DQA-1 contrast carry-forward, D-04 CSS-side echo (folded into F-1 above rather than treated as new).

## Recommendation

**PASS.** No CRITICAL/HIGH/MEDIUM findings; one LOW (already effectively covered by the accepted D-04 carry-forward). Safe to proceed to the next gate.
