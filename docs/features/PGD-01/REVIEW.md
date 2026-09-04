# Code Review — feature/PGD-01

- Date: 2026-09-04T04:45:41Z
- Mode: story (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate)
- Snapshot: ee5ad949ab357738
- Files reviewed: 13 modified + 27 untracked (backend: 7, frontend: 23, docs/config: 3) — excludes `.claude/agent-memory/`, `.claude/worktrees/`, `services/api/.claude/`, `docs/activity/activity.jsonl` per instruction.
- Verdict: **PASS**

## Executive summary

PGD-01 ships the Program Detail page shell (`GET /api/overview/program-detail/{program_id}` + `/programs/[program_id]`) with unusually tight traceability: every field, token, and test assertion cites the ADR/DECISIONS.md/DESIGN.md entry it implements. ADR-0007's `{header, summary[7]}` contract is implemented byte-exact (glyph/label constants, card-4 ratio exemption, `format_number()` arithmetic verified by hand against the test fixtures). AC-6 byte-identical-across-personas is enforced by an AST walk (not a substring grep) proving no `current_user.role`/`.persona` access in `overview.py`. `program_visibility` is called once, with the real `program_id`, no membership filter (C-3 honored). CORS/perf/a11y/log-PII checks all pass. The three undeclared-in-PLAN files (`test_auth_cors.py`, `apps/web/.gitignore`, the `.backLinkRow` cleanup) are legitimate, disclosed consequences of in-scope tasks, not scope creep. AF-01..AF-07 remain open exactly as raised — none contradicted, none newly discovered as incorrect.

🟢 strengths: ADR/contract fidelity, AST-based persona-branch test, out-of-order switch-reload guard, byte-exact design tokens, honest perf-budget test (not loosened to pass).
⚠️ warnings: two LOW test/a11y observations below; CF-05's `harness carry-forward resolve` command still needs to be run post-merge.
🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 2 | testability (1), component-architecture/a11y (1) |

## Detailed findings

### LOW

#### F-1 — testability: keyboard-activation tests don't structurally prove Enter/Space triggers the action
- Category: testability
- Path: `apps/web/src/components/ProgramSwitcher.test.tsx:66-73`, `apps/web/src/components/ProgramDetailView.test.tsx:237-244`
- Source: review instruction item 7 (test quality)
- Description: Both tests fire `keyDown("Enter"/" ")` immediately followed by a manual `fireEvent.click(trigger)` and assert on the click's effect, not the keydown's. jsdom does not synthesize a click from a button's native Enter/Space default action, and the test comments say so — but that means the assertion trusts native `<button>` semantics rather than exercising them. Real-browser risk is low (native `<button>` guarantees this), so this doesn't block, but a future regression that swapped the trigger for a non-native focusable element (e.g. a styled `<div role="button">`) would pass this suite unchanged.
- Suggested fix: N/A now — accept as a `@testing-library/user-event`-shaped gap (D-09 declined that dependency). Worth a one-line carry-forward if `user-event` is ever added for another story, to backfill a real keyboard-activation assertion here.

#### F-2 — component-architecture: "Switch program" label isn't programmatically associated with the trigger
- Category: component-architecture
- Path: `apps/web/src/components/ProgramSwitcher.tsx:74-85`
- Source: `.claude/rules/accessibility-baseline.md` ("every interactive element ... has an accessible name")
- Description: The visible `Switch program` `<span>` sits outside the `<button>` with no `aria-labelledby`/`htmlFor` link. The button already has an accessible name from its own text content (current program name + caret), so this is not a WCAG violation, but a screen-reader user tabbing to the control hears the program name, not the "Switch program" affordance label — DESIGN.md Region 3 treats that label as the control's caption.
- Suggested fix: Add `aria-labelledby` pointing the button at the label span's `id` (additive, no visual change), or `aria-label="Switch program"` supplementing the visible text.

## What went well

- ADR-0007 fidelity verified line-by-line: `_SUMMARY_CARD_GLYPHS_LABELS` order/glyphs/labels match DESIGN.md Region 4 exactly; `format_number()` arithmetic hand-checked against TC-01's fixture values (2,500,000→"2.5M", 8,500→"8.5K", 125,000→"125.0K") — all correct.
- `docs/requirements/api.md#program-detail-api` updated in the same diff as the surface it documents — no contract drift.
- `program_visibility(current_user, program_id)` called once with the real id, never filters by `current_user.programs` — C-3 honored; confirmed against `app/core/rbac.py`'s own docstring contract.
- TC-01's no-persona-branch assertion walks the AST (`ast.parse` + `ast.Attribute` check) rather than grepping raw text — immune to false positives from the module's own prose docstring.
- TC-04 is an honest performance test: budget breach is reported via `print()`+assertion message, never silently loosened; single-SELECT budget enforced via a real `before_cursor_execute` spy, not an approximation.
- `ProgramDetailView`'s `latestSwitchRequestId` ref guards against out-of-order switch-reload responses (performance-baseline "no silent races" spirit) — genuinely tested (test asserts `router.replace` receives the final id).
- Every fetch call sets an explicit 5s timeout (`AbortSignal.timeout`) — performance-baseline's "I/O has explicit timeouts" honored on the one new frontend network boundary.
- CSS module values for all four regions are byte-identical to DESIGN.md's quoted tokens (spot-checked every literal in Regions 1–4); `.typeChip` matches `ProgramContext.module.css`'s existing recipe exactly, per D-05's cross-component consistency intent.
- The three plan-absent files (`test_auth_cors.py`, `apps/web/.gitignore`, dead `.backLinkRow` CSS) are each a necessary, disclosed side effect of an in-scope task (D-07's CORS header, F-32's `.env.example` unstageable-without-it, AF-05's re-nesting) — not scope creep.
- AUTH-04's `href` fix (D-04, T-04) lands as its own isolated two-file diff exactly as decided, independently reviewable.

## Recommendation

**PASS.** No CRITICAL or HIGH findings; the two LOW items are non-blocking polish, not defects. Proceed past the gate. Post-merge action (not a review blocker): run `harness carry-forward resolve --for AUTH-04 CF-05` now that T-04's fix has landed in this diff — `docs/features/AUTH-04/state.json`'s CF-05 entry has no `resolved_at`/status field yet.
