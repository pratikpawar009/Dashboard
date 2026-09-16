# Code Review — feature/PGD-03 (working tree vs HEAD/origin/main)

- Date: 2026-09-16T00:00:00Z
- Mode: story (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 25 (14 modified, 11 new; excludes `services/mcp-server/uv.lock`, unrelated lockfile noise)
- Verdict: PASS WITH WARNINGS

## Executive summary

PGD-03 adds a paginated releases endpoint and Program Detail panel. Backend and frontend both closely track DECISIONS.md: the shared `get_offset_limit`/`MAX_OFFSET_LIMIT` dependency is genuinely untouched (D-01), window parity is achieved by construction — `range_to_start` is called exactly once and the resulting `range_start` is reused unmodified in both the row query and the count query (FR-6) — the D-02 wire contract hoists `tagColor`/`tagBg` to the top level while D-03's status vocabulary correctly raises on an unknown `type` (contrast: the unrelated `_tag_colors_for_program` path correctly does NOT raise, falling back to `Migration`). ADR-0008's no-token-in-client-JS guarantee holds: `programDetailApi.client.ts`'s `fetchProgramReleases` has no token concept anywhere in it, matching its own docstring's claim, confirmed by reading the file rather than trusting the comment. Migration 007 / ORM `__table_args__` / schema fixture all agree (ADR-0015, alembic-patterns discipline). The contract doc (`docs/requirements/api.md`) and README are updated in the same diff — no contract-drift. Two test files outside the strict `tasks.json` file_plan were touched to fix newly-broken mocks in sibling test suites; the edits are minimal, mechanically necessary, and traceable to the F-19 mount, but they were never added to `tasks.json`'s `file_plan`, which is a real (if low-stakes) scope-declaration gap.

🟢 window-parity by construction, D-01/D-02/D-03 correctly and separately implemented, ADR-0008 token discipline holds, migration/model/fixture triad in sync, contract doc updated same-diff.
⚠️ two test files edited outside the declared file_plan (justified, undeclared); third `ProgramSummary` query per request is an accepted, documented tradeoff, not free.
🛑 none.

## Findings summary

| Severity | Count | Category distribution                          |
|----------|-------|-------------------------------------------------|
| CRITICAL |   0   | —                                                 |
| HIGH     |   0   | —                                                 |
| MEDIUM   |   1   | scope-creep (1)                                  |
| LOW      |   2   | performance (1), testability (1)                 |

## Detailed findings

### MEDIUM

#### F-1 — scope-creep: two test files edited without a `tasks.json` file_plan entry
- Category: scope-creep
- Path: `apps/web/src/components/ProgramDetailView.test.tsx`, `apps/web/src/components/ProgramDetailView.authFlow.test.tsx`
- Source: `docs/features/PGD-03/tasks.json` → `file_plan` (F-01..F-20; neither file appears)
- Description: Mounting `<ReleasesList>` in `ProgramDetailView.tsx` (F-19) breaks both test files' module-level `vi.mock("@/lib/programDetailApi.client", ...)` factories, since the new self-fetching child now needs `fetchProgramReleases` resolved or its effect throws. The fix (adding a `fetchProgramReleasesClientMock` alongside the existing mocks, and including its calls in the auth-flow file's "no Authorization leaked to client" assertion) is minimal, correctly scoped to only what broke, and mirrors the precedented pattern PGD-02's `DailyTokenTrendChart` mount used in the same files. The change itself is not objectionable — the gap is procedural: `tasks.json`'s `file_plan` has no `F-NN` entry for either file, so a scope-discipline read of the plan alone would flag these as unscoped edits.
- Suggested fix: Add two `file_plan` entries (e.g. F-21/F-22, action `modify`) for these files under the T-15 task, with reason "sibling test mock update forced by ReleasesList mount (F-19)" — a one-line retcon that makes the plan match what was actually necessary, for future scope-creep checks to pass cleanly without re-litigating the judgment call.

### LOW

#### F-2 — performance: third query per request (ProgramSummary lookup) for tag colors
- Category: Integration points / performance-baseline
- Path: `services/api/app/services/program_releases.py:52-63` (`_tag_colors_for_program`)
- Source: `.claude/rules/performance-baseline.md` ("No N+1 queries or unbounded fan-out reads")
- Description: The endpoint issues three queries per request (row fetch, count, `ProgramSummary` lookup for `tagColor`/`tagBg`) instead of two. This is a fixed one-extra-query-per-request cost, not per-row fan-out, so it does not violate the N+1 rule, and the module docstring explicitly documents the tradeoff. It is nonetheless a real third round-trip on every call to an endpoint whose own NFR-002 budget is ≤2s, and the perf test (`test_program_releases_perf.py`) measures end-to-end p95 including this query, so the budget claim is evidenced, not just asserted. No index was added for the `ProgramSummary` lookup by `program_id`, but `program_summary.program_id` is already the table's primary/unique key from earlier stories (unverified in this diff — the model wasn't touched here — but no new index gap was introduced).
- Suggested fix: No action required now; the perf test already covers this. If p95 later regresses, the first lever is caching `program_id -> (tagColor, tagBg)` at the request layer (it changes only when a program's `type` changes), not query restructuring.

#### F-3 — testability: `ProgramDetailView.test.tsx` mock uses a loosely-typed `(...args: unknown[])` signature diverging slightly from sibling mocks
- Category: Testability
- Path: `apps/web/src/components/ProgramDetailView.test.tsx:54-61`
- Source: `.claude/rules/reusability-baseline.md` (consistency of established idiom)
- Description: The new `fetchProgramReleases` mock is typed `vi.fn(async (..._args: unknown[]) => ...)`, while the pre-existing `fetchProgramDetail`/`fetchPrograms` mocks in the same file are untyped `vi.fn()`. Purely cosmetic — no behavioral risk — but introduces a second style for the same kind of mock inside one file.
- Suggested fix: None required; optional follow-up to align mock declarations if this file is touched again for an unrelated reason (per `surgical-changes` — not worth a dedicated edit now).

## What went well

- Window-parity (FR-6) is provably correct by construction, not just by test: `fetch_program_releases` computes `range_start` once and passes the identical value into both the `select(ProgramReleases)` and `select(func.count())` statements.
- D-01's clamp-not-reject pagination default is implemented via a story-local `_releases_offset_limit` wrapper that imports `MAX_OFFSET_LIMIT` from the shared `app/dependencies/pagination.py` rather than duplicating the literal `50` — `get_offset_limit` itself is verified untouched via `git diff`.
- D-02/D-03 are correctly kept separate: an unrecognized program `type` (tag colors) falls back silently to `Migration`; an unrecognized release `type` (status vocabulary) raises `ValueError` → 500. The backend's `_PROGRAM_TYPE_TAG_COLORS` table is byte-identical to the frontend's `programStyle.ts::PROGRAM_TYPE_COLORS`, including the deliberate omission of `Upgradation`.
- ADR-0008 (no access token reaches client JS): verified by reading `programDetailApi.client.ts` line-by-line — no `Authorization` header, no `getApiBaseUrl()`, no token parameter exists in that file's `fetchProgramReleases`; the proxy Route Handler resolves the token server-side via `callWithAuth`.
- Migration 007, `ProgramReleases.__table_args__`, and `tests/fixtures/prd_8_4_schema.json` were all updated together per alembic-patterns discipline (avoiding the BED-05 AF-09 failure mode cited in DECISIONS.md D-04).
- `docs/requirements/api.md`'s `program-releases-api` contract and `README.md`'s API table were both updated in this same diff — no contract-drift.
- `ReleasesList.test.tsx` includes a dedicated regression test for the D-02 top-level-vs-per-row tag hoisting decision.

## Recommendation

PASS WITH WARNINGS — one MEDIUM (undeclared-but-justified file_plan gap for two sibling test files) and two LOW findings, none blocking. Suggest the orchestrator record F-1 as a carry-forward to retcon `tasks.json`'s `file_plan` with the two additional test-file entries; no code change is required before merge.

## Carry-forward (for orchestrator)

- Add `tasks.json` `file_plan` entries for `apps/web/src/components/ProgramDetailView.test.tsx` and `apps/web/src/components/ProgramDetailView.authFlow.test.tsx` under T-15, documenting the mock updates forced by the `ReleasesList` mount (F-1 above).
- Known-accepted, not re-flagged: `program_releases` has no ingest producer (D-06, PLAN.md § 6 HIGH risk, explicit user direction); `design_check` tooling unwired project-wide (AF-03); Playwright browsers not installed (AF-04).
