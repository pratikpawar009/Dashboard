# Agent flags — OVW-04

Raised by implementation workers during `/arh-implement`. Triage with `/arh-human-review OVW-04`.

### AF-01: Pre-existing `tsc --noEmit` failure in a PGD-06 proxy test
- **status**: resolved (fixed in-session under explicit user authorization)
- **kind**: risky-pattern
- **raised by**: T-07
- **source**: `apps/web/src/app/api/proxy/program-detail/[program_id]/releases/route.test.ts:200`

`tsc --noEmit` fails with TS2559 — a `"bogus"` string argument checked against a typed
query-params object. Surfaced while running T-07's required typecheck, **not caused by OVW-04**:
the file is unmodified on this branch and was last touched by PGD-06's merge commit `7d928b7`
(#466), so the failure is already on `main`.

Not fixed inline per `.claude/rules/surgical-changes.md`. Carry-forward to the PR body; it will
also surface in the evidence pass's typecheck dimension, where it must be attributed here rather
than treated as an OVW-04 regression.

### AF-02: T-12's default-prop conflated "absent" with "failed" (fixed in-session)
- **status**: triaged — accepted, fix verified by code review round 2
- **kind**: bug
- **raised by**: T-13, fixed by the fix-loop
- **source**: `apps/web/src/components/AdoptionOverview.tsx`

T-12 defaulted the optional `programBoardResult` prop to `{status: "error"}`, so a caller that
simply omitted the prop rendered as a failed fetch. This regressed 4 pre-existing shipped tests,
including `overview/page.test.tsx`'s D-03 sentinel — a failed `GET /api/me` began rendering
"You don't have access to this view." instead of degrading to a neutral persona badge.

Root-caused and fixed: the default is removed; an omitted prop now renders no board region and no
error panel, while a genuine non-ok result still renders the error panel. Regression coverage
added in `ProgramLeaderboard.test.tsx`.

Recorded because the fix also required an **additive** change to a pre-existing shipped test file
(`overview/page.test.tsx`): T-12 added a third concurrent fetch that file never mocked. A
`vi.mock("@/lib/programBoardApi")` plus an "ok" default were added; no assertion was changed or
weakened. Worth an engineer's eye at triage to confirm that judgement.

### AF-03: evidence-na · task: n/a · docs/config/project-commands.yaml
`design_check` dimension marked N/A — source key `design_check:` is empty in
`docs/config/project-commands.yaml`. No accessibility/console-error-scan/perf tool has been
chosen or wired for this project yet (the file's own comment confirms this is deliberate, not an
oversight) — raised per the evidence-pass skill rather than fabricating a PASS or inventing a
tool at implementation time.

**Resolution (2026-09-18).** Fixed here as a **scoped exception** to
`.claude/rules/surgical-changes.md`, on the user's explicit instruction, because the inherited
failure blocked OVW-04's evidence gate. `buildRequest("bogus")` passed a bare string where the
helper takes `{range?, offset?, limit?}`; it now passes `{ range: "bogus" }`, preserving the
test's original intent (an invalid `range` value maps to 400 `invalid_range`, never a 502).
That file's 11 tests still pass, `tsc --noEmit` is clean, and the full 325-test suite is green.
Called out in the PR body as an unrelated fix carried to unblock the gate.

---

## Triage record — 2026-09-18, pre-commit

| Flag | Disposition |
|---|---|
| AF-01 | **Resolved.** Inherited TS2559 from PGD-06 (#466), fixed here under explicit user authorization as a scoped exception to `surgical-changes`. Typecheck clean; the affected test's 11 cases and the full 325-test suite pass. Called out in the PR body. |
| AF-02 | **Accepted.** T-12's default-prop defect was root-caused and fixed, with regression coverage in `ProgramLeaderboard.test.tsx`. Code review round 2 independently confirmed the fix removes the cause rather than special-casing the symptom, and that the additive edit to `overview/page.test.tsx` weakened no assertion. |
| AF-03 | **Accepted as N/A.** `design_check` is deliberately empty in `docs/config/project-commands.yaml` — no a11y/console-scan tool is wired for this project yet. This is the project's own documented state, not an OVW-04 gap. Remains a standing carry-forward until a tool is chosen and wired. |

Also carried forward, not fixed in this story:
- **WCAG AA chip contrast** (3.02–4.35:1) across the program-type and MoM chips — systemic to the
  design system's tint-on-tint recipe and already shipped in `ProgramContext.tsx` / `ReleasesList.tsx`.
  Accepted at the Product Gate; needs its own story since the fix is token-level.
- **Review findings F-1 / F-2** (both LOW, restated unchanged in round 2): the interim `console.info`
  telemetry in `ProgramCardLink.tsx:39` (D-06-sanctioned pending a real frontend sink), and the absent
  cache/TTL note on `program_summary` reads in `services/api/app/services/program_board.py`.
- **Pre-existing ING-10 perf test failures** in `services/api/tests/perf/` — unrelated to OVW-04.
