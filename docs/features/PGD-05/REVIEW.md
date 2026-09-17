# Code Review — feature/PGD-05 (working tree, snapshot 2e713654)

- Date: 2026-09-17T00:00:00Z
- Mode: branch (GATE MODE — report-only)
- Files reviewed: ~34 (git diff main, tracked) + 16 untracked under services/api / apps/web
- Verdict: PASS

## Executive summary

PGD-05 ships the project-team table (AC-1..8) and the per-member usage popup backend + frontend
(AC-9..12, including the previously chart-deferred AF-05 fix) cleanly. D-01's two-SELECT contract
is implemented and perf-spy-verified; the composite index lands consistently across the migration,
the ORM model, and the schema fixture (alembic-patterns three-way rule). The `member_in_program_visibility`
gate runs `program_visibility` first, short-circuits before any SHP-02 service call, and is proven
by an end-to-end 403-body test that asserts no personal-usage field leaks — not merely a spy on
call count. Zero edits to SHP-02's own route/schema/gate. `member_id` (an email) is threaded
through props only; no new logging or console output touches it. Frontend proxies apply no
caching and forward auth/denial statuses correctly. All 36 PGD-05-scoped unit tests pass locally
under `HARNESS_TEST_DB_SUFFIX=pgd05review`.

The `feature/PGD-05` branch's own commit history is planning-docs-only (`db058ef`); all code is
uncommitted working tree, per the task brief. Apparent scope-creep in `git diff main...HEAD`
(`docs/features/AUTH-03`, `ING-02`, `PGD-07` security-review backfills) is inherited branch
history from `fcdfaf9`, not PGD-05 work product — excluded from findings below.

🟢 Two-SELECT contract, RBAC gate ordering/logging, and index consistency all verified against
source, not just docstrings. Self-witnessing log assertions used correctly (avoids the
vacuous-log-assertion trap this project has hit before).
⚠️ Two low-severity documentation/consistency nits below.
🛑 None.

## Findings summary

| Severity | Count | Category distribution                          |
|----------|-------|--------------------------------------------------|
| CRITICAL |   0   | —                                                  |
| HIGH     |   0   | —                                                  |
| MEDIUM   |   0   | —                                                  |
| LOW      |   2   | testability (1), component-architecture (1)       |

## Detailed findings

### LOW

#### F-1 — testability: `program_team.py`'s `tokens = int(tokens or 0)` reassigns the loop variable's type mid-body
- Category: testability
- Path: `services/api/app/services/program_team.py:70-71`
- Source: `.claude/rules/reusability-baseline.md` (clarity/single-responsibility spirit — not a functional defect)
- Description: `for user_id, sessions, tokens in metrics_result.all(): ... tokens = int(tokens or 0)` shadows the unpacked `tokens` (a SQL `Decimal`/`None` from `SUM`) with an `int` in the same name. Correct today, but a future diff adding a line between the loop header and this reassignment risks using the un-coerced value.
- Suggested fix: rename the unpacked value (e.g. `raw_tokens`) before coercion, or coerce inline in the `ProgramTeamRow(...)` constructor call. Non-blocking — purely a readability guard.

#### F-2 — component-architecture: two client fetchers now exist for adjacent concerns with similar names
- Category: component-architecture
- Path: `apps/web/src/lib/programTeamApi.ts`, `apps/web/src/lib/programTeamApi.client.ts`, `apps/web/src/lib/memberUsageApi.client.ts`
- Source: FLAGS.md AF-04 (triaged, closed — noted here only as a documentation pointer, not a new finding)
- Description: The server/`.client` fetcher split matches shipped sibling precedent (`programCommandsApi` / `programTokenTrendApi`) and was explicitly triaged as correct in FLAGS.md. Recorded here only so a future reader of REVIEW.md (who may not read FLAGS.md) has the pointer.
- Suggested fix: none required — informational only.

## What went well

- D-01 (two SELECTs, merged in Python, active-in-range semantics) implemented exactly as decided; `tests/perf/test_program_team_perf.py`'s query-count spy enforces it mechanically, not just by convention.
- D-02/ADR-0016's index is declared consistently in the migration, `UsageEvent.__table_args__`, and `tests/fixtures/prd_8_4_schema.json` — satisfies the alembic-patterns schema-diff-gate rule.
- D-04's gate ordering (`program_visibility` before self-or-cio) is tested with an explicit ordering assertion (TC-10/TC-18), not just an outcome check, and AC-12 is proven with a real 403 response body inspection (`test_denied_response_body_has_no_personal_usage_fields_tc13`) rather than a mock-call-count proxy — stronger evidence than the plan required.
- `member_view_denied` (not `individual_view_denied`) is asserted via self-witnessing log capture, avoiding this project's known vacuous-log-assertion failure mode (Alembic `fileConfig` disabling app loggers).
- AF-05's chart-block fix (`DailyTokenPoint.tokens: int` additive field) is verified against the actual schema/service/test files, not taken on the flag's word — `value == format_number(tokens)` drift guard exists.
- `TokenAreaChart` extraction is a clean, minimal reuse (default `height=240` preserves the existing Program Detail render byte-for-byte; popup uses `180`) — no duplicate chart implementation.
- Design tokens added (`qa-engineer` persona color, `18px` modal radius, modal shadow/overlay) are each traced to the mockup and dated, consistent with `CLAUDE.md`'s design-system contract.
- Proxy routes apply no caching, scope every call to the resolved `program_id`/`member_id` from the request, and never forward the 403 body upstream-to-browser (AC-12 preserved through the proxy layer).

## Recommendation

PASS. No CRITICAL/HIGH/MEDIUM findings. The two LOW findings are non-blocking style/documentation notes. Proceed to `/arh-security-review` per the standard hand-off; no rework required first.
