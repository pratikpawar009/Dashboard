# Code Review — feature/PGD-02 (diff vs origin/main)

- Date: 2026-09-16
- Mode: story (GATE MODE — report-only), round 2
- Files reviewed: 27 (14 modified + 13 new, per `git diff origin/main --name-status` + untracked)
- Verdict: PASS WITH WARNINGS

## Executive summary

Round 1 found the PGD-02 implementation itself clean (zero CRITICAL/HIGH in the feature's own code, no ADR violations, no contract drift, D-01..D-05 honoured) but BLOCKED on two findings in `.mcp.json`: a CRITICAL literal GitHub PAT and a HIGH scope-creep (that file traces to no PGD-02 task). Both are now resolved — `.mcp.json` is absent from `git status --porcelain` and `git diff origin/main -- .mcp.json` is empty, confirmed independently this round, not assumed. Round 2 re-verified every item the brief flagged rather than trusting round 1's write-up at face value: the `test_format.py` allowlist is still filename-scoped and the underlying identifier check still fires; `formatTokens` correctly avoids the mockup `fmtM` billions-scale defect across boundary values; ADR-0008 token isolation holds end-to-end in the proxy/client split; the backend service is a single grouped SELECT with correct fixed-divisor `avg_per_day` and inclusive zero-padding; every changed file traces to a `file_plan` entry (F-01..F-21).

The only remaining item is the LOW-severity untracked `services/mcp-server/uv.lock`, left over from a prior unrelated commit. It is not in PGD-02's `file_plan`, and since the commit stages only `file_plan` paths it will not be swept into this story's commit. Disposition accepted — non-blocking, informational only.

🟢 strengths: correct zero-padding/avg math, correct frontend formatting fix, ADR-0008 honored, single grouped SELECT, explicit I/O timeouts, contract fully filled, scoped test-guard exception well-justified, prior CRITICAL/HIGH fully resolved.
⚠️ warnings: stray untracked `services/mcp-server/uv.lock`, unrelated to PGD-02, will not be staged.
🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution        |
|----------|-------|-------------------------------|
| CRITICAL |   0   | —                              |
| HIGH     |   0   | —                              |
| MEDIUM   |   0   | —                              |
| LOW      |   1   | scope-creep (1)                |

## Detailed findings

### LOW

#### F-1 — scope-creep: stray `services/mcp-server/uv.lock`
- Category: scope-creep
- Path: `services/mcp-server/uv.lock`
- Source: `tasks.json` `file_plan` (F-01..F-21) — not listed; unrelated to PGD-02's `services/api`/`apps/web` surface
- Description: Untracked lockfile left over from a prior, already-merged commit (`feat(mcp): add push_manifest tool...`) sitting in the working tree. Not part of any PGD-02 task. Confirmed not git-ignored and not staged by anything in this diff; the commit that lands PGD-02 stages only `file_plan` paths, so this file will not ride along.
- Suggested fix: No action required for PGD-02 to merge. Commit it separately under its own MCP-server-scoped change, or clean it from the working tree, whenever convenient.

## What went well

- `.mcp.json` fully reverted to `${GITHUB_TOKEN}` — verified via empty `git diff origin/main -- .mcp.json` and absence from `git status --porcelain`, not assumed from the round-1 narration.
- `_zero_padded_points` correctly implements the inclusive `num_days`-day window (R-01) and never omits a sparse day (R-02).
- `avg_per_day = round(period_total / num_days)` matches D-03 exactly (fixed range length, not days-with-data) — traced through `range_to_start`'s fixed `_RANGE_DAYS` map.
- Single grouped `SELECT ... GROUP BY date_trunc('day', date)` — no N+1, backed by the existing composite index leading column, matches DATA-DESIGN.md § 8.
- `formatTokens` in `DailyTokenTrendChart.tsx` correctly buckets raw token counts (bare int < 1,000; K at 1,000, 1dp; M at 1,000,000, 2dp; no B bucket) — re-verified against the mockup's `fmtM` millions-scale trap; 1,200 renders "1.2K", not "1.20B". Boundary values (999/1000/999999/1000000) covered in `DailyTokenTrendChart.test.tsx`.
- ADR-0008 honored end-to-end: `programTokenTrendApi.client.ts` has zero token concept, no `Authorization` header, no `tokenStore`/`next/headers` import, and calls only the same-origin proxy; `programTokenTrendApi.ts` (server-only) and the proxy Route Handler are the only places the bearer token exists.
- `test_format.py`'s `_ALLOWED_SUFFIX_MATCH_FILES` allowlist is filename-scoped to `DailyTokenTrendChart.tsx`, applies only to the K/M-suffix regex, cites D-04 inline, and leaves the `_FORBIDDEN_PATTERNS` identifier check (`formatNumber`/`formatMK`/etc.) unconditional across every file — re-verified directly by reading the diff hunk, not re-trusting the round-1 injection test.
- Every I/O call carries an explicit timeout: both fetch modules use `AbortSignal.timeout(5000)`; the DB path is a single bounded SELECT — `performance-baseline.md` satisfied.
- `docs/requirements/api.md` contract fill for `program-token-trend-api` is complete and matches the shipped code — no `contract-drift`.
- Every changed/created file in the diff resolves to a `file_plan` entry (F-01..F-21) in `tasks.json`; `docs/activity/activity.jsonl`, `docs/state/features.json`, `docs/stories/PGD-02.md` are harness-owned bookkeeping, not feature source, and are out of `surgical-changes` scope by design.

## Recommendation

PASS WITH WARNINGS. Both blocking findings from round 1 are resolved and independently re-verified. The single remaining LOW (`services/mcp-server/uv.lock`) is a non-blocking, PR-body-only warning — it traces to no PGD-02 task but will not be staged into this story's commit. No further changes required to merge PGD-02.
