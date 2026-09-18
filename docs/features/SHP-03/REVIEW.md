# Code Review — feature/SHP-03 (working tree vs origin/main)

- Date: 2026-09-18T18:15:00Z
- Mode: branch (GATE MODE — report-only)
- Files reviewed: 17 in-scope (all resolve to `tasks.json` `file_plan` F-01..F-17)
- Verdict: PASS

## Executive summary

SHP-03 adds `GET /api/personal-usage/{user_id}/sessions` (paginated session list) plus the standalone `SessionsTable` frontend panel. The diff is a clean, disciplined implementation of PLAN.md/DECISIONS.md/DATA-DESIGN.md: two new sibling formatters leave `format_duration`/`format_number` untouched (D-01/D-02), the response schema locks exactly 4 fields with `extra="forbid"` and no raw `session_identifier`/`started_at` siblings (D-03), the RBAC gate is called bare with no new logging (D-04), the contract was filled in `docs/requirements/api.md` (D-05), `SessionsTable` ships unwired (D-06), and the `#4a5261` color question resolves to `text-700`/`#5b6472` (D-07). `services/api/app/dependencies/pagination.py` is confirmed unedited (sealed, BED-02 D-01). Ruff, mypy, ESLint, and tsc are all clean on the changed files; 26 backend unit tests and 22 frontend tests pass. No scope-creep: every changed/added file maps 1:1 to `tasks.json` `file_plan`. No ADR violations found. No new contract-drift — the one contract this story produces (`personal-sessions-api`) was updated in the same diff.

🟢 Strengths — formatter separation honored to the letter with regression tests pinning F-02's documented edge cases; RBAC test suite pairs every "not logged" self-access assertion with a same-window positive control, defeating the known Alembic-logger-disabled false-negative trap; N+1 guarded by an explicit 2-SELECT query-count test; accessibility exceeds the mockup (real `<table>`, `aria-current`, `aria-label`s, live region).

⚠️ Warnings — none blocking; two low-severity documentation/robustness notes below.

🛑 Blockers — none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH     | 0 | — |
| MEDIUM   | 0 | — |
| LOW      | 2 | testability (1), design-patterns (1) |

## Detailed findings

### LOW

#### L-1 — testability: React list key derived from `meta`, not a stable id
- Category: testability
- Path: `apps/web/src/components/SessionsTable.tsx:171`
- Source: `.claude/rules/reusability-baseline.md` (implicit — React keys should be stable/unique identifiers, not composed display strings)
- Description: `key={`${s.meta}-${i}`}` uses the pre-formatted `meta` string (itself index-free but not guaranteed unique if two sessions share the same `session_identifier` display format edge case) combined with array index as a tiebreak. Functionally safe today since `meta` embeds `session_identifier`, but the response envelope carries no raw id field a component could key on directly (by design, D-03) — the index-suffix fallback is doing the real uniqueness work.
- Suggested fix: no action required now; if `PersonalSessionEntry` ever gains a stable id field for another purpose, prefer keying on it instead of `meta`.

#### L-2 — design-patterns: `%-d` strftime flag is platform-dependent
- Category: design-patterns
- Path: `services/api/app/services/personal_usage.py:219`
- Source: `program_releases.py:85`'s own D-02 comment, which already flags `%-d`/`%#d` as non-portable across platforms
- Description: `f"{row.started_at:%b %-d, %Y}"` relies on the glibc/BSD-specific `%-d` flag (no leading zero), which is absent on Windows' C runtime. This matches existing precedent in `program_releases.py` and the deploy target is Linux-only (Docker), so it is not a new risk, but it is a second call site now relying on the same non-portable flag with no shared helper.
- Suggested fix: none required for this story; worth a future carry-forward to extract a small `_format_day_no_pad()` helper shared by both call sites if a third one appears.

## What went well

- Every `DECISIONS.md` entry (D-01..D-07) is honored in the actual diff, verified line-by-line against source.
- `app/dependencies/pagination.py` confirmed byte-for-byte unedited (`git diff` empty) — sealed BED-02 D-01 contract intact.
- `format_duration()`/`format_number()` confirmed unedited — sealed contracts intact; new siblings added beside them per D-01/D-02.
- Test suite pins both F-02 documented edge cases (`999_999 -> "1000K"`, banker's-rounding `2_500 -> "2K"`) as regression tests rather than leaving them undocumented.
- Frontend proxy route and client/server API split exactly mirrors the `ArtifactsPanel`/`personal-usage` precedent (ADR-0008 full server-to-server proxy, no token reaches client JS).
- `docs/requirements/api.md`'s `personal-sessions-api` contract section was filled with the concrete shape in the same diff — no contract-drift.
- All ran-and-verified: `uv run ruff check` clean, `uv run mypy` clean (0 issues, 4 files), `uv run pytest` 26/26 passed, `pnpm exec tsc --noEmit` clean, `pnpm exec eslint` clean, `pnpm exec vitest run` 22/22 passed.
- Known-open items F-01 through F-04 (DECISIONS.md D-02 wording drift, un-designed formatter edges, `user_sessions.name` data-reality gap, PLAN.md's stale TC-12/13/14 citations) all confirmed still accurately described in `FLAGS.md` and not re-raised here as new blockers, per instruction.

## Recommendation

PASS. No CRITICAL/HIGH/MEDIUM findings. Proceed to merge; the two LOW notes are informational only and need no action before merge.
