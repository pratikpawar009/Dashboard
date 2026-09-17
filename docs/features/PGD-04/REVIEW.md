# Code Review — feature/PGD-04 (uncommitted working tree, vs origin/main)

- Date: 2026-09-17T00:00:00Z
- Mode: current (GATE MODE — report-only)
- Files reviewed: 18 (+1 unplanned: `apps/web/src/lib/programDetailApi.ts`; +1 stray untracked: `services/mcp-server/uv.lock`)
- Verdict: PASS WITH WARNINGS

## Executive summary

PGD-04 adds a fourth sibling route (`GET /program-detail/{program_id}/commands`) on the existing `overview` router, backed by a new `usage_events`-aggregating service that faithfully mirrors SHP-02's `personal_usage.py::fetch_commands_breakdown`/`_build_commands_panel` line-for-line (same query shape, same ordering/tiebreak, same `_build_commands_panel` helper), correctly swapping `WHERE user=` for `WHERE program_id=`. All four DECISIONS.md entries (D-01 data source, D-02 no-404, D-03 schema reuse, D-04 proxy-ahead-of-UI) are honored in code, not just asserted in prose — the D-01 differential-range guard (TC-05/#427) and the D-02 empty-shape tests are concrete, comparative assertions that would genuinely fail on a regression, not tautological status checks. The route handler's `program_visibility` gate placement matches its siblings exactly. Frontend proxy, fetcher, and TS types are new, unwired plumbing per D-04, with solid test coverage including a real no-token-leak assertion.

The one real defect is a leftover dead edit in `apps/web/src/lib/programDetailApi.ts` — an empty `import type {} from "@/types/programCommands"` plus a stray trailing blank line, in a file not in this story's `file_plan` at all, contradicting T-11's own recorded resolution (fetcher shipped correctly into the new `programCommandsApi.ts` per plan, not into `programDetailApi.ts`). This is unrelated, unused, and will very likely trip ESLint/TS. `tasks.json`'s F-13 (`project-commands.yaml` "modify") and its own T-11 `reason` field are now stale relative to what's actually in the diff.

🟢 strengths: faithful SHP-02 mirroring, self-witnessing log-absence test, comparative (non-tautological) differential-range and empty-shape tests, precise DECISIONS.md-to-code traceability, careful docstrings warning future maintainers off "fixing" D-02's asymmetry.
⚠️ warnings: dead code in an out-of-plan file; stale tasks.json bookkeeping (F-13, T-11 reason); untracked unrelated lockfile in the diff.
🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution                                              |
|----------|-------|--------------------------------------------------------------------|
| CRITICAL |   0   | —                                                                    |
| HIGH     |   0   | —                                                                    |
| MEDIUM   |   2   | scope-creep (1), testability/hygiene (1)                            |
| LOW      |   3   | scope-creep (1), documentation drift (1), design-pattern note (1)   |

## Detailed findings

### MEDIUM

#### F-1 — scope-creep: dead edit in a file outside the declared file_plan
- Category: scope-creep
- Path: `apps/web/src/lib/programDetailApi.ts:11-12` (added `import type {\n} from "@/types/programCommands";`), `:188` (added trailing blank line)
- Source: `docs/features/PGD-04/tasks.json` `file_plan` (no `F-NN` entry names `programDetailApi.ts`); `.claude/rules/surgical-changes.md` ("Touch only what the current task requires... Remove imports... YOUR changes made unused")
- Description: This file was edited but isn't in the file plan, and the edit that landed is dead: an empty named-import statement importing nothing from `@/types/programCommands`. T-11's own `reason` field ("F-10 path deviation recorded as AF-01 — shipped into shared programDetailApi.ts") describes an approach that was apparently abandoned mid-implementation — the actual `fetchProgramCommands()` correctly lives in the new, plan-conforming `apps/web/src/lib/programCommandsApi.ts` (F-10) instead. The empty import in `programDetailApi.ts` is a leftover fragment of the abandoned approach that was never cleaned up.
- Suggested fix: Revert the two hunks in `programDetailApi.ts` entirely (the empty import and the trailing blank line) — the file should be untouched by this diff. Separately correct T-11's `reason` field in `tasks.json` to state the fetcher shipped into `programCommandsApi.ts` per the original plan, with no deviation.

#### F-2 — testability/hygiene: `tasks.json` F-13 claims a file edit that never happened
- Category: testability (plan/state fidelity)
- Path: `docs/features/PGD-04/tasks.json` (F-13 `file_plan` entry, action `modify`, path `docs/config/project-commands.yaml`); confirmed via `git diff -- docs/config/project-commands.yaml` (empty)
- Source: `docs/features/PGD-04/tasks.json` `file_plan.F-13` vs actual diff
- Description: F-13 is declared as a `modify` action against `project-commands.yaml`, and T-14 is marked `"status": "done"` with `files_touched: []` and a `reason` explaining no edit was warranted. The task's own bookkeeping is internally consistent, but the `file_plan` entry's `action: "modify"` is now inaccurate — nothing in the shipped diff touches that file. This is a paperwork-only inconsistency (PLAN.md's own Docs/Config-drift gates correctly do not depend on F-13 being edited), not a functional defect.
- Suggested fix: Update F-13's `action` to `verify` (or equivalent no-op marker) instead of `modify`, so a future reader of `tasks.json` doesn't go looking for a diff that isn't there.

### LOW

#### F-3 — scope-creep: untracked, unrelated lockfile in the working tree
- Category: scope-creep
- Path: `services/mcp-server/uv.lock` (untracked)
- Source: `docs/features/PGD-04/tasks.json` `file_plan` (no entry); `.claude/rules/surgical-changes.md`
- Description: `services/mcp-server/uv.lock` is untracked and unrelated to any PGD-04 `F-NN`; it's not part of the FastAPI/Next.js work this story touches and looks like a local `uv sync` byproduct in a sibling package. Harmless if never committed, but worth flagging before staging.
- Suggested fix: Confirm it's not staged/committed with the PGD-04 changes; add to `.gitignore` if it's expected to regenerate locally, or commit separately if intentional infra housekeeping.

#### F-4 — documentation drift: `docs/stories/PGD-04.md` decision-log correction is good, but AC-1's earlier wording drift wasn't caught until now
- Category: contract-drift (self-corrected within this diff, informational only)
- Path: `docs/stories/PGD-04.md` (AC-1, Decision log entries dated 2026-09-17)
- Source: `docs/requirements/api.md#program-commands-api` (T-08 fill)
- Description: Not a defect — the story doc's own decision log transparently documents that earlier AC-1 wording (`run_count`/`total_run_count`) never matched the shipped wire names (`count`/`total_runs`), and corrects it in this same diff with a clear rationale tied to D-03. Recorded here only as a positive note for the review trail — no action needed.
- Suggested fix: N/A — already resolved correctly in this diff.

#### F-5 — design-pattern observation: D-03 cross-module schema coupling is honestly assessed, not hidden
- Category: design-patterns
- Path: `services/api/app/services/program_commands.py:21`, `services/api/app/schemas/personal_usage.py:6-10`
- Source: DECISIONS.md D-03
- Description: `program_commands.py` imports `CommandEntry`/`CommandsPanel` directly from `personal_usage.py`, creating a cross-feature schema dependency (SHP-02 owns the source module; PGD-04 is a second consumer). This is a recorded decision (D-03), not a violation — flagging only that it is a real coupling: SHP-02 can no longer change `CommandsPanel`'s shape without checking PGD-04's route/tests too. The co-consumer docstring note in `personal_usage.py` and the "extract only on third consumer" carry-forward are the right mitigation for now.
- Suggested fix: None required. If a third consumer of this shape appears, honor the carry-forward and extract `app/schemas/commands.py` at that point, not before.

## What went well

- `program_commands.py` mirrors `personal_usage.py`'s aggregation query, ordering/tiebreak, and `_build_commands_panel` helper exactly — no copy-paste drift found (verified line-by-line against `services/api/app/services/personal_usage.py:153-192`).
- The differential-range test (`test_differential_range_7d_vs_90d_totals_differ_tc05`) and the story e2e test both use explicit not-equal/value assertions on a shared seeded fixture — this is the correct shape to actually catch a D-01 regression (reading `program_commands` instead of `usage_events`), not two independent 200 checks.
- The structured-logging test (`test_structured_request_log_and_no_rbac_audit_event_tc17`) self-witnesses the known Alembic-fileConfig logger-disabling trap by positively asserting the completion log fires before asserting audit-event absence — matches the project's own prior lesson on this exact failure mode.
- Route handler placement of `program_visibility()` is consistent with all three sibling routes on the same router; the D-02 no-404 asymmetry is documented in both the module docstring and the function docstring, explicitly warning a future editor not to "fix" it by analogy with `/releases`.
- The Next.js proxy route test includes a genuine no-token-leak assertion (checks response headers and body for the sentinel token), not just status-code mapping.
- `docs/requirements/api.md` and `README.md` updates are precise, contract-complete, and correctly flag the D-01/D-02 asymmetries for downstream consumers (ARC-01/DEV-01/PMD-01/EMD-01).

## Recommendation

PASS WITH WARNINGS. No blocking defects — the aggregation logic, route wiring, decision compliance, and test suite are sound and the differential-range guard genuinely protects against the story's single highest-risk regression. Before merge: revert the dead edit in `apps/web/src/lib/programDetailApi.ts` (F-1) and correct `tasks.json`'s F-13 action / T-11 reason text (F-2) so the plan artefacts match what shipped. Confirm `services/mcp-server/uv.lock` isn't accidentally staged (F-3).
